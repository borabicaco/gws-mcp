from __future__ import annotations

import base64

from gws_mcp.services.mime import (
    b64url_decode,
    body_as_text,
    extract_bodies,
    find_attachments,
    find_part,
    headers_of,
    html_to_text,
)


def b64(text: str, charset: str = "utf-8") -> str:
    # Gmail uses URL-safe base64 without padding.
    return base64.urlsafe_b64encode(text.encode(charset)).decode().rstrip("=")


def part(mime, data=None, *, part_id="0", charset=None, filename="", attachment_id=None, size=0):
    headers = []
    if charset:
        headers.append({"name": "Content-Type", "value": f"{mime}; charset={charset}"})
    body = {"size": size}
    if data is not None:
        body["data"] = data
    if attachment_id:
        body["attachmentId"] = attachment_id
    return {
        "partId": part_id,
        "mimeType": mime,
        "filename": filename,
        "headers": headers,
        "body": body,
    }


def multipart(mime, *children, part_id=""):
    return {
        "partId": part_id,
        "mimeType": mime,
        "headers": [],
        "body": {"size": 0},
        "parts": list(children),
    }


def test_b64url_decode_handles_missing_padding():
    assert b64url_decode(b64("hi")) == b"hi"


def test_simple_text_message():
    assert body_as_text(part("text/plain", b64("Hello"))) == "Hello"


def test_nested_mixed_alternative_with_attachment():
    payload = multipart(
        "multipart/mixed",
        multipart(
            "multipart/alternative",
            part("text/plain", b64("Plain body"), part_id="0.0"),
            part("text/html", b64("<p>HTML body</p>"), part_id="0.1"),
            part_id="0",
        ),
        part(
            "application/pdf", filename="invoice.pdf", attachment_id="ATT1", size=1234, part_id="1"
        ),
    )
    bodies = extract_bodies(payload)
    assert bodies.text == "Plain body"
    assert bodies.html == "<p>HTML body</p>"
    assert body_as_text(payload) == "Plain body"

    attachments = find_attachments(payload)
    assert [a.filename for a in attachments] == ["invoice.pdf"]
    assert attachments[0].attachment_id == "ATT1"
    assert attachments[0].size == 1234
    assert attachments[0].part_id == "1"


def test_deeply_nested_related_html_only_falls_back_to_html():
    payload = multipart(
        "multipart/mixed",
        multipart(
            "multipart/related",
            multipart(
                "multipart/alternative",
                part("text/html", b64("<div>Merhaba<br>Dünya</div><style>x{}</style>")),
            ),
            part("image/png", filename="logo.png", attachment_id="IMG", size=10, part_id="0.1"),
        ),
    )
    assert body_as_text(payload) == "Merhaba\nDünya"
    assert [a.filename for a in find_attachments(payload)] == ["logo.png"]


def test_non_utf8_charset_is_decoded():
    payload = part("text/plain", b64("Şişli ğüç", "iso-8859-9"), charset="iso-8859-9")
    assert body_as_text(payload) == "Şişli ğüç"


def test_unknown_charset_falls_back_to_utf8():
    payload = part("text/plain", b64("ok"), charset="x-made-up")
    assert body_as_text(payload) == "ok"


def test_text_attachment_is_not_part_of_body():
    payload = multipart(
        "multipart/mixed",
        part("text/plain", b64("Body")),
        part("text/plain", b64("file content"), filename="notes.txt", part_id="1"),
    )
    assert body_as_text(payload) == "Body"
    assert [a.filename for a in find_attachments(payload)] == ["notes.txt"]


def test_forwarded_message_body_is_included():
    payload = multipart(
        "multipart/mixed",
        part("text/plain", b64("See below. ")),
        {
            "partId": "1",
            "mimeType": "message/rfc822",
            "filename": "",
            "headers": [],
            "body": {"size": 0},
            "parts": [part("text/plain", b64("Original"))],
        },
    )
    assert body_as_text(payload) == "See below. Original"


def test_find_part_and_headers():
    inner = part("text/plain", b64("x"), part_id="0.1")
    payload = multipart("multipart/mixed", multipart("multipart/alternative", inner, part_id="0"))
    assert find_part(payload, "0.1") is inner
    assert find_part(payload, "9") is None
    assert headers_of(
        {"headers": [{"name": "Subject", "value": "A"}, {"name": "subject", "value": "B"}]}
    ) == {"subject": "A"}


def test_html_to_text():
    html = (
        "<html><head><title>T</title></head><body><h1>Hi</h1>"
        "<ul><li>a</li><li>b</li></ul>&amp; more<script>evil()</script></body></html>"
    )
    text = html_to_text(html)
    assert [line for line in text.splitlines() if line] == ["Hi", "- a", "- b", "& more"]
    assert "evil" not in text
