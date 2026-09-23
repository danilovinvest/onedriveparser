from pathlib import Path

import httpx
import pytest
import respx
from mcp import Client

from onedrive_mcp import server
from onedrive_mcp.config import load_settings
from onedrive_mcp.graph import GRAPH_BASE, GraphClient

NOTE = {"id": "ABC!7", "name": "note.txt", "size": 11, "file": {"mimeType": "text/plain"}}


@pytest.fixture
def fake_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = load_settings(
        {
            "ONEDRIVE_CLIENT_ID": "x",
            "ONEDRIVE_TOKEN_CACHE": str(tmp_path / "c.json"),
            "ONEDRIVE_MAX_TEXT_CHARS": "5",
        }
    )
    client = GraphClient(lambda: "tok", httpx.AsyncClient(follow_redirects=True))

    async def context() -> tuple[GraphClient, object]:
        return client, settings

    monkeypatch.setattr(server, "_context", context)


@pytest.mark.anyio
async def test_tools_are_registered_read_only() -> None:
    async with Client(server.server) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    assert set(tools) == {"list_folder", "search", "get_metadata", "read_file"}
    assert all(tool.annotations.read_only_hint for tool in tools.values())


@pytest.mark.anyio
@respx.mock
async def test_read_file_extracts_and_truncates(fake_context: None) -> None:
    respx.get(f"{GRAPH_BASE}/me/drive/root:/Docs/note.txt:").mock(
        return_value=httpx.Response(200, json=NOTE)
    )
    respx.get(f"{GRAPH_BASE}/me/drive/items/ABC!7/content").mock(
        return_value=httpx.Response(200, content=b"hello world")
    )
    async with Client(server.server) as client:
        result = await client.call_tool("read_file", {"path": "Docs/note.txt"})
    assert not result.is_error
    assert result.content[0].text.startswith("hello\n\n[truncated")


@pytest.mark.anyio
@respx.mock
async def test_graph_errors_reach_the_model(fake_context: None) -> None:
    respx.get(f"{GRAPH_BASE}/me/drive/root/search(q='x')").mock(
        return_value=httpx.Response(401, json={"error": {"message": "Token expired"}})
    )
    async with Client(server.server) as client:
        result = await client.call_tool("search", {"query": "x"})
    assert result.is_error
    assert "Token expired" in result.content[0].text


@pytest.mark.anyio
async def test_missing_config_is_explained(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ONEDRIVE_CLIENT_ID", raising=False)
    server._build_context.cache_clear()
    async with Client(server.server) as client:
        result = await client.call_tool("list_folder", {})
    assert result.is_error
    assert "ONEDRIVE_CLIENT_ID" in result.content[0].text


@pytest.mark.parametrize(("given", "expected"), [(-5, 1), (0, 1), (50, 50), (10**9, 1000)])
def test_limit_is_bounded(given: int, expected: int) -> None:
    assert server._bounded(given) == expected
