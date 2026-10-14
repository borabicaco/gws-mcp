"""Per-account Google API clients.

Credentials are cached per account and refreshed (and persisted) when they expire.
API service objects are built per call: httplib2 is not thread-safe and MCP runs
sync tools in worker threads. Building uses the bundled discovery documents, so
it costs no network round-trip.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from gws_mcp.auth.credentials import account_scope_status, load_credentials
from gws_mcp.auth.token_store import TokenStore
from gws_mcp.config import AccountConfig, AppConfig
from gws_mcp.scopes import ScopeStatus

BuildFn = Callable[..., Any]


class GoogleClients:
    def __init__(self, config: AppConfig, store: TokenStore, build_fn: BuildFn = build) -> None:
        self.config = config
        self._store = store
        self._build = build_fn
        self._creds: dict[str, Credentials] = {}
        self._lock = threading.Lock()

    def account(self, alias: str | None) -> AccountConfig:
        return self.config.resolve_account(alias)

    def credentials(self, account: AccountConfig) -> Credentials:
        with self._lock:
            creds = self._creds.get(account.alias)
            if creds is None or not creds.valid:
                creds = load_credentials(account, self._store)
                self._creds[account.alias] = creds
            return creds

    def scope_status(self, account: AccountConfig) -> ScopeStatus:
        return account_scope_status(account, self.credentials(account))

    def _service(self, account: AccountConfig, name: str, version: str) -> Any:
        return self._build(
            name, version, credentials=self.credentials(account), cache_discovery=False
        )

    def gmail(self, account: AccountConfig) -> Any:
        return self._service(account, "gmail", "v1")

    def calendar(self, account: AccountConfig) -> Any:
        return self._service(account, "calendar", "v3")

    def drive(self, account: AccountConfig) -> Any:
        return self._service(account, "drive", "v3")
