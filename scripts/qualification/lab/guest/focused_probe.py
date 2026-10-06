#!/usr/bin/env python3
"""Focused native launches and file-dialog diagnostics, never task qualification."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def guard():
    root = Path(os.environ["ODIN_ORCA_ROOT"])
    spec = importlib.util.spec_from_file_location(
        "focused_guest_guard", root / "app/test/e2e/orca-guest.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.guard()


def speech_records(text):
    return [
        line
        for line in text.splitlines()
        if re.match(r"^\d{2}:\d{2}:\d{2}\.\d+ - SPEECH OUTPUT: '", line)
    ]


def key(chord):
    guard()
    from evdev import UInput
    from evdev import ecodes as e

    names = {
        "Escape": e.KEY_ESC,
        "Tab": e.KEY_TAB,
        "Shift": e.KEY_LEFTSHIFT,
        "Alt": e.KEY_LEFTALT,
        "Super": e.KEY_LEFTMETA,
        "Enter": e.KEY_ENTER,
    }
    if chord not in ("Escape", "Tab", "Shift+Tab", "Alt+Tab", "Super", "Enter"):
        raise ValueError("Unsupported focused guest key")
    with UInput({e.EV_KEY: list(names.values())}, name="odq-orca-focused-probe") as device:
        time.sleep(0.4)
        held = []
        try:
            for part in chord.split("+"):
                code = names[part]
                device.write(e.EV_KEY, code, 1)
                device.syn()
                held.append(code)
            time.sleep(0.04)
        finally:
            for code in reversed(held):
                device.write(e.EV_KEY, code, 0)
                device.syn()


def snapshot():
    guard()
    import dbus
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    bus = dbus.SessionBus()
    address = str(
        bus.get_object("org.a11y.Bus", "/org/a11y/bus").GetAddress(dbus_interface="org.a11y.Bus")
    )
    Atspi.init()
    pending = [(Atspi.get_desktop(0), 0)]
    nodes = []
    while pending and len(nodes) < 2500:
        item, depth = pending.pop(0)
        try:
            states = item.get_state_set()
            nodes.append(
                {
                    "name": item.get_name(),
                    "role": item.get_role_name(),
                    "pid": item.get_process_id(),
                    "depth": depth,
                    "states": [
                        name
                        for name in ("ACTIVE", "SHOWING", "VISIBLE", "FOCUSED")
                        if states.contains(getattr(Atspi.StateType, name))
                    ],
                }
            )
            if depth < 18:
                pending.extend(
                    (item.get_child_at_index(i), depth + 1)
                    for i in range(min(item.get_child_count(), 500))
                )
        except Exception as exc:
            nodes.append({"error": str(exc), "depth": depth})
    return {"a11y_bus_address": address, "nodes": nodes, "bounded": bool(pending)}


def gtk_app():
    guard()
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk

    window = Gtk.Window(title="Orca GTK focused probe")
    window.set_default_size(480, 180)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    entry = Gtk.Entry()
    entry.get_accessible().set_name("Probe message")
    button = Gtk.Button(label="Probe action")
    box.pack_start(entry, True, True, 0)
    box.pack_start(button, True, True, 0)
    window.add(box)
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    GLib.idle_add(lambda: (window.present(), entry.grab_focus(), False)[-1])
    print(json.dumps({"gtk_show_all": True}), flush=True)
    Gtk.main()


def measure_gtk(evidence, log):
    start = log.stat().st_size
    with (evidence / "probe-gtk-console.log").open("w") as output:
        app = subprocess.Popen(
            [sys.executable, "-B", __file__, "gtk-app"], stdout=output, stderr=subprocess.STDOUT
        )
        try:
            time.sleep(3)
            key("Escape")
            time.sleep(1)
            key("Tab")
            time.sleep(1)
            key("Shift+Tab")
            time.sleep(2)
            tree = subprocess.check_output(
                [sys.executable, "-B", __file__, "snapshot"], text=True, timeout=25
            )
            (evidence / "probe-gtk-atspi.json").write_text(tree)
            subprocess.run(
                ["/usr/local/lib/odq/capture", str(evidence / "probe-gtk.png")],
                check=True,
                timeout=75,
            )
            records = speech_records(log.read_bytes()[start:].decode(errors="replace"))
            (evidence / "probe-gtk-speech.json").write_text(json.dumps(records, indent=2))
            spoken = "\n".join(records)
            passed = (
                "Probe message" in spoken
                and "Probe action" in spoken
                and bool(re.search(r"button", spoken, re.I))
            )
            return {"passed": passed, "speech_records": len(records), "launches": 1, "pid": app.pid}
        finally:
            if app.poll() is None:
                app.terminate()
                app.wait(timeout=10)


def dialog_snapshot(title="Attach files"):
    guard()
    root = Path(os.environ["ODIN_ORCA_ROOT"])
    spec = importlib.util.spec_from_file_location(
        "probe_native_events", root / "scripts/qualification/lab/guest/native_dialog_events.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    binding = module.active_dialog(title)
    binding.revalidate(title)
    return binding.record


def run(mode):
    if mode not in ("electron", "gtk-electron", "native-attach", "native-files"):
        raise ValueError("Only focused launch modes")
    identity = guard()
    os.environ["DEBUG"] = "pw:browser"
    os.environ["ODIN_ORCA_PROBE"] = mode
    root = Path(os.environ["ODIN_ORCA_ROOT"])
    evidence = Path(os.environ["ODIN_ORCA_EVIDENCE"])
    log = Path(os.environ["ODIN_ORCA_LOG"])
    result = {
        "kind": "focused-probes-not-qualification",
        "probe": mode,
        "guard": identity,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "passed": False,
    }
    try:
        if mode == "gtk-electron":
            result["gtk"] = measure_gtk(evidence, log)
            if not result["gtk"]["passed"]:
                raise RuntimeError("Plain GTK native speech failed; Electron not launched")
        with (evidence / "probe-electron-console.log").open("w") as output:
            launch = subprocess.run(
                [str(root / "bin/node"), str(Path(__file__).with_name("focused_electron.cjs"))],
                cwd=root / "app",
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=360 if mode == "native-files" else 150,
            )
        result["electron_exit_code"] = launch.returncode
        result["passed"] = launch.returncode == 0
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        (evidence / "probe-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    operation = sys.argv[1]
    if operation == "gtk-app":
        gtk_app()
    elif operation == "snapshot":
        print(json.dumps(snapshot(), indent=2))
    elif operation == "key":
        key(sys.argv[2])
    elif operation == "dialog":
        print(json.dumps(dialog_snapshot(sys.argv[2] if len(sys.argv) > 2 else "Attach files")))
    else:
        sys.exit(run(operation))
