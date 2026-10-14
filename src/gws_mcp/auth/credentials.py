"""Load stored credentials, refresh them when expired and persist the result."""

from __future__ import annotations

import json
import logging

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from gws_mcp.auth.token_store import TokenData, TokenStore
from gws_mcp.config import AccountConfig
from gws_mcp.scopes import ScopeStatus, scope_status

log = logging.getLogger(__name__)


class NotAuthorizedError(Exception):
    """The account has no usable token; the user must run ``gws-mcp auth <alias>``."""

    def __init__(self, alias: str, reason: str) -> None:
        super().__init__(f"Account '{alias}' {reason}. Authorize it with: gws-mcp auth {alias}")
        self.alias = alias


def credentials_to_data(creds: Credentials) -> TokenData:
    return json.loads(creds.to_json())


def save_credentials(store: TokenStore, alias: str, creds: Credentials) -> None:
    store.save(alias, credentials_to_data(creds))


def load_credentials(account: AccountConfig, store: TokenStore) -> Credentials:
    """Return valid credentials for ``account``, refreshing and persisting if needed."""
    data = store.load(account.alias)
    if data is None:
        raise NotAuthorizedError(account.alias, "is not authorized yet")

    try:
        creds = Credentials.from_authorized_user_info(data)
    except ValueError:
        raise NotAuthorizedError(account.alias, "has an invalid stored token") from None

    if creds.valid:
        return creds
    if not creds.refresh_token:
        raise NotAuthorizedError(account.alias, "has an expired token and no refresh token")

    try:
        creds.refresh(Request())
    except RefreshError:
        # Revoked, expired (e.g. password change) or client deleted. Don't log details.
        raise NotAuthorizedError(account.alias, "could not refresh its token") from None
    except TransportError:
        raise ConnectionError(
            f"Network error while refreshing token for '{account.alias}'"
        ) from None

    save_credentials(store, account.alias, creds)
    log.info("Refreshed access token for account '%s'", account.alias)
    return creds


def granted_scopes(creds: Credentials) -> set[str]:
    return set(creds.granted_scopes or creds.scopes or ())


def account_scope_status(account: AccountConfig, creds: Credentials) -> ScopeStatus:
    return scope_status(granted_scopes(creds), account.write)
