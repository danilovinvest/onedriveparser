import httpx
import pytest
import respx

from onedrive_mcp.graph import (
    GRAPH_BASE,
    DriveItem,
    GraphClient,
    GraphError,
    item_path,
    search_path,
)

FILE = {"id": "ABC!12", "name": "a.txt", "size": 5, "file": {"mimeType": "text/plain"}}
FOLDER = {"id": "ABC!1", "name": "Docs", "size": 0, "folder": {"childCount": 1}}


def make_client() -> GraphClient:
    return GraphClient(lambda: "tok", httpx.AsyncClient(follow_redirects=True))


def test_item_path_variants() -> None:
    assert item_path() == "/me/drive/root"
    assert item_path(path="/") == "/me/drive/root"
    assert item_path(item_id="ABC!12") == "/me/drive/items/ABC!12"
    assert item_path(path="My Docs/été.pdf") == "/me/drive/root:/My%20Docs/%C3%A9t%C3%A9.pdf:"


@pytest.mark.parametrize("bad", ["../x", "a/b?c", "x y", ""])
def test_item_path_rejects_bad_ids(bad: str) -> None:
    if bad == "":
        assert item_path(item_id=bad) == "/me/drive/root"
        return
    with pytest.raises(ValueError):
        item_path(item_id=bad)


def test_item_path_rejects_dot_segments() -> None:
    with pytest.raises(ValueError):
        item_path(path="Docs/../secret")


def test_search_path_escapes_quotes() -> None:
    assert search_path("l'été") == "/me/drive/root/search(q='l%27%27%C3%A9t%C3%A9')"
    with pytest.raises(ValueError):
        search_path("  ")


def test_drive_item_kind() -> None:
    assert DriveItem.from_graph(FOLDER).kind == "folder"
    assert DriveItem.from_graph(FILE).mime_type == "text/plain"


@pytest.mark.anyio
@respx.mock
async def test_list_children_follows_pagination_and_sends_token() -> None:
    next_link = f"{GRAPH_BASE}/me/drive/root/children?$skiptoken=2"
    # respx matches in registration order and a query-less route matches any
    # query string, so the more specific next page must be declared first.
    respx.get(next_link).mock(return_value=httpx.Response(200, json={"value": [FILE]}))
    first = respx.get(f"{GRAPH_BASE}/me/drive/root/children").mock(
        return_value=httpx.Response(200, json={"value": [FOLDER], "@odata.nextLink": next_link})
    )
    items = await make_client().list_children()
    assert [i.name for i in items] == ["Docs", "a.txt"]
    assert first.calls[0].request.headers["Authorization"] == "Bearer tok"


@pytest.mark.anyio
@respx.mock
async def test_refuses_next_link_outside_graph() -> None:
    respx.get(f"{GRAPH_BASE}/me/drive/root/children").mock(
        return_value=httpx.Response(
            200, json={"value": [FILE], "@odata.nextLink": "https://evil.example/x"}
        )
    )
    with pytest.raises(GraphError, match="Refusing"):
        await make_client().list_children(limit=10)


@pytest.mark.anyio
@respx.mock
async def test_graph_error_message_is_surfaced() -> None:
    respx.get(f"{GRAPH_BASE}/me/drive/items/NOPE").mock(
        return_value=httpx.Response(404, json={"error": {"message": "Item not found"}})
    )
    with pytest.raises(GraphError, match="404: Item not found"):
        await make_client().get_item("NOPE")


@pytest.mark.anyio
@respx.mock
async def test_download_follows_redirect_without_token() -> None:
    respx.get(f"{GRAPH_BASE}/me/drive/items/ABC!12/content").mock(
        return_value=httpx.Response(302, headers={"Location": "https://dl.example/f"})
    )
    download = respx.get("https://dl.example/f").mock(
        return_value=httpx.Response(200, content=b"hello")
    )
    data = await make_client().download(DriveItem.from_graph(FILE), max_bytes=100)
    assert data == b"hello"
    assert "Authorization" not in download.calls[0].request.headers


@pytest.mark.anyio
async def test_download_rejects_large_files_and_folders() -> None:
    client = make_client()
    with pytest.raises(ValueError, match="limit"):
        await client.download(DriveItem.from_graph(FILE), max_bytes=4)
    with pytest.raises(ValueError, match="folder"):
        await client.download(DriveItem.from_graph(FOLDER), max_bytes=100)


@pytest.mark.anyio
@respx.mock
async def test_download_caps_stream_when_size_lies() -> None:
    respx.get(f"{GRAPH_BASE}/me/drive/items/ABC!12/content").mock(
        return_value=httpx.Response(200, content=b"x" * 50)
    )
    with pytest.raises(ValueError, match="exceeded"):
        await make_client().download(DriveItem.from_graph(FILE), max_bytes=10)
