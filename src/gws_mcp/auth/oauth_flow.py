"""First-time authorization: loopback browser flow for ``gws-mcp auth <alias>``."""

from __future__ import annotations

import logging

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from gws_mcp.auth.credentials import credentials_to_data
from gws_mcp.auth.token_store import TokenStore
from gws_mcp.config import AccountConfig
from gws_mcp.scopes import ScopeStatus, required_scopes, scope_status

log = logging.getLogger(__name__)


class AuthFlowError(Exception):
    """Authorization failed; the message is safe to show the user."""


def _signed_in_email(creds: Credentials) -> str:
    gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
    return gmail.users().getProfile(userId="me").execute().get("emailAddress", "").lower()


def run_auth_flow(
    account: AccountConfig,
    store: TokenStore,
    *,
    open_browser: bool = True,
    flow_factory=InstalledAppFlow.from_client_secrets_file,
    email_lookup=_signed_in_email,
) -> ScopeStatus:
    """Authorize ``account`` in the browser and store its token.

    The token is only saved if the Google account that signed in matches the
    configured email, so a wrong browser profile can't end up under this alias.
    """
    if not account.client_secrets.is_file():
        raise AuthFlowError(
            f"OAuth client file not found: {account.client_secrets}. "
            "Download the 'Desktop app' client JSON from Google Cloud Console."
        )

    scopes = required_scopes(account.write)
    flow = flow_factory(str(account.client_secrets), scopes=scopes)
    creds = flow.run_local_server(
        host="localhost",
        port=0,  # any free port (loopback redirect)
        open_browser=open_browser,
        authorization_prompt_message="Open this URL in your browser to authorize: {url}",
        success_message="Authorization complete. You can close this window.",
        # Passed through to Google's authorization URL:
        login_hint=account.email,
        access_type="offline",  # get a refresh token
        prompt="consent",  # always return a refresh token, even on re-auth
    )

    signed_in = email_lookup(creds)
    if signed_in != account.email:
        raise AuthFlowError(
            f"Signed in as {signed_in or 'an unknown account'}, but account "
            f"'{account.alias}' is configured for {account.email}. Nothing was saved."
        )
    if not creds.refresh_token:
        raise AuthFlowError("Google returned no refresh token. Nothing was saved; try again.")

    data = credentials_to_data(creds)
    # Store what Google actually granted (the user may untick some permissions).
    granted = sorted(creds.granted_scopes or scopes)
    data["scopes"] = granted
    store.save(account.alias, data)
    log.info("Stored token for account '%s'", account.alias)
    return scope_status(granted, account.write)
