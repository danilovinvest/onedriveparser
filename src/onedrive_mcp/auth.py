"""Delegated auth for personal Microsoft accounts via msal (public client)."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path

import msal

from onedrive_mcp.config import Settings


class AuthError(RuntimeError):
    """Raised when no valid token can be obtained."""


def load_cache(path: Path) -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if path.exists():
        cache.deserialize(path.read_text(encoding="utf-8"))
    return cache


def save_cache(cache: msal.SerializableTokenCache, path: Path) -> None:
    if not cache.has_state_changed:
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # mkstemp creates a fresh 0600 file with O_EXCL; os.replace then swaps it in
    # atomically and replaces a pre-planted symlink instead of following it.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".token_cache.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(cache.serialize())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


AppFactory = Callable[[Settings, msal.SerializableTokenCache], msal.PublicClientApplication]


def default_app(
    settings: Settings, cache: msal.SerializableTokenCache
) -> msal.PublicClientApplication:
    # Note: msal fetches the authority's OpenID config here (network call).
    return msal.PublicClientApplication(
        settings.client_id, authority=settings.authority, token_cache=cache
    )


class TokenProvider:
    def __init__(self, settings: Settings, app_factory: AppFactory = default_app) -> None:
        self._settings = settings
        self._cache = load_cache(settings.cache_path)
        self._app = app_factory(settings, self._cache)

    def get_token(self) -> str:
        """Return an access token from cache, refreshing silently if needed."""
        accounts = self._app.get_accounts()
        if not accounts:
            raise AuthError("Not signed in. Run `onedrive-mcp login` first.")
        result = self._app.acquire_token_silent(
            list(self._settings.scopes), account=accounts[0]
        )
        save_cache(self._cache, self._settings.cache_path)
        if not result or "access_token" not in result:
            detail = (result or {}).get("error_description", "no cached token")
            raise AuthError(
                f"Silent sign-in failed ({detail}). Run `onedrive-mcp login`."
            )
        return result["access_token"]

    def account_name(self) -> str | None:
        accounts = self._app.get_accounts()
        return accounts[0].get("username") if accounts else None

    def login(
        self,
        show: Callable[[str], None] = print,
        open_url: Callable[[str], object] | None = None,
    ) -> str:
        """Run the device code flow; returns the signed-in username."""
        flow = self._app.initiate_device_flow(scopes=list(self._settings.scopes))
        if "user_code" not in flow:
            raise AuthError(
                f"Device flow failed: {flow.get('error_description', flow)}"
            )
        show(flow["message"])
        if open_url and flow.get("verification_uri"):
            open_url(flow["verification_uri"])
        result = self._app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise AuthError(
                f"Login failed: {result.get('error_description', result)}"
            )
        save_cache(self._cache, self._settings.cache_path)
        return result.get("id_token_claims", {}).get("preferred_username", "unknown")

    def logout(self) -> None:
        for account in self._app.get_accounts():
            self._app.remove_account(account)
        save_cache(self._cache, self._settings.cache_path)
