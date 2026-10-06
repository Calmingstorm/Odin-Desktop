"""Offline tray collector behaviour. No desktop, VM, service or input calls."""

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "tray_probe", ROOT / "scripts/qualification/lab/guest/native-p33-probe.py")
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


def identities():
    inner = {"pid": 16, "uid": 1001, "startTicks": "444", "namespace": "pid:[999]",
             "executable": "/app/electron"}
    outer = {"pid": 2400, "uid": 1001, "start_ticks": "444", "pid_namespace": "pid:[999]",
             "exe": "/app/electron", "namespace_pids": [2400, 16]}
    return inner, outer


def test_inner_pid_is_not_arbitrary_outer_pid():
    inner, outer = identities()
    assert PROBE.matches_inner(outer, inner, 1001)
    unrelated = {**outer, "pid": 16, "namespace_pids": [16], "pid_namespace": "pid:[1]"}
    assert not PROBE.matches_inner(unrelated, inner, 1001)


@pytest.mark.parametrize("field,value", [("uid", 1002), ("start_ticks", "445"),
    ("pid_namespace", "pid:[1]"), ("exe", "/wrong"), ("namespace_pids", [2400, 17])])
def test_all_namespace_identity_fields_required(field, value):
    inner, outer = identities()
    assert not PROBE.matches_inner({**outer, field: value}, inner, 1001)


def test_resolve_inner_unique_kernel_mapping_and_pid_reuse():
    inner, outer = identities()
    entries = [Path("/proc/16"), Path("/proc/2400")]
    unrelated = {**outer, "pid": 16, "namespace_pids": [16], "start_ticks": "2"}
    with patch.object(Path, "iterdir", return_value=entries), \
            patch.object(PROBE, "identity", side_effect=[unrelated, outer]) as identify:
        assert PROBE.resolve_inner(inner, 1001) == outer
        assert [call.args[0] for call in identify.call_args_list] == [16, 2400]
    with patch.object(Path, "iterdir", return_value=entries), \
            patch.object(PROBE, "identity", return_value=outer), \
            pytest.raises(RuntimeError, match="unique"):
        PROBE.resolve_inner(inner, 1001)


def test_accessible_identity_uses_native_bus_peer_not_inner_pid():
    _, outer = identities()
    application = SimpleNamespace(app=SimpleNamespace(bus_name=":1.42"), get_process_id=lambda: 16)
    obj = SimpleNamespace(getApplication=lambda: application)
    api = Mock()
    api.GetConnectionUnixProcessID.return_value = 2400
    with patch.object(PROBE, "identity", return_value=outer) as identify:
        assert PROBE.accessible_peer_identity(obj, api, 1001) == outer
        identify.assert_called_once_with(2400)
        api.GetConnectionUnixProcessID.assert_called_once_with(":1.42")
    with patch.object(PROBE, "identity", return_value={**outer, "uid": 1002}), \
            pytest.raises(RuntimeError, match="foreign UID"):
        PROBE.accessible_peer_identity(obj, api, 1001)
    application.app.bus_name = "electron"
    with pytest.raises(RuntimeError, match="unique bus peer"):
        PROBE.accessible_peer_identity(obj, api, 1001)


class Node:
    def __init__(self, name, role, children=(), showing=True):
        self.name, self.role, self.children, self.showing = name, role, children, showing
        self.childCount = len(children)

    def __getitem__(self, index):
        return self.children[index]

    def getRoleName(self):  # noqa: N802 - matches the native AT-SPI interface
        return self.role

    def getState(self):  # noqa: N802 - matches the native AT-SPI interface
        return SimpleNamespace(contains=lambda state: self.showing)


def test_opened_popup_app_subtree_and_showing_prerequisites():
    item = Node("Open Odin", "menu item")
    menu = Node("", "popup menu", [item])
    root = Node("electron", "application", [menu])
    found = list(PROBE.walk_tree(root))
    assert found[-1] == (item, [menu, root])
    assert PROBE.opened_item(item, found[-1][1], "Open Odin", 1)
    menu.showing = False
    assert not PROBE.opened_item(item, [menu, root], "Open Odin", 1)
    menu.showing, item.showing = True, False
    assert not PROBE.opened_item(item, [menu, root], "Open Odin", 1)
    item.showing = True
    assert not PROBE.opened_item(item, [root], "Open Odin", 1)
    assert not PROBE.opened_item(item, [menu], "Exit Odin", 1)


def test_tree_depth_bound():
    leaf = Node("Open Odin", "menu item")
    root = leaf
    for _ in range(30):
        root = Node("", "panel", [root])
    assert len(list(PROBE.walk_tree(root))) == 17


def test_xembed_geometry_observed_and_actual_peer_required():
    _, outer = identities()
    def output(args, **kwargs):
        if args[:3] == ["xwininfo", "-root", "-tree"]:
            return '  0xabc "electron": () 24x24+1142+768\n'
        if args[0] == "xprop":
            return '_NET_WM_PID(CARDINAL) = 16\n_XEMBED_INFO(_XEMBED_INFO) = 0, 1\n'
        return ('Map State: IsViewable\nAbsolute upper-left X: 1142\n'
                'Absolute upper-left Y: 768\nWidth: 24\nHeight: 24\n')
    with patch.object(PROBE.subprocess, "check_output", side_effect=output), \
            patch.object(PROBE, "identity", return_value=outer), \
            patch.object(PROBE, "x11_peer_pid", return_value=2400):
        windows = PROBE.x11_owned_windows(outer)
        assert windows[0]["rectangle"] == [1142, 768, 24, 24]
        assert windows[0]["embedded"]
    with patch.object(PROBE.subprocess, "check_output", side_effect=output), \
            patch.object(PROBE, "identity", return_value=outer), \
            patch.object(PROBE, "x11_peer_pid", return_value=16):
        assert PROBE.x11_owned_windows(outer) == []


def test_xembed_reused_outer_pid_refuses():
    _, outer = identities()
    with patch.object(PROBE.subprocess, "check_output", return_value=""), \
            patch.object(PROBE, "identity", return_value={**outer, "start_ticks": "445"}), \
            pytest.raises(RuntimeError, match="changed"):
        PROBE.x11_owned_windows(outer)


def test_runner_failed_row_selection_and_notifications_not_global_gate():
    source = (ROOT / "app/scripts/native-p33-guest.mjs").read_text()
    assert "selectedCases: cases" in source
    assert "cases.includes('tray-open')" in source
    assert "app_identity: identities.main" in source
    assert (source.index("notification row unavailable")
            > source.index("if (cases.includes('notification'))"))
    assert "Real desktop notification owner absent')" not in source
    assert "trayOpenSetup = { visible: false }" in source


@pytest.mark.parametrize("core,cases,success", [
    ("real", "tray-open,tray-exit", True),
    ("notification-fixture", "notification,tray-exit", True),
    ("real", "notification", False), ("real", "tray-open,tray-open", False),
    ("real", "callback", False), ("real", "", False),
])
def test_case_validation_executes_offline(core, cases, success):
    source = (ROOT / "app/scripts/native-p33-guest.mjs").read_text()
    block = source[source.index("const allowedCases"):
                   source.index("execFileSync('/usr/bin/python3'")]
    # Execute only the pure validation block, never import/launch Electron or guard.
    script = f"const options = {{core:{core!r}, cases:{cases!r}}};\n" + block
    result = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True)
    assert (result.returncode == 0) == success
