from __future__ import annotations

import asyncio
import base64
import datetime as dt
from unittest.mock import MagicMock

import httplib2
import pytest
from googleapiclient.errors import HttpError
from mcp.server.mcpserver.exceptions import ToolError

from gws_mcp.auth.oauth_flow import AuthFlowError, run_auth_flow
from gws_mcp.config import AppConfig
from gws_mcp.google_clients import GoogleClients
from gws_mcp.scopes import READ_SCOPES, WRITE_SCOPES
from gws_mcp.server import build_server
from gws_mcp.services import gmail


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def full_message(msg_id="m1"):
    return {
        "id": msg_id,
        "threadId": "t1",
        "snippet": "Hello there",
        "labelIds": ["INBOX"],
        "payload": {
            "partId": "",
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": "Ali <ali@example.com>"},
                {"name": "To", "value": "me@example.com"},
                {"name": "Subject", "value": "Report"},
                {"name": "Date", "value": "Tue, 13 Oct 2026 10:00:00 +0300"},
                {"name": "Message-ID", "value": "<abc@example.com>"},
            ],
            "body": {"size": 0},
            "parts": [
                {
                    "partId": "0",
                    "mimeType": "text/plain",
                    "filename": "",
                    "headers": [],
                    "body": {"size": 5, "data": b64(b"Body text")},
                },
                {
                    "partId": "1",
                    "mimeType": "text/csv",
                    "filename": "data.csv",
                    "headers": [],
                    "body": {"size": 7, "attachmentId": "ATT"},
                },
            ],
        },
    }


@pytest.fixture
def service():
    svc = MagicMock()
    messages = svc.users.return_value.messages.return_value
    messages.get.return_value.execute.return_value = full_message()
    messages.attachments.return_value.get.return_value.execute.return_value = {
        "data": b64(b"a,b\n1,2")
    }
    return svc


def test_get_profile(service):
    service.users.return_value.getProfile.return_value.execute.return_value = {
        "emailAddress": "me@example.com",
        "messagesTotal": 10,
        "threadsTotal": 4,
    }
    assert gmail.get_profile(service) == {
        "email": "me@example.com",
        "messages_total": 10,
        "threads_total": 4,
    }


def test_search_passes_query_and_caps_results(service):
    messages = service.users.return_value.messages.return_value
    messages.list.return_value.execute.return_value = {
        "messages": [{"id": "m1"}],
        "nextPageToken": "next",
    }
    result = gmail.search_messages(service, "from:ali has:attachment", max_results=500)
    messages.list.assert_called_once_with(
        userId="me", q="from:ali has:attachment", maxResults=50, pageToken=None
    )
    assert result["next_page_token"] == "next"
    assert result["messages"][0]["subject"] == "Report"
    assert result["messages"][0]["from"] == "Ali <ali@example.com>"


def test_get_message_parses_body_and_attachments(service):
    result = gmail.get_message(service, "m1")
    assert result["body"] == "Body text"
    assert result["body_truncated"] is False
    assert result["message_id_header"] == "<abc@example.com>"
    assert result["attachments"][0]["filename"] == "data.csv"


def test_get_message_truncates_long_body(service):
    result = gmail.get_message(service, "m1", max_body_chars=4)
    assert result["body"] == "Body" and result["body_truncated"] is True


def test_get_thread(service):
    service.users.return_value.threads.return_value.get.return_value.execute.return_value = {
        "id": "t1",
        "messages": [full_message("m1"), full_message("m2")],
    }
    result = gmail.get_thread(service, "t1")
    assert [m["id"] for m in result["messages"]] == ["m1", "m2"]


def test_download_attachment_saves_without_overwriting(service, tmp_path):
    (tmp_path / "data.csv").write_text("existing")
    result = gmail.download_attachment(service, "m1", "1", tmp_path, max_inline_bytes=1000)
    assert result["text"] == "a,b\n1,2"
    assert result["saved_to"].endswith("data (2).csv")
    assert (tmp_path / "data.csv").read_text() == "existing"


def test_download_attachment_unknown_part(service, tmp_path):
    with pytest.raises(gmail.GmailError, match="No part"):
        gmail.download_attachment(service, "m1", "9", tmp_path, max_inline_bytes=1000)


def test_list_labels_and_drafts(service):
    users = service.users.return_value
    users.labels.return_value.list.return_value.execute.return_value = {
        "labels": [{"id": "INBOX", "name": "INBOX", "type": "system"}]
    }
    users.drafts.return_value.list.return_value.execute.return_value = {"drafts": [{"id": "d1"}]}
    users.drafts.return_value.get.return_value.execute.return_value = {
        "id": "d1",
        "message": full_message(),
    }
    assert gmail.list_labels(service) == [{"id": "INBOX", "name": "INBOX", "type": "system"}]
    drafts = gmail.list_drafts(service)
    assert drafts[0]["draft_id"] == "d1" and drafts[0]["subject"] == "Report"


# --- Tool layer -----------------------------------------------------------------


class Store:
    def __init__(self, tokens):
        self.tokens = tokens

    def load(self, alias):
        return self.tokens.get(alias)

    def save(self, alias, data):
        self.tokens[alias] = data


def valid_token():
    expiry = dt.datetime.now(dt.UTC).replace(tzinfo=None) + dt.timedelta(hours=1)
    return {
        "token": "ya29.x",
        "refresh_token": "1//r",
        "client_id": "c",
        "client_secret": "s",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": list(READ_SCOPES),
        "expiry": expiry.isoformat() + "Z",
    }


@pytest.fixture
def server_and_service(service):
    config = AppConfig.model_validate(
        {
            "accounts": {
                "work": {"email": "me@work.example", "client_secrets": "/x.json"},
                "home": {"email": "me@home.example", "client_secrets": "/y.json"},
            },
            "default_account": "work",
        }
    )
    build_fn = MagicMock(return_value=service)
    clients = GoogleClients(config, Store({"work": valid_token()}), build_fn=build_fn)
    return build_server(config, clients=clients), service, build_fn


def call(server, name, args):
    return asyncio.run(server.call_tool(name, args))


EXPECTED_READ_TOOLS = {
    "list_accounts",
    "gmail_get_profile",
    "gmail_search",
    "gmail_get_message",
    "gmail_get_thread",
    "gmail_list_attachments",
    "gmail_download_attachment",
    "gmail_list_labels",
    "gmail_list_drafts",
    "calendar_list_calendars",
    "calendar_list_events",
    "calendar_search_events",
    "calendar_get_event",
    "drive_search",
    "drive_recent_files",
    "drive_get_metadata",
    "drive_read_file",
}


def test_server_registers_read_tools_only(server_and_service):
    server, _, _ = server_and_service
    tools = asyncio.run(server.list_tools())
    assert {t.name for t in tools} == EXPECTED_READ_TOOLS
    assert all(t.annotations.read_only_hint for t in tools)
    search = next(t for t in tools if t.name == "gmail_search")
    assert "account" in search.input_schema["properties"]


def test_tool_uses_default_account(server_and_service):
    server, _, build_fn = server_and_service
    result = call(server, "gmail_get_message", {"message_id": "m1"})
    assert result.is_error is False
    assert result.structured_content["subject"] == "Report"
    assert build_fn.call_args.args[:2] == ("gmail", "v1")


def test_unauthorized_account_gives_clear_error(server_and_service):
    server, _, _ = server_and_service
    with pytest.raises(ToolError, match="gws-mcp auth home"):
        call(server, "gmail_get_profile", {"account": "home"})


def test_unknown_account_gives_clear_error(server_and_service):
    server, _, _ = server_and_service
    with pytest.raises(ToolError, match="Available accounts: work, home"):
        call(server, "gmail_get_profile", {"account": "nope"})


def test_google_404_becomes_readable_error(server_and_service):
    server, service, _ = server_and_service
    resp = httplib2.Response({"status": 404})
    resp.reason = "Not Found"
    service.users.return_value.messages.return_value.get.return_value.execute.side_effect = (
        HttpError(resp, b"{}")
    )
    with pytest.raises(ToolError, match="Not found"):
        call(server, "gmail_get_message", {"message_id": "zzz"})


def test_list_accounts_tool(server_and_service):
    server, _, _ = server_and_service
    result = call(server, "list_accounts", {})
    accounts = result.structured_content["result"]
    assert [a["account"] for a in accounts] == ["work", "home"]
    assert accounts[0]["default"] is True and accounts[0]["write_enabled"] is False


# --- Auth flow --------------------------------------------------------------------


def make_flow(creds):
    flow = MagicMock()
    flow.run_local_server.return_value = creds
    return MagicMock(return_value=flow), flow


def fake_creds(granted):
    creds = MagicMock()
    creds.refresh_token = "1//r"
    creds.granted_scopes = granted
    creds.to_json.return_value = '{"token": "ya29.x", "refresh_token": "1//r", "scopes": []}'
    return creds


@pytest.fixture
def account(tmp_path):
    secrets = tmp_path / "client.json"
    secrets.write_text("{}")
    config = AppConfig.model_validate(
        {"accounts": {"work": {"email": "me@work.example", "client_secrets": str(secrets)}}}
    )
    return config.resolve_account()


def test_auth_flow_requests_readonly_scopes_and_saves(account):
    factory, flow = make_flow(fake_creds(list(READ_SCOPES)))
    store = Store({})
    status = run_auth_flow(
        account, store, flow_factory=factory, email_lookup=lambda c: "me@work.example"
    )
    assert factory.call_args.kwargs["scopes"] == list(READ_SCOPES)
    kwargs = flow.run_local_server.call_args.kwargs
    assert kwargs["login_hint"] == "me@work.example" and kwargs["access_type"] == "offline"
    assert store.tokens["work"]["scopes"] == sorted(READ_SCOPES)
    assert not status.needs_reauth and not status.can_write


def test_auth_flow_requests_write_scopes_when_enabled(account):
    account = account.model_copy(update={"write": True})
    factory, _ = make_flow(fake_creds(list(READ_SCOPES + WRITE_SCOPES)))
    status = run_auth_flow(
        account, Store({}), flow_factory=factory, email_lookup=lambda c: "me@work.example"
    )
    assert set(factory.call_args.kwargs["scopes"]) == set(READ_SCOPES + WRITE_SCOPES)
    assert status.can_write


def test_auth_flow_rejects_wrong_google_account(account):
    factory, _ = make_flow(fake_creds(list(READ_SCOPES)))
    store = Store({})
    with pytest.raises(AuthFlowError, match="Nothing was saved"):
        run_auth_flow(account, store, flow_factory=factory, email_lookup=lambda c: "other@x.com")
    assert store.tokens == {}


def test_auth_flow_missing_client_file(account):
    account = account.model_copy(
        update={"client_secrets": account.client_secrets.with_name("nope.json")}
    )
    with pytest.raises(AuthFlowError, match="client file not found"):
        run_auth_flow(account, Store({}))
