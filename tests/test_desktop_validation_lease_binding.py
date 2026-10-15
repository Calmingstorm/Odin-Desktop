"""Odin 4.15.1 (#660): validate_action binds each check to one host lease before its command is
built, and the timeout-wrapped callback runs only on that bound target.

This is Odin's rewritten tests/test_hosts_executor_leases.py case, which replaces the retired
frozen v4.13.0 case (the alias-only resolver and the callback's own lease no longer exist). It
runs on the shared tools adapter's executor: Desktop's owner, grants and readiness, with the
transport replaced before any execution.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config.schema import ToolHost, ToolsConfig
from src.tools.hosts import HostRegistry
from tests.desktop_adapters.tools_cases import ToolExecutor, owner_fixture


@pytest.fixture(autouse=True)
def desktop_tool_owner(tmp_path_factory):
    with owner_fixture(tmp_path_factory.mktemp("desktop-owner")):
        yield


def _executor(tmp_path: Path, *, access=None) -> ToolExecutor:
    registry = HostRegistry(
        {
            "alpha": ToolHost(address="127.0.0.1"),
            "remote": ToolHost(address="192.0.2.10"),
        },
        default_host="alpha",
        trust_dir=tmp_path / "trust",
    )
    return ToolExecutor(
        config=ToolsConfig(),
        host_registry=registry,
        host_access_manager=access,
    )


async def test_validation_exec_acquires_a_lease_and_reports_unknown_alias(tmp_path, monkeypatch):
    executor = _executor(tmp_path)
    calls = []

    async def transport(address, command, ssh_user, **kwargs):
        calls.append((address, command, ssh_user, kwargs))
        return 0, "checked"

    monkeypatch.setattr(executor, "_exec_command", transport)

    async def fake_run_bundle(_checks, *, resolve_host, bind_host, exec_command, **_kwargs):
        assert resolve_host("alpha") == ("127.0.0.1", "root", "linux")
        assert resolve_host("absent") is None
        with bind_host("absent") as resolved:
            assert resolved is None
        with pytest.raises(PermissionError, match="unbound validation host alias: absent"):
            await exec_command("absent", "true", "", timeout=3)
        with bind_host("alpha") as resolved:
            assert resolved == ("alpha", "", "linux")
            assert await exec_command("alpha", "true", "", timeout=3, use_workspace=True) == (
                0,
                "checked",
            )
        return {"verdict": "pass"}

    monkeypatch.setattr("src.tools.post_validation.run_bundle", fake_run_bundle)
    monkeypatch.setattr(
        "src.tools.post_validation.format_report_summary", lambda report: report["verdict"]
    )
    assert (
        await executor.validation_tools._handle_validate_action({"checks": [{"type": "command"}]})
        == "pass"
    )
    assert calls[0][3]["target"].alias == "alpha"
    assert await executor.validation_tools._handle_validate_action({"checks": []}) == (
        "Error: 'checks' must be a non-empty list. See tool description for check schema."
    )
