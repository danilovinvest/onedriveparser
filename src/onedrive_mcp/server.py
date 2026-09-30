"""MCP server exposing OneDrive read and write tools over stdio."""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from onedrive_mcp.auth import AuthError, TokenProvider
from onedrive_mcp.config import ConfigError, Settings, load_settings
from onedrive_mcp.extract import UnsupportedFormat, extract_text, truncate
from onedrive_mcp.graph import GraphClient, GraphError

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True)
MAX_LIMIT = 1000

server = MCPServer(
    "onedrive",
    instructions=(
        "Read and write access to the user's personal OneDrive. Use `search` or "
        "`list_folder` to find items, then `read_file` with the item id. "
        "`write_file`, `create_folder`, `move_item` and `delete_item` change the "
        "drive: confirm with the user before overwriting or deleting."
    ),
)


@functools.cache
def _build_context() -> tuple[GraphClient, Settings]:
    """Built on first tool call so the server starts even before login."""
    settings = load_settings()
    return GraphClient(TokenProvider(settings).get_token), settings


async def _context() -> tuple[GraphClient, Settings]:
    # msal fetches the authority's OpenID config on init: keep it off the loop.
    return await asyncio.to_thread(_build_context)


async def _client() -> GraphClient:
    return (await _context())[0]


def _bounded(limit: int) -> int:
    """`limit` comes from the model: never let it walk the whole drive."""
    return max(1, min(limit, MAX_LIMIT))


def _user_errors[**P, R](fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Surface expected failures to the model instead of a masked error."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await fn(*args, **kwargs)
        except (AuthError, ConfigError, GraphError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


@server.tool(annotations=READ_ONLY)
@_user_errors
async def list_folder(
    path: str = "", item_id: str = "", limit: int = 100
) -> list[dict[str, Any]]:
    """List a OneDrive folder. Give a drive path like "Documents/Taxes" or an
    item id; leave both empty for the root. `limit` is capped at 1000."""
    client = await _client()
    items = await client.list_children(item_id or None, path or None, _bounded(limit))
    return [asdict(item) for item in items]


@server.tool(annotations=READ_ONLY)
@_user_errors
async def search(query: str, limit: int = 25) -> list[dict[str, Any]]:
    """Search file and folder names and contents across the whole OneDrive."""
    client = await _client()
    return [asdict(item) for item in await client.search(query, _bounded(limit))]


@server.tool(annotations=READ_ONLY)
@_user_errors
async def get_metadata(path: str = "", item_id: str = "") -> dict[str, Any]:
    """Get metadata (size, type, dates, web link) for one item."""
    client = await _client()
    return asdict(await client.get_item(item_id or None, path or None))


@server.tool(annotations=READ_ONLY)
@_user_errors
async def read_file(path: str = "", item_id: str = "") -> str:
    """Download a file and return its text. Supports pdf, docx, xlsx and
    plain-text formats; long content is truncated."""
    if not (path or item_id):
        raise ValueError("Give a path or an item_id")
    client, settings = await _context()
    item = await client.get_item(item_id or None, path or None)
    data = await client.download(item, settings.max_download_bytes)
    try:
        text = extract_text(item.name, data, item.mime_type)
    except UnsupportedFormat:
        raise
    except Exception as exc:  # corrupt or encrypted document
        raise ValueError(f"Could not parse {item.name!r}: {exc}") from exc
    return truncate(text, settings.max_text_chars)


@server.tool(annotations=DESTRUCTIVE)
@_user_errors
async def write_file(path: str, content: str, overwrite: bool = False) -> dict[str, Any]:
    """Create a UTF-8 text file at a drive path like "Documents/notes.md" (the
    parent folder must exist). Fails if the file exists unless `overwrite` is
    true, which replaces its content. Limited to 4 MB."""
    client = await _client()
    return asdict(await client.upload(path, content.encode("utf-8"), overwrite))


@server.tool(annotations=WRITE)
@_user_errors
async def create_folder(path: str) -> dict[str, Any]:
    """Create a folder at a drive path like "Documents/Taxes/2026" (the parent
    folder must exist). Fails if an item with that name already exists."""
    client = await _client()
    return asdict(await client.create_folder(path))


@server.tool(annotations=WRITE)
@_user_errors
async def move_item(
    path: str = "",
    item_id: str = "",
    destination_path: str = "",
    destination_id: str = "",
    new_name: str = "",
) -> dict[str, Any]:
    """Move and/or rename one item. Give the destination folder as a drive
    path ("/" for the root) or an item id to move it, `new_name` to rename it,
    or both. Fails if the target name is already taken."""
    if destination_path and destination_id:
        raise ValueError("Give destination_path or destination_id, not both")
    client = await _client()
    if destination_path:
        destination_id = (await client.get_item(path=destination_path)).id
    item = await client.update_item(
        item_id or None, path or None, new_name or None, destination_id or None
    )
    return asdict(item)


@server.tool(annotations=DESTRUCTIVE)
@_user_errors
async def delete_item(path: str = "", item_id: str = "") -> str:
    """Delete one file or folder (with everything in it). The item goes to the
    OneDrive recycle bin, where the user can restore it."""
    client = await _client()
    await client.delete_item(item_id or None, path or None)
    return f"Deleted {item_id or path} (moved to the recycle bin)"


def run() -> None:
    server.run("stdio")
