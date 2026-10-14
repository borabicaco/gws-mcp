"""Persistent, non-plaintext token storage.

Two backends:
- KeyringTokenStore: the OS keychain (macOS Keychain, Windows Credential Manager).
- EncryptedFileTokenStore: a Fernet-encrypted file for headless servers without a
  keyring; the key comes from the GWS_MCP_TOKEN_KEY environment variable.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Protocol

import keyring
from cryptography.fernet import Fernet, InvalidToken

from gws_mcp.config import StorageConfig

KEYRING_SERVICE = "gws-mcp"
TOKEN_KEY_ENV_VAR = "GWS_MCP_TOKEN_KEY"  # noqa: S105 (env var name, not a secret)

TokenData = dict[str, Any]


class TokenStoreError(Exception):
    """Raised when tokens cannot be read or written."""


class TokenStore(Protocol):
    def load(self, alias: str) -> TokenData | None: ...

    def save(self, alias: str, data: TokenData) -> None: ...


class KeyringTokenStore:
    def __init__(self, service: str = KEYRING_SERVICE) -> None:
        self._service = service

    def load(self, alias: str) -> TokenData | None:
        try:
            raw = keyring.get_password(self._service, alias)
        except keyring.errors.KeyringError as exc:
            raise TokenStoreError(f"Could not read token for '{alias}' from keyring") from exc
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TokenStoreError(f"Stored token for '{alias}' is corrupted") from exc

    def save(self, alias: str, data: TokenData) -> None:
        try:
            keyring.set_password(self._service, alias, json.dumps(data))
        except keyring.errors.KeyringError as exc:
            raise TokenStoreError(f"Could not write token for '{alias}' to keyring") from exc


def generate_key() -> str:
    """Create a new key for EncryptedFileTokenStore."""
    return Fernet.generate_key().decode("ascii")


class EncryptedFileTokenStore:
    def __init__(self, path: Path, key: str | None = None) -> None:
        key = key if key is not None else os.environ.get(TOKEN_KEY_ENV_VAR)
        if not key:
            raise TokenStoreError(
                f"{TOKEN_KEY_ENV_VAR} is not set. Generate a key with: gws-mcp gen-key"
            )
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise TokenStoreError(f"{TOKEN_KEY_ENV_VAR} is not a valid key") from exc
        self._path = path

    def _read_all(self) -> dict[str, TokenData]:
        if not self._path.exists():
            return {}
        try:
            plaintext = self._fernet.decrypt(self._path.read_bytes())
        except InvalidToken as exc:
            raise TokenStoreError(
                f"Cannot decrypt {self._path}: wrong {TOKEN_KEY_ENV_VAR} or corrupted file"
            ) from exc
        return json.loads(plaintext)

    def _write_all(self, tokens: dict[str, TokenData]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        ciphertext = self._fernet.encrypt(json.dumps(tokens).encode("utf-8"))
        # Write to a private temp file, then atomically move it into place.
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".tokens-")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(ciphertext)
            os.replace(tmp, self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def load(self, alias: str) -> TokenData | None:
        return self._read_all().get(alias)

    def save(self, alias: str, data: TokenData) -> None:
        tokens = self._read_all()
        tokens[alias] = data
        self._write_all(tokens)


def make_token_store(storage: StorageConfig) -> TokenStore:
    if storage.backend == "encrypted_file":
        return EncryptedFileTokenStore(storage.encrypted_file_path)
    return KeyringTokenStore()
