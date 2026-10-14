"""Gmail write operations: drafts and labels only.

Deliberately absent: sending messages or drafts, deleting or trashing anything.
"""

from __future__ import annotations

import base64
import re
from email.message import EmailMessage
from email.utils import getaddresses
from typing import Any

from gws_mcp.services.gmail import USER, GmailError
from gws_mcp.services.mime import body_as_text, find_attachments, headers_of

# Hidden header marking drafts created by this server.
MARKER_HEADER = "X-GWS-MCP"
MARKER_VALUE = "draft"

# Adding these labels would trash or spam a message, so they are refused.
BLOCKED_ADD_LABELS = frozenset({"TRASH", "SPAM"})

_RE_PREFIX = re.compile(r"^\s*(re|ynt|yanıt)\s*:", re.IGNORECASE)


def _encode(msg: EmailMessage) -> str:
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def build_message(
    *,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
    marker: bool = True,
) -> EmailMessage:
    msg = EmailMessage()
    if to:
        msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    if marker:
        msg[MARKER_HEADER] = MARKER_VALUE
    msg.set_content(body)
    return msg


def _draft_result(draft: dict[str, Any]) -> dict[str, Any]:
    message = draft.get("message") or {}
    return {
        "draft_id": draft.get("id"),
        "message_id": message.get("id"),
        "thread_id": message.get("threadId"),
    }


def create_draft(
    service: Any,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
) -> dict[str, Any]:
    msg = build_message(to=to, subject=subject, body=body, cc=cc, bcc=bcc)
    draft = (
        service.users()
        .drafts()
        .create(userId=USER, body={"message": {"raw": _encode(msg)}})
        .execute()
    )
    return _draft_result(draft)


def _addresses(*values: str) -> list[str]:
    return [addr for _, addr in getaddresses([v for v in values if v]) if addr]


def reply_subject(subject: str) -> str:
    return subject if _RE_PREFIX.match(subject) else f"Re: {subject}".strip()


def create_reply_draft(
    service: Any,
    message_id: str,
    body: str,
    reply_all: bool = False,
    cc: list[str] | None = None,
) -> dict[str, Any]:
    """Create a reply draft attached to the original message's thread."""
    original = (
        service.users()
        .messages()
        .get(
            userId=USER,
            id=message_id,
            format="metadata",
            metadataHeaders=["From", "To", "Cc", "Reply-To", "Subject", "Message-ID", "References"],
        )
        .execute()
    )
    headers = headers_of(original.get("payload") or {})
    me = (service.users().getProfile(userId=USER).execute().get("emailAddress") or "").lower()

    to = _addresses(headers.get("reply-to") or headers.get("from", ""))
    if to and to[0].lower() == me:
        # Replying to my own message: answer the original recipients instead.
        to = _addresses(headers.get("to", ""))
    cc_list = list(cc or [])
    if reply_all:
        seen = {a.lower() for a in to + cc_list} | {me}
        for addr in _addresses(headers.get("to", ""), headers.get("cc", "")):
            if addr.lower() not in seen:
                cc_list.append(addr)
                seen.add(addr.lower())
    if not to:
        raise GmailError("Could not determine who to reply to")

    original_id = headers.get("message-id", "")
    references = " ".join(x for x in (headers.get("references", ""), original_id) if x) or None
    msg = build_message(
        to=to,
        cc=cc_list,
        subject=reply_subject(headers.get("subject", "")),
        body=body,
        in_reply_to=original_id or None,
        references=references,
    )
    draft = (
        service.users()
        .drafts()
        .create(
            userId=USER,
            body={"message": {"raw": _encode(msg), "threadId": original.get("threadId")}},
        )
        .execute()
    )
    return _draft_result(draft)


def update_draft(
    service: Any,
    draft_id: str,
    *,
    to: list[str] | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    subject: str | None = None,
    body: str | None = None,
    allow_user_draft: bool = False,
    expected_subject: str | None = None,
) -> dict[str, Any]:
    """Replace fields of a draft; unspecified fields keep their current value.

    By default only drafts created by this server (marked with MARKER_HEADER)
    may be changed. Changing the user's own drafts requires ``allow_user_draft``
    and ``expected_subject`` equal to the draft's current subject.
    """
    draft = service.users().drafts().get(userId=USER, id=draft_id, format="full").execute()
    message = draft.get("message") or {}
    payload = message.get("payload") or {}
    headers = headers_of(payload)
    is_ours = headers.get(MARKER_HEADER.lower()) == MARKER_VALUE

    if not is_ours:
        if not allow_user_draft:
            raise GmailError(
                "This draft was not created by Claude, so gmail_update_draft may not change it. "
                "Use gmail_update_user_draft, which requires the user's approval."
            )
        current_subject = headers.get("subject", "").strip()
        if expected_subject is None or expected_subject.strip() != current_subject:
            raise GmailError(
                "expected_subject does not match the draft's current subject; "
                "read the draft first and pass its exact subject."
            )
    if find_attachments(payload):
        raise GmailError("This draft has attachments; updating it would remove them. Not changed.")

    warnings = []
    if not is_ours and payload.get("mimeType", "").startswith("multipart/"):
        warnings.append("Formatting (HTML) was replaced by plain text.")

    msg = build_message(
        to=to if to is not None else _addresses(headers.get("to", "")),
        cc=cc if cc is not None else _addresses(headers.get("cc", "")),
        bcc=bcc if bcc is not None else _addresses(headers.get("bcc", "")),
        subject=subject if subject is not None else headers.get("subject", ""),
        body=body if body is not None else body_as_text(payload),
        in_reply_to=headers.get("in-reply-to") or None,
        references=headers.get("references") or None,
        marker=is_ours,
    )
    new_message: dict[str, Any] = {"raw": _encode(msg)}
    if message.get("threadId"):
        new_message["threadId"] = message["threadId"]
    updated = (
        service.users()
        .drafts()
        .update(userId=USER, id=draft_id, body={"id": draft_id, "message": new_message})
        .execute()
    )
    result = _draft_result(updated)
    if warnings:
        result["warnings"] = warnings
    return result


def _label_ids(service: Any, names_or_ids: list[str]) -> list[str]:
    labels = service.users().labels().list(userId=USER).execute().get("labels", [])
    by_name = {lb["name"].lower(): lb["id"] for lb in labels}
    ids = {lb["id"] for lb in labels}
    resolved = []
    for value in names_or_ids:
        if value in ids:
            resolved.append(value)
        elif value.lower() in by_name:
            resolved.append(by_name[value.lower()])
        else:
            raise GmailError(f"Unknown label '{value}'. Create it first with gmail_create_label.")
    return resolved


def modify_labels(
    service: Any,
    message_id: str,
    add: list[str] | None = None,
    remove: list[str] | None = None,
) -> dict[str, Any]:
    add, remove = list(add or []), list(remove or [])
    if not add and not remove:
        raise GmailError("Nothing to change: pass labels to add and/or remove")
    add_ids = _label_ids(service, add) if add else []
    blocked = BLOCKED_ADD_LABELS.intersection(add_ids)
    if blocked:
        raise GmailError(
            f"Adding {', '.join(sorted(blocked))} would trash or spam the message; not allowed."
        )
    remove_ids = _label_ids(service, remove) if remove else []
    message = (
        service.users()
        .messages()
        .modify(
            userId=USER, id=message_id, body={"addLabelIds": add_ids, "removeLabelIds": remove_ids}
        )
        .execute()
    )
    return {"message_id": message.get("id"), "labels": message.get("labelIds", [])}


def create_label(service: Any, name: str) -> dict[str, Any]:
    labels = service.users().labels().list(userId=USER).execute().get("labels", [])
    for lb in labels:
        if lb["name"].lower() == name.lower():
            return {"id": lb["id"], "name": lb["name"], "created": False}
    label = (
        service.users()
        .labels()
        .create(
            userId=USER,
            body={
                "name": name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        )
        .execute()
    )
    return {"id": label["id"], "name": label["name"], "created": True}
