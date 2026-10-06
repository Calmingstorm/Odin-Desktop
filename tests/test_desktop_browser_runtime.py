"""Bundled browser lifecycle using stubbed Playwright, never network or graphics."""
from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.config.schema import BrowserConfig
from src.desktop.browser_runtime import (
    BrowserRuntime,
    DesktopBrowserManager,
    resolve_bundled_chromium,
)
from src.tools.browser import BrowserManager, handle_browser_read_page, handle_browser_screenshot


def bundle(tmp_path, layout="browser/chromium/chrome-headless-shell-linux64/chrome-headless-shell"):
    root = tmp_path / "bundle"
    executable = root / layout
    executable.parent.mkdir(parents=True)
    # Never executed: all launch/worker primitives are stubbed below.
    executable.write_text("bundled Chromium fixture")
    executable.chmod(0o755)
    return root, executable


class Context:
    def __init__(self, *, websocket=True):
        self.route = AsyncMock()
        self.route_web_socket = AsyncMock() if websocket else None
        self.set_default_timeout = Mock()
        self.new_page = AsyncMock(return_value=SimpleNamespace(goto=AsyncMock()))
        self.close = AsyncMock()


class Browser:
    def __init__(self, context_factory=Context):
        self.connected = True
        self.contexts = []
        self.callback = None
        self._context_factory = context_factory
        self.new_context = AsyncMock(side_effect=self.make_context)
        self.close = AsyncMock(side_effect=self.disconnect)

    async def make_context(self, **kwargs):
        context = self._context_factory()
        self.contexts.append(context)
        return context

    def is_connected(self):
        return self.connected

    def on(self, name, callback):
        assert name == "disconnected"
        self.callback = callback

    def disconnect(self):
        self.connected = False
        if self.callback:
            self.callback(self)


@pytest.fixture
def driver(monkeypatch):
    """Stub the driver startup too, so no browser/worker execution is possible."""
    browsers = []

    async def launch(**kwargs):
        browser = Browser()
        browsers.append(browser)
        return browser

    async def connect(url):
        return await launch()

    playwright = SimpleNamespace(
        chromium=SimpleNamespace(launch=AsyncMock(side_effect=launch),
                                 connect_over_cdp=AsyncMock(side_effect=connect)),
        stop=AsyncMock(),
    )
    starter = SimpleNamespace(start=AsyncMock(return_value=playwright))
    module = ModuleType("playwright.async_api")
    module.async_playwright = Mock(return_value=starter)
    monkeypatch.setitem(sys.modules, "playwright.async_api", module)
    # Fail if a test unexpectedly navigates through the production safe transport.
    fetch = AsyncMock(side_effect=AssertionError("No real network in browser lifecycle tests"))
    monkeypatch.setattr("src.tools.safe_fetch.safe_fetch", fetch)
    return SimpleNamespace(playwright=playwright, starter=starter, browsers=browsers, fetch=fetch)


@pytest.mark.parametrize("layout", [
    "browser/chromium/chrome-headless-shell-linux64/chrome-headless-shell",
    "chromium/chrome-linux64/chrome", "chrome-linux/chrome",
    "chromium-1234/chrome-linux/chrome",
])
def test_resolve_package_layout_only(tmp_path, monkeypatch, layout):
    root, executable = bundle(tmp_path, layout)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/unused/operator/cache")
    assert resolve_bundled_chromium(root) == executable


def test_bundle_directory_symlink_and_unrelated_modes_preserved(tmp_path):
    root, executable = bundle(tmp_path)
    root.chmod(0o777)
    alias = tmp_path / "package-link"
    alias.symlink_to(root, target_is_directory=True)
    assert resolve_bundled_chromium(alias) == executable
    assert root.stat().st_mode & 0o777 == 0o777


def test_resolver_no_path_cache_or_external_binary_fallback(tmp_path, monkeypatch):
    root, executable = bundle(tmp_path)
    outside = tmp_path / "operator-chrome"
    outside.write_text("unused fixture")
    outside.chmod(0o755)
    executable.unlink()
    executable.symlink_to(outside)
    monkeypatch.setenv("BROWSER", str(outside))
    with pytest.raises(RuntimeError, match="bundled Chromium is missing"):
        resolve_bundled_chromium(root)
    with pytest.raises(RuntimeError, match="must be absolute"):
        resolve_bundled_chromium("relative")


def test_resolver_nonexecutable_not_usable(tmp_path):
    root, executable = bundle(tmp_path)
    executable.chmod(0o600)
    with pytest.raises(RuntimeError, match="not executable"):
        resolve_bundled_chromium(root)


@pytest.mark.asyncio
async def test_disabled_default_does_not_resolve_launch_or_publish(tmp_path, driver):
    executor = SimpleNamespace(_browser_manager=None)
    owner = BrowserRuntime(BrowserConfig(), executor=executor, bundle_root=tmp_path / "missing")
    assert not await owner.start()
    assert owner.status() == {"state": "disabled", "ready": False, "reason": None,
                              "retry_available": False}
    assert not owner.available()
    assert executor._browser_manager is None
    driver.starter.start.assert_not_awaited()


@pytest.mark.asyncio
async def test_qualify_before_publication_uses_bundle_and_boot_policy(
    tmp_path, driver, monkeypatch,
):
    root, executable = bundle(tmp_path)
    monkeypatch.setenv("DISPLAY", ":operator")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "operator-session")
    monkeypatch.setenv("CHROME_USER_DATA_DIR", "operator-profile")
    executor = SimpleNamespace(_browser_manager=None)
    config = BrowserConfig(enabled=True,
                           default_timeout_ms=1500, max_wait_timeout_seconds=7,
                           allow_private_targets=["http://127.0.0.1:8080/"])
    owner = BrowserRuntime(SimpleNamespace(config=SimpleNamespace(browser=config)),
                           executor=executor, bundle_root=root)
    # Saving new browser values must not silently mutate this startup snapshot.
    config.max_wait_timeout_seconds = 20
    config.allow_private_targets.append("http://127.0.0.2/")
    assert owner.manager is None
    assert await owner.start()
    manager = owner.manager
    assert executor._browser_manager is owner
    assert manager.wait_timeout_ms(40) == 7000
    assert manager.allowed_urls == ["http://127.0.0.1:8080/"]
    options = driver.playwright.chromium.launch.call_args.kwargs
    assert options["executable_path"] == str(executable)
    assert options["headless"] is True
    assert not ({"DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "CHROME_USER_DATA_DIR"}
                & options["env"].keys())
    driver.playwright.chromium.connect_over_cdp.assert_not_awaited()
    context = driver.browsers[0].contexts[0]
    assert driver.browsers[0].new_context.call_args.kwargs["service_workers"] == "block"
    context.route.assert_awaited_once()
    context.route_web_socket.assert_awaited_once()
    context.new_page.assert_awaited_once()
    context.new_page.return_value.goto.assert_not_awaited()
    context.close.assert_awaited_once()
    driver.fetch.assert_not_awaited()
    assert await owner.start()  # idempotent start
    driver.playwright.chromium.launch.assert_awaited_once()
    await owner.close()
    assert owner.status()["state"] == "closed"
    assert owner.status()["retry_available"] is False
    assert not owner.readiness() and executor._browser_manager is None
    with pytest.raises(RuntimeError, match="closed"):
        await manager._ensure_connected()
    assert not await owner.start()
    driver.playwright.stop.assert_awaited_once()
    with pytest.raises(RuntimeError, match="closed"):
        async with owner.new_page():
            pass


@pytest.mark.asyncio
async def test_missing_bundle_unavailable_without_worker_or_install(tmp_path, driver):
    owner = BrowserRuntime(BrowserConfig(enabled=True), bundle_root=tmp_path / "missing")
    assert not await owner.start()
    assert owner.status()["state"] == "unavailable"
    assert owner.status()["ready"] is False
    assert owner.status()["retry_available"] is True
    assert owner.manager is None
    driver.starter.start.assert_not_awaited()


@pytest.mark.asyncio
async def test_guard_qualification_failure_cleans_up_and_never_publishes(tmp_path, driver):
    root, _ = bundle(tmp_path)
    browser = Browser(lambda: Context(websocket=False))
    driver.playwright.chromium.launch.side_effect = None
    driver.playwright.chromium.launch.return_value = browser
    executor = SimpleNamespace(_browser_manager=None)
    owner = BrowserRuntime(BrowserConfig(enabled=True), executor=executor, bundle_root=root)
    assert not await owner.start()
    assert not owner.readiness() and owner.manager is None
    assert owner.available() and executor._browser_manager is owner
    assert owner.status()["ready"] is False
    assert owner.status()["retry_available"] is True
    browser.contexts[0].close.assert_awaited_once()
    browser.close.assert_awaited_once()
    assert driver.playwright.stop.await_count >= 1
    driver.fetch.assert_not_awaited()
    recovered = Browser()
    driver.playwright.chromium.launch.return_value = recovered
    async with executor._browser_manager.new_page():
        assert owner.readiness()
        assert owner.status()["ready"] is True
        assert owner.status()["retry_available"] is True
    assert driver.playwright.chromium.launch.await_count == 2
    assert len(recovered.contexts) == 2
    await owner.close()


@pytest.mark.asyncio
async def test_launch_failure_diagnostic_does_not_leak_exception(tmp_path, driver):
    root, _ = bundle(tmp_path)
    driver.playwright.chromium.launch.side_effect = RuntimeError("fixture private value")
    owner = BrowserRuntime(BrowserConfig(enabled=True), bundle_root=root)
    assert not await owner.start()
    assert "fixture private value" not in str(owner.status())
    driver.playwright.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_disconnect_readiness_withdrawn_and_reconnect_requalified(tmp_path, driver):
    root, _ = bundle(tmp_path)
    owner = BrowserRuntime(BrowserConfig(enabled=True), bundle_root=root)
    assert await owner.start()
    manager = owner.manager
    original = driver.browsers[0]
    original.disconnect()
    assert not owner.readiness() and owner.manager is None
    assert owner.status()["state"] == "unavailable"
    await manager._ensure_connected()
    assert owner.readiness()
    assert len(driver.browsers) == 2
    driver.browsers[1].contexts[0].close.assert_awaited_once()
    original.callback(original)  # delayed old-generation event cannot erase new browser
    assert owner.readiness()
    await owner.close()


@pytest.mark.asyncio
async def test_start_waits_for_qualification_and_close_withdraws(tmp_path, driver):
    root, _ = bundle(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    browser = Browser()

    async def new_page():
        entered.set()
        await release.wait()
        return SimpleNamespace()

    context = Context()
    context.new_page.side_effect = new_page
    browser._context_factory = lambda: context
    driver.playwright.chromium.launch.side_effect = None
    driver.playwright.chromium.launch.return_value = browser
    executor = SimpleNamespace(_browser_manager=None)
    owner = BrowserRuntime(BrowserConfig(enabled=True), executor=executor, bundle_root=root)
    start = asyncio.create_task(owner.start())
    await entered.wait()
    assert owner.status()["state"] == "qualifying"
    assert owner.manager is None and executor._browser_manager is None
    close = asyncio.create_task(owner.close())
    await asyncio.sleep(0)
    release.set()
    assert not await start
    await close
    assert owner.status()["state"] == "closed"
    browser.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_qualification_cleans_driver(tmp_path, driver):
    root, _ = bundle(tmp_path)
    entered = asyncio.Event()
    browser = Browser()
    context = Context()

    async def new_page():
        entered.set()
        await asyncio.Event().wait()

    context.new_page.side_effect = new_page
    browser._context_factory = lambda: context
    driver.playwright.chromium.launch.side_effect = None
    driver.playwright.chromium.launch.return_value = browser
    owner = BrowserRuntime(BrowserConfig(enabled=True), bundle_root=root)
    start = asyncio.create_task(owner.start())
    await entered.wait()
    start.cancel()
    with pytest.raises(asyncio.CancelledError):
        await start
    assert owner.manager is None
    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()
    driver.playwright.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_copied_network_guard_fails_closed_and_blocks_websockets(tmp_path, driver):
    root, _ = bundle(tmp_path)
    owner = BrowserRuntime(BrowserConfig(enabled=True), bundle_root=root)
    assert await owner.start()
    context = driver.browsers[0].contexts[0]
    route = SimpleNamespace(request=SimpleNamespace(url="https://example.invalid/",
                            method="GET", post_data_buffer=None,
                            all_headers=AsyncMock(return_value={})),
                            fulfill=AsyncMock(), abort=AsyncMock())
    await context.route.call_args.args[1](route)
    route.abort.assert_awaited_once_with("blockedbyclient")
    route.fulfill.assert_not_awaited()
    socket = SimpleNamespace(url="wss://example.invalid/", close=AsyncMock())
    await context.route_web_socket.call_args.args[1](socket)
    socket.close.assert_awaited_once_with(code=1008, reason="Browser network policy")
    await owner.close()


@pytest.mark.asyncio
async def test_builtin_manager_optional_startup_options_preserve_defaults(tmp_path, driver):
    _, executable = bundle(tmp_path)
    manager = BrowserManager(bundled_executable=str(executable))
    await manager._ensure_connected()
    assert "env" not in driver.playwright.chromium.launch.call_args.kwargs
    # Generic copied manager remains lazy and does not run Desktop qualification.
    driver.browsers[0].new_context.assert_not_awaited()
    await manager.shutdown()


@pytest.mark.asyncio
async def test_copied_handler_uses_isolated_context_returns_owned_bytes(
    tmp_path, driver, monkeypatch,
):
    root, _ = bundle(tmp_path)
    # URL validation invokes DNS too: this stub cannot contact the network.
    dns = Mock(return_value=[(2, 1, 6, "", ("93.184.216.34", 443))])
    monkeypatch.setattr("src.tools.url_safety.socket.getaddrinfo", dns)
    owner = BrowserRuntime(BrowserConfig(enabled=True), bundle_root=root)
    assert await owner.start()
    browser = driver.browsers[0]
    contexts = []

    def context_factory():
        context = Context()
        page = SimpleNamespace(
            goto=AsyncMock(return_value=SimpleNamespace(status=200)),
            screenshot=AsyncMock(return_value=b"fixture image bytes"),
            title=AsyncMock(return_value="fixture title"),
            url="https://example.invalid/",
        )
        context.new_page.return_value = page
        contexts.append(context)
        return context

    browser._context_factory = context_factory
    for _ in range(2):
        description, image = await handle_browser_screenshot(owner.manager, {
            "url": "https://example.invalid/", "full_page": True,
        })
        assert "fixture title" in description
        assert image == b"fixture image bytes"
    assert len(contexts) == 2 and contexts[0] is not contexts[1]
    for context in contexts:
        context.close.assert_awaited_once()
        context.new_page.return_value.screenshot.assert_awaited_once_with(
            full_page=True, type="png")
        context.route.assert_awaited_once()
        context.route_web_socket.assert_awaited_once()
    assert dns.call_count == 2
    driver.fetch.assert_not_awaited()
    await owner.close()


@pytest.mark.asyncio
async def test_qualification_close_failure_never_publishes(tmp_path, driver):
    root, _ = bundle(tmp_path)
    browser = Browser()
    context = Context()
    context.close.side_effect = RuntimeError("fixture close refusal")
    browser._context_factory = lambda: context
    driver.playwright.chromium.launch.side_effect = None
    driver.playwright.chromium.launch.return_value = browser
    owner = BrowserRuntime(BrowserConfig(enabled=True), bundle_root=root)
    assert not await owner.start()
    assert owner.manager is None
    browser.close.assert_awaited_once()
    driver.playwright.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_bounded_launch_failure_cleans_driver(tmp_path, driver):
    _, executable = bundle(tmp_path)
    manager = DesktopBrowserManager(bundled_executable=str(executable),
                                    startup_timeout_seconds=0.01)
    cancelled = asyncio.Event()

    async def launch(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    driver.playwright.chromium.launch.side_effect = launch
    with pytest.raises(RuntimeError, match="Failed to launch required bundled Chromium"):
        await manager.start()
    await cancelled.wait()
    assert not manager.readiness()
    assert driver.playwright.chromium.launch.call_args.kwargs["timeout"] == 10
    driver.playwright.stop.assert_awaited_once()
    await manager.shutdown()


@pytest.mark.asyncio
async def test_supervised_shutdown_is_idempotent(tmp_path, driver):
    root, _ = bundle(tmp_path)
    executor = SimpleNamespace(_browser_manager=None)
    owner = BrowserRuntime(BrowserConfig(enabled=True), executor=executor, bundle_root=root)
    assert await owner.start()
    await owner.close()
    await owner.close()
    driver.browsers[0].close.assert_awaited_once()
    driver.playwright.stop.assert_awaited_once()
    assert executor._browser_manager is None


@pytest.mark.asyncio
async def test_close_withdraws_publication_before_cleanup_finishes(tmp_path, driver):
    root, _ = bundle(tmp_path)
    executor = SimpleNamespace(_browser_manager=None)
    owner = BrowserRuntime(BrowserConfig(enabled=True), executor=executor, bundle_root=root)
    assert await owner.start()
    entered, release = asyncio.Event(), asyncio.Event()

    async def close():
        entered.set()
        await release.wait()
        driver.browsers[0].disconnect()

    driver.browsers[0].close.side_effect = close
    cleanup = asyncio.create_task(owner.close())
    await entered.wait()
    assert owner.manager is None and not owner.readiness()
    assert executor._browser_manager is None
    release.set()
    await cleanup
    assert owner.status()["state"] == "closed"


@pytest.mark.asyncio
async def test_bundle_root_environment_matches_packaging_authority(tmp_path, driver, monkeypatch):
    root, executable = bundle(tmp_path)
    monkeypatch.setenv("ODIN_DESKTOP_BUNDLE_ROOT", str(root))
    owner = BrowserRuntime(BrowserConfig(enabled=True))
    assert await owner.start()
    assert driver.playwright.chromium.launch.call_args.kwargs["executable_path"] == str(executable)
    await owner.close()


def test_p41_directory_symlink_escape_is_rejected(tmp_path):
    root, executable = bundle(tmp_path)
    directory = executable.parent
    outside = tmp_path / "outside"
    directory.rename(outside)
    directory.symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match="bundled Chromium is missing"):
        resolve_bundled_chromium(root)


@pytest.mark.asyncio
async def test_explicit_root_takes_precedence_over_environment(tmp_path, driver, monkeypatch):
    root, executable = bundle(tmp_path)
    monkeypatch.setenv("ODIN_DESKTOP_BUNDLE_ROOT", str(tmp_path / "missing"))
    owner = BrowserRuntime(BrowserConfig(enabled=True), bundle_root=root)
    assert await owner.start()
    assert driver.playwright.chromium.launch.call_args.kwargs["executable_path"] == str(executable)
    await owner.close()


@pytest.mark.asyncio
async def test_cdp_honored_without_bundle_and_guarded_disposable_context(tmp_path, driver):
    config = BrowserConfig(enabled=True, cdp_url="https://configured.invalid/?secret=fixture")
    owner = BrowserRuntime(config, bundle_root=tmp_path / "missing")
    config.cdp_url = "https://saved-not-effective.invalid/"
    assert await owner.start()
    driver.playwright.chromium.connect_over_cdp.assert_awaited_once_with(
        "https://configured.invalid/?secret=fixture")
    driver.playwright.chromium.launch.assert_not_awaited()
    context = driver.browsers[0].contexts[0]
    context.route.assert_awaited_once()
    context.route_web_socket.assert_awaited_once()
    context.close.assert_awaited_once()
    context.new_page.return_value.goto.assert_not_awaited()
    await owner.close()


@pytest.mark.asyncio
async def test_cdp_failure_scrubbed_and_retry_next_use(tmp_path, driver):
    executor = SimpleNamespace(_browser_manager=None)
    owner = BrowserRuntime(BrowserConfig(enabled=True, cdp_url="https://configured.invalid/"),
                           executor=executor, bundle_root=tmp_path / "missing")
    driver.playwright.chromium.connect_over_cdp.side_effect = RuntimeError("private fixture")
    assert not await owner.start()
    assert not owner.readiness() and owner.manager is None
    assert "private fixture" not in str(owner.status())
    assert "configured.invalid" not in str(owner.status())
    assert executor._browser_manager is owner and owner.available()
    driver.playwright.chromium.connect_over_cdp.side_effect = None
    driver.playwright.chromium.connect_over_cdp.return_value = Browser()
    async with executor._browser_manager.new_page():
        assert owner.readiness()
    assert driver.playwright.chromium.connect_over_cdp.await_count == 2
    await owner.close()


@pytest.mark.asyncio
async def test_failed_launch_retry_reachable_through_catalog_and_copied_handler(
    tmp_path, driver, monkeypatch,
):
    from src.config.schema import Config
    from src.desktop.tool_catalog import DesktopToolCatalog
    from src.tools.builtin_policy import BuiltinToolPolicy

    root, _ = bundle(tmp_path)
    executor = SimpleNamespace(_browser_manager=None)
    config = Config()
    config.browser.enabled = True
    owner = BrowserRuntime(config, executor=executor, bundle_root=root)
    policy = BuiltinToolPolicy(lambda: config,
                              lambda: {"browser_read_page": owner.available()})
    catalog = DesktopToolCatalog(builtin_policy=policy, get_config=lambda: config,
                                skill_manager=SimpleNamespace(get_tool_definitions=lambda: []),
                                computer_available=lambda: False)
    assert not policy.is_available("browser_read_page")
    driver.playwright.chromium.launch.side_effect = RuntimeError("fixture startup failure")
    assert not await owner.start()
    assert not owner.readiness()
    assert "browser_read_page" in {item["name"] for item in catalog.merged_definitions()}
    assert policy.is_available("browser_read_page")
    page = SimpleNamespace(goto=AsyncMock(), inner_text=AsyncMock(return_value="fixture body"),
                           title=AsyncMock(return_value="fixture"), url="https://example.invalid/")
    browser = Browser()
    context = Context()
    context.new_page.return_value = page
    browser._context_factory = lambda: context
    driver.playwright.chromium.launch.side_effect = None
    driver.playwright.chromium.launch.return_value = browser
    monkeypatch.setattr("src.tools.url_safety.socket.getaddrinfo",
                        Mock(return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]))
    result = await handle_browser_read_page(executor._browser_manager,
                                           {"url": "https://example.invalid/"})
    assert "fixture body" in result
    assert owner.readiness()
    assert driver.playwright.chromium.launch.await_count == 2
    stale = executor._browser_manager
    await owner.close()
    assert not policy.is_available("browser_read_page")
    assert "browser_read_page" not in {item["name"] for item in catalog.merged_definitions()}
    with pytest.raises(RuntimeError, match="closed"):
        async with stale.new_page():
            pass
    assert driver.playwright.chromium.launch.await_count == 2


@pytest.mark.asyncio
async def test_missing_bundle_retried_next_use_without_status_launch(tmp_path, driver):
    root = tmp_path / "bundle"
    owner = BrowserRuntime(BrowserConfig(enabled=True), bundle_root=root)
    assert not await owner.start()
    assert owner.available() and not owner.readiness()
    for _ in range(2):
        assert owner.status()["state"] == "unavailable"
    driver.starter.start.assert_not_awaited()
    bundle(tmp_path)
    async with owner.new_page():
        assert owner.readiness()
    await owner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["cdp", "qualification"])
async def test_end_to_end_qualification_budget_and_next_use_retry(
    tmp_path, driver, monkeypatch, stage,
):
    monkeypatch.setattr("src.desktop.browser_runtime._STARTUP_TIMEOUT", 0.03)
    cancelled = asyncio.Event()

    async def blocked(*args, **kwargs):
        try:
            if stage == "qualification":
                # Each stage would fit 30ms alone, but their 40ms total does not.
                await asyncio.sleep(0.02)
                return SimpleNamespace()
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    owner = BrowserRuntime(BrowserConfig(enabled=True, cdp_url="https://configured.invalid/"),
                           bundle_root=tmp_path / "missing")
    browser = Browser()
    context = Context()
    browser._context_factory = lambda: context
    driver.playwright.chromium.connect_over_cdp.side_effect = None
    driver.playwright.chromium.connect_over_cdp.return_value = browser
    if stage == "cdp":
        driver.playwright.chromium.connect_over_cdp.side_effect = blocked
    else:
        # Driver startup consumes some of the SAME budget as page qualification.
        async def startup():
            await asyncio.sleep(0.02)
            return driver.playwright
        driver.starter.start.side_effect = startup
        context.new_page.side_effect = blocked
    loop = asyncio.get_running_loop()
    before = loop.time()
    assert not await owner.start()
    assert loop.time() - before < 0.15
    await cancelled.wait()
    assert not owner.readiness() and owner.available()
    driver.playwright.stop.assert_awaited_once()
    driver.playwright.chromium.connect_over_cdp.side_effect = None
    driver.starter.start.side_effect = None
    context.new_page.side_effect = None
    driver.playwright.chromium.connect_over_cdp.return_value = Browser()
    async with owner.new_page():
        assert owner.readiness()
    await owner.close()


@pytest.mark.asyncio
async def test_composed_browser_retry_publication_is_not_qualified_readiness(
    tmp_path, driver, monkeypatch,
):
    from src.desktop.core import CoreService
    from src.desktop.provisioning import fresh_config_document
    from tests.test_desktop_core_lifecycle import profile
    from tests.test_desktop_management_core import TemporaryKeyring

    def configured(paths):
        document = fresh_config_document(paths)
        document["browser"] = {"enabled": True, "cdp_url": "https://configured.invalid/"}
        return document

    # Change only fresh disposable profile data, never saved/live configuration.
    monkeypatch.setattr("src.desktop.provisioning.fresh_config_document", configured)
    driver.playwright.chromium.connect_over_cdp.side_effect = RuntimeError("fixture failure")
    paths, socket_path, token_file = profile(tmp_path)
    import os
    read_fd, write_fd = os.pipe()
    core = CoreService(paths, socket_path, token_file, secret_backend=TemporaryKeyring())
    try:
        await core.start(read_fd)
        browser = core.management.browser
        executor = core.management.executor
        assert not browser.readiness() and browser.status()["state"] == "unavailable"
        assert executor._browser_manager is browser
        assert executor._builtin_policy.is_available("browser_read_page")
        names = {tool["name"] for tool in core.management.tool_catalog.merged_definitions()}
        assert "browser_read_page" in names
        driver.playwright.chromium.connect_over_cdp.side_effect = None
        driver.playwright.chromium.connect_over_cdp.return_value = Browser()
        async with executor._browser_manager.new_page():
            assert browser.readiness()
    finally:
        await core.close()
        os.close(read_fd)
        os.close(write_fd)
    assert not executor._builtin_policy.is_available("browser_read_page")


@pytest.mark.asyncio
async def test_next_use_retry_is_single_flight(tmp_path, driver):
    root, _ = bundle(tmp_path)
    owner = BrowserRuntime(BrowserConfig(enabled=True), bundle_root=root)
    driver.playwright.chromium.launch.side_effect = RuntimeError("fixture first failure")
    assert not await owner.start()
    entered, release = asyncio.Event(), asyncio.Event()
    browser = Browser()

    async def launch(**kwargs):
        entered.set()
        await release.wait()
        return browser

    driver.playwright.chromium.launch.side_effect = launch

    async def use():
        async with owner.new_page():
            assert owner.readiness()

    calls = [asyncio.create_task(use()) for _ in range(2)]
    await entered.wait()
    assert owner.available() and not owner.readiness()
    release.set()
    await asyncio.gather(*calls)
    assert driver.playwright.chromium.launch.await_count == 2
    assert len(browser.contexts) == 3  # one qualification, two request contexts
    for context in browser.contexts:
        context.close.assert_awaited_once()
    await owner.close()
