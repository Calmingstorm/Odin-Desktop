#!/usr/bin/env python3
"""VM-only AT-SPI event references for the suite's two native file choosers.

Protocol provenance: at-spi2-core 2.52 atspi/atspi-event-listener.c
(_atspi_dbus_handle_event, notify_event_registered) and xml/Registry.xml.
Window/Object sources are the message sender and object path. The trailing
(so) is NOT the source; the variant can also contain an unrelated accessible.
Both siiv(so) and siiva{sv} are accepted by libatspi. No names from Orca logs,
desktop enumeration, cache entries or anonymous refs confer input authority.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import sys
import time
from pathlib import Path

ACCESSIBLE = "org.a11y.atspi.Accessible"
PROPERTIES = "org.freedesktop.DBus.Properties"
REGISTRY = "org.a11y.atspi.Registry"
EVENTS = ("window:activate", "object:state-changed:active")
UNIQUE = re.compile(r"^:[0-9]+\.[0-9]+$")
OBJECT_PATH = re.compile(r"^/org/a11y/atspi/accessible/[A-Za-z0-9_/]+$")
GNOME_PATH = re.compile(
    r"^/org/gtk/application/xdg_desktop_portal_gnome/a11y/"
    r"[0-9a-f]{8}(?:_[0-9a-f]{4}){3}_[0-9a-f]{12}$"
)
# Noble's installed chooser backend, not any similarly named application.
PORTAL_EXECUTABLES = frozenset({"/usr/libexec/xdg-desktop-portal-gnome"})
TITLES = ("Attach files", "Save file")


def trusted_executable(filename):
    path = Path(filename)
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise RuntimeError("Native executable must be an exact canonical installed path")
    for item in (path, *path.parents):
        info = item.stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError(
                "Native executable and ancestors must be root-owned and immutable to odq"
            )
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o111:
        raise RuntimeError("Native executable is not an installed executable file")


def source_identity(bus, peer, path):
    identity = peer_identity(bus, peer)
    executable = identity["exe"]
    if executable in PORTAL_EXECUTABLES:
        if os.environ.get("ODIN_ORCA_DESKTOP") != "gnome" or not (
            GNOME_PATH.fullmatch(path) or OBJECT_PATH.fullmatch(path)
        ):
            raise RuntimeError("Native portal source is outside the exact guest backend scope")
    elif executable == os.environ.get("ODIN_ORCA_ELECTRON"):
        if not OBJECT_PATH.fullmatch(path):
            raise RuntimeError("Unknown Electron native source path")
    else:
        raise RuntimeError(
            "AT-SPI peer is not the installed Electron or exact native portal backend"
        )
    trusted_executable(executable)
    return identity


def process_identity(pid):
    proc = Path(f"/proc/{pid}")
    # Field 22 after the parenthesized comm, which may itself contain spaces.
    start = proc.joinpath("stat").read_text().rsplit(")", 1)[1].split()[19]
    return {
        "pid": int(pid),
        "uid": proc.stat().st_uid,
        "exe": str(proc.joinpath("exe").resolve(strict=True)),
        "start": start,
    }


def peer_identity(bus, peer):
    if not UNIQUE.fullmatch(str(peer)):
        raise RuntimeError("AT-SPI source must have a unique bus name")
    uid = int(bus.get_unix_user(peer))
    pid = int(
        bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus").GetConnectionUnixProcessID(
            peer, dbus_interface="org.freedesktop.DBus"
        )
    )
    identity = process_identity(pid)
    if uid != os.geteuid() or identity["uid"] != uid:
        raise RuntimeError("AT-SPI peer is not owned by odq")
    return identity


def electron_identity(bus, peer):
    identity = peer_identity(bus, peer)
    if Path(identity["exe"]).name != "electron":
        raise RuntimeError("AT-SPI peer is not the owned Electron process")
    return identity


def event_reference(message):
    """Decode the real libatspi source, never an arbitrary variant/trailer ref."""
    interface, member = message.get_interface(), message.get_member()
    if message.get_signature() not in ("siiv(so)", "siiva{sv}"):
        raise RuntimeError("Unknown AT-SPI event signature")
    args = message.get_args_list()
    if len(args) != 5:
        raise RuntimeError("Malformed AT-SPI event")
    if interface == "org.a11y.atspi.Event.Window" and member == "Activate":
        kind = "window:activate"
    elif (
        interface == "org.a11y.atspi.Event.Object"
        and member == "StateChanged"
        and str(args[0]) == "active"
        and int(args[1]) in (0, 1)
    ):
        kind = "object:state-changed:" + ("active" if int(args[1]) else "inactive")
    else:
        return None
    peer, path = str(message.get_sender()), str(message.get_path())
    if not UNIQUE.fullmatch(peer) or not (
        OBJECT_PATH.fullmatch(path) or GNOME_PATH.fullmatch(path)
    ):
        raise RuntimeError("Unknown AT-SPI event source")
    return {"peer": peer, "path": path, "event": kind, "signature": str(message.get_signature())}


def bus_connection():
    import dbus

    session = dbus.SessionBus()
    address = str(
        session.get_object("org.a11y.Bus", "/org/a11y/bus").GetAddress(
            dbus_interface="org.a11y.Bus"
        )
    )
    return dbus.bus.BusConnection(address), address


def event_path():
    root = Path(os.environ["ODIN_ORCA_ROOT"]).resolve(strict=True)
    path = Path(os.environ["ODIN_ORCA_DIALOG_EVENTS"])
    if path.is_symlink() or path.parent.resolve(strict=True) != root / "evidence":
        raise RuntimeError("Native event file must be in this run's private evidence directory")
    return path


def read_events(bus, address):
    path = event_path()
    info = path.stat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_size > 1048576
    ):
        raise RuntimeError("Native event file is not private, owned and bounded")
    lines = path.read_text().splitlines()
    if not lines:
        raise RuntimeError("Native event collector is not ready")
    ready = json.loads(lines[0])
    if ready.get("type") != "ready" or ready.get("address") != address:
        raise RuntimeError("Native event collector bus mismatch")
    collector = peer_identity(bus, ready["collector_peer"])
    if collector != ready["collector"]:
        raise RuntimeError("Stale native collector process binding")
    proc = Path(f"/proc/{collector['pid']}")
    if not any(
        Path(arg.decode()).name == "native_dialog_events.py"
        for arg in proc.joinpath("cmdline").read_bytes().split(b"\0")
        if arg
    ):
        raise RuntimeError("Native collector executable mismatch")
    if not any(fd.resolve() == path.resolve() for fd in proc.joinpath("fd").iterdir()):
        raise RuntimeError("Native event file is not bound to the live collector")
    now = time.monotonic_ns()
    records = []
    for line in lines[1:]:
        record = json.loads(line)
        if (
            record.get("type") in ("source", "revocation")
            and record.get("run") == ready["run"]
            and ready["started_ns"] <= record["observed_ns"] <= now
            and now - record["observed_ns"] <= 60_000_000_000
        ):
            records.append(record)
    return records


class DialogBinding:
    def __init__(self, bus, record, atspi):
        self.bus, self.record, self.atspi = bus, record, atspi

    def revalidate(self, title):
        record, atspi = self.record, self.atspi
        if (
            title not in TITLES
            or record["event"] not in EVENTS
            or not UNIQUE.fullmatch(record["peer"])
            or not (OBJECT_PATH.fullmatch(record["path"]) or GNOME_PATH.fullmatch(record["path"]))
        ):
            raise RuntimeError("Invalid observed native source")
        if source_identity(self.bus, record["peer"], record["path"]) != record["identity"]:
            raise RuntimeError("Stale native source process binding")
        item = self.bus.get_object(record["peer"], record["path"])
        name = str(item.Get(ACCESSIBLE, "Name", dbus_interface=PROPERTIES))
        role = int(item.GetRole(dbus_interface=ACCESSIBLE))
        words = item.GetState(dbus_interface=ACCESSIBLE)
        if len(words) != 2:
            raise RuntimeError("Unknown native state representation")
        flags = int(words[0]) | (int(words[1]) << 32)
        active = bool(flags & (1 << int(atspi.StateType.ACTIVE)))
        if record["identity"]["exe"] in PORTAL_EXECUTABLES and not active:
            # GTK4's GetState omits ACTIVE even for its native focused modal.
            # Use the actual active(1) event, revoked by a later active(0) or
            # another activation, never title inference or cached Orca text.
            _, address = bus_connection()
            activity = read_events(self.bus, address)
            latest = activity[-1] if activity else {}
            active = (
                record["event"] == "object:state-changed:active"
                and latest == record
                and bool(flags & (1 << int(atspi.StateType.MODAL)))
            )
        if (
            name != title
            or role not in (int(atspi.Role.DIALOG), int(atspi.Role.FILE_CHOOSER))
            or not active
            or not flags & (1 << int(atspi.StateType.SHOWING))
        ):
            raise RuntimeError(
                f"No owned active AT-SPI dialog with current title, role and states: "
                f"name={name!r} role={role} state_words={[int(word) for word in words]}"
            )
        # Close the query window with another credential/PID/start-time check.
        if source_identity(self.bus, record["peer"], record["path"]) != record["identity"]:
            raise RuntimeError("Native source changed during validation")
        return item


def active_dialog(title):
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    bus, address = bus_connection()
    records = read_events(bus, address)
    seen, diagnostics = set(), []
    for record in reversed(records):
        reference = (record["peer"], record["path"])
        if reference in seen:
            continue
        seen.add(reference)
        if record.get("type") != "source" or record["event"] not in EVENTS:
            continue  # An actual inactive event revokes earlier source activation.
        binding = DialogBinding(bus, record, Atspi)
        try:
            binding.revalidate(title)
            return binding
        except Exception as error:
            diagnostics.append({"peer": reference[0], "path": reference[1], "error": str(error)})
    print(json.dumps({"native_dialog_lookup": diagnostics}), flush=True)
    raise RuntimeError(f"No owned active AT-SPI dialog: {title}")


def register(bus, dbus, callback):
    """One stable connection owns both signal matches and Registry registration."""
    for interface, member in (("Window", "Activate"), ("Object", "StateChanged")):
        bus.add_signal_receiver(
            callback,
            signal_name=member,
            dbus_interface=f"org.a11y.atspi.Event.{interface}",
            message_keyword="message",
        )
    registry = bus.get_object("org.a11y.atspi.Registry", "/org/a11y/atspi/registry")
    for event in EVENTS:
        registry.RegisterEvent(event, dbus.Array([], signature="s"), "", dbus_interface=REGISTRY)
    return registry


def collect():
    # The same VM/session/Orca guard as input, before connecting any bus.
    root = Path(os.environ["ODIN_ORCA_ROOT"])
    spec = importlib.util.spec_from_file_location(
        "orca_guest_guard", root / "app/test/e2e/orca-guest.py"
    )
    guest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guest)
    guest.guard()
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib

    DBusGMainLoop(set_as_default=True)
    bus, address = bus_connection()
    path = event_path()
    started = time.monotonic_ns()
    run = os.urandom(16).hex()
    loop = GLib.MainLoop()
    # Exclusive fresh creation: stale files are not recycled or appended to.
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", buffering=1) as output:
        count = 0
        ready = False

        def callback(*args, message):
            nonlocal count
            # A synchronous registry call may dispatch queued signals. The
            # header must be first; only post-readiness events belong to this run.
            if not ready:
                return
            try:
                reference = event_reference(message)
                if reference is None:
                    return
                if count >= 4096:
                    raise RuntimeError("Native source evidence bound exhausted")
                try:
                    identity = source_identity(bus, reference["peer"], reference["path"])
                    record_type = "source"
                except Exception:
                    # A foreign activation revokes the GTK4 active-event lease;
                    # it never supplies an input target or executable authority.
                    identity = None
                    record_type = "revocation"
                output.write(
                    json.dumps(
                        {
                            "type": record_type,
                            "run": run,
                            "observed_ns": time.monotonic_ns(),
                            "identity": identity,
                            **reference,
                        }
                    )
                    + "\n"
                )
                count += 1
            except Exception as error:
                # Foreign peers/errors are diagnostic only, never synthetic sources.
                print(json.dumps({"native_event_rejected": str(error)}), flush=True)

        registry = register(bus, dbus, callback)
        started = time.monotonic_ns()
        output.write(
            json.dumps(
                {
                    "type": "ready",
                    "run": run,
                    "started_ns": started,
                    "address": address,
                    "collector_peer": bus.get_unique_name(),
                    "collector": process_identity(os.getpid()),
                }
            )
            + "\n"
        )
        print(json.dumps({"native_event_collector": "ready", "path": str(path)}), flush=True)
        ready = True
        try:
            loop.run()
        finally:
            for event in EVENTS:
                registry.DeregisterEvent(event, dbus_interface=REGISTRY)
            bus.close()


if __name__ == "__main__":
    try:
        collect()
    except Exception as error:
        print(json.dumps({"passed": False, "error": str(error)}), flush=True)
        sys.exit(1)
