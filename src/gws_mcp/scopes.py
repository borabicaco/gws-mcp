"""OAuth scope sets for read-only and write modes.

Note: Google has no "drafts only" scope. ``gmail.modify`` also permits sending and
trashing, and ``calendar.events`` permits deleting. Those actions are blocked at the
tool layer: the server simply never implements send/delete/trash tools.
``drive.file`` only allows writing files this app created, so existing Drive files
can never be overwritten.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
CALENDAR_READONLY = "https://www.googleapis.com/auth/calendar.readonly"
DRIVE_READONLY = "https://www.googleapis.com/auth/drive.readonly"

GMAIL_MODIFY = "https://www.googleapis.com/auth/gmail.modify"
CALENDAR_EVENTS = "https://www.googleapis.com/auth/calendar.events"
DRIVE_FILE = "https://www.googleapis.com/auth/drive.file"

READ_SCOPES: tuple[str, ...] = (GMAIL_READONLY, CALENDAR_READONLY, DRIVE_READONLY)
WRITE_SCOPES: tuple[str, ...] = (GMAIL_MODIFY, CALENDAR_EVENTS, DRIVE_FILE)


def required_scopes(write: bool) -> list[str]:
    """Scopes to request from Google for an account with the given write setting."""
    return list(READ_SCOPES + WRITE_SCOPES) if write else list(READ_SCOPES)


@dataclass(frozen=True)
class ScopeStatus:
    """How the scopes granted by Google compare with what the config asks for."""

    can_read: bool
    can_write: bool
    missing: tuple[str, ...]

    @property
    def needs_reauth(self) -> bool:
        return bool(self.missing)


def scope_status(granted: Iterable[str] | None, write_enabled: bool) -> ScopeStatus:
    granted_set = set(granted or ())
    wanted = required_scopes(write_enabled)
    missing = tuple(s for s in wanted if s not in granted_set)
    return ScopeStatus(
        can_read=all(s in granted_set for s in READ_SCOPES),
        # Both layers must agree: write enabled in config AND write scopes granted.
        can_write=write_enabled and all(s in granted_set for s in WRITE_SCOPES),
        missing=missing,
    )


def reauth_message(alias: str) -> str:
    return (
        f"Account '{alias}' was authorized with different permissions than the config "
        f"requires. Re-authorize it with: gws-mcp auth {alias}"
    )
