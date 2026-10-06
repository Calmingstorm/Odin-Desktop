"""The actual BrowserManager uses immutable resources and never weakens sandboxing."""
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.tools.browser import BrowserManager


@pytest.mark.asyncio
async def test_runtime_bundle_env_and_sandbox(tmp_path, monkeypatch):
    root = tmp_path / "runtime with spaces"
    executable = root / "browser/chromium/chrome-headless-shell-linux64/chrome-headless-shell"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"fake executable never executed")
    executable.chmod(0o755)
    monkeypatch.setenv("ODIN_DESKTOP_BUNDLE_ROOT", str(root))
    browser = MagicMock()
    launch = AsyncMock(return_value=browser)
    playwright = SimpleNamespace(chromium=SimpleNamespace(launch=launch))
    factory = SimpleNamespace(start=AsyncMock(return_value=playwright))
    monkeypatch.setitem(
        sys.modules, "playwright.async_api", SimpleNamespace(async_playwright=lambda: factory)
    )
    manager = BrowserManager()
    await manager._ensure_connected()
    kwargs = launch.call_args.kwargs
    assert kwargs["executable_path"] == str(executable)
    assert kwargs["chromium_sandbox"] is True
    assert "--no-sandbox" not in kwargs["args"]
    assert "--disable-setuid-sandbox" not in kwargs["args"]


@pytest.mark.asyncio
async def test_absent_bundle_fails_before_playwright_import(tmp_path, monkeypatch):
    monkeypatch.setenv("ODIN_DESKTOP_BUNDLE_ROOT", str(tmp_path))
    with pytest.raises(RuntimeError, match="required bundled Chromium is not configured"):
        await BrowserManager()._ensure_connected()
