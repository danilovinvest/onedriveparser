"""Runtime settings, read from environment variables only."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Personal Microsoft accounts only (outlook.com, hotmail.com, live.com).
DEFAULT_AUTHORITY = "https://login.microsoftonline.com/consumers"
# offline_access / openid / profile are reserved: msal adds them itself.
SCOPES = ("Files.Read", "User.Read")
DEFAULT_CACHE_PATH = Path.home() / ".config" / "onedrive-mcp" / "token_cache.json"
DEFAULT_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_TEXT_CHARS = 100_000


class ConfigError(RuntimeError):
    """Raised when required settings are missing or invalid."""


@dataclass(frozen=True)
class Settings:
    client_id: str
    authority: str
    cache_path: Path
    max_download_bytes: int
    max_text_chars: int
    scopes: tuple[str, ...] = SCOPES


def _positive_int(env: dict[str, str], key: str, default: int) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{key} must be positive, got {value}")
    return value


def load_settings(env: dict[str, str] | None = None) -> Settings:
    env = dict(os.environ) if env is None else env
    client_id = env.get("ONEDRIVE_CLIENT_ID", "").strip()
    if not client_id:
        raise ConfigError(
            "ONEDRIVE_CLIENT_ID is not set. Register an app in your Entra "
            "directory (personal Microsoft accounts) and export its client id."
        )
    cache_raw = env.get("ONEDRIVE_TOKEN_CACHE", "").strip()
    return Settings(
        client_id=client_id,
        authority=env.get("ONEDRIVE_AUTHORITY", "").strip() or DEFAULT_AUTHORITY,
        cache_path=Path(cache_raw).expanduser() if cache_raw else DEFAULT_CACHE_PATH,
        max_download_bytes=_positive_int(
            env, "ONEDRIVE_MAX_DOWNLOAD_BYTES", DEFAULT_MAX_DOWNLOAD_BYTES
        ),
        max_text_chars=_positive_int(
            env, "ONEDRIVE_MAX_TEXT_CHARS", DEFAULT_MAX_TEXT_CHARS
        ),
    )
