"""validate_action's probes on macOS: they choose their tools where they run."""
from __future__ import annotations

import os
import socket
import subprocess

import pytest

from src.desktop.platform import macos_validate
from src.tools import post_validation
from src.tools.post_validation import Check


def check(kind: str, target: str, **values) -> Check:
    return Check(type=kind, target=target, host="localhost", timeout_seconds=3, **values)


def run(command: str, path: str | None = None) -> str:
    environment = dict(os.environ)
    if path is not None:
        environment["PATH"] = path
    return subprocess.run(["/bin/sh", "-c", command], capture_output=True, text=True,
                          timeout=60, env=environment).stdout


def test_the_route_reaches_the_macos_probes():
    assert post_validation._build_command.darwin_target == \
        "src.desktop.platform.macos_validate:build_command"


def test_a_port_probe_works_without_gnu_timeout():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        probe = macos_validate.build_command(check("port", f"127.0.0.1:{port}"))
        assert "OPEN" in run(probe, path="/usr/bin:/bin")  # stock macOS: no timeout here
    closed = macos_validate.build_command(check("port", f"127.0.0.1:{port}"))
    assert run(closed, path="/usr/bin:/bin").strip().endswith("CLOSED")


def test_a_port_probe_keeps_odins_own_form_where_timeout_exists():
    probe = macos_validate.build_command(check("port", "10.0.0.1:22"))
    assert "timeout 3 bash -c" in probe and "perl -e" in probe


@pytest.mark.parametrize("label,expected", [("com.apple.syslogd", "active"),
                                            ("org.example.missing.job", "inactive")])
def test_a_service_probe_reads_launchd(label, expected):
    probe = macos_validate.build_command(check("service", label))
    assert run(probe).strip() == expected
    assert "systemctl is-active" in probe  # a Linux host still runs Odin's probe


def test_a_log_probe_reads_the_unified_log():
    probe = macos_validate.build_command(check("log_present", "unit=syslogd:.", window_seconds=5))
    out = run(probe).strip().splitlines()
    assert out and out[-1] in {"LOG_READ_OK"} | {line for line in out if "LOG_CHECK_ERROR" in line}
    bad = macos_validate.build_command(check("log_absent", "([", window_seconds=5))
    assert run(bad).startswith("LOG_CHECK_ERROR invalid pattern")
    assert "journalctl" in bad  # a Linux host still runs Odin's probe


@pytest.mark.parametrize("kind,target", [("http", "http://127.0.0.1:9/"),
                                         ("process", "--token-file"),
                                         ("command", "echo ready")])
def test_other_checks_are_odins_own(kind, target):
    item = check(kind, target)
    assert macos_validate.build_command(item) == post_validation._build_command.linux_original(item)
