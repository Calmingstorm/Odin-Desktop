#!/usr/bin/env python3
"""VM guest-only AT-SPI collector, outside app PID namespace. No fake services."""
import argparse
import json
import os
from pathlib import Path
import pwd
import re
import socket
import stat
import subprocess
import time


def guard():
    account = pwd.getpwnam("odq")
    if os.getuid() != account.pw_uid or os.getuid() == 0:
        raise RuntimeError("Requires nonroot odq")
    marker = Path("/etc/odin-desktop-qualification")
    info = marker.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError("Unsafe VM marker")
    if marker.read_text() != "odin-desktop-qualification-v1\n":
        raise RuntimeError("Missing qualification marker")
    if socket.gethostname() not in ("odq-cinnamon", "odq-gnome", "odq-kde", "odq-hyprland"):
        raise RuntimeError("Not a qualification hostname")
    if subprocess.run(["systemd-detect-virt", "--vm", "--quiet"], check=False).returncode:
        raise RuntimeError("Not a VM")
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", ""))
    if runtime != Path(f"/run/user/{account.pw_uid}") or runtime.stat().st_uid != account.pw_uid:
        raise RuntimeError("Requires guest odq runtime")
    address = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    if not re.fullmatch(re.escape(f"unix:path={runtime}/bus") + r"(?:,guid=[0-9a-f]+)?", address):
        raise RuntimeError("Requires guest local session bus")
    if not stat.S_ISSOCK((runtime / "bus").stat().st_mode):
        raise RuntimeError("Guest bus socket missing")
    display = os.environ.get("DISPLAY", "")
    if display and (not display.startswith(":") or not display[1:].split(".")[0].isdigit()):
        raise RuntimeError("Forwarded display refused")
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        wayland = os.environ.get("WAYLAND_DISPLAY", "")
        if "/" in wayland or not wayland or not stat.S_ISSOCK((runtime / wayland).stat().st_mode):
            raise RuntimeError("Guest Wayland socket missing")
    elif os.environ.get("XDG_SESSION_TYPE") != "x11" or not display:
        raise RuntimeError("Requires native guest X11 or Wayland")
    if display and not stat.S_ISSOCK(Path(f"/tmp/.X11-unix/X{display[1:].split('.')[0]}").stat().st_mode):
        raise RuntimeError("Guest local X11 socket missing")
    return account


def identity(pid):
    base = Path(f"/proc/{pid}")
    status = base.joinpath("status").read_text()
    uid = int(next(line for line in status.splitlines() if line.startswith("Uid:")).split()[1])
    return {"pid": pid, "uid": uid,
            "start_ticks": base.joinpath("stat").read_text().rsplit(") ", 1)[1].split()[19],
            "exe": os.readlink(base / "exe"), "pid_namespace": os.readlink(base / "ns/pid")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    args = parser.parse_args()
    account = guard()
    path = Path(args.socket)
    if (path.parent.resolve() != path.parent or not str(path.parent).startswith("/tmp/odrc-")
            or path.parent.stat().st_uid != account.pw_uid or path.parent.stat().st_mode & 0o077):
        raise RuntimeError("Socket requires owned /tmp/odrc-* directory")
    if path.exists() or path.is_symlink():
        raise RuntimeError("Socket occupant refused")
    import dbus
    import dbus.mainloop.glib
    from gi.repository import GLib
    import pyatspi
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    api = dbus.Interface(bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus"), "org.freedesktop.DBus")
    owner = str(api.GetNameOwner("org.freedesktop.Notifications"))
    owner_identity = identity(int(api.GetConnectionUnixProcessID(owner)))
    if owner_identity["uid"] != account.pw_uid:
        raise RuntimeError("Notification daemon has foreign UID")
    signals = []
    observed_menu = {}
    bus.add_signal_receiver(lambda nid, action: signals.append({"id": int(nid), "action": str(action)}),
                            signal_name="ActionInvoked", dbus_interface="org.freedesktop.Notifications", bus_name=owner)
    context = GLib.MainContext.default()

    def pump():
        for _ in range(100):
            if not context.pending():
                break
            context.iteration(False)

    def describe(obj):
        actions = []
        try:
            action = obj.queryAction()
            actions = [action.getName(i) for i in range(action.nActions)]
        except Exception:
            pass
        return {"name": obj.name, "role": obj.getRoleName(), "description": obj.description,
                "pid": int(obj.getApplication().get_process_id()), "actions": actions}

    def nodes():
        queue = [(pyatspi.Registry.getDesktop(0), [])]
        deadline = time.monotonic() + 3
        count = 0
        while queue and count < 4000 and time.monotonic() < deadline:
            obj, parents = queue.pop(0)
            count += 1
            try:
                yield obj, parents
                if len(parents) < 16:
                    queue.extend((obj[i], [obj, *parents]) for i in range(min(obj.childCount, 300)))
            except Exception:
                continue

    def find(predicate, seconds=8):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            pump()
            for obj, parents in nodes():
                try:
                    if predicate(obj):
                        return obj, parents
                except Exception:
                    continue
            time.sleep(0.1)
        raise RuntimeError("Native accessible target absent after bounded search")

    def activate(obj, index):
        record = describe(obj)
        record["process"] = identity(record["pid"])
        if record["process"]["uid"] != account.pw_uid:
            raise RuntimeError("Native target has foreign UID")
        if not obj.queryAction().doAction(index):
            raise RuntimeError("Native AT-SPI action rejected")
        return {"target": record, "action_index": index, "transport": "AT-SPI"}

    def dispatch(request):
        pump()
        operation = request["operation"]
        if operation == "stop":
            return {"stopped": True}
        if operation == "inspect":
            owners = {}
            for name in ("org.freedesktop.Notifications", "org.kde.StatusNotifierWatcher"):
                if api.NameHasOwner(name):
                    current = str(api.GetNameOwner(name))
                    owners[name] = {"owner": current, "process": identity(int(api.GetConnectionUnixProcessID(current)))}
            applications = []
            desktop = pyatspi.Registry.getDesktop(0)
            for i in range(min(desktop.childCount, 100)):
                try:
                    applications.append(describe(desktop[i]))
                except Exception:
                    pass
            return {"owners": owners, "applications": applications, "actions": list(signals),
                    "collector": identity(os.getpid()), "session_type": os.environ["XDG_SESSION_TYPE"]}
        if operation == "tray-menu":
            obj, _ = find(lambda obj: "odin" in (obj.name + " " + obj.description).lower()
                          and obj.getRoleName() not in ("application", "frame", "menu item", "label")
                          and "odin" not in obj.getApplication().name.lower())
            info = describe(obj)
            for i, name in enumerate(info["actions"]):
                if "menu" in name.lower():
                    result = activate(obj, i)
                    break
            else:
                if os.environ["XDG_SESSION_TYPE"] != "x11":
                    raise RuntimeError(f"Wayland tray lacks native AT-SPI menu action: {info}")
                process = identity(info["pid"])
                if process["uid"] != account.pw_uid:
                    raise RuntimeError("Foreign tray UID")
                box = obj.queryComponent().getExtents(pyatspi.DESKTOP_COORDS)
                if box.width < 1 or box.height < 1 or box.x < 0 or box.y < 0:
                    raise RuntimeError("Tray has no observed screen rectangle")
                pyatspi.Registry.generateMouseEvent(box.x + box.width // 2, box.y + box.height // 2, "b3c")
                result = {"target": info, "process": process, "transport": "AT-SPI X11 right-click",
                          "rectangle": [box.x, box.y, box.width, box.height]}
            opened, _ = find(lambda obj: obj.name == "Open Odin" and obj.getRoleName() == "menu item")
            result["appeared"] = describe(opened)
            observed_menu.update(identity(result["appeared"]["pid"]))
            return result
        if operation == "tray-action":
            label = request["label"]
            if label not in ("Open Odin", "Exit Odin"):
                raise RuntimeError("Unknown tray action")
            obj, parents = find(lambda obj: obj.name == label and obj.getRoleName() == "menu item")
            current = identity(describe(obj)["pid"])
            if current != observed_menu:
                raise RuntimeError("Menu process differs from freshly observed tray menu")
            if not any(parent.getRoleName() in ("menu", "popup menu") for parent in parents[:3]):
                raise RuntimeError("Action is not in an observed native menu")
            return activate(obj, 0)
        if operation == "notification-click":
            text = request["text"]
            if not text.startswith("P33 native ") or len(text) > 100:
                raise RuntimeError("Requires qualification notification marker")
            obj, parents = find(lambda obj: text in obj.name or text in obj.description)
            appeared = describe(obj)
            if appeared["pid"] != owner_identity["pid"] or identity(appeared["pid"])["start_ticks"] != owner_identity["start_ticks"]:
                raise RuntimeError("Notification accessible not owned by real daemon")
            for candidate in [obj, *parents[:4]]:
                info = describe(candidate)
                if info["role"] in ("application", "frame"):
                    break
                for i, name in enumerate(info["actions"]):
                    if name.lower() in ("click", "activate", "press", "default", "open"):
                        return {"appeared": appeared, **activate(candidate, i)}
            raise RuntimeError(f"Notification appeared but no native click action: {appeared}")
        raise RuntimeError("Unknown collector operation")

    server = socket.socket(socket.AF_UNIX)
    server.bind(str(path))
    path.chmod(0o600)
    server.listen(1)
    server.settimeout(0.2)
    print(json.dumps({"ready": str(path), "collector": identity(os.getpid())}), flush=True)
    deadline = time.monotonic() + 900
    try:
        while time.monotonic() < deadline:
            pump()
            try:
                connection, _ = server.accept()
            except TimeoutError:
                continue
            with connection:
                connection.settimeout(5)
                data = bytearray()
                while b"\n" not in data and len(data) <= 4096:
                    chunk = connection.recv(4096)
                    if not chunk:
                        break
                    data.extend(chunk)
                try:
                    result = {"ok": True, "result": dispatch(json.loads(data))}
                except Exception as exc:
                    result = {"ok": False, "error": str(exc)}
                connection.sendall((json.dumps(result) + "\n").encode())
                if result.get("ok") and result.get("result", {}).get("stopped"):
                    break
    finally:
        server.close()
        path.unlink()


if __name__ == "__main__":
    main()
