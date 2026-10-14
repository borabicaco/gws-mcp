from __future__ import annotations

import asyncio
import base64
import datetime as dt
from unittest.mock import MagicMock

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from gws_mcp.config import AppConfig
from gws_mcp.google_clients import GoogleClients
from gws_mcp.scopes import READ_SCOPES, WRITE_SCOPES
from gws_mcp.server import build_server
from gws_mcp.services import calendar_write, drive_write, gmail_write
from gws_mcp.services.calendar import CalendarError
from gws_mcp.services.gmail import GmailError

WRITE_TOOLS = {
    "gmail_create_draft",
    "gmail_create_reply_draft",
    "gmail_update_draft",
    "gmail_update_user_draft",
    "gmail_modify_labels",
    "gmail_create_label",
    "calendar_create_event",
    "calendar_update_event",
    "drive_create_file",
    "drive_create_folder",
}


class Store:
    def __init__(self, tokens):
        self.tokens = tokens

    def load(self, alias):
        return self.tokens.get(alias)

    def save(self, alias, data):
        self.tokens[alias] = data


def token(scopes):
    expiry = dt.datetime.now(dt.UTC).replace(tzinfo=None) + dt.timedelta(hours=1)
    return {
        "token": "ya29.x",
        "refresh_token": "1//r",
        "client_id": "c",
        "client_secret": "s",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": list(scopes),
        "expiry": expiry.isoformat() + "Z",
    }


def make_server(accounts: dict, tokens: dict):
    config = AppConfig.model_validate(
        {
            "accounts": {
                alias: {"email": f"{alias}@x.example", "client_secrets": "/c.json", "write": write}
                for alias, write in accounts.items()
            },
            "default_account": next(iter(accounts)),
        }
    )
    service = MagicMock()
    clients = GoogleClients(config, Store(tokens), build_fn=MagicMock(return_value=service))
    return build_server(config, clients=clients), service


def tool_names(server):
    return {t.name for t in asyncio.run(server.list_tools())}


def call(server, name, args):
    return asyncio.run(server.call_tool(name, args))


ALL_SCOPES = READ_SCOPES + WRITE_SCOPES


# --- Layer 1: config --------------------------------------------------------------


def test_write_tools_absent_when_write_disabled():
    server, _ = make_server({"work": False}, {"work": token(ALL_SCOPES)})
    names = tool_names(server)
    assert not names & WRITE_TOOLS
    assert "gmail_search" in names


def test_write_tools_present_when_write_enabled():
    server, _ = make_server({"work": True}, {"work": token(ALL_SCOPES)})
    assert WRITE_TOOLS <= tool_names(server)


def test_write_refused_for_read_only_account_in_mixed_setup():
    server, service = make_server(
        {"work": True, "home": False},
        {
            "work": token(ALL_SCOPES),
            "home": token(ALL_SCOPES),
        },
    )
    with pytest.raises(ToolError, match="Write access is disabled for account 'home'"):
        call(
            server,
            "gmail_create_draft",
            {
                "to": ["a@b.c"],
                "subject": "s",
                "body": "b",
                "account": "home",
            },
        )
    service.users.return_value.drafts.return_value.create.assert_not_called()


# --- Layer 2: granted scopes ----------------------------------------------------


def test_write_refused_when_token_lacks_write_scopes():
    server, service = make_server({"work": True}, {"work": token(READ_SCOPES)})
    with pytest.raises(ToolError, match="gws-mcp auth work"):
        call(server, "gmail_create_label", {"name": "Clients"})
    service.users.return_value.labels.return_value.create.assert_not_called()


def test_write_allowed_when_both_layers_agree():
    server, service = make_server({"work": True}, {"work": token(ALL_SCOPES)})
    service.users.return_value.drafts.return_value.create.return_value.execute.return_value = {
        "id": "d1",
        "message": {"id": "m1", "threadId": "t1"},
    }
    result = call(server, "gmail_create_draft", {"to": ["a@b.c"], "subject": "Hi", "body": "Yo"})
    assert result.is_error is False
    assert result.structured_content["draft_id"] == "d1"


# --- Forbidden capabilities -------------------------------------------------------


def test_no_send_delete_or_trash_tools_exist():
    server, _ = make_server({"work": True}, {"work": token(ALL_SCOPES)})
    for name in tool_names(server):
        for forbidden in ("send", "delete", "trash", "remove_file", "cancel"):
            assert forbidden not in name, name


@pytest.mark.parametrize("label", ["TRASH", "SPAM", "trash"])
def test_adding_trash_or_spam_label_is_refused(label):
    service = MagicMock()
    service.users.return_value.labels.return_value.list.return_value.execute.return_value = {
        "labels": [{"id": "TRASH", "name": "TRASH"}, {"id": "SPAM", "name": "SPAM"}],
    }
    with pytest.raises(GmailError, match="not allowed"):
        gmail_write.modify_labels(service, "m1", add=[label])
    service.users.return_value.messages.return_value.modify.assert_not_called()


def test_label_names_are_resolved_to_ids():
    service = MagicMock()
    service.users.return_value.labels.return_value.list.return_value.execute.return_value = {
        "labels": [{"id": "Label_7", "name": "Clients"}, {"id": "INBOX", "name": "INBOX"}],
    }
    gmail_write.modify_labels(service, "m1", add=["clients"], remove=["INBOX"])
    body = service.users.return_value.messages.return_value.modify.call_args.kwargs["body"]
    assert body == {"addLabelIds": ["Label_7"], "removeLabelIds": ["INBOX"]}


def test_calendar_writes_never_send_emails_and_cannot_cancel():
    service = MagicMock()
    calendar_write.create_event(
        service, "Demo", "2026-10-20T10:00", "2026-10-20T11:00", attendees=["a@b.c"]
    )
    insert = service.events.return_value.insert.call_args.kwargs
    assert insert["sendUpdates"] == "none"
    assert insert["body"]["attendees"] == [{"email": "a@b.c"}]

    calendar_write.update_event(service, "e1", summary="New title")
    patch = service.events.return_value.patch.call_args.kwargs
    assert patch["sendUpdates"] == "none"
    assert patch["body"] == {"summary": "New title"}
    assert "status" not in patch["body"]


def test_calendar_update_tool_has_no_status_parameter():
    server, _ = make_server({"work": True}, {"work": token(ALL_SCOPES)})
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert "status" not in tools["calendar_update_event"].input_schema["properties"]


def test_all_day_event_end_is_exclusive():
    service = MagicMock()
    calendar_write.create_event(service, "Holiday", "2026-10-29")
    body = service.events.return_value.insert.call_args.kwargs["body"]
    assert body["start"] == {"date": "2026-10-29"} and body["end"] == {"date": "2026-10-30"}


def test_timed_event_requires_valid_end():
    with pytest.raises(CalendarError, match="end is required"):
        calendar_write.create_event(MagicMock(), "x", "2026-10-20T10:00")
    with pytest.raises(CalendarError, match="after start"):
        calendar_write.create_event(MagicMock(), "x", "2026-10-20T10:00", "2026-10-20T09:00")


def test_drive_only_creates_never_updates():
    service = MagicMock()
    drive_write.create_file(service, "notes.txt", "hello", parent_id="folder1")
    drive_write.create_folder(service, "Reports")
    files = service.files.return_value
    assert files.create.call_count == 2
    files.update.assert_not_called()
    first = files.create.call_args_list[0].kwargs
    assert first["body"] == {"name": "notes.txt", "parents": ["folder1"]}


# --- Draft ownership ----------------------------------------------------------------


def stored_draft(service, headers, mime="text/plain", parts=None):
    payload = {
        "mimeType": mime,
        "headers": [{"name": k, "value": v} for k, v in headers.items()],
        "body": {"data": base64.urlsafe_b64encode(b"old").decode()},
    }
    if parts:
        payload["parts"] = parts
    service.users.return_value.drafts.return_value.get.return_value.execute.return_value = {
        "id": "d1",
        "message": {"id": "m1", "threadId": "t1", "payload": payload},
    }
    service.users.return_value.drafts.return_value.update.return_value.execute.return_value = {
        "id": "d1",
        "message": {"id": "m2", "threadId": "t1"},
    }


def test_update_draft_refuses_user_written_draft():
    service = MagicMock()
    stored_draft(service, {"Subject": "My own draft", "To": "x@y.z"})
    with pytest.raises(GmailError, match="not created by Claude"):
        gmail_write.update_draft(service, "d1", body="changed")
    service.users.return_value.drafts.return_value.update.assert_not_called()


def test_update_user_draft_requires_matching_subject():
    service = MagicMock()
    stored_draft(service, {"Subject": "My own draft", "To": "x@y.z"})
    with pytest.raises(GmailError, match="expected_subject"):
        gmail_write.update_draft(
            service, "d1", body="c", allow_user_draft=True, expected_subject="Other"
        )
    gmail_write.update_draft(
        service, "d1", body="c", allow_user_draft=True, expected_subject="My own draft"
    )
    service.users.return_value.drafts.return_value.update.assert_called_once()


def test_user_draft_stays_unmarked_after_update():
    service = MagicMock()
    stored_draft(service, {"Subject": "Mine", "To": "x@y.z"})
    gmail_write.update_draft(
        service, "d1", body="c", allow_user_draft=True, expected_subject="Mine"
    )
    raw = service.users.return_value.drafts.return_value.update.call_args.kwargs["body"]
    decoded = base64.urlsafe_b64decode(raw["message"]["raw"])
    assert gmail_write.MARKER_HEADER.encode() not in decoded


def test_draft_with_attachments_is_never_rewritten():
    service = MagicMock()
    parts = [
        {
            "partId": "0",
            "mimeType": "text/plain",
            "filename": "",
            "headers": [],
            "body": {"data": "b2xk"},
        },
        {
            "partId": "1",
            "mimeType": "application/pdf",
            "filename": "a.pdf",
            "headers": [],
            "body": {"attachmentId": "A", "size": 3},
        },
    ]
    stored_draft(
        service,
        {"Subject": "Mine", gmail_write.MARKER_HEADER: "draft"},
        mime="multipart/mixed",
        parts=parts,
    )
    with pytest.raises(GmailError, match="attachments"):
        gmail_write.update_draft(service, "d1", body="c")
    service.users.return_value.drafts.return_value.update.assert_not_called()
