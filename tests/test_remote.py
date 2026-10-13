import logging
from collections.abc import Iterator

import pytest
from starlette.testclient import TestClient

from onedrive_mcp import cli, remote
from onedrive_mcp.config import ConfigError

TOKEN = "a" * 64
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
HEADERS = {"accept": "application/json, text/event-stream"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(remote.build_app(TOKEN)) as c:
        yield c


@pytest.mark.parametrize("env", [{}, {"ONEDRIVE_MCP_TOKEN": ""}, {"ONEDRIVE_MCP_TOKEN": "x" * 31}])
def test_missing_or_short_token_refused(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        remote.load_token(env)


def test_token_with_url_unsafe_chars_refused() -> None:
    with pytest.raises(ConfigError):
        remote.load_token({"ONEDRIVE_MCP_TOKEN": "a" * 32 + "/x"})


def test_serve_http_refuses_to_start_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ONEDRIVE_MCP_TOKEN", raising=False)
    assert cli.main(["serve-http"]) == 1


def test_port_defaults_and_validation() -> None:
    assert remote.load_port({}) == 8000
    assert remote.load_port({"ONEDRIVE_MCP_PORT": "9000"}) == 9000
    with pytest.raises(ConfigError):
        remote.load_port({"ONEDRIVE_MCP_PORT": "abc"})


@pytest.mark.parametrize(
    "path",
    ["/", "/mcp", "/mcp/", f"/mcp/{'b' * 64}", f"/mcp/{TOKEN[:-1]}", f"/mcp/{TOKEN}/", f"/x/mcp/{TOKEN}"],
)
def test_wrong_path_is_bare_404(client: TestClient, path: str) -> None:
    response = client.post(path, json=INIT, headers=HEADERS)
    assert response.status_code == 404
    assert response.content == b""


def test_right_token_reaches_mcp(client: TestClient) -> None:
    response = client.post(f"/mcp/{TOKEN}", json=INIT, headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert body["result"]["serverInfo"]["name"] == "onedrive"


def test_right_token_lists_tools(client: TestClient) -> None:
    client.post(f"/mcp/{TOKEN}", json=INIT, headers=HEADERS)
    response = client.post(
        f"/mcp/{TOKEN}",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers={**HEADERS, "mcp-protocol-version": "2025-06-18"},
    )
    assert response.status_code == 200
    names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert {"list_folder", "read_file", "write_file"} <= names


def test_mask_hides_the_token() -> None:
    line = f'1.2.3.4 - "POST /mcp/{TOKEN} HTTP/1.1" 200'
    assert TOKEN not in remote.mask(line)
    record = logging.LogRecord("uvicorn.access", 20, "", 0, '%s "%s %s"', ("ip", "POST", f"/mcp/{TOKEN}"), None)
    remote._MaskSecretPath().filter(record)
    assert TOKEN not in record.getMessage()
