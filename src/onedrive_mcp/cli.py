"""Command line entry point: `onedrive-mcp {login,logout,status,serve}`."""

from __future__ import annotations

import argparse
import sys
import webbrowser

from onedrive_mcp.auth import AuthError, TokenProvider
from onedrive_mcp.config import ConfigError, load_settings

EXIT_NOT_SIGNED_IN = 3


def _err(message: str) -> None:
    # stdout is reserved for MCP traffic when serving; keep messages on stderr.
    print(message, file=sys.stderr)


def _login(args: argparse.Namespace) -> int:
    provider = TokenProvider(load_settings())
    open_url = webbrowser.open if args.open_browser else None
    user = provider.login(show=_err, open_url=open_url)
    _err(f"Signed in as {user}.")
    return 0


def _logout(_args: argparse.Namespace) -> int:
    TokenProvider(load_settings()).logout()
    _err("Signed out; cached tokens removed.")
    return 0


def _status(_args: argparse.Namespace) -> int:
    provider = TokenProvider(load_settings())
    try:
        provider.get_token()  # proves the refresh token still works
    except AuthError as exc:
        _err(str(exc))
        return EXIT_NOT_SIGNED_IN
    _err(f"Signed in as {provider.account_name()}.")
    return 0


def _serve(_args: argparse.Namespace) -> int:
    from onedrive_mcp.server import run

    run()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="onedrive-mcp")
    parser.add_argument("command", choices=("login", "logout", "status", "serve"))
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="login: open the sign-in page in the default browser",
    )
    args = parser.parse_args(argv)
    handlers = {"login": _login, "logout": _logout, "status": _status, "serve": _serve}
    try:
        return handlers[args.command](args)
    except (ConfigError, AuthError) as exc:
        _err(f"error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
