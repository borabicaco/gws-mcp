"""Load and validate the TOML configuration file."""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

CONFIG_ENV_VAR = "GWS_MCP_CONFIG"
DEFAULT_CONFIG_PATH = Path("~/.config/gws-mcp/config.toml")

_ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class ConfigError(Exception):
    """Raised when the configuration is missing or invalid."""


def _expand(path: Path) -> Path:
    return Path(os.path.expandvars(str(path))).expanduser()


class AccountConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    alias: str
    email: str
    client_secrets: Path
    write: bool = False

    @field_validator("alias")
    @classmethod
    def _check_alias(cls, value: str) -> str:
        if not _ALIAS_RE.match(value):
            raise ValueError(
                "account alias must be 1-32 chars of lowercase letters, digits, '-' or '_'"
            )
        return value

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str) -> str:
        if "@" not in value:
            raise ValueError("email must be an email address")
        return value.strip().lower()

    @field_validator("client_secrets")
    @classmethod
    def _expand_path(cls, value: Path) -> Path:
        return _expand(value)


class StorageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    backend: Literal["keyring", "encrypted_file"] = "keyring"
    encrypted_file_path: Path = Path("~/.config/gws-mcp/tokens.enc")

    @field_validator("encrypted_file_path")
    @classmethod
    def _expand_path(cls, value: Path) -> Path:
        return _expand(value)


class DownloadsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    dir: Path = Path("~/Downloads/gws-mcp")
    max_inline_bytes: int = Field(default=1_000_000, gt=0)

    @field_validator("dir")
    @classmethod
    def _expand_path(cls, value: Path) -> Path:
        return _expand(value)


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    default_account: str | None = None
    accounts: dict[str, AccountConfig]
    storage: StorageConfig = StorageConfig()
    downloads: DownloadsConfig = DownloadsConfig()

    @model_validator(mode="before")
    @classmethod
    def _inject_aliases(cls, data: object) -> object:
        # In TOML the alias is the table name ([accounts.work]); copy it into each account.
        if isinstance(data, dict) and isinstance(data.get("accounts"), dict):
            accounts = {}
            for alias, account in data["accounts"].items():
                if isinstance(account, dict):
                    account = {**account, "alias": alias}
                accounts[alias] = account
            data = {**data, "accounts": accounts}
        return data

    @model_validator(mode="after")
    def _check_accounts(self) -> AppConfig:
        if not self.accounts:
            raise ValueError("at least one account must be defined under [accounts.<alias>]")
        if self.default_account is not None and self.default_account not in self.accounts:
            raise ValueError(f"default_account '{self.default_account}' is not a defined account")
        return self

    @property
    def aliases(self) -> list[str]:
        return list(self.accounts)

    def resolve_account(self, alias: str | None = None) -> AccountConfig:
        """Return the account for ``alias``, falling back to the default account."""
        if alias:
            try:
                return self.accounts[alias]
            except KeyError:
                raise ConfigError(
                    f"Unknown account '{alias}'. Available accounts: {', '.join(self.aliases)}"
                ) from None
        if self.default_account:
            return self.accounts[self.default_account]
        if len(self.accounts) == 1:
            return next(iter(self.accounts.values()))
        raise ConfigError(
            "Several accounts are configured and no default_account is set; "
            f"pass an account explicitly. Available accounts: {', '.join(self.aliases)}"
        )


def config_path() -> Path:
    """Config location: $GWS_MCP_CONFIG, else ~/.config/gws-mcp/config.toml."""
    override = os.environ.get(CONFIG_ENV_VAR)
    return _expand(Path(override)) if override else _expand(DEFAULT_CONFIG_PATH)


def load_config(path: Path | None = None) -> AppConfig:
    path = _expand(path) if path else config_path()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(
            f"Config file not found: {path}. Copy config.example.toml there and edit it."
        ) from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Config file {path} is not valid TOML: {exc}") from None
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"Invalid config file {path}:\n{exc}") from None
