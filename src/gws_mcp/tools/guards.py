"""Two-layer write protection.

A write tool runs only if BOTH are true for the account:
1. ``write = true`` in the config, and
2. Google actually granted the write scopes to the stored token.
"""

from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError

from gws_mcp.config import AccountConfig
from gws_mcp.google_clients import GoogleClients
from gws_mcp.scopes import reauth_message


class WriteNotAllowedError(ToolError):
    """Raised when a write tool is called for an account that may not write."""


def require_write(clients: GoogleClients, alias: str | None) -> AccountConfig:
    account = clients.account(alias)
    if not account.write:
        raise WriteNotAllowedError(
            f"Write access is disabled for account '{account.alias}'. To enable it, set "
            f"write = true for this account in the config and run: gws-mcp auth {account.alias}"
        )
    if not clients.scope_status(account).can_write:
        raise WriteNotAllowedError(reauth_message(account.alias))
    return account
