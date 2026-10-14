"""MCP tool layer: thin wrappers that resolve the account and call ``services``."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Annotated, Any, ParamSpec, TypeVar

from googleapiclient.errors import HttpError
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from gws_mcp.auth.credentials import NotAuthorizedError
from gws_mcp.auth.token_store import TokenStoreError
from gws_mcp.config import ConfigError
from gws_mcp.google_clients import GoogleClients
from gws_mcp.services.calendar import CalendarError
from gws_mcp.services.drive import DriveError
from gws_mcp.services.gmail import GmailError

log = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

AccountArg = Annotated[
    str | None,
    Field(description="Account alias from the config (e.g. 'work'). Omit to use the default."),
]

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True)

_EXPECTED = (
    ConfigError,
    NotAuthorizedError,
    TokenStoreError,
    GmailError,
    CalendarError,
    DriveError,
    ConnectionError,
)


def _http_error_message(exc: HttpError) -> str:
    status = getattr(exc, "status_code", None) or exc.resp.status
    reason = exc.reason if isinstance(exc.reason, str) else ""
    if status == 403 and "insufficient" in reason.lower():
        return "Google refused the request: the account lacks the required permission (scope)."
    if status == 404:
        return "Not found: check the id and the account."
    return f"Google API error {status}: {reason or 'request failed'}"


def tool_errors[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    """Turn anticipated failures into ToolError so the model sees a useful message."""

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except _EXPECTED as exc:
            raise ToolError(str(exc)) from None
        except HttpError as exc:
            message = _http_error_message(exc)
            log.info("%s failed: %s", fn.__name__, message)
            raise ToolError(message) from None

    return wrapper


def register_tools(server: MCPServer, clients: GoogleClients) -> None:
    from gws_mcp.tools import calendar_tools, drive_tools, gmail_tools, write_tools

    @server.tool(annotations=READ_ONLY)
    @tool_errors
    def list_accounts() -> list[dict[str, Any]]:
        """List the configured Google accounts, which one is default and whether write is on."""
        config = clients.config
        default = config.default_account or (
            config.aliases[0] if len(config.aliases) == 1 else None
        )
        return [
            {
                "account": a.alias,
                "email": a.email,
                "default": a.alias == default,
                "write_enabled": a.write,
            }
            for a in config.accounts.values()
        ]

    gmail_tools.register(server, clients)
    calendar_tools.register(server, clients)
    drive_tools.register(server, clients)
    write_tools.register(server, clients)  # no-op unless an account has write = true
