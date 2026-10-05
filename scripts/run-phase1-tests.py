#!/usr/bin/env python3
"""Run an explicitly classified test selection behind the required PID boundary."""

from __future__ import annotations

import json
import os
import pwd
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISOLATION_HELPER = "/usr/local/sbin/odin-desktop-isolate"

# The same check runs in the capability probe and immediately before pytest.
# Never infer isolation from a successful unshare invocation alone, or rerun a
# failed suite through a different launcher. The supervisor remains PID 1 so
# pytest is not responsible for reaping children or handling PID-1 signals.
NAMESPACE_SUPERVISOR = """\
import os, signal, subprocess, sys
uid, gid, parent_namespace = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
namespace = os.readlink('/proc/self/ns/pid')
if (uid == 0 or os.getuid() != uid or os.geteuid() != uid
        or os.getgid() != gid or os.getegid() != gid or os.getpid() != 1
        or namespace == parent_namespace or os.readlink('/proc/1/ns/pid') != namespace):
    raise SystemExit('Refusing tests: PID namespace or non-root invoking identity not verified')
if len(sys.argv) == 4:
    raise SystemExit(0)
def terminate(signum, frame):
    raise SystemExit(128 + signum)
signal.signal(signal.SIGINT, terminate)
signal.signal(signal.SIGTERM, terminate)
child = subprocess.Popen(sys.argv[4:])
while True:
    pid, status = os.wait()
    if pid == child.pid:
        child.returncode = os.waitstatus_to_exitcode(status)
        raise SystemExit(child.returncode)
"""


def namespace_command(environment: dict[str, str]) -> list[str]:
    uid, gid = os.getuid(), os.getgid()
    if uid == 0 or gid == 0 or os.geteuid() != uid or os.getegid() != gid:
        raise SystemExit("Refusing tests: invoke the launcher as a non-root, unprivileged user")
    # Resolve the actual caller, not the spoofable USER environment variable.
    pwd.getpwuid(uid)
    parent_namespace = os.readlink("/proc/self/ns/pid")
    payload = [
        "env", "-i", *(f"{key}={value}" for key, value in environment.items()),
        str(ROOT / ".venv/bin/python"), "-c", NAMESPACE_SUPERVISOR,
        str(uid), str(gid), parent_namespace,
    ]
    candidates = []
    failures = []
    try:
        permission = subprocess.run(
            ["sudo", "-n", "-l", ISOLATION_HELPER],
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10,
        )
        if permission.returncode == 0:
            candidates.append(("restricted isolation helper", ["sudo", "-n", ISOLATION_HELPER]))
        else:
            failures.append(f"restricted isolation helper permission: exit {permission.returncode}")
    except (OSError, subprocess.TimeoutExpired) as exc:
        failures.append(f"restricted isolation helper permission: {type(exc).__name__}")
    # A current-user-only user namespace maps root-owned ancestors to overflow
    # UID 65534. It cannot pass unchanged ownership guards, even if PID checks pass.
    candidates.extend([
        ("non-interactive sudo fallback", [
            "sudo", "-n", "unshare", "--mount", "--pid", "--fork", "--mount-proc",
            "--kill-child", "sudo", "-n", "-u", f"#{uid}", "-g", f"#{gid}",
        ]),
    ])
    for label, prefix in candidates:
        command = [*prefix, *payload]
        try:
            returncode = _run_namespace(command, timeout=10, quiet=True)
        except (OSError, subprocess.TimeoutExpired) as exc:
            failures.append(f"{label}: {type(exc).__name__}")
            continue
        if returncode == 0:
            print(f"PID isolation: {label}; invoking UID {uid}", flush=True)
            return command
        failures.append(f"{label}: exit {returncode}")
    raise SystemExit(
        "Cannot establish a verified non-root PID namespace; no tests were started. "
        + "; ".join(failures)
        + ". Provision the restricted isolation helper or the non-interactive sudo fallback. "
        "Current-user-only user namespaces are not usable: root-owned ancestors become UID 65534."
    )


def run_namespace(command: list[str]) -> int:
    return _run_namespace(command)


def _run_namespace(command: list[str], *, timeout: int | None = None, quiet: bool = False) -> int:
    """Own one new process group; cancellation kills its init and all descendants."""
    def terminate(signum, frame):
        raise SystemExit(128 + signum)

    previous = {sig: signal.signal(sig, terminate) for sig in (signal.SIGINT, signal.SIGTERM)}
    process = None
    try:
        process = subprocess.Popen(
            command, cwd=ROOT, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            start_new_session=True,
            **({"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL} if quiet else {}),
        )
        return process.wait(**({"timeout": timeout} if timeout is not None else {}))
    finally:
        try:
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=10)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def main() -> int:
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Use the repository Python 3.12 environment")
    state = ROOT / ".test-state"
    state.mkdir(mode=0o700, exist_ok=True)
    arguments = sys.argv[1:]
    if not any(not argument.startswith("-") for argument in arguments):
        plan = json.loads((ROOT / "maintenance/test-plan.json").read_text())
        # A qualified frozen adapter executes the complete inherited corpus.
        # Do not also select its obsolete, unadapted setup as a duplicate.
        mapping_path = ROOT / "maintenance/phase2-suite-map.json"
        mapping = json.loads(mapping_path.read_text()) if mapping_path.exists() else {}
        adapted = {row["path"] for row in mapping.get("entries", [])
                   if row.get("status") == "restored"
                   and row.get("restoration", {}).get("mode") == "frozen-adapter"}
        selected = [path for path in plan["safe_pass_now"] if path not in adapted]
        if not selected:
            raise SystemExit("Refusing an unclassified full-suite invocation")
        arguments.extend(selected)
        arguments.extend(
            str(path.relative_to(ROOT))
            for path in sorted((ROOT / "tests").glob("test_desktop_*.py"))
        )
    if not any(not argument.startswith("-") for argument in arguments):
        raise SystemExit("Refusing an unclassified full-suite invocation")
    with tempfile.TemporaryDirectory(prefix="isolation-", dir=state) as scratch:
        home = Path(scratch)
        for name in ("home", "config", "data", "cache"):
            (home / name).mkdir(mode=0o700)
        environment = {
            "PATH": f"{ROOT / '.venv/bin'}:/usr/bin:/bin",
            "HOME": str(home / "home"),
            "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_DATA_HOME": str(home / "data"),
            "XDG_CACHE_HOME": str(home / "cache"),
            "LANG": "C.UTF-8",
            "PYTHONPATH": str(ROOT),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        }
        # This is a cleanup tag, not an authentication credential. Preserve it
        # so GitHub can also identify children after an abrupt launcher death.
        if tracking := os.environ.get("RUNNER_TRACKING_ID"):
            environment["RUNNER_TRACKING_ID"] = tracking
        # env -i excludes credentials, display/socket paths and live config overrides.
        command = [
            *namespace_command(environment),
            str(ROOT / ".venv/bin/pytest"), "-p", "pytest_asyncio.plugin",
            "-p", "pytest_cov.plugin", "-p", "pytest_timeout", "--timeout=90",
            "--timeout-method=signal", "-q", *arguments,
        ]
        return run_namespace(command)


if __name__ == "__main__":
    raise SystemExit(main())
