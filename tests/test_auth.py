import stat
from pathlib import Path

import msal
import pytest

from onedrive_mcp.auth import AuthError, TokenProvider, load_cache, save_cache
from onedrive_mcp.config import load_settings


def test_cache_file_is_private(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "cache.json"
    cache = msal.SerializableTokenCache()
    cache.has_state_changed = True
    save_cache(cache, path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_cache(path).serialize() == cache.serialize()


def test_cache_write_does_not_follow_symlink(tmp_path: Path) -> None:
    target = tmp_path / "attacker_owned.json"
    target.write_text("untouched")
    link = tmp_path / "cache.json"
    link.symlink_to(target)
    cache = msal.SerializableTokenCache()
    cache.has_state_changed = True
    save_cache(cache, link)
    assert target.read_text() == "untouched"
    assert not link.is_symlink()
    assert stat.S_IMODE(link.stat().st_mode) == 0o600


class FakeApp:
    """Stands in for msal.PublicClientApplication, which hits the network on init."""

    def __init__(self, accounts: list[dict], result: dict | None) -> None:
        self.accounts, self.result, self.scopes = accounts, result, None

    def get_accounts(self) -> list[dict]:
        return self.accounts

    def acquire_token_silent(self, scopes: list[str], account: dict) -> dict | None:
        self.scopes = scopes
        return self.result


def provider_with(tmp_path: Path, app: FakeApp) -> TokenProvider:
    settings = load_settings(
        {"ONEDRIVE_CLIENT_ID": "x", "ONEDRIVE_TOKEN_CACHE": str(tmp_path / "c.json")}
    )
    return TokenProvider(settings, app_factory=lambda _s, _c: app)


def test_get_token_without_login_asks_to_login(tmp_path: Path) -> None:
    with pytest.raises(AuthError, match="onedrive-mcp login"):
        provider_with(tmp_path, FakeApp([], None)).get_token()


def test_get_token_silent_success(tmp_path: Path) -> None:
    app = FakeApp([{"username": "me"}], {"access_token": "tok"})
    assert provider_with(tmp_path, app).get_token() == "tok"
    assert app.scopes == ["Files.Read", "User.Read"]


def test_get_token_silent_failure_explains(tmp_path: Path) -> None:
    app = FakeApp([{"username": "me"}], {"error_description": "refresh token expired"})
    with pytest.raises(AuthError, match="refresh token expired"):
        provider_with(tmp_path, app).get_token()
