"""Run the real KDE emitter with namespace-local ownership, never host root.

Pytest remains the invoking non-root user in its existing PID namespace. A
single-ID child can emit fresh fixtures; a real ownership retry needs two IDs.
The restricted PID helper deliberately prevents subordinate-ID elevation, so
that capability can be unavailable. Only a failed capability probe is skippable,
never a failed emitter or assertion after the probe succeeded.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


class NamespaceUnavailableError(RuntimeError):
    """The exact requested unprivileged mapping could not be established."""


def namespace_prefix(retry: bool) -> list[str]:
    if retry:
        return ["unshare", "--user", "--map-auto", "--map-current-user",
                "--setuid", "0", "--setgid", "0", "--fork", "--kill-child=SIGKILL"]
    return ["unshare", "--user", "--map-root-user", "--fork", "--kill-child=SIGKILL"]


PROBE = """\
import json, os
from pathlib import Path
print(json.dumps({
    'uid': os.getuid(), 'euid': os.geteuid(),
    'gid': os.getgid(), 'egid': os.getegid(),
    'uid_map': [[int(x) for x in row.split()]
                for row in Path('/proc/self/uid_map').read_text().splitlines()],
    'gid_map': [[int(x) for x in row.split()]
                for row in Path('/proc/self/gid_map').read_text().splitlines()],
}))
"""


def verify_mapping(payload: dict, uid: int, gid: int, retry: bool) -> None:
    if [payload[key] for key in ("uid", "euid", "gid", "egid")] != [0, 0, 0, 0]:
        raise RuntimeError("Fixture worker did not enter namespace-local root")
    for key, caller in (("uid_map", uid), ("gid_map", gid)):
        rows = payload[key]
        if not rows or any(len(row) != 3 or min(row) < 0 or row[2] == 0
                           or row[1] == 0 for row in rows):
            raise RuntimeError(f"Unsafe {key}: host root must never be mapped")

        def mapped(identity):
            matches = [outer + identity - inner for inner, outer, count in rows
                       if inner <= identity < inner + count]
            if len(matches) != 1:
                raise RuntimeError(f"Missing or overlapping {key} for {identity}")
            return matches[0]

        if retry:
            if mapped(caller) != caller or mapped(0) == caller:
                raise RuntimeError(f"Retry needs distinct root and caller {key} mappings")
        elif rows != [[0, caller, 1]]:
            raise RuntimeError(f"Fresh fixture needs only the caller's {key}")


def probe_namespace(retry: bool) -> list[str]:
    uid, gid = os.getuid(), os.getgid()
    if uid == 0 or gid == 0 or os.geteuid() != uid or os.getegid() != gid:
        raise RuntimeError("Fixture pytest must remain a non-root, unprivileged caller")
    prefix = namespace_prefix(retry)
    requirement = ("two distinct subordinate UID/GID mappings for root-owned retry"
                   if retry else "unprivileged --map-root-user for fresh configuration")
    try:
        result = subprocess.run(
            [*prefix, sys.executable, "-c", PROBE],
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise NamespaceUnavailableError(f"KDE fixture needs {requirement}: {error}") from error
    if result.returncode:
        detail = result.stderr.strip()[:400] or f"probe exited {result.returncode}"
        raise NamespaceUnavailableError(f"KDE fixture needs {requirement}: {detail}")
    verify_mapping(json.loads(result.stdout), uid, gid, retry)
    return prefix


EMIT = """\
set -euo pipefail
source "$1"
home=$2 owner=$3 group=$4 retry=$5
if [[ $retry == yes ]]; then
    # Repair even a partially generated retry before ordinary pytest teardown.
    # Never repair a successful emission here: that would hide emitter bugs
    # from the non-root ownership and write assertions in the calling tests.
    cleanup_failed_retry() {
        local status=$?
        if (( status != 0 )); then
            chown -R "$owner:$group" -- "$home" || exit 1
        fi
        return "$status"
    }
    trap cleanup_failed_retry EXIT
    kde_write_user_config "$home" 0 0
    [[ $(stat -c '%u:%g' "$home/.config") == 0:0 ]]
    [[ $(stat -c '%u:%g' "$home/.config/kaccessrc") == 0:0 ]]
    printf 'retry initial namespace ownership: 0:0\n'
fi
kde_write_user_config "$home" "$owner" "$group"
for relative in .config .config/plasma-workspace .config/plasma-workspace/env \
        .config/plasma-workspace/env/odq-software.sh .config/kaccessrc; do
    [[ $(stat -c '%u:%g' "$home/$relative") == "$owner:$group" ]]
done
"""


def emit_config(recipe: Path, home: Path, retry: bool) -> None:
    # The probe is separate so only capability absence can skip. Execution,
    # timeout, malformed mappings and recipe failures stay hard test failures.
    prefix = probe_namespace(retry)
    owner, group = (os.getuid(), os.getgid()) if retry else (0, 0)
    try:
        result = subprocess.run(
            [*prefix, "bash", "-c", EMIT, "kde-fixture", str(recipe), str(home),
             str(owner), str(group), "yes" if retry else "no"],
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15,
        )
        if result.returncode:
            raise RuntimeError(
                f"KDE emitter failed after a successful mapping probe: {result.stderr}")
        if retry and result.stdout != "retry initial namespace ownership: 0:0\n":
            raise RuntimeError("KDE retry did not verify distinct initial root ownership")
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        if retry:
            # SIGKILL on timeout cannot run Bash's EXIT trap. Re-enter the same
            # mapped namespace for bounded ownership release, only after failure.
            # Never turn the original failure into a pass or capability skip.
            try:
                subprocess.run(
                    [*prefix, "chown", "-R", f"{owner}:{group}", "--", str(home)],
                    env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                    stdin=subprocess.DEVNULL, capture_output=True, text=True,
                    timeout=10, check=True,
                )
            except (OSError, subprocess.SubprocessError) as cleanup_error:
                error.add_note(f"Failed retry ownership cleanup for {home}: {cleanup_error}")
        raise
