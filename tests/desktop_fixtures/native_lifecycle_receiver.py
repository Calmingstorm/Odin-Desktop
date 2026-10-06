"""Harmless X11 witness, admitted only by the private namespace qualification."""
from __future__ import annotations

import json
import os
import select
import sys
from pathlib import Path

from Xlib import X, Xatom, display


def assert_private_native():
    root = os.environ.get("ODIN_REAL_CORE_ROOT", "")
    outer = os.environ.get("ODIN_REAL_CORE_OUTER_PID_NS", "")
    init = Path("/proc/1/cmdline").read_bytes().split(b"\0")
    assert os.geteuid() != 0 and root and os.environ.get("HOME") == root
    assert root.startswith("/tmp/odrc-") and outer
    assert os.readlink("/proc/self/ns/pid") != outer
    assert b"--inside-run" in init
    assert any(v.endswith(b"/app/scripts/real-core-isolation.mjs") for v in init)
    assert os.environ.get("ODIN_APP_E2E") == "1"
    assert os.environ.get("DISPLAY", "").startswith(":")
    authority = Path(os.environ["XAUTHORITY"])
    assert authority.is_file() and authority.stat().st_uid == os.geteuid()
    assert os.environ.get("DBUS_SESSION_BUS_ADDRESS")


def main():
    assert_private_native()
    target = Path(sys.argv[1])
    assert target.resolve().is_relative_to(Path(os.environ["ODIN_REAL_CORE_ROOT"]).resolve())
    connection = display.Display()
    screen = connection.screen()
    window = screen.root.create_window(30, 30, 260, 160, 0, screen.root_depth,
        X.InputOutput, X.CopyFromParent, background_pixel=0xffffff,
        event_mask=X.KeyPressMask | X.KeyReleaseMask | X.ButtonPressMask | X.ButtonReleaseMask)
    window.set_wm_name("Odin dedicated native lifecycle witness")
    window.change_property(connection.intern_atom("_NET_WM_PID"), Xatom.CARDINAL, 32, [os.getpid()])
    window.map()
    window.set_input_focus(X.RevertToParent, X.CurrentTime)
    connection.sync()
    with target.open("w", encoding="utf-8") as log:
        def emit(value):
            log.write(json.dumps(value, sort_keys=True) + "\n")
            log.flush()
        emit({"kind": "ready", "pid": os.getpid(), "window": window.id,
              "namespace": os.readlink("/proc/self/ns/pid"), "display": os.environ["DISPLAY"]})
        try:
            while True:
                readable, _, _ = select.select([connection.fileno(), sys.stdin], [], [], .02)
                if sys.stdin in readable:
                    command = os.read(0, 4096)
                    if not command:
                        break
                    if command.strip() == b"focus":
                        window.set_input_focus(X.RevertToParent, X.CurrentTime)
                        connection.sync()
                        emit({"kind": "focused", "window": window.id})
                    elif command.strip() == b"state":
                        mapping = connection.query_keymap()
                        keys = [code for code in range(256)
                                if mapping[code // 8] & (1 << (code % 8))]
                        emit({"kind": "server-keymap", "keys": keys,
                              "measurement": "real-XQueryKeymap-shared-server-not-owned-ledger"})
                while connection.pending_events():
                    event = connection.next_event()
                    if event.type in (X.KeyPress, X.KeyRelease, X.ButtonPress, X.ButtonRelease):
                        emit({"kind": "edge", "type": event.type, "detail": event.detail,
                              "window": event.window.id, "send_event": event.send_event})
        finally:
            window.destroy()
            connection.sync()
            connection.close()
            emit({"kind": "closed"})


if __name__ == "__main__":
    main()
