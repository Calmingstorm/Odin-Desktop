#!/usr/bin/env python3
"""Guest-only native qualification command, never a workstation input helper.

Run as guest root through Incus. Graphics and bus belong to the actual odq
login; commands drop to odq. Optional PID isolation is a real unshare, not a
claimed namespace. This development helper is not installed in candidates.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pwd
import subprocess
import sys
from pathlib import Path


def capture_target(value: str, root: Path = Path("/home/odq/qualification")) -> Path:
    """Validate existing parent and resolved destination before invoking capture."""
    allowed = root.resolve(strict=True)
    if allowed != root.absolute() or not allowed.is_dir():
        raise RuntimeError("Qualification capture root must be a real directory")
    target = Path(value).absolute()
    parent = target.parent.resolve(strict=True)
    resolved = target.resolve(strict=False)
    if (not parent.is_relative_to(allowed) or not resolved.is_relative_to(allowed)
            or resolved == allowed or target.is_symlink() or not parent.is_dir()):
        raise RuntimeError("Capture must stay in the guest qualification directory")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("desktop", choices=("cinnamon", "gnome", "kde"))
    parser.add_argument("--home")
    parser.add_argument("--isolated", action="store_true")
    parser.add_argument("--capture")
    args, argv = parser.parse_known_args()
    if os.geteuid() != 0:
        raise RuntimeError("Use guest root to discover and drop to the native login")
    if subprocess.check_output(["systemd-detect-virt"], text=True).strip() not in ("kvm", "qemu"):
        raise RuntimeError("Native qualification requires a real lab VM")
    if Path("/etc/hostname").read_text().strip() != f"odq-{args.desktop}":
        raise RuntimeError("Guest name does not match the selected lab desktop")
    marker = Path("/etc/odin-desktop-qualification")
    if marker.is_symlink() or marker.stat().st_uid != 0 or marker.stat().st_mode & 0o022:
        raise RuntimeError(
            "Qualification marker must be root-owned and not writable by the guest user")
    if marker.read_text() != "odin-desktop-qualification-v1\n":
        raise RuntimeError("Wrong qualification marker")
    spec = importlib.util.spec_from_file_location("odq_smoke", Path(__file__).with_name("smoke.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("Missing reviewed guest session discovery")
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    account = pwd.getpwnam("odq")
    info = smoke.session_info()
    expected = "x11" if args.desktop == "cinnamon" else "wayland"
    if info["Type"] != expected:
        raise RuntimeError(f"Expected {expected}, got {info['Type']}")
    env = smoke.session_environment(account.pw_uid, expected)
    if args.home:
        home = Path(args.home).resolve(strict=True)
        allowed = Path("/home/odq/qualification").resolve(strict=True)
        temporary = home.parent == Path("/tmp") and home.name.startswith("odrc-")
        if ((not home.is_relative_to(allowed) and not temporary)
                or home.stat().st_uid != account.pw_uid):
            raise RuntimeError("Override HOME must be an odq-owned qualification directory")
        env["HOME"] = str(home)
        env["XDG_CONFIG_HOME"] = str(home / ".config")
        env["XDG_DATA_HOME"] = str(home / ".local/share")
        env["XDG_CACHE_HOME"] = str(home / ".cache")
    if argv and argv[0] == "--":
        argv = argv[1:]
    if args.capture:
        target = capture_target(args.capture)
        argv = ["/usr/local/lib/odq/capture", str(target)]
    if not argv:
        print(json.dumps({"session": info, "environment": env, "uid": account.pw_uid,
                          "outer_pid_ns": os.readlink("/proc/self/ns/pid")}, sort_keys=True))
        return 0
    if args.isolated:
        if not args.home:
            raise RuntimeError("Source seam requires an explicit disposable HOME")
        env.update({"ODIN_APP_E2E": "1", "ODIN_REAL_CORE_TEST_ISOLATED": "1",
                    "ODIN_REAL_CORE_ROOT": env["HOME"],
                    "ODIN_REAL_CORE_OUTER_PID_NS": os.readlink("/proc/self/ns/pid")})
    command = ["runuser", "-u", "odq", "--", "env", "-i",
               *(f"{key}={value}" for key, value in env.items()), *argv]
    if args.isolated:
        command = ["unshare", "--pid", "--fork", "--mount-proc", "--", *command]
    return subprocess.call(command)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(json.dumps({"passed": False, "error": str(error)}), file=sys.stderr)
        sys.exit(1)
