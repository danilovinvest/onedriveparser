"""Minimal async Microsoft Graph client for the signed-in user's OneDrive."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
# Personal OneDrive ids look like "ABCDEF0123456789!123"; business ids are
# base32-ish. Anything else is rejected before it reaches a URL.
_ITEM_ID_RE = re.compile(r"^[A-Za-z0-9!._-]{1,256}$")
_ITEM_FIELDS = "id,name,size,file,folder,lastModifiedDateTime,webUrl,parentReference"


class GraphError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Graph API error {status}: {message}")
        self.status = status


@dataclass(frozen=True)
class DriveItem:
    id: str
    name: str
    kind: str  # "file" or "folder"
    size: int
    mime_type: str | None
    last_modified: str | None
    web_url: str | None
    parent_path: str | None

    @classmethod
    def from_graph(cls, raw: dict[str, Any]) -> DriveItem:
        return cls(
            id=raw["id"],
            name=raw.get("name", ""),
            kind="folder" if "folder" in raw else "file",
            size=int(raw.get("size", 0)),
            mime_type=(raw.get("file") or {}).get("mimeType"),
            last_modified=raw.get("lastModifiedDateTime"),
            web_url=raw.get("webUrl"),
            parent_path=(raw.get("parentReference") or {}).get("path"),
        )


def item_path(item_id: str | None = None, path: str | None = None) -> str:
    """Graph path addressing one item by id, by drive path, or the root."""
    if item_id:
        if not _ITEM_ID_RE.match(item_id):
            raise ValueError(f"Invalid item id: {item_id!r}")
        return f"/me/drive/items/{quote(item_id, safe='!')}"
    segments = [s for s in (path or "").split("/") if s]
    if not segments:
        return "/me/drive/root"
    if any(s in (".", "..") for s in segments):
        raise ValueError("Path must not contain '.' or '..' segments")
    return f"/me/drive/root:/{'/'.join(quote(s, safe='') for s in segments)}:"


def search_path(query: str) -> str:
    if not query.strip():
        raise ValueError("Search query must not be empty")
    escaped = query.replace("'", "''")  # OData string literal escaping
    return f"/me/drive/root/search(q='{quote(escaped, safe='')}')"


def _error_message(response: httpx.Response) -> str:
    try:
        return response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return response.text[:200] or response.reason_phrase


class GraphClient:
    def __init__(
        self,
        get_token: Callable[[], str],
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._get_token = get_token
        self._http = http or httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _headers(self) -> dict[str, str]:
        # msal may hit the network on refresh: keep it off the event loop.
        token = await asyncio.to_thread(self._get_token)
        return {"Authorization": f"Bearer {token}"}

    async def _get_json(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        if not url.startswith(GRAPH_BASE):
            raise GraphError(0, f"Refusing to send token to {url!r}")
        response = await self._http.get(url, params=params, headers=await self._headers())
        if response.status_code >= 400:
            raise GraphError(response.status_code, _error_message(response))
        return response.json()

    async def _collect(self, path: str, limit: int) -> list[DriveItem]:
        url: str | None = GRAPH_BASE + path
        params: dict[str, str] | None = {"$select": _ITEM_FIELDS, "$top": str(min(limit, 200))}
        items: list[DriveItem] = []
        while url and len(items) < limit:
            page = await self._get_json(url, params)
            items.extend(DriveItem.from_graph(raw) for raw in page.get("value", []))
            url = page.get("@odata.nextLink")
            params = None  # nextLink already carries the query string
        return items[:limit]

    async def get_item(self, item_id: str | None = None, path: str | None = None) -> DriveItem:
        raw = await self._get_json(
            GRAPH_BASE + item_path(item_id, path), {"$select": _ITEM_FIELDS}
        )
        return DriveItem.from_graph(raw)

    async def list_children(
        self, item_id: str | None = None, path: str | None = None, limit: int = 100
    ) -> list[DriveItem]:
        return await self._collect(item_path(item_id, path) + "/children", limit)

    async def search(self, query: str, limit: int = 25) -> list[DriveItem]:
        return await self._collect(search_path(query), limit)

    async def download(self, item: DriveItem, max_bytes: int) -> bytes:
        if item.kind != "file":
            raise ValueError(f"{item.name!r} is a folder, not a file")
        if item.size > max_bytes:
            raise ValueError(
                f"{item.name!r} is {item.size} bytes, above the {max_bytes} byte limit"
            )
        url = GRAPH_BASE + item_path(item.id) + "/content"
        chunks: list[bytes] = []
        received = 0
        # The 302 to the download host drops Authorization (httpx cross-origin rule).
        async with self._http.stream("GET", url, headers=await self._headers()) as response:
            if response.status_code >= 400:
                await response.aread()
                raise GraphError(response.status_code, _error_message(response))
            async for chunk in response.aiter_bytes():
                received += len(chunk)
                if received > max_bytes:
                    raise ValueError(f"{item.name!r} exceeded the {max_bytes} byte limit")
                chunks.append(chunk)
        return b"".join(chunks)
