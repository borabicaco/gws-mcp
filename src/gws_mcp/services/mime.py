"""Decode Gmail API message payloads: nested MIME parts, charsets, HTML, attachments."""

from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass
from email.message import Message
from html.parser import HTMLParser
from typing import Any

Payload = dict[str, Any]


def b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def headers_of(payload: Payload) -> dict[str, str]:
    """Header name (lower-case) -> value. First occurrence wins."""
    result: dict[str, str] = {}
    for header in payload.get("headers") or []:
        result.setdefault(header.get("name", "").lower(), header.get("value", ""))
    return result


def _charset(part: Payload) -> str:
    content_type = headers_of(part).get("content-type", "")
    msg = Message()
    msg["content-type"] = content_type or "text/plain"
    return msg.get_content_charset() or "utf-8"


def _decode_text(part: Payload) -> str:
    data = (part.get("body") or {}).get("data")
    if not data:
        return ""
    raw = b64url_decode(data)
    try:
        return raw.decode(_charset(part), errors="replace")
    except LookupError:  # unknown charset name
        return raw.decode("utf-8", errors="replace")


def _is_attachment(part: Payload) -> bool:
    body = part.get("body") or {}
    disposition = headers_of(part).get("content-disposition", "").lower()
    return (
        bool(part.get("filename"))
        or "attachment" in disposition
        or ("attachmentId" in body and not part.get("mimeType", "").startswith("text/"))
    )


@dataclass
class Bodies:
    text: str = ""
    html: str = ""


def extract_bodies(payload: Payload) -> Bodies:
    """Collect text/plain and text/html bodies from any nesting of multipart parts.

    In multipart/alternative, plain and HTML versions are kept separately; in
    multipart/mixed or related, sibling text parts are concatenated in order.
    """
    bodies = Bodies()

    def walk(part: Payload) -> None:
        mime_type = (part.get("mimeType") or "").lower()
        if mime_type.startswith("multipart/"):
            for child in part.get("parts") or []:
                walk(child)
            return
        if _is_attachment(part):
            return
        if mime_type == "text/plain":
            bodies.text += _decode_text(part)
        elif mime_type == "text/html":
            bodies.html += _decode_text(part)
        elif mime_type == "message/rfc822":
            for child in part.get("parts") or []:
                walk(child)

    walk(payload)
    return bodies


def body_as_text(payload: Payload) -> str:
    """Best plain-text rendering of a message: text/plain, else HTML converted."""
    bodies = extract_bodies(payload)
    if bodies.text.strip():
        return bodies.text.strip()
    return html_to_text(bodies.html) if bodies.html else ""


@dataclass
class AttachmentInfo:
    filename: str
    mime_type: str
    size: int
    attachment_id: str | None
    part_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size": self.size,
            "attachment_id": self.attachment_id,
            "part_id": self.part_id,
        }


def find_attachments(payload: Payload) -> list[AttachmentInfo]:
    found: list[AttachmentInfo] = []

    def walk(part: Payload) -> None:
        for child in part.get("parts") or []:
            walk(child)
        if part.get("parts"):
            return
        if _is_attachment(part):
            body = part.get("body") or {}
            found.append(
                AttachmentInfo(
                    filename=part.get("filename") or "attachment",
                    mime_type=part.get("mimeType") or "application/octet-stream",
                    size=int(body.get("size") or 0),
                    attachment_id=body.get("attachmentId"),
                    part_id=part.get("partId") or "",
                )
            )

    walk(payload)
    return found


def find_part(payload: Payload, part_id: str) -> Payload | None:
    if payload.get("partId") == part_id:
        return payload
    for child in payload.get("parts") or []:
        match = find_part(child, part_id)
        if match is not None:
            return match
    return None


class _TextExtractor(HTMLParser):
    _BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "hr"}
    _SKIP = {"script", "style", "head", "title"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self.chunks.append("\n")
        if tag == "li":
            self.chunks.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BLOCK:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.chunks.append(data)


def html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    text = html.unescape("".join(parser.chunks))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
