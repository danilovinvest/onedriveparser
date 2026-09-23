import pytest

from onedrive_mcp import cli
from onedrive_mcp.auth import AuthError


class StubProvider:
    fail = False

    def __init__(self, _settings: object) -> None:
        pass

    def get_token(self) -> str:
        if StubProvider.fail:
            raise AuthError("Not signed in. Run `onedrive-mcp login` first.")
        return "tok"

    def account_name(self) -> str:
        return "me@x"


@pytest.fixture(autouse=True)
def stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEDRIVE_CLIENT_ID", "x")
    monkeypatch.setattr(cli, "TokenProvider", StubProvider)


def test_status_signed_in(capsys: pytest.CaptureFixture[str]) -> None:
    StubProvider.fail = False
    assert cli.main(["status"]) == 0
    captured = capsys.readouterr()
    assert "Signed in as me@x" in captured.err and captured.out == ""


def test_status_not_signed_in() -> None:
    StubProvider.fail = True
    assert cli.main(["status"]) == cli.EXIT_NOT_SIGNED_IN


def test_missing_client_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ONEDRIVE_CLIENT_ID")
    assert cli.main(["status"]) == 1
