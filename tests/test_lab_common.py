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
                                    ("provision",)])
def test_execution_never_implicitly_provisions_or_writes_host_root(emit, arguments):
    result = emit(*arguments)
    assert result.returncode == 64
    assert "unexpected provisioning" not in result.stderr
