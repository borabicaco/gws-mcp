"""Google Calendar read tools."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from gws_mcp.google_clients import GoogleClients
from gws_mcp.services import calendar
from gws_mcp.tools import READ_ONLY, AccountArg, tool_errors


def register(server: MCPServer, clients: GoogleClients) -> None:
    @server.tool(annotations=READ_ONLY)
    @tool_errors
    def calendar_list_calendars(account: AccountArg = None) -> list[dict[str, Any]]:
        """List the calendars the account can see."""
        return calendar.list_calendars(clients.calendar(clients.account(account)))

    @server.tool(annotations=READ_ONLY)
    @tool_errors
    def calendar_list_events(
        time_min: str | None = None,
        time_max: str | None = None,
        calendar_id: str = "primary",
        max_results: int = 50,
        account: AccountArg = None,
    ) -> list[dict[str, Any]]:
        """List events in a date range (YYYY-MM-DD or ISO 8601). Defaults to the next 7 days.

        Recurring events are expanded into individual occurrences.
        """
        return calendar.list_events(
            clients.calendar(clients.account(account)),
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            max_results=max_results,
        )

    @server.tool(annotations=READ_ONLY)
    @tool_errors
    def calendar_search_events(
        query: str,
        time_min: str | None = None,
        time_max: str | None = None,
        calendar_id: str = "primary",
        max_results: int = 50,
        account: AccountArg = None,
    ) -> list[dict[str, Any]]:
        """Search events by keyword (title, description, location, attendees).

        Defaults to one year back and one year ahead.
        """
        return calendar.search_events(
            clients.calendar(clients.account(account)),
            query,
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            max_results=max_results,
        )

    @server.tool(annotations=READ_ONLY)
    @tool_errors
    def calendar_get_event(
        event_id: str, calendar_id: str = "primary", account: AccountArg = None
    ) -> dict[str, Any]:
        """Get one event in detail: description, attendees and responses, Meet link."""
        return calendar.get_event(clients.calendar(clients.account(account)), event_id, calendar_id)
