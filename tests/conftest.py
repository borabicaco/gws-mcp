from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from gws_mcp.auth.token_store import TokenData


class MemoryTokenStore:
    """In-memory TokenStore for tests."""

    def __init__(self, initial: dict[str, TokenData] | None = None) -> None:
        self.tokens: dict[str, TokenData] = dict(initial or {})
        self.saves = 0

    def load(self, alias: str) -> TokenData | None:
        return self.tokens.get(alias)

    def save(self, alias: str, data: TokenData) -> None:
        self.tokens[alias] = data
        self.saves += 1


@pytest.fixture
def make_store():
    """Factory for MemoryTokenStore, optionally pre-filled with tokens."""
    return MemoryTokenStore


@pytest.fixture
def write_config(tmp_path: Path):
    """Write a TOML config to a temp file and return its path."""

    def _write(body: str) -> Path:
        path = tmp_path / "config.toml"
        path.write_text(textwrap.dedent(body), encoding="utf-8")
        return path

    return _write


_SINGLE_ACCOUNT = """
    [accounts.work]
    email = "Me@Example.com"
    client_secrets = "~/clients/work.json"
"""

_TWO_ACCOUNTS = """
    [accounts.work]
    email = "me@work.example"
    client_secrets = "/tmp/work.json"
    write = true

    [accounts.home]
    email = "me@home.example"
    client_secrets = "/tmp/home.json"
"""


@pytest.fixture
def single_account() -> str:
    return _SINGLE_ACCOUNT


@pytest.fixture
def two_accounts() -> str:
    return _TWO_ACCOUNTS
