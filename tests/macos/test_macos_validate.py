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


def stub_log(tmp_path, body: str) -> str:
    """A ``log`` on PATH that writes what the test says, then the real tools."""
    folder = tmp_path / "bin"
    folder.mkdir()
    (folder / "log").write_text("#!/bin/sh\n" + body)
    (folder / "log").chmod(0o755)
    return f"{folder}:/usr/bin:/bin"


def run_log(tmp_path, body: str, pattern: str = "error") -> tuple[str, list[str]]:
    scratch = tmp_path / "tmp"
    scratch.mkdir(exist_ok=True)
    probe = macos_validate.build_command(check("log_present", f"unit=sshd:{pattern}",
                                               window_seconds=5))
    environment = {**os.environ, "PATH": stub_log(tmp_path, body), "TMPDIR": str(scratch)}
    out = subprocess.run(["/bin/sh", "-c", probe], capture_output=True, text=True, timeout=60,
                         env=environment).stdout
    return out, sorted(path.name for path in scratch.iterdir())


def test_the_log_query_that_supplies_the_lines_is_the_one_that_decides(tmp_path):
    out, left = run_log(tmp_path, 'echo "an error here"; echo "fine"; exit 0\n')
    assert out == "an error here\nLOG_READ_OK\n" and left == []


def test_a_failed_log_query_is_an_error_with_its_reason_never_a_read(tmp_path):
    """Odin's case: the data query fails (exit 65); nothing may say the log was read."""
    out, left = run_log(tmp_path, 'echo "an error here"; echo "log: access denied" >&2; exit 65\n')
    assert out == "LOG_CHECK_ERROR log exit 65\nlog: access denied\n" and left == []


def test_many_matches_are_bounded_and_still_a_read(tmp_path):
    out, left = run_log(tmp_path, 'i=0; while [ $i -lt 500 ]; do echo "error $i"; '
                                  'i=$((i + 1)); done\n')
    lines = out.splitlines()
    assert lines[:2] == ["error 0", "error 1"] and len(lines) == 21
    assert lines[-1] == "LOG_READ_OK" and left == []


def test_the_log_and_service_probes_pass_the_governor_as_low_risk():
    from src.desktop.platform import macos_safety
    from src.tools.risk_classifier import RiskLevel

    for item in (check("log_absent", "unit=sshd:error", window_seconds=5),
                 check("service", "com.example.job")):
        probe = macos_validate.build_command(item)
        assert macos_safety.assess_command(probe).assessment.level == RiskLevel.LOW, probe


@pytest.mark.parametrize("kind,target", [("http", "http://127.0.0.1:9/"),
                                         ("process", "--token-file"),
                                         ("command", "echo ready")])
def test_other_checks_are_odins_own(kind, target):
    item = check(kind, target)
    assert macos_validate.build_command(item) == post_validation._build_command.linux_original(item)
