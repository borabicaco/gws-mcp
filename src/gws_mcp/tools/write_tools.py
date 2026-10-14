"""Write tools. Registered only if at least one account has ``write = true``.

Every call is checked again by ``require_write`` (config AND granted scopes).
There are no tools to send email, send drafts, delete, or trash anything.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from gws_mcp.google_clients import GoogleClients
from gws_mcp.services import calendar_write, drive_write, gmail_write
from gws_mcp.tools import AccountArg, tool_errors
from gws_mcp.tools.guards import require_write

WRITE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
)
# Changing the user's own drafts is the one write that can alter user-authored content.
WRITE_USER_CONTENT = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True
)

Emails = Annotated[list[str], Field(description="Email addresses")]
OptionalEmails = Annotated[list[str] | None, Field(description="Email addresses")]
TimeArg = Annotated[
    str,
    Field(description="YYYY-MM-DD for all-day, or ISO 8601 like 2026-10-14T09:00 (local time)"),
]


def write_enabled_anywhere(clients: GoogleClients) -> bool:
    return any(a.write for a in clients.config.accounts.values())


def register(server: MCPServer, clients: GoogleClients) -> None:
    if not write_enabled_anywhere(clients):
        return

    # --- Gmail ---------------------------------------------------------------

    @server.tool(annotations=WRITE)
    @tool_errors
    def gmail_create_draft(
        to: Emails,
        subject: str,
        body: str,
        cc: OptionalEmails = None,
        bcc: OptionalEmails = None,
        account: AccountArg = None,
    ) -> dict[str, Any]:
        """Create a new email draft (plain text). It is NOT sent; the user sends it."""
        acct = require_write(clients, account)
        return gmail_write.create_draft(clients.gmail(acct), to, subject, body, cc, bcc)

    @server.tool(annotations=WRITE)
    @tool_errors
    def gmail_create_reply_draft(
        message_id: str,
        body: str,
        reply_all: bool = False,
        cc: OptionalEmails = None,
        account: AccountArg = None,
    ) -> dict[str, Any]:
        """Create a reply draft in the same conversation as message_id. It is NOT sent.

        Recipients, 'Re:' subject and threading headers are filled in automatically.
        """
        acct = require_write(clients, account)
        return gmail_write.create_reply_draft(clients.gmail(acct), message_id, body, reply_all, cc)

    @server.tool(annotations=WRITE)
    @tool_errors
    def gmail_update_draft(
        draft_id: str,
        to: OptionalEmails = None,
        cc: OptionalEmails = None,
        bcc: OptionalEmails = None,
        subject: str | None = None,
        body: str | None = None,
        account: AccountArg = None,
    ) -> dict[str, Any]:
        """Update a draft that Claude created. Omitted fields keep their current value.

        Drafts written by the user are refused; use gmail_update_user_draft for those.
        """
        acct = require_write(clients, account)
        return gmail_write.update_draft(
            clients.gmail(acct), draft_id, to=to, cc=cc, bcc=bcc, subject=subject, body=body
        )

    @server.tool(annotations=WRITE_USER_CONTENT)
    @tool_errors
    def gmail_update_user_draft(
        draft_id: str,
        expected_subject: Annotated[
            str, Field(description="The draft's current subject, exactly as read")
        ],
        to: OptionalEmails = None,
        cc: OptionalEmails = None,
        bcc: OptionalEmails = None,
        subject: str | None = None,
        body: str | None = None,
        account: AccountArg = None,
    ) -> dict[str, Any]:
        """Change a draft the USER wrote. Only use when the user explicitly asked to edit it.

        Read the draft first and pass its current subject as expected_subject.
        HTML formatting becomes plain text; drafts with attachments are refused.
        """
        acct = require_write(clients, account)
        return gmail_write.update_draft(
            clients.gmail(acct),
            draft_id,
            to=to,
            cc=cc,
            bcc=bcc,
            subject=subject,
            body=body,
            allow_user_draft=True,
            expected_subject=expected_subject,
        )

    @server.tool(annotations=WRITE)
    @tool_errors
    def gmail_modify_labels(
        message_id: str,
        add_labels: Annotated[list[str] | None, Field(description="Label names or ids")] = None,
        remove_labels: Annotated[list[str] | None, Field(description="Label names or ids")] = None,
        account: AccountArg = None,
    ) -> dict[str, Any]:
        """Add or remove labels on a message. TRASH and SPAM cannot be added."""
        acct = require_write(clients, account)
        return gmail_write.modify_labels(clients.gmail(acct), message_id, add_labels, remove_labels)

    @server.tool(annotations=WRITE)
    @tool_errors
    def gmail_create_label(name: str, account: AccountArg = None) -> dict[str, Any]:
        """Create a Gmail label (returns the existing one if the name is taken)."""
        acct = require_write(clients, account)
        return gmail_write.create_label(clients.gmail(acct), name)

    # --- Calendar ------------------------------------------------------------

    @server.tool(annotations=WRITE)
    @tool_errors
    def calendar_create_event(
        summary: str,
        start: TimeArg,
        end: Annotated[str | None, Field(description="Same format as start")] = None,
        description: str | None = None,
        location: str | None = None,
        attendees: OptionalEmails = None,
        calendar_id: str = "primary",
        account: AccountArg = None,
    ) -> dict[str, Any]:
        """Create an event. No invitation emails are sent to attendees."""
        acct = require_write(clients, account)
        return calendar_write.create_event(
            clients.calendar(acct),
            summary,
            start,
            end,
            calendar_id,
            description,
            location,
            attendees,
        )

    @server.tool(annotations=WRITE)
    @tool_errors
    def calendar_update_event(
        event_id: str,
        summary: str | None = None,
        start: Annotated[str | None, Field(description="Pass together with end")] = None,
        end: Annotated[str | None, Field(description="Pass together with start")] = None,
        description: str | None = None,
        location: str | None = None,
        attendees: Annotated[
            list[str] | None, Field(description="Replaces the whole attendee list")
        ] = None,
        calendar_id: str = "primary",
        account: AccountArg = None,
    ) -> dict[str, Any]:
        """Change an event's details. Only given fields change. No update emails are sent.

        Events cannot be cancelled or deleted with this server.
        """
        acct = require_write(clients, account)
        return calendar_write.update_event(
            clients.calendar(acct),
            event_id,
            calendar_id,
            summary,
            start,
            end,
            description,
            location,
            attendees,
        )

    # --- Drive -----------------------------------------------------------------

    @server.tool(annotations=WRITE)
    @tool_errors
    def drive_create_file(
        name: str,
        content: str,
        mime_type: str = "text/plain",
        parent_id: str | None = None,
        as_google_doc: Annotated[
            bool, Field(description="Convert the text into a Google Doc")
        ] = False,
        account: AccountArg = None,
    ) -> dict[str, Any]:
        """Create a NEW file from text. Existing files are never overwritten.

        Note: a parent folder may need to be one created by this server.
        """
        acct = require_write(clients, account)
        return drive_write.create_file(
            clients.drive(acct), name, content, mime_type, parent_id, as_google_doc
        )

    @server.tool(annotations=WRITE)
    @tool_errors
    def drive_create_folder(
        name: str, parent_id: str | None = None, account: AccountArg = None
    ) -> dict[str, Any]:
        """Create a new folder."""
        acct = require_write(clients, account)
        return drive_write.create_folder(clients.drive(acct), name, parent_id)
