"""Exercise common guest emitters in fixtures, never source/run provisioning."""

import configparser
import os
import subprocess
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1] / "scripts/qualification/lab/guest/common.sh"


@pytest.fixture
def emit(tmp_path):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    # Any accidental provisioning or daemon call fails before touching the host.
    for tool in ("apt-get", "systemctl", "useradd", "passwd", "systemd-detect-virt", "id"):
        stub = binaries / tool
        stub.write_text('#!/bin/sh\necho "unexpected provisioning: $0" >&2\nexit 99\n')
        stub.chmod(0o755)
    def execute(*args):
        return subprocess.run(
            ["/bin/bash", str(RECIPE), *map(str, args)], capture_output=True, text=True,
            env={"PATH": f"{binaries}:/usr/bin:/bin"},
        )
    return execute


def test_common_explicit_session_and_speech_dependencies(emit):
    result = emit("--print-packages")
    assert result.returncode == 0, result.stderr
    packages = result.stdout.splitlines()
    assert len(packages) == len(set(packages))
    assert set(packages) == {
        "orca", "dbus-x11", "at-spi2-core", "python3", "python3-gi", "python3-pil",
        "gir1.2-atspi-2.0", "gir1.2-gtk-3.0", "fonts-dejavu-core", "mesa-utils",
        "libpam-systemd", "speech-dispatcher", "speech-dispatcher-espeak-ng",
        "espeak-ng", "iproute2",
    }


def test_guest_logind_poweroff_and_idle_policy_emitted_without_daemon_access(emit, tmp_path):
    root = tmp_path / "guest"
    result = emit("--write-power-config", root)
    assert result.returncode == 0, result.stderr
    config = configparser.ConfigParser()
    config.optionxform = str
    config.read(root / "etc/systemd/logind.conf.d/99-odq-power.conf")
    assert dict(config["Login"]) == {
        "HandlePowerKey": "poweroff", "HandlePowerKeyLongPress": "poweroff",
        "HandleSuspendKey": "ignore", "HandleHibernateKey": "ignore",
        "HandleLidSwitch": "ignore", "HandleLidSwitchExternalPower": "ignore",
        "HandleLidSwitchDocked": "ignore", "IdleAction": "ignore",
    }
    units = root / "etc/systemd/system"
    assert {path.name for path in units.iterdir()} == {
        "sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target",
        "suspend-then-hibernate.target", "systemd-suspend.service",
        "systemd-hibernate.service", "systemd-hybrid-sleep.service",
        "systemd-suspend-then-hibernate.service",
    }
    assert all(path.is_symlink() and os.readlink(path) == "/dev/null"
               for path in units.iterdir())
    # A second emission remains idempotent, including existing masks.
    assert emit("--write-power-config", root).returncode == 0


@pytest.mark.parametrize("arguments", [(), ("--write-power-config",),
                                    ("--write-power-config", "/"),
                                    ("--write-power-config", "relative"),
                                    ("--write-accessibility-config",),
                                    ("--write-accessibility-config", "/"),
                                    ("--write-accessibility-config", "relative"),
                                    ("provision",)])
def test_execution_never_implicitly_provisions_or_writes_host_root(emit, arguments):
    result = emit(*arguments)
    assert result.returncode == 64
    assert "unexpected provisioning" not in result.stderr


@pytest.fixture
def accessibility(emit, tmp_path):
    root = tmp_path / "guest"
    autostart = root / "etc/xdg/autostart"
    autostart.mkdir(parents=True)
    (autostart / "odq-accessibility.desktop").write_text("old concurrent activation")
    result = emit("--write-accessibility-config", root)
    assert result.returncode == 0, result.stderr
    return root


def test_accessibility_has_one_guest_scoped_startup_owner(accessibility, emit):
    root = accessibility
    autostart = root / "etc/xdg/autostart"
    config = configparser.ConfigParser()
    config.optionxform = str
    config.read(autostart / "odq-orca.desktop")
    assert config["Desktop Entry"]["Exec"] == "/usr/local/lib/odq/orca-session"
    config.read(autostart / "orca-autostart.desktop")
    assert config["Desktop Entry"]["Hidden"] == "true"
    assert not (autostart / "odq-accessibility.desktop").exists()
    assert {p.name for p in autostart.iterdir()} == {
        "orca-autostart.desktop", "odq-orca.desktop",
    }
    assert (root / "usr/local/lib/odq/orca-session").stat().st_mode & 0o111 == 0o111
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert emit("--write-accessibility-config", root).returncode == 0
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert not (root / "etc/systemd").exists()  # No broad service masks.


@pytest.fixture
def run_orca_wrapper(accessibility, tmp_path):
    binaries = tmp_path / "fake-session-bin"
    binaries.mkdir()
    log = tmp_path / "calls"
    counter = tmp_path / "bus-calls"
    scripts = {
        "gsettings": '''printf 'gsettings %s\\n' "$*" >>"$CALL_LOG"
[ "${FAIL_SETTING:-}" != "$3" ] || exit 23
''',
        "orca": '''printf 'orca %s\\n' "$*" >>"$CALL_LOG"
printf '%s\\n' "$$" >"$ORCA_PID"
exit "${ORCA_EXIT:-0}"
''',
        "dbus-send": '''printf 'dbus-send %s\\n' "$*" >>"$CALL_LOG"
n=0
if [ -f "$BUS_COUNTER" ]; then n=$(cat "$BUS_COUNTER"); fi
n=$((n + 1))
printf '%s\\n' "$n" >"$BUS_COUNTER"
if [ "$n" -ge "${READY_AFTER:-1}" ]; then
    printf 'boolean true\\n'
else
    printf 'boolean false\\n'
fi
''',
        "sleep": '''printf 'sleep %s\\n' "$*" >>"$CALL_LOG"
''',
    }
    for name, body in scripts.items():
        binary = binaries / name
        binary.write_text("#!/bin/sh\nset -eu\n" + body)
        binary.chmod(0o755)
    def execute(**env):
        # Everything which could alter accessibility is fake. No real session
        # environment or gsettings/orca execution is inherited from the host.
        process = subprocess.Popen(
            [str(accessibility / "usr/local/lib/odq/orca-session")],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={"PATH": f"{binaries}:/usr/bin:/bin", "CALL_LOG": str(log),
                 "BUS_COUNTER": str(counter), "ORCA_PID": str(tmp_path / "orca-pid"),
                 **env},
        )
        stdout, stderr = process.communicate(timeout=5)
        result = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
        calls = log.read_text().splitlines() if log.exists() else []
        pid_file = tmp_path / "orca-pid"
        return result, calls, process.pid, int(pid_file.read_text()) if pid_file.exists() else None
    return execute


@pytest.mark.parametrize("desktop", ["GNOME", "X-Cinnamon", "Hyprland", ""])
def test_orca_single_exec_follows_both_accessibility_settings(run_orca_wrapper, desktop):
    result, calls, wrapper_pid, orca_pid = run_orca_wrapper(XDG_CURRENT_DESKTOP=desktop)
    assert result.returncode == 0, result.stderr
    assert calls == [
        "gsettings set org.gnome.desktop.interface toolkit-accessibility true",
        "gsettings set org.gnome.desktop.a11y.applications screen-reader-enabled true",
        "orca --replace",
    ]
    assert wrapper_pid == orca_pid  # exec, not a detached child or restart supervisor.


def test_kde_waits_for_shell_then_executes_orca_once(run_orca_wrapper):
    result, calls, wrapper_pid, orca_pid = run_orca_wrapper(
        XDG_CURRENT_DESKTOP="KDE", READY_AFTER="3", ORCA_EXIT="17",
    )
    assert result.returncode == 17  # Preserve Orca failure, never restart it.
    assert calls[:2] == [
        "gsettings set org.gnome.desktop.interface toolkit-accessibility true",
        "gsettings set org.gnome.desktop.a11y.applications screen-reader-enabled true",
    ]
    assert len([call for call in calls if call.startswith("dbus-send ")]) == 3
    assert calls.count("sleep 1") == 2
    assert calls[-1] == "orca --replace"
    assert calls.count("orca --replace") == 1
    assert all("--reply-timeout=1000" in call and "string:org.kde.plasmashell" in call
               for call in calls if call.startswith("dbus-send "))
    assert wrapper_pid == orca_pid


def test_kde_readiness_timeout_is_bounded_and_never_launches_orca(run_orca_wrapper):
    result, calls, _, orca_pid = run_orca_wrapper(
        XDG_CURRENT_DESKTOP="KDE", READY_AFTER="999",
    )
    assert result.returncode == 78
    assert "Plasma session bus name not ready" in result.stderr
    assert len([call for call in calls if call.startswith("dbus-send ")]) == 30
    assert calls.count("sleep 1") == 29
    assert not any(call.startswith("orca ") for call in calls)
    assert orca_pid is None


@pytest.mark.parametrize("setting, call_count", [
    ("toolkit-accessibility", 1), ("screen-reader-enabled", 2),
])
def test_failed_accessibility_setting_prevents_orca_start(run_orca_wrapper, setting, call_count):
    result, calls, _, orca_pid = run_orca_wrapper(FAIL_SETTING=setting)
    assert result.returncode == 23
    assert len(calls) == call_count
    assert all(call.startswith("gsettings ") for call in calls)
    assert orca_pid is None
