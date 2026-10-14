from __future__ import annotations

import datetime as dt
from unittest.mock import patch

import pytest
from google.auth.exceptions import RefreshError

from gws_mcp.auth.credentials import (
    NotAuthorizedError,
    account_scope_status,
    load_credentials,
)
from gws_mcp.config import AccountConfig
from gws_mcp.scopes import READ_SCOPES, WRITE_SCOPES, required_scopes, scope_status


def make_account(write: bool = False) -> AccountConfig:
    return AccountConfig(
        alias="work", email="me@example.com", client_secrets="/x.json", write=write
    )


def token_data(expired: bool, refresh_token: str | None = "1//refresh", scopes=READ_SCOPES):
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    expiry = now - dt.timedelta(minutes=5) if expired else now + dt.timedelta(hours=1)
    data = {
        "token": "ya29.old",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "scopes": list(scopes),
        "expiry": expiry.isoformat() + "Z",
    }
    if refresh_token:
        data["refresh_token"] = refresh_token
    return data


def fake_refresh(self, request):
    self.token = "ya29.new"
    self.expiry = dt.datetime.now(dt.UTC).replace(tzinfo=None) + dt.timedelta(hours=1)


def test_valid_token_is_not_refreshed(make_store):
    store = make_store({"work": token_data(expired=False)})
    with patch("google.oauth2.credentials.Credentials.refresh") as refresh:
        creds = load_credentials(make_account(), store)
    refresh.assert_not_called()
    assert creds.token == "ya29.old"
    assert store.saves == 0


def test_expired_token_is_refreshed_and_persisted(make_store):
    store = make_store({"work": token_data(expired=True)})
    with patch("google.oauth2.credentials.Credentials.refresh", fake_refresh):
        creds = load_credentials(make_account(), store)
    assert creds.token == "ya29.new"
    assert store.saves == 1
    assert store.tokens["work"]["token"] == "ya29.new"
    # The refresh token must survive the round trip.
    assert store.tokens["work"]["refresh_token"] == "1//refresh"


def test_missing_token_raises_not_authorized(make_store):
    with pytest.raises(NotAuthorizedError, match="gws-mcp auth work"):
        load_credentials(make_account(), make_store())


def test_token_without_refresh_token_requires_reauth(make_store):
    store = make_store({"work": token_data(expired=True, refresh_token=None)})
    with pytest.raises(NotAuthorizedError, match="gws-mcp auth work"):
        load_credentials(make_account(), store)


def test_revoked_refresh_token_raises_not_authorized(make_store):
    store = make_store({"work": token_data(expired=True)})

    def boom(self, request):
        raise RefreshError("invalid_grant: secret details")

    with patch("google.oauth2.credentials.Credentials.refresh", boom):
        with pytest.raises(NotAuthorizedError) as exc_info:
            load_credentials(make_account(), store)
    assert "secret details" not in str(exc_info.value)
    assert store.saves == 0


def test_read_only_account_requests_only_readonly_scopes(make_store):
    assert required_scopes(False) == list(READ_SCOPES)
    assert set(required_scopes(True)) == set(READ_SCOPES) | set(WRITE_SCOPES)


def test_write_requires_both_config_and_scopes(make_store):
    granted_all = READ_SCOPES + WRITE_SCOPES
    # Config off, scopes granted -> still no write.
    assert scope_status(granted_all, write_enabled=False).can_write is False
    # Config on, scopes missing -> no write, re-auth needed.
    status = scope_status(READ_SCOPES, write_enabled=True)
    assert status.can_write is False
    assert status.needs_reauth
    assert set(status.missing) == set(WRITE_SCOPES)
    # Both on -> write.
    assert scope_status(granted_all, write_enabled=True).can_write is True


def test_account_scope_status_from_credentials(make_store):
    store = make_store({"work": token_data(expired=False)})
    creds = load_credentials(make_account(write=True), store)
    status = account_scope_status(make_account(write=True), creds)
    assert status.can_read and not status.can_write and status.needs_reauth
