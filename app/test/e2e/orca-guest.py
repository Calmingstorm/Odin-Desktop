#!/usr/bin/env python3
"""VM-only identity guard and AT-SPI-grounded file-dialog keyboard input."""

from __future__ import annotations

import json
import os
import pwd
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path


def command(*args):
    return subprocess.check_output(args, text=True, timeout=15).strip()


def guard():
    if command("systemd-detect-virt") not in ("kvm", "qemu") or not socket.gethostname().startswith(
        "odq-"
    ):
        raise RuntimeError("Actual odq VM required")
    account = pwd.getpwnam("odq")
    root = Path(os.environ["ODIN_ORCA_ROOT"])
    if (
        os.geteuid() != account.pw_uid
        or not str(root).startswith("/var/tmp/odq-orca-")
        or root.is_symlink()
        or root.stat().st_uid != account.pw_uid
    ):
        raise RuntimeError("Owned odq user and disposable guest root required")
    home = Path(os.environ["HOME"]).resolve(strict=True)
    if not home.is_relative_to(root.resolve(strict=True)) or home.stat().st_uid != account.pw_uid:
        raise RuntimeError("Disposable guest home required")
    sid = os.environ.get("XDG_SESSION_ID", "")
    if not sid or not sid.isalnum():
        raise RuntimeError("Explicit graphical logind session required")
    info = dict(
        line.split("=", 1)
        for line in command(
            "loginctl",
            "show-session",
            sid,
            "-p",
            "User",
            "-p",
            "Name",
            "-p",
            "Active",
            "-p",
            "Type",
        ).splitlines()
    )
    expected = "x11" if os.environ["ODIN_ORCA_DESKTOP"] == "cinnamon" else "wayland"
    if (
        info.get("User") != str(account.pw_uid)
        or info.get("Name") != "odq"
        or info.get("Active") != "yes"
        or info.get("Type") != expected
    ):
        raise RuntimeError("Not the owned active odq graphical session")
    runtime = Path(f"/run/user/{account.pw_uid}")
    if os.environ.get("XDG_RUNTIME_DIR") != str(runtime) or runtime.stat().st_uid != account.pw_uid:
        raise RuntimeError("Owned guest runtime required")
    bus = runtime / "bus"
    if (
        os.environ.get("DBUS_SESSION_BUS_ADDRESS") != f"unix:path={bus}"
        or not stat.S_ISSOCK(bus.stat().st_mode)
        or bus.stat().st_uid != account.pw_uid
    ):
        raise RuntimeError("Owned guest user bus required")
    if expected == "wayland":
        name = os.environ.get("WAYLAND_DISPLAY", "")
        if not name or "/" in name:
            raise RuntimeError("Guest compositor socket required")
        display = runtime / name
        if not stat.S_ISSOCK(display.stat().st_mode) or display.stat().st_uid != account.pw_uid:
            raise RuntimeError("Unowned compositor socket")
    elif not os.environ.get("DISPLAY", "").startswith(":"):
        raise RuntimeError("Local guest X11 display required")
    pid = int(os.environ["ODIN_ORCA_PID"])
    proc = Path(f"/proc/{pid}")
    argv = proc.joinpath("cmdline").read_bytes().split(b"\0")
    if proc.stat().st_uid != account.pw_uid or not any(
        Path(a.decode()).name == "orca" for a in argv if a
    ):
        raise RuntimeError("Owned live Orca process required")
    log = Path(os.environ["ODIN_ORCA_LOG"])
    evidence = Path(os.environ["ODIN_ORCA_EVIDENCE"]).resolve(strict=True)
    if (
        log.resolve(strict=True).parent != evidence
        or log.is_symlink()
        or not log.is_file()
        or log.stat().st_uid != account.pw_uid
    ):
        raise RuntimeError("Fresh owned evidence log required")
    # Orca 46 changes its process title to 'orca', erasing its original argv.
    # Require an actual open descriptor to this log, not a caller-supplied path alone.
    bound = False
    for fd in proc.joinpath("fd").iterdir():
        try:
            if fd.resolve(strict=True) == log.resolve(strict=True):
                bound = True
                break
        except FileNotFoundError:
            continue  # A descriptor closed while inspected does not invalidate other bindings.
    if not bound:
        raise RuntimeError("Log not bound to the live Orca debug process")
    return {"session": info, "orca_pid": pid, "uid": account.pw_uid}


def active_dialog(title):
    import importlib.util

    helper = (
        Path(__file__).resolve().parents[3]
        / "scripts/qualification/lab/guest/native_dialog_events.py"
    )
    spec = importlib.util.spec_from_file_location("native_dialog_events", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.active_dialog(title)


def native(title, action, path=None):
    if title not in ("Attach files", "Save file") or action not in ("cancel", "file", "describe"):
        raise ValueError("Only the task suite file dialogs are permitted")
    binding = active_dialog(title)
    from evdev import UInput
    from evdev import ecodes as e

    letters = {c: getattr(e, f"KEY_{c.upper()}") for c in "abcdefghijklmnopqrstuvwxyz"}
    punctuation = {"/": e.KEY_SLASH, ".": e.KEY_DOT, "-": e.KEY_MINUS, " ": e.KEY_SPACE}
    keys = [
        e.KEY_ESC,
        e.KEY_ENTER,
        e.KEY_KPENTER,
        e.KEY_INSERT,
        e.KEY_LEFTCTRL,
        e.KEY_LEFTSHIFT,
        e.KEY_LEFTALT,
        *punctuation.values(),
        *letters.values(),
        *range(e.KEY_1, e.KEY_0 + 1),
    ]
    root = Path(os.environ["ODIN_ORCA_ROOT"]).resolve(strict=True)
    if action == "file" and (
        not path
        or not Path(path).resolve().is_relative_to(root)
        or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789/._- " for c in path)
    ):
        raise ValueError("Native file path must be a lowercase suite-owned guest path")
    with UInput({e.EV_KEY: sorted(set(keys))}, name="odq-orca-file-dialog") as keyboard:
        time.sleep(0.4)

        def chord(*codes):
            # Same observed event source, revalidated after device settle and
            # before each bounded chord. Missing/changed targets stop, never retry.
            try:
                binding.revalidate(title)
            except Exception as error:
                # TS polls pre-input lookup failures only. Never expose its
                # lookup retry sentinel once the device/input plan is open.
                raise RuntimeError("Native source revalidation failed; no replay") from error
            held = []
            try:
                for code in codes:
                    keyboard.write(e.EV_KEY, code, 1)
                    keyboard.syn()
                    held.append(code)
                time.sleep(0.035)
            finally:
                for code in reversed(held):
                    keyboard.write(e.EV_KEY, code, 0)
                    keyboard.syn()
            time.sleep(0.035)

        if action == "cancel":
            chord(e.KEY_ESC)
            return
        if action == "describe":
            # Real Orca desktop-layout title and Where Am I commands. No generated speech.
            chord(e.KEY_INSERT, e.KEY_KPENTER)
            time.sleep(0.5)
            chord(e.KEY_KPENTER)
            return
        chord(e.KEY_LEFTCTRL, e.KEY_L)
        time.sleep(0.25)
        chord(e.KEY_LEFTCTRL, e.KEY_A)

        def type_text(text):
            for char in text:
                if char == "_":
                    chord(e.KEY_LEFTSHIFT, e.KEY_MINUS)
                else:
                    chord(
                        letters[char]
                        if char in letters
                        else punctuation[char]
                        if char in punctuation
                        else getattr(e, f"KEY_{char}")
                    )

        if title == "Save file":
            type_text(str(Path(path).parent))
            chord(e.KEY_ENTER)
            time.sleep(0.4)
            chord(e.KEY_LEFTALT, e.KEY_N)
            chord(e.KEY_LEFTCTRL, e.KEY_A)
            type_text(Path(path).name)
        else:
            type_text(path)
        chord(e.KEY_ENTER)


if __name__ == "__main__":
    try:
        evidence = guard()
        if len(sys.argv) > 1 and sys.argv[1] == "native":
            native(*sys.argv[2:])
        elif sys.argv[1:] not in ([], ["guard"]):
            raise ValueError("Unknown operation")
        print(json.dumps(evidence))
    except Exception as exc:
        print(json.dumps({"passed": False, "error": str(exc)}))
        sys.exit(1)
