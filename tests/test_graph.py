import json

import httpx
import pytest
import respx

from onedrive_mcp.graph import (
    GRAPH_BASE,
    MAX_UPLOAD_BYTES,
    DriveItem,
    GraphClient,
    GraphError,
    item_path,
    search_path,
    split_path,
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


@pytest.mark.parametrize("bad", ["../x", "a/b?c", "x y", ".", "..", ""])
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
async def test_refuses_lookalike_graph_host() -> None:
    with pytest.raises(GraphError, match="Refusing"):
        await make_client()._get_json(f"{GRAPH_BASE}.evil.example/me")


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


def test_split_path() -> None:
    assert split_path("/Docs/Taxes/a.txt") == ("Docs/Taxes", "a.txt")
    assert split_path("a.txt") == ("", "a.txt")


@pytest.mark.parametrize("bad", ["", "/", "Docs/a:b.txt", "Docs/..", "Docs/a?.txt", "Docs/ "])
def test_split_path_rejects_bad_names(bad: str) -> None:
    with pytest.raises(ValueError):
        split_path(bad)


@pytest.mark.anyio
@respx.mock
@pytest.mark.parametrize(("overwrite", "behavior"), [(False, "fail"), (True, "replace")])
async def test_upload_sends_bytes_and_conflict_behavior(overwrite: bool, behavior: str) -> None:
    route = respx.put(f"{GRAPH_BASE}/me/drive/root:/Docs/a.txt:/content").mock(
        return_value=httpx.Response(201, json=FILE)
    )
    item = await make_client().upload("Docs/a.txt", b"hello", overwrite=overwrite)
    request = route.calls[0].request
    assert item.id == "ABC!12"
    assert request.content == b"hello"
    assert request.url.params["@microsoft.graph.conflictBehavior"] == behavior
    assert request.headers["Authorization"] == "Bearer tok"


@pytest.mark.anyio
async def test_upload_rejects_oversized_content_and_missing_name() -> None:
    client = make_client()
    with pytest.raises(ValueError, match="upload limit"):
        await client.upload("a.txt", b"x" * (MAX_UPLOAD_BYTES + 1))
    with pytest.raises(ValueError, match="name"):
        await client.upload("/", b"x")


@pytest.mark.anyio
@respx.mock
async def test_upload_conflict_is_surfaced() -> None:
    respx.put(f"{GRAPH_BASE}/me/drive/root:/a.txt:/content").mock(
        return_value=httpx.Response(409, json={"error": {"message": "Name already exists"}})
    )
    with pytest.raises(GraphError, match="409: Name already exists"):
        await make_client().upload("a.txt", b"x")


@pytest.mark.anyio
@respx.mock
async def test_create_folder_posts_to_parent() -> None:
    nested = respx.post(f"{GRAPH_BASE}/me/drive/root:/Docs:/children").mock(
        return_value=httpx.Response(201, json=FOLDER)
    )
    at_root = respx.post(f"{GRAPH_BASE}/me/drive/root/children").mock(
        return_value=httpx.Response(201, json=FOLDER)
    )
    client = make_client()
    assert (await client.create_folder("Docs/Taxes")).kind == "folder"
    await client.create_folder("Taxes")
    expected = {"name": "Taxes", "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}
    assert json.loads(nested.calls[0].request.content) == expected
    assert json.loads(at_root.calls[0].request.content) == expected


@pytest.mark.anyio
@respx.mock
async def test_update_item_renames_and_moves() -> None:
    route = respx.patch(f"{GRAPH_BASE}/me/drive/items/ABC!12").mock(
        return_value=httpx.Response(200, json=FILE)
    )
    await make_client().update_item("ABC!12", new_name="b.txt", new_parent_id="ABC!1")
    assert json.loads(route.calls[0].request.content) == {
        "name": "b.txt",
        "parentReference": {"id": "ABC!1"},
    }


@pytest.mark.anyio
async def test_update_item_validates_arguments() -> None:
    client = make_client()
    with pytest.raises(ValueError, match="new name"):
        await client.update_item("ABC!12")
    with pytest.raises(ValueError, match="path or an item_id"):
        await client.update_item(path="/", new_name="x")
    with pytest.raises(ValueError, match="must not contain"):
        await client.update_item("ABC!12", new_name="a/b")


@pytest.mark.anyio
@respx.mock
async def test_delete_item_by_path_and_refuses_root() -> None:
    route = respx.delete(f"{GRAPH_BASE}/me/drive/root:/Docs/a.txt:").mock(
        return_value=httpx.Response(204)
    )
    client = make_client()
    await client.delete_item(path="Docs/a.txt")
    assert route.called
    for root in ("", "/", None):
        with pytest.raises(ValueError, match="path or an item_id"):
            await client.delete_item(path=root)
    for root_id in ("root", "ROOT"):
        with pytest.raises(ValueError, match="root cannot be changed"):
            await client.delete_item(root_id)
        with pytest.raises(ValueError, match="root cannot be changed"):
            await client.update_item(root_id, new_name="x")
