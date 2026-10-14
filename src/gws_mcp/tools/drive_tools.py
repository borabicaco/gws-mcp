"""Google Drive read tools."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from gws_mcp.google_clients import GoogleClients
from gws_mcp.services import drive
from gws_mcp.tools import READ_ONLY, AccountArg, tool_errors


def register(server: MCPServer, clients: GoogleClients) -> None:
    downloads = clients.config.downloads

    @server.tool(annotations=READ_ONLY)
    @tool_errors
    def drive_search(
        text: str | None = None,
        raw_query: str | None = None,
        max_results: int = 25,
        page_token: str | None = None,
        account: AccountArg = None,
    ) -> dict[str, Any]:
        """Search Drive (including shared drives); trashed files are excluded.

        text: full-text search over names and content.
        raw_query: Drive query syntax, e.g. "name contains 'budget'" or
        "'<folder_id>' in parents" or "mimeType = 'application/pdf'".
        """
        return drive.search_files(
            clients.drive(clients.account(account)), text, raw_query, max_results, page_token
        )

    @server.tool(annotations=READ_ONLY)
    @tool_errors
    def drive_recent_files(
        max_results: int = 25, account: AccountArg = None
    ) -> list[dict[str, Any]]:
        """List the most recently modified files."""
        return drive.recent_files(clients.drive(clients.account(account)), max_results)

    @server.tool(annotations=READ_ONLY)
    @tool_errors
    def drive_get_metadata(file_id: str, account: AccountArg = None) -> dict[str, Any]:
        """Get a file's metadata: name, type, size, owners, dates, link, parents."""
        return drive.get_metadata(clients.drive(clients.account(account)), file_id)

    @server.tool(annotations=READ_ONLY)
    @tool_errors
    def drive_read_file(file_id: str, account: AccountArg = None) -> dict[str, Any]:
        """Read a file's content.

        Google Docs and Slides are exported as plain text, Sheets as CSV (first sheet).
        Small text content is returned inline; PDFs and other files are saved to the
        downloads folder and the local path is returned.
        """
        return drive.read_file(
            clients.drive(clients.account(account)),
            file_id,
            downloads.dir,
            downloads.max_inline_bytes,
        )
