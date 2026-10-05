"""Supervised bundled Chromium owner, never the user's browser or session.

Part-B request wiring uses the executor manager only after ``await start()`` and
checks ``readiness()`` at publication. Copied handlers retain URL, connect-time
network and disposable-context rules. This owner grants no request authority,
shell route or workspace access. Browser config is a restart-only snapshot.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from ..runtime_paths import runtime_install_root
from ..tools.browser import BrowserManager, _await_bounded

_STARTUP_TIMEOUT = 30.0
_DESKTOP_ENV = frozenset({
    "DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR",
    "BROWSER", "CHROME_USER_DATA_DIR", "CHROMIUM_USER_DATA_DIR",
    "XAUTHORITY", "ICEAUTHORITY", "SESSION_MANAGER",
})


def resolve_bundled_chromium(bundle_root: Path) -> Path:
    """Resolve packaging-owned layouts only, never PATH or Playwright's cache.

    The root is supplied by packaging/startup, not tool text. Directory symlinks
    are supported as in Desktop's existing path rules. A binary escaping the
    resolved root is not bundled. No permission-mode tightening or installation.
    """
    root = Path(bundle_root)
    if not root.is_absolute():
        raise RuntimeError("Browser unavailable: Chromium bundle root must be absolute.")
    root = root.resolve()
    candidates = [root / parent / layout / "chrome"
                  for parent in ("chromium", "")
                  for layout in ("chrome-linux64", "chrome-linux")]
    for revision in sorted(root.glob("chromium-*"), reverse=True):
        candidates.extend(revision / layout / "chrome"
                          for layout in ("chrome-linux64", "chrome-linux"))
    for candidate in candidates:
        resolved = candidate.resolve()
        if (resolved.is_relative_to(root) and resolved.is_file()
                and os.access(resolved, os.X_OK)):
            return resolved
    raise RuntimeError(
        "Browser unavailable: required bundled Chromium is missing or not executable. "
        "Repair the desktop installation."
    )


class DesktopBrowserManager(BrowserManager):
    """Qualify each browser generation before request use, including reconnect.

    Shutdown is terminal for stale request references: no lazy resurrection.
    Qualification proves a fresh context/page and both network guards locally,
    without navigation, script evaluation or site access.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._lifecycle_lock = asyncio.Lock()
        self._qualified_browser = None
        self._closed = False

    def readiness(self) -> bool:
        try:
            return bool(not self._closed and self._browser is not None
                        and self._qualified_browser is self._browser
                        and self._browser.is_connected())
        except Exception:
            return False

    def _on_browser_disconnected(self, browser=None):
        if browser is not None and browser is not self._browser:
            return
        self._qualified_browser = None
        super()._on_browser_disconnected(browser)

    async def _ensure_connected(self) -> None:
        async with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("Browser runtime is closed.")
            if self.readiness():
                return
            self._qualified_browser = None
            try:
                await super()._ensure_connected()
                browser = self._browser
                context, _page = await _await_bounded(
                    self._create_page(), _STARTUP_TIMEOUT, "qualifying bundled Chromium"
                )
                await _await_bounded(context.close(), 5.0, "closing browser qualification context")
                if browser is not self._browser or not browser.is_connected() or self._closed:
                    raise RuntimeError("Bundled Chromium disconnected during qualification.")
                self._qualified_browser = browser
            except BaseException:
                await super().shutdown()
                raise

    async def start(self) -> None:
        await self._ensure_connected()

    async def shutdown(self) -> None:
        self._closed = True
        self._qualified_browser = None
        async with self._lifecycle_lock:
            await super().shutdown()


class BrowserRuntime:
    """Lifecycle seam with qualification-before-publication, no generic consent.

    ``config`` accepts SettingsService, full config, or BrowserConfig. Saved
    browser changes do not mutate this boot snapshot or prove readiness. Desktop
    uses bundled headless Chromium even when legacy CDP is configured.
    """

    def __init__(self, config, paths=None, executor=None, *, bundle_root: Path | None = None,
                 manager_factory=DesktopBrowserManager):
        config = getattr(config, "config", config)
        self._config = getattr(config, "browser", config).model_copy(deep=True)
        self.paths = paths
        self.executor = executor
        self.bundle_root = (Path(bundle_root) if bundle_root is not None
                            else runtime_install_root() / "assets" / "browser")
        self._manager_factory = manager_factory
        self._manager = None
        self._lock = asyncio.Lock()
        self._closed = False
        self._state = "pending" if self._config.enabled else "disabled"
        self._reason = None

    @property
    def manager(self):
        return self._manager if self.readiness() else None

    def readiness(self) -> bool:
        return bool(not self._closed and self._manager is not None
                    and self._manager.readiness())

    def status(self) -> dict:
        state = self._state
        if state == "ready" and not self.readiness():
            state = "unavailable"
        return {"state": state, "ready": self.readiness(), "reason": self._reason}

    async def start(self) -> bool:
        async with self._lock:
            if self._closed:
                return False
            if not self._config.enabled:
                self._state = "disabled"
                return False
            if self.readiness():
                return True
            previous, self._manager = self._manager, None
            if self.executor is not None and self.executor._browser_manager is previous:
                self.executor._browser_manager = None
            if previous is not None:
                await previous.shutdown()
            candidate = None
            self._state, self._reason = "qualifying", None
            try:
                executable = resolve_bundled_chromium(self.bundle_root)
                candidate = self._manager_factory(
                    cdp_url="", bundled_executable=str(executable),
                    default_timeout_ms=self._config.default_timeout_ms,
                    max_wait_timeout_seconds=self._config.max_wait_timeout_seconds,
                    viewport_width=self._config.viewport_width,
                    viewport_height=self._config.viewport_height,
                    allow_private_targets=list(self._config.allow_private_targets),
                    launch_env={key: value for key, value in os.environ.items()
                                if key not in _DESKTOP_ENV},
                    startup_timeout_seconds=_STARTUP_TIMEOUT,
                )
                await candidate.start()
                if not candidate.readiness() or self._closed:
                    raise RuntimeError("Bundled Chromium did not qualify.")
                self._manager = candidate
                if self.executor is not None:
                    self.executor._browser_manager = candidate
                self._state = "ready"
                return True
            except BaseException as exc:
                self._state = "unavailable"
                # Playwright exceptions can include URLs, paths or credentials.
                self._reason = (
                    "Bundled Chromium qualification failed; repair the desktop installation.")
                if candidate is not None:
                    await candidate.shutdown()
                if not isinstance(exc, Exception):
                    raise
                return False

    async def close(self) -> None:
        self._closed = True
        async with self._lock:
            manager, self._manager = self._manager, None
            if self.executor is not None and self.executor._browser_manager is manager:
                self.executor._browser_manager = None
            self._state, self._reason = "closed", None
            if manager is not None:
                await manager.shutdown()
