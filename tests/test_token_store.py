from __future__ import annotations

import logging
import stat

import keyring
import pytest
from keyring.backend import KeyringBackend

from gws_mcp.auth.token_store import (
    EncryptedFileTokenStore,
    KeyringTokenStore,
    TokenStoreError,
    generate_key,
    make_token_store,
)
from gws_mcp.config import StorageConfig
from gws_mcp.logging_setup import REDACTED, RedactingFilter, redact

TOKEN = {"token": "ya29.secret-access", "refresh_token": "1//secret-refresh-token", "scopes": []}


class InMemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self.passwords: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.passwords.get((service, username))

    def set_password(self, service, username, password):
        self.passwords[(service, username)] = password

    def delete_password(self, service, username):
        raise NotImplementedError


@pytest.fixture
def fake_keyring():
    previous = keyring.get_keyring()
    backend = InMemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


def test_keyring_roundtrip(fake_keyring):
    store = KeyringTokenStore()
    assert store.load("work") is None
    store.save("work", TOKEN)
    assert store.load("work") == TOKEN
    assert ("gws-mcp", "work") in fake_keyring.passwords


def test_keyring_accounts_are_separate(fake_keyring):
    store = KeyringTokenStore()
    store.save("work", TOKEN)
    store.save("home", {**TOKEN, "token": "other"})
    assert store.load("work")["token"] == "ya29.secret-access"
    assert store.load("home")["token"] == "other"


def test_keyring_corrupted_entry(fake_keyring):
    fake_keyring.passwords[("gws-mcp", "work")] = "not json"
    with pytest.raises(TokenStoreError, match="corrupted"):
        KeyringTokenStore().load("work")


def test_encrypted_file_roundtrip_and_not_plaintext(tmp_path):
    path = tmp_path / "tokens.enc"
    store = EncryptedFileTokenStore(path, key=generate_key())
    store.save("work", TOKEN)
    store.save("home", {**TOKEN, "token": "other"})

    raw = path.read_bytes()
    assert b"secret" not in raw and b"refresh_token" not in raw
    assert store.load("work") == TOKEN
    assert store.load("home")["token"] == "other"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_encrypted_file_wrong_key(tmp_path):
    path = tmp_path / "tokens.enc"
    EncryptedFileTokenStore(path, key=generate_key()).save("work", TOKEN)
    with pytest.raises(TokenStoreError, match="Cannot decrypt"):
        EncryptedFileTokenStore(path, key=generate_key()).load("work")


def test_encrypted_file_requires_key(tmp_path, monkeypatch):
    monkeypatch.delenv("GWS_MCP_TOKEN_KEY", raising=False)
    with pytest.raises(TokenStoreError, match="gen-key"):
        EncryptedFileTokenStore(tmp_path / "t.enc")


def test_encrypted_file_rejects_invalid_key(tmp_path):
    with pytest.raises(TokenStoreError, match="not a valid key"):
        EncryptedFileTokenStore(tmp_path / "t.enc", key="short")


def test_make_token_store_uses_env_key(tmp_path, monkeypatch):
    monkeypatch.setenv("GWS_MCP_TOKEN_KEY", generate_key())
    store = make_token_store(
        StorageConfig(backend="encrypted_file", encrypted_file_path=tmp_path / "t.enc")
    )
    assert isinstance(store, EncryptedFileTokenStore)
    assert isinstance(make_token_store(StorageConfig()), KeyringTokenStore)


@pytest.mark.parametrize(
    "text",
    [
        '{"refresh_token": "1//abcdefghijklmnop", "token": "ya29.zzz"}',
        "Authorization: Bearer ya29.a0AfH6SMB",
        "client_secret=GOCSPX-abc123",
        "leaked ya29.a0AfH6SMBxyz in message",
    ],
)
def test_redact_removes_tokens(text):
    out = redact(text)
    for secret in ("1//abcdefghijklmnop", "ya29.", "GOCSPX-abc123"):
        assert secret not in out
    assert REDACTED in out


def test_tokens_never_reach_logs(caplog):
    logger = logging.getLogger("gws_mcp.test")
    logger.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO, logger="gws_mcp.test"):
        logger.info("stored %s", TOKEN)
    assert "secret" not in caplog.text
