"""Command line entry point: `onedrive-mcp {login,logout,serve}`."""

from __future__ import annotations

import argparse
import sys

from onedrive_mcp.auth import AuthError, TokenProvider
from onedrive_mcp.config import ConfigError, load_settings


def _login() -> int:
    provider = TokenProvider(load_settings())
    # stdout is reserved for MCP traffic when serving; keep prompts on stderr.
    user = provider.login(show=lambda msg: print(msg, file=sys.stderr))
    print(f"Signed in as {user}.", file=sys.stderr)
    return 0


def _logout() -> int:
    TokenProvider(load_settings()).logout()
    print("Signed out; cached tokens removed.", file=sys.stderr)
    return 0


def _serve() -> int:
    from onedrive_mcp.server import run

    run()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="onedrive-mcp")
    parser.add_argument("command", choices=("login", "logout", "serve"))
    args = parser.parse_args(argv)
    handlers = {"login": _login, "logout": _logout, "serve": _serve}
    try:
        return handlers[args.command]()
    except (ConfigError, AuthError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
