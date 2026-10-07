"""Deterministic entry dispatch and browser failure contracts, without live resources."""

import runpy
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src import __main__ as entry
from src import cli
from src.tools import browser, process_manager, url_safety


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("existing_marker", [None, "existing-process-marker"])
def test_containment_stamps_child_provenance_without_overwriting_it(
    monkeypatch, enabled, existing_marker,
):
    """Exercise the entry boundary, but never change the kernel subreaper state."""
    import secrets

    if existing_marker is None:
        monkeypatch.delenv(process_manager.PROC_TOKEN_ENV, raising=False)
        monkeypatch.delenv(process_manager.JOB_TOKEN_ENV, raising=False)
    else:
        monkeypatch.setenv(process_manager.PROC_TOKEN_ENV, existing_marker)
        monkeypatch.setenv(process_manager.JOB_TOKEN_ENV, "existing-job-marker")
    token_hex = Mock(return_value="0123456789abcdef")
    subreaper = Mock(return_value=enabled)
    monkeypatch.setattr(secrets, "token_hex", token_hex)
    monkeypatch.setattr(process_manager, "set_child_subreaper", subreaper)
    log = Mock()

    assert entry._enable_process_containment(log) is enabled

    token_hex.assert_called_once_with(8)
    subreaper.assert_called_once_with(True)
    assert entry.os.environ[process_manager.PROC_TOKEN_ENV] == (
        existing_marker or "0123456789abcdef"
    )
    assert entry.os.environ[process_manager.JOB_TOKEN_ENV] == (
        "existing-job-marker" if existing_marker else process_manager.DEFAULT_JOB_TOKEN
    )
    if enabled:
        log.debug.assert_called_once_with("Child-subreaper containment active")
        log.error.assert_not_called()
    else:
        log.debug.assert_not_called()
        log.error.assert_called_once()
        assert "in-place restarts will be blocked" in log.error.call_args.args[0]


def test_core_script_version_dispatch_does_not_start_a_core(monkeypatch, capsys):
    from src import version

    get_version = Mock(return_value="b3-test-version")
    monkeypatch.setattr(version, "get_version", get_version)
    monkeypatch.setattr(sys, "argv", ["odin-core", "--version"])
    # Run the real module guard with its package context. Temporarily removing
    # the cached module avoids runpy's duplicate-module warning; monkeypatch
    # restores the registry before other tests run.
    monkeypatch.delitem(sys.modules, "src.__main__")
    result = runpy.run_module("src.__main__", run_name="__main__", alter_sys=True)

    get_version.assert_called_once_with()
    assert result["__name__"] == "__main__"
    assert capsys.readouterr().out == "Odin Desktop b3-test-version\n"


def test_cli_script_returns_authenticated_client_exit_status(monkeypatch):
    arguments = ["--socket", "/unused/ipc.sock", "--token-file", "/unused/ipc.token",
                 "--profile", "b3-fixture", "--prompt", "test prompt"]
    client = Mock(return_value=23)
    monkeypatch.setattr(cli.local_client, "main", client)
    monkeypatch.setattr(sys, "argv", ["odin", *arguments])
    monkeypatch.delitem(sys.modules, "src.cli")

    with pytest.raises(SystemExit) as stopped:
        runpy.run_module("src.cli", run_name="__main__", alter_sys=True)

    assert stopped.value.code == 23
    client.assert_called_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["click", "fill"])
async def test_browser_selector_failure_returns_diagnostic_and_closes_page(
    monkeypatch, operation,
):
    """A deterministic driver failure, not a race against Chromium or a website."""
    url = "https://8.8.8.8/fixture"
    selector = "#missing-field"
    failure = RuntimeError("selector unavailable in fixture")
    page = SimpleNamespace(
        goto=AsyncMock(), click=AsyncMock(side_effect=failure),
        fill=AsyncMock(side_effect=failure), press=AsyncMock(),
        title=AsyncMock(), wait_for_timeout=AsyncMock(),
    )
    closed = Mock()

    @asynccontextmanager
    async def new_page():
        try:
            yield page
        finally:
            closed()

    manager = browser.BrowserManager(max_wait_timeout_seconds=7)
    open_page = Mock(side_effect=new_page)
    monkeypatch.setattr(manager, "new_page", open_page)
    # Keep real URL validation, but never ask the host resolver or network.
    dns = Mock(return_value=[(2, 1, 6, "", ("8.8.8.8", 443))])
    monkeypatch.setattr(url_safety.socket, "getaddrinfo", dns)
    arguments = {"url": url, "selector": selector, "wait_timeout_seconds": 99}
    if operation == "click":
        result = await browser.handle_browser_click(manager, arguments)
        page.click.assert_awaited_once_with(selector, timeout=7000)
        page.fill.assert_not_awaited()
    else:
        arguments.update(value="fixture text", submit=True)
        result = await browser.handle_browser_fill(manager, arguments)
        page.fill.assert_awaited_once_with(selector, "fixture text", timeout=7000)
        page.click.assert_not_awaited()

    assert result == f"Failed to {operation} `{selector}`: selector unavailable in fixture"
    open_page.assert_called_once_with()
    page.goto.assert_awaited_once_with(url, wait_until="domcontentloaded")
    closed.assert_called_once_with()
    page.press.assert_not_awaited()
    page.title.assert_not_awaited()
    page.wait_for_timeout.assert_not_awaited()
