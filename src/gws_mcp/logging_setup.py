"""Logging to stderr with a redaction safety net.

stdout is the MCP stdio channel, so logs must never go there. The code never logs
credentials or message content on purpose; the filter below is a second line of
defence that scrubs anything token-shaped that slips through (e.g. from libraries).
"""

from __future__ import annotations

import logging
import re
import sys

REDACTED = "[REDACTED]"

_PATTERNS: tuple[re.Pattern[str], ...] = (
    # JSON / dict style secrets: "refresh_token": "..."
    re.compile(
        r"""(?P<key>["']?(?:access_token|refresh_token|id_token|client_secret|token|code)"""
        r"""["']?\s*[:=]\s*)["']?[^"',\s}]+["']?""",
        re.IGNORECASE,
    ),
    re.compile(r"(?P<key>Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    # Google access tokens and refresh tokens.
    re.compile(r"ya29\.[A-Za-z0-9._-]+"),
    re.compile(r"1//[A-Za-z0-9._-]{10,}"),
    # OAuth client secrets.
    re.compile(r"GOCSPX-[A-Za-z0-9_-]+"),
)


def redact(text: str) -> str:
    for pattern in _PATTERNS:
        if "key" in pattern.groupindex:
            text = pattern.sub(lambda m: f"{m.group('key')}{REDACTED}", text)
        else:
            text = pattern.sub(REDACTED, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        record.msg = redact(message)
        record.args = None
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

    # googleapiclient logs request URLs and bodies at DEBUG; keep it quiet.
    for noisy in ("googleapiclient", "google_auth_oauthlib", "urllib3", "oauthlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
