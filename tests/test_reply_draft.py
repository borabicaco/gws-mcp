from __future__ import annotations

import base64
import email
from email import policy
from unittest.mock import MagicMock

import pytest

from gws_mcp.services import gmail_write
from gws_mcp.services.gmail import GmailError

ME = "me@work.example"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def original(headers: dict[str, str], thread_id="thread-42"):
    return {
        "id": "m1",
        "threadId": thread_id,
        "payload": {"headers": [{"name": k, "value": v} for k, v in headers.items()]},
    }


def make_service(original_message):
    svc = MagicMock()
    users = svc.users.return_value
    users.getProfile.return_value.execute.return_value = {"emailAddress": ME}
    users.messages.return_value.get.return_value.execute.return_value = original_message
    users.drafts.return_value.create.return_value.execute.return_value = {
        "id": "d1",
        "message": {"id": "dm1", "threadId": original_message.get("threadId")},
    }
    return svc


def sent_body(svc, method="create"):
    call = getattr(svc.users.return_value.drafts.return_value, method).call_args
    return call.kwargs["body"]


def parse_raw(raw: str):
    return email.message_from_bytes(base64.urlsafe_b64decode(raw), policy=policy.default)


BASE = {
    "From": "Ali Veli <ali@client.example>",
    "To": f"{ME}, ayse@client.example",
    "Cc": "boss@client.example",
    "Subject": "Teklif",
    "Message-ID": "<orig-123@client.example>",
    "References": "<first-1@client.example>",
}


def test_reply_draft_is_attached_to_original_thread():
    svc = make_service(original(BASE))
    result = gmail_write.create_reply_draft(svc, "m1", "Teşekkürler, inceliyorum.")
    body = sent_body(svc)
    assert body["message"]["threadId"] == "thread-42"
    assert result == {"draft_id": "d1", "message_id": "dm1", "thread_id": "thread-42"}


def test_reply_draft_headers_link_to_original():
    svc = make_service(original(BASE))
    gmail_write.create_reply_draft(svc, "m1", "Teşekkürler, inceliyorum.")
    msg = parse_raw(sent_body(svc)["message"]["raw"])
    assert msg["In-Reply-To"] == "<orig-123@client.example>"
    assert msg["References"] == "<first-1@client.example> <orig-123@client.example>"
    assert msg["Subject"] == "Re: Teklif"
    assert msg["To"] == "ali@client.example"
    assert msg["Cc"] is None
    assert msg[gmail_write.MARKER_HEADER] == gmail_write.MARKER_VALUE
    assert msg.get_content().strip() == "Teşekkürler, inceliyorum."


def test_reply_all_includes_others_but_not_me():
    svc = make_service(original(BASE))
    gmail_write.create_reply_draft(svc, "m1", "ok", reply_all=True)
    msg = parse_raw(sent_body(svc)["message"]["raw"])
    assert msg["To"] == "ali@client.example"
    assert msg["Cc"] == "ayse@client.example, boss@client.example"
    assert ME not in msg["Cc"]


def test_reply_prefers_reply_to_header():
    svc = make_service(original({**BASE, "Reply-To": "support@client.example"}))
    gmail_write.create_reply_draft(svc, "m1", "ok")
    assert parse_raw(sent_body(svc)["message"]["raw"])["To"] == "support@client.example"


@pytest.mark.parametrize("subject", ["Re: Teklif", "RE: Teklif", "Ynt: Teklif"])
def test_subject_prefix_not_duplicated(subject):
    assert gmail_write.reply_subject(subject) == subject


def test_reply_to_my_own_message_goes_to_original_recipients():
    headers = {**BASE, "From": f"Me <{ME}>", "To": "ali@client.example"}
    svc = make_service(original(headers))
    gmail_write.create_reply_draft(svc, "m1", "follow-up")
    assert parse_raw(sent_body(svc)["message"]["raw"])["To"] == "ali@client.example"


def test_reply_without_references_uses_message_id_only():
    headers = {k: v for k, v in BASE.items() if k != "References"}
    svc = make_service(original(headers))
    gmail_write.create_reply_draft(svc, "m1", "ok")
    assert parse_raw(sent_body(svc)["message"]["raw"])["References"] == "<orig-123@client.example>"


def test_reply_with_no_recipient_fails():
    svc = make_service(original({"Subject": "x"}))
    with pytest.raises(GmailError, match="who to reply"):
        gmail_write.create_reply_draft(svc, "m1", "ok")


def test_updating_own_reply_draft_keeps_thread_and_headers():
    svc = make_service(original(BASE))
    gmail_write.create_reply_draft(svc, "m1", "first version")
    created = parse_raw(sent_body(svc)["message"]["raw"])

    # Simulate Gmail returning the stored draft.
    headers = [{"name": k, "value": v} for k, v in created.items()]
    svc.users.return_value.drafts.return_value.get.return_value.execute.return_value = {
        "id": "d1",
        "message": {
            "id": "dm1",
            "threadId": "thread-42",
            "payload": {
                "mimeType": "text/plain",
                "headers": headers,
                "body": {"data": b64(b"first version")},
            },
        },
    }
    svc.users.return_value.drafts.return_value.update.return_value.execute.return_value = {
        "id": "d1",
        "message": {"id": "dm2", "threadId": "thread-42"},
    }
    gmail_write.update_draft(svc, "d1", body="second version")
    body = sent_body(svc, "update")
    assert body["message"]["threadId"] == "thread-42"
    updated = parse_raw(body["message"]["raw"])
    assert updated["In-Reply-To"] == "<orig-123@client.example>"
    assert updated["Subject"] == "Re: Teklif"
    assert updated[gmail_write.MARKER_HEADER] == gmail_write.MARKER_VALUE
    assert updated.get_content().strip() == "second version"
