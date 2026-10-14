"""Run the server over stdio for Claude Desktop."""

from __future__ import annotations

from gws_mcp.config import AppConfig
from gws_mcp.server import build_server


def run(config: AppConfig) -> None:
    # stdout carries the MCP protocol; logging is already configured to stderr.
    build_server(config).run("stdio")
