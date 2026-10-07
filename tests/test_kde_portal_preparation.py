"""Fixed guest KDE backend preparation; never touches an actual user manager."""
import importlib.util
import types
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/qualification/lab/guest/orca_run.py"


@pytest.fixture
def prepared(monkeypatch):
    spec = importlib.util.spec_from_file_location("kde_portal_guest", SCRIPT)
    guest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guest)
    commands = []
    config = {"prior": "", "status": "b true", "fail_restart": False}
    executable = "/usr/lib/x86_64-linux-gnu/libexec/xdg-desktop-portal-kde"
    monkeypatch.setattr(
        guest.Path, "lstat", lambda p: types.SimpleNamespace(st_uid=0, st_mode=0o755)
    )
    monkeypatch.setattr(guest.Path, "is_symlink", lambda p: False)
    monkeypatch.setattr(guest.Path, "stat", lambda p: types.SimpleNamespace(st_uid=1001))
    monkeypatch.setattr(guest.Path, "resolve", lambda p: Path(executable))
    flags_text = (
        "QT_ACCESSIBILITY=1\0QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1\0"
        "DBUS_SESSION_BUS_ADDRESS=guest-session\0"
        "XDG_RUNTIME_DIR=/run/user/1001\0WAYLAND_DISPLAY=wayland-0\0"
    )
    monkeypatch.setattr(
        guest.Path, "read_text", lambda p: flags_text
    )

    def output(argv, **kwargs):
        assert kwargs["user"] == kwargs["group"] == 1001
        assert kwargs["timeout"] == 20
        assert argv[:3] == ["env", "-i", "DBUS_SESSION_BUS_ADDRESS=guest-session"]
        cmd = argv[5:]
        commands.append(cmd)
        if cmd[-1] == "show-environment":
            return config["prior"]
        if cmd[0] == "busctl":
            if cmd[-1] == "GetAddress":
                return 's "actual-a11y"'
            return config["status"]
        if "restart" in cmd and config["fail_restart"]:
            raise RuntimeError("restart failure")
        if "MainPID" in cmd:
            return "123"
        return ""

    monkeypatch.setattr(guest.subprocess, "check_output", output)
    return guest, commands, config


def invoke(guest):
    return guest.prepare_kde_portal(
        {"DBUS_SESSION_BUS_ADDRESS": "guest-session", "XDG_RUNTIME_DIR": "/run/user/1001",
         "WAYLAND_DISPLAY": "wayland-0"},
        types.SimpleNamespace(pw_uid=1001, pw_gid=1001), {"address": "actual-a11y"},
    )


def test_restart_exact_service_and_restore_absent_manager_values(prepared):
    guest, commands, _ = prepared
    result = invoke(guest)
    assert ["systemctl", "--user", "restart", "plasma-xdg-desktop-portal-kde.service"] in commands
    assert [
        "systemctl", "--user", "unset-environment", "QT_ACCESSIBILITY",
        "QT_LINUX_ACCESSIBILITY_ALWAYS_ON",
    ] in commands
    assert result["manager_environment_restored"] is True
    assert result["collector_address"] == "actual-a11y"
    assert all("plasmashell" not in str(cmd) for cmd in commands)


def test_restore_existing_value_even_on_restart_failure(prepared):
    guest, commands, config = prepared
    config.update(prior="QT_ACCESSIBILITY=0\nUNRELATED=private", fail_restart=True)
    with pytest.raises(RuntimeError, match="restart failure"):
        invoke(guest)
    assert commands[-1] == ["systemctl", "--user", "set-environment", "QT_ACCESSIBILITY=0"]
    assert commands[-2] == [
        "systemctl", "--user", "unset-environment", "QT_LINUX_ACCESSIBILITY_ALWAYS_ON"
    ]
    assert "private" not in str(commands)


def test_disabled_accessibility_blocks_restart(prepared):
    guest, commands, config = prepared
    config["status"] = "b false"
    with pytest.raises(RuntimeError, match="enabled live accessibility"):
        invoke(guest)
    assert not any("restart" in cmd for cmd in commands)


def test_unexpected_manager_value_blocks_mutation(prepared):
    guest, commands, config = prepared
    config["prior"] = "QT_ACCESSIBILITY=unexpected"
    with pytest.raises(RuntimeError, match="Unsupported prior"):
        invoke(guest)
    assert not any("set-environment" in cmd for cmd in commands)


def test_ready_collector_required(prepared):
    guest, commands, _ = prepared
    with pytest.raises(RuntimeError, match="ready accessibility collector"):
        guest.prepare_kde_portal({}, types.SimpleNamespace(pw_uid=1001, pw_gid=1001), {})
    assert not commands
