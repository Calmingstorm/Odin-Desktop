"""Supervised bundled Chromium or explicitly configured CDP browser owner.

Part-B request wiring uses the lazy runtime seam after ``await start()``. Actual
readiness stays separate from retry availability. Copied handlers retain URL,
connect-time network and disposable-context rules. This owner grants no request authority,
shell route or workspace access. Browser config is a restart-only snapshot.
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
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
    candidates = [root / "browser/chromium/chrome-headless-shell-linux64/chrome-headless-shell"]
    # Retain development bundles; P4.1 resources are the packaging authority.
    legacy_root = root / "browser" if (root / "browser").is_dir() else root
    candidates.extend(legacy_root / parent / layout / "chrome"
                      for parent in ("chromium", "")
                      for layout in ("chrome-linux64", "chrome-linux"))
    for revision in sorted(legacy_root.glob("chromium-*"), reverse=True):
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
                await _await_bounded(self._qualify(), _STARTUP_TIMEOUT,
                                     "qualifying browser")
            except BaseException:
                await super().shutdown()
                raise

    async def _qualify(self) -> None:
        # One budget covers driver startup, launch/CDP, guards, page and close.
        # This also bounds CDP, whose copied connect has no separate deadline.
        # Failed qualification still gets the copied bounded shutdown afterwards.
        await super()._ensure_connected()
        browser = self._browser
        context, _page = await self._create_page()
        await context.close()
        if browser is not self._browser or not browser.is_connected() or self._closed:
            raise RuntimeError("Browser disconnected during qualification.")
        self._qualified_browser = browser

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
    honors configured CDP, otherwise uses only bundled headless Chromium. After
    startup settles the executor owns a lazy seam, not an unqualified manager.
    """

    def __init__(self, config, paths=None, executor=None, *, bundle_root: Path | None = None,
                 manager_factory=DesktopBrowserManager):
        config = getattr(config, "config", config)
        self._config = getattr(config, "browser", config).model_copy(deep=True)
        self.paths = paths
        self.executor = executor
        self.bundle_root = (Path(bundle_root) if bundle_root is not None
                            else Path(os.environ.get("ODIN_DESKTOP_BUNDLE_ROOT")
                                      or runtime_install_root() / "assets"))
        self._manager_factory = manager_factory
        self._manager = None
        self._lock = asyncio.Lock()
        self._closed = False
        self._state = "pending" if self._config.enabled else "disabled"
        self._started = False
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
        return {"state": state, "ready": self.readiness(), "reason": self._reason,
                "retry_available": self.available()}

    def available(self) -> bool:
        """A wired retry seam, not a claim that a browser has qualified."""
        return bool(self._config.enabled and self._started and not self._closed)

    @property
    def allowed_urls(self):
        return list(self._config.allow_private_targets)

    def wait_timeout_ms(self, value=None) -> int:
        # Pure copied timeout policy, with no driver, connection or launch.
        return BrowserManager(
            max_wait_timeout_seconds=self._config.max_wait_timeout_seconds,
        ).wait_timeout_ms(value)

    @asynccontextmanager
    async def new_page(self, timeout_ms=None):
        if self._closed:
            raise RuntimeError("Browser runtime is closed.")
        if not await self.start():
            raise RuntimeError(self._reason or "Browser runtime is unavailable.")
        manager = self.manager
        if manager is None:
            raise RuntimeError("Browser runtime is unavailable.")
        async with manager.new_page(timeout_ms) as page:
            yield page

    def _publish_retry_seam(self) -> None:
        if not self._closed:
            self._started = True
            if self.executor is not None:
                self.executor._browser_manager = self

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
            if previous is not None:
                await previous.shutdown()
            candidate = None
            self._state, self._reason = "qualifying", None
            try:
                executable = (None if self._config.cdp_url
                              else resolve_bundled_chromium(self.bundle_root))
                candidate = self._manager_factory(
                    cdp_url=self._config.cdp_url,
                    bundled_executable=str(executable) if executable is not None else None,
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
                    raise RuntimeError("Browser did not qualify.")
                self._manager = candidate
                self._publish_retry_seam()
                self._state = "ready"
                return True
            except BaseException as exc:
                self._state = "unavailable"
                # Playwright exceptions can include URLs, paths or credentials.
                self._reason = (
                    "Browser qualification failed; check the configured CDP endpoint."
                    if self._config.cdp_url else
                    "Bundled Chromium qualification failed; repair the desktop installation.")
                if candidate is not None:
                    await candidate.shutdown()
                if not isinstance(exc, Exception):
                    raise
                self._publish_retry_seam()
                return False

    async def close(self) -> None:
        self._closed = True
        async with self._lock:
            manager, self._manager = self._manager, None
            if self.executor is not None and self.executor._browser_manager is self:
                self.executor._browser_manager = None
            self._state, self._reason = "closed", None
            if manager is not None:
                await manager.shutdown()
