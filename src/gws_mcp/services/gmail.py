"""Read-only Gmail operations. ``service`` is a googleapiclient Gmail v1 resource."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gws_mcp.services import save_download, truncate
from gws_mcp.services.mime import (
    b64url_decode,
    body_as_text,
    find_attachments,
    find_part,
    headers_of,
)

USER = "me"
SUMMARY_HEADERS = ["From", "To", "Cc", "Subject", "Date"]
MAX_RESULTS_CAP = 50
DEFAULT_BODY_CHARS = 20_000


class GmailError(Exception):
    """An anticipated Gmail failure with a message safe to show the user."""


def _summary(message: dict[str, Any]) -> dict[str, Any]:
    headers = headers_of(message.get("payload") or {})
    return {
        "id": message["id"],
        "thread_id": message.get("threadId"),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", ""),
        "date": headers.get("date", ""),
        "snippet": message.get("snippet", ""),
        "labels": message.get("labelIds", []),
    }


def get_profile(service: Any) -> dict[str, Any]:
    profile = service.users().getProfile(userId=USER).execute()
    return {
        "email": profile.get("emailAddress"),
        "messages_total": profile.get("messagesTotal"),
        "threads_total": profile.get("threadsTotal"),
    }


def search_messages(
    service: Any, query: str, max_results: int = 20, page_token: str | None = None
) -> dict[str, Any]:
    """Search with Gmail operators (from:, subject:, has:attachment, after:, ...)."""
    max_results = max(1, min(max_results, MAX_RESULTS_CAP))
    listing = (
        service.users()
        .messages()
        .list(userId=USER, q=query, maxResults=max_results, pageToken=page_token)
        .execute()
    )
    messages = []
    for ref in listing.get("messages", []):
        message = (
            service.users()
            .messages()
            .get(userId=USER, id=ref["id"], format="metadata", metadataHeaders=SUMMARY_HEADERS)
            .execute()
        )
        messages.append(_summary(message))
    return {"messages": messages, "next_page_token": listing.get("nextPageToken")}


def _parse_message(message: dict[str, Any], max_body_chars: int) -> dict[str, Any]:
    payload = message.get("payload") or {}
    body, truncated = truncate(body_as_text(payload), max_body_chars)
    result = _summary(message)
    result.update(
        {
            "body": body,
            "body_truncated": truncated,
            "message_id_header": headers_of(payload).get("message-id", ""),
            "attachments": [a.as_dict() for a in find_attachments(payload)],
        }
    )
    return result


def get_message(
    service: Any, message_id: str, max_body_chars: int = DEFAULT_BODY_CHARS
) -> dict[str, Any]:
    message = service.users().messages().get(userId=USER, id=message_id, format="full").execute()
    return _parse_message(message, max_body_chars)


def get_thread(
    service: Any, thread_id: str, max_body_chars: int = DEFAULT_BODY_CHARS
) -> dict[str, Any]:
    thread = service.users().threads().get(userId=USER, id=thread_id, format="full").execute()
    messages = thread.get("messages", [])
    per_message = max(1000, max_body_chars // max(1, len(messages)))
    return {
        "id": thread["id"],
        "messages": [_parse_message(m, per_message) for m in messages],
    }


def list_attachments(service: Any, message_id: str) -> list[dict[str, Any]]:
    message = service.users().messages().get(userId=USER, id=message_id, format="full").execute()
    return [a.as_dict() for a in find_attachments(message.get("payload") or {})]


def download_attachment(
    service: Any,
    message_id: str,
    part_id: str,
    downloads_dir: Path,
    max_inline_bytes: int,
) -> dict[str, Any]:
    """Save an attachment to ``downloads_dir``; small text attachments are also inlined."""
    message = service.users().messages().get(userId=USER, id=message_id, format="full").execute()
    part = find_part(message.get("payload") or {}, part_id)
    if part is None:
        raise GmailError(f"No part '{part_id}' in message {message_id}")
    body = part.get("body") or {}
    if body.get("attachmentId"):
        raw = (
            service.users()
            .messages()
            .attachments()
            .get(userId=USER, messageId=message_id, id=body["attachmentId"])
            .execute()
        )
        data = b64url_decode(raw.get("data", ""))
    elif body.get("data"):
        data = b64url_decode(body["data"])
    else:
        raise GmailError(f"Part '{part_id}' has no content")

    filename = part.get("filename") or f"attachment-{part_id}"
    mime_type = part.get("mimeType") or "application/octet-stream"
    path = save_download(downloads_dir, filename, data)
    result: dict[str, Any] = {
        "filename": filename,
        "mime_type": mime_type,
        "size": len(data),
        "saved_to": str(path),
    }
    if mime_type.startswith("text/") and len(data) <= max_inline_bytes:
        result["text"] = data.decode("utf-8", errors="replace")
    return result


def list_labels(service: Any) -> list[dict[str, Any]]:
    labels = service.users().labels().list(userId=USER).execute().get("labels", [])
    return [{"id": lb["id"], "name": lb["name"], "type": lb.get("type")} for lb in labels]


def list_drafts(service: Any, max_results: int = 20) -> list[dict[str, Any]]:
    max_results = max(1, min(max_results, MAX_RESULTS_CAP))
    listing = service.users().drafts().list(userId=USER, maxResults=max_results).execute()
    drafts = []
    for ref in listing.get("drafts", []):
        draft = service.users().drafts().get(userId=USER, id=ref["id"], format="metadata").execute()
        message = draft.get("message") or {}
        drafts.append({"draft_id": draft["id"], **_summary(message)})
    return drafts
