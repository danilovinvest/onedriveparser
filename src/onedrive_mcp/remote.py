"""Streamable HTTP transport for remote clients (claude.ai custom connectors).

claude.ai custom connectors cannot send headers, so the secret lives in the
URL: the MCP endpoint is `/mcp/<token>`. Every other path answers a bare 404.
"""

from __future__ import annotations

import hmac
import logging
import os
import re
from collections.abc import Mapping

from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

from onedrive_mcp.config import ConfigError

TOKEN_ENV = "ONEDRIVE_MCP_TOKEN"
PORT_ENV = "ONEDRIVE_MCP_PORT"
DEFAULT_PORT = 8000
MIN_TOKEN_LENGTH = 32
PREFIX = "/mcp/"
INNER_PATH = "/mcp"
_TOKEN_CHARS = re.compile(r"[A-Za-z0-9_-]+")
_SECRET_SEGMENT = re.compile(r"/mcp/[^\s?\"]*")


def load_token(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    token = env.get(TOKEN_ENV, "").strip()
    if not token:
        raise ConfigError(
            f"{TOKEN_ENV} is not set. Generate one with: "
            'python -c "import secrets;print(secrets.token_hex(32))"'
        )
    if len(token) < MIN_TOKEN_LENGTH:
        raise ConfigError(f"{TOKEN_ENV} must be at least {MIN_TOKEN_LENGTH} characters long.")
    if not _TOKEN_CHARS.fullmatch(token):
        raise ConfigError(f"{TOKEN_ENV} may only contain letters, digits, '-' and '_'.")
    return token


def load_port(env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    raw = env.get(PORT_ENV, "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{PORT_ENV} must be an integer, got {raw!r}") from exc
    if not 0 < port < 65536:
        raise ConfigError(f"{PORT_ENV} must be a TCP port, got {port}")
    return port


def mask(text: str) -> str:
    """Hide the secret path segment wherever a path may be logged."""
    return _SECRET_SEGMENT.sub("/mcp/***", text)


class TokenGate:
    """Let `/mcp/<token>` through as `/mcp`, answer an empty 404 to anything else.

    The token is compared in constant time; routing on it with a plain path
    match would leak its prefix through response timing.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self._app = app
        self._token = token.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)  # lifespan starts the session manager
            return
        path: str = scope["path"]
        candidate = path[len(PREFIX) :] if path.startswith(PREFIX) else ""
        if scope["type"] == "http" and hmac.compare_digest(candidate.encode(), self._token):
            inner = dict(scope, path=INNER_PATH, raw_path=INNER_PATH.encode())
            await self._app(inner, receive, send)
            return
        await _not_found(scope, send)


async def _not_found(scope: Scope, send: Send) -> None:
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1008})
        return
    await send({"type": "http.response.start", "status": 404, "headers": [(b"content-length", b"0")]})
    await send({"type": "http.response.body", "body": b""})


class _MaskSecretPath(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(mask(a) if isinstance(a, str) else a for a in record.args)
        record.msg = mask(str(record.msg))
        return True


def build_app(token: str) -> ASGIApp:
    from onedrive_mcp.server import server

    inner = server.streamable_http_app(
        streamable_http_path=INNER_PATH,
        stateless_http=True,
        json_response=True,
        # Reached through a reverse proxy whose public Host we don't know here;
        # the URL secret is the access control.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        host="0.0.0.0",
    )
    return TokenGate(inner, token)


def run(env: Mapping[str, str] | None = None) -> None:
    import uvicorn

    token = load_token(env)
    port = load_port(env)
    config = uvicorn.Config(build_app(token), host="0.0.0.0", port=port, log_level="info")
    # Config() applies uvicorn's logging setup: add the filter after it.
    secret_filter = _MaskSecretPath()
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).addFilter(secret_filter)
    uvicorn.Server(config).run()
