#!/usr/bin/env python3
"""Guest-only smoke. Validate logind, an owned Orca process and a real capture."""

from __future__ import annotations

import json
import pwd
import subprocess
import sys
import time
from pathlib import Path


def command(*argv):
    return subprocess.check_output(argv, text=True, timeout=20).strip()


def session_info():
    sessions = json.loads(command("loginctl", "list-sessions", "--json=short"))
    for session in sessions:
        if session.get("user") == "odq":
            values = command("loginctl", "show-session", str(session["session"]),
                             "-p", "Type", "-p", "Active", "-p", "Desktop", "-p", "State")
            result = dict(line.split("=", 1) for line in values.splitlines())
            if result.get("Active") == "yes" and result.get("Type") in ("x11", "wayland"):
                return result
    raise RuntimeError("No active odq graphical logind session")


def session_environment(uid, expected_type):
    candidates = []
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != uid:
                continue
            entries = (process / "environ").read_bytes().split(b"\0")
            environment = dict(entry.decode().split("=", 1) for entry in entries if b"=" in entry)
            if "DISPLAY" in environment or "WAYLAND_DISPLAY" in environment:
                candidates.append(environment)
        except (OSError, UnicodeError, ValueError):
            continue
    for environment in candidates:
        if (environment.get("DBUS_SESSION_BUS_ADDRESS")
                and environment.get("XDG_SESSION_TYPE") == expected_type
                and (expected_type != "wayland" or environment.get("WAYLAND_DISPLAY"))):
            # Never inherit arbitrary guest credentials into a proof helper.
            selected = {key: value for key, value in environment.items() if key in (
                "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR",
                "DBUS_SESSION_BUS_ADDRESS", "HYPRLAND_INSTANCE_SIGNATURE",
                "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP",
            )}
            selected.update({"HOME": "/home/odq", "USER": "odq", "LOGNAME": "odq",
                             "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"})
            return selected
    raise RuntimeError("No graphical session environment with its guest user bus")


def smoke(desktop):
    if command("systemd-detect-virt") not in ("kvm", "qemu"):
        raise RuntimeError("Guest smoke requires a VM")
    account = pwd.getpwnam("odq")
    info = session_info()
    expected = "x11" if desktop == "cinnamon" else "wayland"
    if info["Type"] != expected:
        raise RuntimeError(f"Expected {expected}, got {info['Type']}")
    expected_desktops = {"cinnamon": ("cinnamon",), "gnome": ("gnome",),
                         "kde": ("plasma", "kde"), "hyprland": ("hyprland",)}[desktop]
    if not any(value in info.get("Desktop", "").lower() for value in expected_desktops):
        raise RuntimeError(f"Wrong desktop identity: {info}")
    environment = session_environment(account.pw_uid, expected)
    orca = command("pgrep", "-u", str(account.pw_uid), "-f", "(^|/)orca( |$)")
    if not orca:
        raise RuntimeError("Orca is not running as odq")
    target = Path("/var/tmp/odq-smoke.png")
    target.unlink(missing_ok=True)
    capture = subprocess.run(
        ["runuser", "-u", "odq", "--", "env", "-i",
         *(f"{key}={value}" for key, value in environment.items()),
         "/usr/local/lib/odq/capture", str(target)], check=True, timeout=75,
        text=True, capture_output=True,
    )
    from PIL import Image
    with Image.open(target) as image:
        image.load()
        if image.width < 640 or image.height < 480:
            raise RuntimeError("Unexpectedly small screenshot")
        if all(lo == hi for lo, hi in image.convert("RGB").getextrema()):
            raise RuntimeError("Uniform screenshot is not a graphical smoke proof")
        size = [image.width, image.height]
    listeners = command("ss", "-H", "-lntup")
    for line in listeners.splitlines():
        address = line.split()[4].rsplit(":", 1)[0].strip("[]")
        if address not in ("127.0.0.1", "::1"):
            # DHCP clients bind the managed interface for NAT networking.
            if not (line.startswith("udp")
                    and line.split()[4].rsplit(":", 1)[1] in ("68", "546")):
                raise RuntimeError(f"Guest exposes a listener: {line}")
    return {"passed": True, "session": info, "orca_pids": orca.splitlines(),
            "screenshot_size": size, "timestamp": int(time.time()),
            "capture_output": capture.stdout, "listeners": listeners,
            "limits": "Orca process start only, not verified speech or app accessibility"}


if __name__ == "__main__":
    try:
        print(json.dumps(smoke(sys.argv[1])))
    except Exception as exc:
        print(json.dumps({"passed": False, "error": str(exc)}))
        raise SystemExit(1)
