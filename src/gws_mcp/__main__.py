"""Command-line entry point: ``gws-mcp serve | auth <alias> | accounts | gen-key``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gws_mcp import __version__
from gws_mcp.auth.credentials import NotAuthorizedError, account_scope_status, load_credentials
from gws_mcp.auth.oauth_flow import AuthFlowError, run_auth_flow
from gws_mcp.auth.token_store import TokenStoreError, generate_key, make_token_store
from gws_mcp.config import ConfigError, load_config
from gws_mcp.logging_setup import configure_logging
from gws_mcp.scopes import reauth_message


def _cmd_accounts(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    store = make_token_store(config.storage)
    default = config.default_account or (config.aliases[0] if len(config.aliases) == 1 else None)
    for account in config.accounts.values():
        marker = "*" if account.alias == default else " "
        write = "write=on " if account.write else "write=off"
        try:
            creds = load_credentials(account, store)
        except NotAuthorizedError:
            status = "not authorized"
        except (TokenStoreError, ConnectionError) as exc:
            status = f"error: {exc}"
        else:
            scopes = account_scope_status(account, creds)
            status = "re-auth needed" if scopes.needs_reauth else "authorized"
        print(f"{marker} {account.alias:<16} {account.email:<36} {write}  {status}")
    return 0


def _cmd_gen_key(_: argparse.Namespace) -> int:
    print(generate_key())
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    from gws_mcp.entrypoints import stdio

    stdio.run(load_config(args.config))
    return 0


def _cmd_auth(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    account = config.resolve_account(args.alias)
    store = make_token_store(config.storage)
    mode = "read + write" if account.write else "read-only"
    print(f"Authorizing '{account.alias}' ({account.email}, {mode}). A browser window will open.")
    status = run_auth_flow(account, store, open_browser=not args.no_browser)
    if status.needs_reauth:
        print("Warning: some permissions were not granted. " + reauth_message(account.alias))
        return 1
    print(f"Done. Account '{account.alias}' is authorized ({mode}).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gws-mcp", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", type=Path, help="config file path")
    parser.add_argument("--log-level", default="WARNING", help="log level (logs go to stderr)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="run the MCP server over stdio").set_defaults(func=_cmd_serve)

    auth = sub.add_parser("auth", help="authorize an account in the browser")
    auth.add_argument("alias", help="account alias from the config file")
    auth.add_argument("--no-browser", action="store_true", help="print the URL instead")
    auth.set_defaults(func=_cmd_auth)

    sub.add_parser("accounts", help="list configured accounts").set_defaults(func=_cmd_accounts)
    sub.add_parser(
        "gen-key", help="print a new key for the encrypted_file token backend"
    ).set_defaults(func=_cmd_gen_key)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level.upper())
    try:
        return args.func(args)
    except (ConfigError, TokenStoreError, AuthFlowError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
