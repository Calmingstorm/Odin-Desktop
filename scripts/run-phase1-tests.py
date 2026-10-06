#!/usr/bin/env python3
"""Run an explicitly classified test selection behind the required PID boundary."""

from __future__ import annotations

import importlib.util
import os
import pwd
import signal
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISOLATION_HELPER = "/usr/local/sbin/odin-desktop-isolate"
# Mounted privately inside the helper namespace; host paths below it are hidden.
PRIVATE_TMP = Path("/tmp")

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
# Keep the command below a namespace-local runner, not PID 2 itself. Frozen
# protocol tests intentionally use PID 2 as a forged recovery-owner identity.
# The wrapper has no authority and init still reaps all orphan descendants.
child = subprocess.Popen([sys.executable, '-c',
    'import subprocess, sys; raise SystemExit(subprocess.call(sys.argv[1:]))', *sys.argv[4:]])
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
            # --private-tmp: a RAM-backed /tmp of its own inside the namespace.
            candidates.append(("restricted isolation helper",
                               ["sudo", "-n", ISOLATION_HELPER, "--private-tmp"]))
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


def _under_tmp(path: Path) -> bool:
    """True when the helper's private /tmp would hide this host path."""
    resolved, hidden = Path(path).resolve(), PRIVATE_TMP.resolve()
    return resolved == hidden or hidden in resolved.parents


def _scratch_root() -> Path | None:
    """An optional private HOME/XDG scratch parent (CI uses tmpfs), never a shared directory.

    TMPDIR is deliberately untouched: the isolation helper already gives each
    namespace a private RAM-backed /tmp, and longer temp paths break socket limits.
    """
    value = os.environ.get("ODIN_TEST_SCRATCH")
    if not value:
        return None
    root = Path(value)
    if not root.is_absolute():
        raise SystemExit("ODIN_TEST_SCRATCH must be an absolute path")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = root.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077):
        raise SystemExit("ODIN_TEST_SCRATCH must be a private directory owned by this user")
    return root


def main(argv: list[str] | None = None) -> int:
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Use the repository Python 3.12 environment")
    state = ROOT / ".test-state"
    state.mkdir(mode=0o700, exist_ok=True)
    arguments = list(sys.argv[1:] if argv is None else argv)
    extras_only = "--additional-desktop-boundaries" in arguments
    if extras_only:
        arguments.remove("--additional-desktop-boundaries")
        if arguments not in ([], ["--collect-only"]):
            raise SystemExit("Additional Desktop selection accepts only --collect-only")
    if not any(not argument.startswith("-") for argument in arguments):
        spec = importlib.util.spec_from_file_location(
            "phase1_default_selection", Path(__file__).with_name("phase1-default-selection.py")
        )
        if spec is None or spec.loader is None:
            raise SystemExit("Refusing an unclassified full-suite invocation")
        selection = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(selection)
        # Run each group in this supervisor process, so cancellation reaches
        # run_namespace's exact owned group rather than orphaning an extra launcher.
        return selection.run_default(ROOT, arguments, execute=lambda command: main(command[2:]),
                                     extras_only=extras_only)
    if not any(not argument.startswith("-") for argument in arguments):
        raise SystemExit("Refusing an unclassified full-suite invocation")
    scratch_root = _scratch_root() or state
    with tempfile.TemporaryDirectory(prefix="isolation-", dir=scratch_root) as scratch:
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
        # Native process-identity guards bound cmdline reads to 16 KiB. The
        # complete classified corpus must not exceed that bound just because
        # pytest receives hundreds of explicit selectors. Pytest >=8.2 expands
        # one UTF-8 response-file argument per line without changing selection.
        if sum(len(os.fsencode(argument)) + 1 for argument in arguments) > 8192:
            if any("\n" in argument or "\r" in argument for argument in arguments):
                raise SystemExit("Refusing newline-containing response-file arguments")
            # Pytest loads -p plugins before expanding response-file arguments.
            # Keep explicit plugin loads on argv, or long selections silently
            # omit collection/ownership hooks while shorter groups load them.
            plugin_arguments, response_arguments = [], []
            index = 0
            while index < len(arguments):
                argument = arguments[index]
                if argument == "-p" and index + 1 < len(arguments):
                    plugin_arguments.extend(arguments[index:index + 2])
                    index += 2
                    continue
                if argument.startswith("-p") and len(argument) > 2:
                    plugin_arguments.append(argument)
                else:
                    response_arguments.append(argument)
                index += 1
            response = home / "pytest-arguments.txt"
            response.write_text("\n".join(response_arguments) + "\n", encoding="utf-8")
            arguments = [*plugin_arguments, f"@{response}"]
        # env -i excludes credentials, display/socket paths and live config overrides.
        isolation = namespace_command(environment)
        if "--private-tmp" in isolation and _under_tmp(ROOT):
            raise SystemExit(f"Repository {ROOT} is under /tmp, which the isolation helper's "
                             "private /tmp hides, with its environment. "
                             "Use a checkout outside /tmp.")
        if "--private-tmp" in isolation and _under_tmp(home):
            raise SystemExit(f"Isolation scratch {home} is under /tmp, which the isolation "
                             "helper's private /tmp hides from pytest. Set ODIN_TEST_SCRATCH "
                             "to a private directory outside /tmp (CI uses /dev/shm).")
        command = [
            *isolation,
            str(ROOT / ".venv/bin/pytest"), "-p", "pytest_asyncio.plugin",
            "-p", "pytest_cov.plugin", "-p", "pytest_timeout", "--timeout=90",
            "--timeout-method=signal", "-q", *arguments,
        ]
        return run_namespace(command)


if __name__ == "__main__":
    raise SystemExit(main())
