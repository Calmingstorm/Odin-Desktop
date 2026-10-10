"""This computer as a Windows host, and its workspace (phase 3 plan C11)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.desktop.platform import win32
from src.desktop.platform.windows_files import dacl_is_private, held, own_sids


def profile(tmp_path):
    from src.desktop.platform.windows import windows_profile_paths

    return windows_profile_paths("default", environ={"LOCALAPPDATA": str(tmp_path)})


def test_a_fresh_profile_names_this_computer_windows_and_a_private_sibling_workspace(tmp_path):
    from src.desktop.platform.windows_engine import ensure_local_workspace
    from src.desktop.provisioning import ensure_profile
    from src.runtime_paths import runtime_install_root
    from src.tools.workspace import WorkspaceError, command_protected_roots

    paths = profile(tmp_path)
    config = ensure_profile(paths)
    local = config.tools.hosts["localhost"]
    assert local.os == "windows"
    workspace = tmp_path / "odin-desktop" / ".odin-desktop-workspaces" / "default"
    assert config.tools.local_working_dir == str(workspace)
    with held(workspace) as chain:
        security = win32.object_security(chain.handle)
    assert security.owner in own_sids() and dacl_is_private(security)
    roots = command_protected_roots(runtime_install_root(), config)
    executor = SimpleNamespace(config=config.tools, _protected_roots=lambda: roots)
    assert ensure_local_workspace(executor) == str(workspace)
    # The profile's own state stays protected from a workspace placed inside it.
    executor.config = config.tools.model_copy(
        update={"local_working_dir": str(paths.data_dir / "sessions")})
    with pytest.raises(WorkspaceError, match="must not overlap"):
        ensure_local_workspace(executor)


def test_the_startup_check_accepts_this_computer_and_flags_a_remote_windows_host():
    from src.desktop.platform.windows_tools import check_host_inventory_compat

    local = SimpleNamespace(address="127.0.0.1", os="windows", trust_mode="legacy", host_keys=[])
    remote = SimpleNamespace(address="192.0.2.7", os="windows", trust_mode="legacy", host_keys=[])
    tools = SimpleNamespace(hosts={"localhost": local}, default_host="localhost",
                            governor=SimpleNamespace(host_overrides={}))
    assert check_host_inventory_compat(tools).passed
    tools.hosts["box"] = remote
    result = check_host_inventory_compat(tools)
    assert not result.passed and "tools.hosts.box.os='windows' is legacy-only" in result.detail


def test_the_hosts_panel_takes_windows_only_for_this_computer():
    from src.desktop.platform.windows_tools import validate_host_details
    from src.tools.hosts.trust import HostTrustError

    details = validate_host_details("localhost", {"address": "127.0.0.1", "os": "Windows"})
    assert details["os"] == "windows"
    assert validate_host_details("box", {"address": "192.0.2.7", "os": "linux"})["os"] == "linux"
    with pytest.raises(HostTrustError, match="'windows' is for this computer only"):
        validate_host_details("box", {"address": "192.0.2.7", "os": "windows"})


@pytest.mark.parametrize("selected, ok, detail", [
    ("windows", True, "authentication and platform verified"),
    ("linux", False, "platform mismatch: observed windows; selected linux"),
])
async def test_the_local_check_runs_through_powershell(tmp_path, selected, ok, detail):
    from src.tools.hosts.control import HostEnrollmentManager
    from src.tools.hosts.registry import HostRegistry

    manager = HostEnrollmentManager(HostRegistry({}, trust_dir=tmp_path))
    candidate = await manager.prepare(
        "localhost", {"address": "127.0.0.1", "os": selected, "confirm_local": True},
        allow_tofu=False)
    tested = await manager.test(candidate.token)
    assert tested.tested is ok
    assert tested.test_result["platform"] == "windows"
    assert tested.test_result["detail"] == detail
