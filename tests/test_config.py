from pathlib import Path

import pytest

from onedrive_mcp.config import DEFAULT_AUTHORITY, ConfigError, load_settings


def test_requires_client_id() -> None:
    with pytest.raises(ConfigError, match="ONEDRIVE_CLIENT_ID"):
        load_settings({})


def test_defaults() -> None:
    settings = load_settings({"ONEDRIVE_CLIENT_ID": " abc "})
    assert settings.client_id == "abc"
    assert settings.authority == DEFAULT_AUTHORITY
    assert "offline_access" not in settings.scopes  # reserved by msal


def test_overrides(tmp_path: Path) -> None:
    settings = load_settings(
        {
            "ONEDRIVE_CLIENT_ID": "abc",
            "ONEDRIVE_TOKEN_CACHE": str(tmp_path / "c.json"),
            "ONEDRIVE_MAX_DOWNLOAD_BYTES": "10",
            "ONEDRIVE_MAX_TEXT_CHARS": "5",
        }
    )
    assert settings.cache_path == tmp_path / "c.json"
    assert (settings.max_download_bytes, settings.max_text_chars) == (10, 5)


@pytest.mark.parametrize("value", ["abc", "0", "-3"])
def test_rejects_bad_limits(value: str) -> None:
    with pytest.raises(ConfigError, match="ONEDRIVE_MAX_TEXT_CHARS"):
        load_settings({"ONEDRIVE_CLIENT_ID": "x", "ONEDRIVE_MAX_TEXT_CHARS": value})
