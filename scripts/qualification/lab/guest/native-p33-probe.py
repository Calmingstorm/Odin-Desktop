#!/usr/bin/env python3
"""VM guest-only AT-SPI collector, outside app PID namespace. No fake services."""

import argparse
import ctypes
import ctypes.util
import json
import os
import pwd
import re
import socket
import stat
import struct
import subprocess
import time
from pathlib import Path

MAX_REQUEST_BYTES = 4096
READ_TIMEOUT_SECONDS = 5
OPERATIONS = frozenset({"stop", "inspect", "tray-menu", "tray-action", "notification-click"})


def read_request(connection, uid, timeout=READ_TIMEOUT_SECONDS):
    """One bounded newline frame, accepted only from the guest collector UID."""
    _, peer_uid, _ = struct.unpack(
        "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
    if peer_uid != uid:
        raise RuntimeError("Foreign collector peer UID refused")
    deadline = time.monotonic() + timeout
    data = bytearray()
    while b"\n" not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Collector request deadline exceeded")
        connection.settimeout(remaining)
        chunk = connection.recv(min(4096, MAX_REQUEST_BYTES + 1 - len(data)))
        if not chunk:
            raise RuntimeError("Incomplete collector frame")
        data.extend(chunk)
        if len(data) > MAX_REQUEST_BYTES:
            raise RuntimeError("Oversized collector frame")
    frame, trailing = bytes(data).split(b"\n", 1)
    if trailing:
        raise RuntimeError("Multiple collector frames refused")
    request = json.loads(frame)
    if not isinstance(request, dict) or request.get("operation") not in OPERATIONS:
        raise RuntimeError("Unknown collector operation")
    return request


def handle_request(connection, uid, dispatch):
    try:
        result = {"ok": True, "result": dispatch(read_request(connection, uid))}
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    connection.settimeout(READ_TIMEOUT_SECONDS)
    try:
        connection.sendall((json.dumps(result) + "\n").encode())
    except OSError:
        pass  # A disconnected/refused peer must not terminate the collector.
    return result


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
    if display and not stat.S_ISSOCK(
            Path(f"/tmp/.X11-unix/X{display[1:].split('.')[0]}").stat().st_mode):
        raise RuntimeError("Guest local X11 socket missing")
    return account


def identity(pid):
    base = Path(f"/proc/{pid}")
    status = base.joinpath("status").read_text()
    uid = int(next(line for line in status.splitlines() if line.startswith("Uid:")).split()[1])
    return {"pid": pid, "uid": uid,
            "namespace_pids": [int(value) for value in next(
                line for line in status.splitlines() if line.startswith("NSpid:")).split()[1:]],
            "start_ticks": base.joinpath("stat").read_text().rsplit(") ", 1)[1].split()[19],
            "exe": os.readlink(base / "exe"), "pid_namespace": os.readlink(base / "ns/pid")}


def matches_inner(process, expected, uid):
    """Compare kernel namespace mapping, never dereference an inner PID as outer."""
    return (process["uid"] == uid == expected.get("uid")
            and process["namespace_pids"][-1] == expected.get("pid")
            and process["start_ticks"] == str(expected.get("startTicks"))
            and process["pid_namespace"] == expected.get("namespace")
            and process["exe"] == expected.get("executable"))


def resolve_inner(expected, uid):
    matches = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            process = identity(int(entry.name))
            if matches_inner(process, expected, uid):
                matches.append(process)
        except (OSError, ValueError, StopIteration):
            continue
    if len(matches) != 1:
        raise RuntimeError("App namespace identity has no unique live outer mapping")
    return matches[0]


def walk_tree(root, seconds=2):
    queue = [(root, [])]
    deadline = time.monotonic() + seconds
    count = 0
    while queue and count < 4000 and time.monotonic() < deadline:
        obj, parents = queue.pop(0)
        count += 1
        yield obj, parents
        try:
            if len(parents) < 16:
                queue.extend((obj[i], [obj, *parents]) for i in range(min(obj.childCount, 300)))
        except Exception:
            continue


def opened_item(obj, parents, label, showing):
    return (obj.name == label and obj.getRoleName() in ("menu item", "check menu item")
            and obj.getState().contains(showing)
            and any(parent.getRoleName() in ("menu", "popup menu")
                    and parent.getState().contains(showing) for parent in parents[:3]))


def accessible_peer_identity(obj, api, uid):
    # libatspi's application PID can be inner; query the actual native bus peer.
    name = str(obj.getApplication().app.bus_name)
    if not re.fullmatch(r":\d+\.\d+", name):
        raise RuntimeError("Accessible lacks native unique bus peer")
    process = identity(int(api.GetConnectionUnixProcessID(name)))
    if process["uid"] != uid:
        raise RuntimeError("Native accessible peer has foreign UID")
    return process


def x11_owned_windows(process):
    """Native XEmbed/property evidence only. No hard-coded icon dimensions/position."""
    tree = subprocess.check_output(["xwininfo", "-root", "-tree"], text=True, timeout=3)
    result = []
    for wid in dict.fromkeys(re.findall(r"^\s+(0x[0-9a-f]+)\s", tree, re.M)):
        props = subprocess.check_output(["xprop", "-id", wid, "_NET_WM_PID",
                                        "WM_CLIENT_LEADER", "_XEMBED_INFO", "_NET_WM_WINDOW_TYPE"],
                                       text=True, timeout=2)
        pid = re.search(r"_NET_WM_PID\(CARDINAL\) = (\d+)", props)
        if not pid:
            leader = re.search(r"WM_CLIENT_LEADER\(WINDOW\).*?(0x[0-9a-f]+)", props)
            if leader:
                value = subprocess.check_output(["xprop", "-id", leader[1], "_NET_WM_PID"],
                                                text=True, timeout=2)
                pid = re.search(r"_NET_WM_PID\(CARDINAL\) = (\d+)", value)
        # _NET_WM_PID may be absent or inner. Only XRes decides native ownership.
        if x11_peer_pid(int(wid, 16)) != process["pid"]:
            continue
        detail = subprocess.check_output(["xwininfo", "-id", wid], text=True, timeout=2)
        if "Map State: IsViewable" not in detail:
            continue
        fields = [re.search(rf"{field}:\s+(-?\d+)", detail) for field in
                  ("Absolute upper-left X", "Absolute upper-left Y", "Width", "Height")]
        if not all(fields):
            continue
        rectangle = [int(field[1]) for field in fields]
        if min(rectangle) < 0 or min(rectangle[2:]) < 1:
            continue
        result.append({"window": wid, "rectangle": rectangle, "properties": props,
                       "details": detail,
                       "embedded": bool(re.search(r"_XEMBED_INFO\(.*?\) =", props)),
                       "popup": "Override Redirect State: yes" in detail
                       and "_NET_WM_WINDOW_TYPE_POPUP_MENU" in props})
    if identity(process["pid"]) != process:
        raise RuntimeError("App identity changed while observing X11 windows")
    return result


def x11_peer_pid(window):
    """XRes local-client PID, not a client-supplied _NET_WM_PID property."""
    class Spec(ctypes.Structure):
        _fields_ = [("client", ctypes.c_ulong), ("mask", ctypes.c_ulong)]

    class Value(ctypes.Structure):
        _fields_ = [("spec", Spec), ("length", ctypes.c_long), ("value", ctypes.c_void_p)]

    x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
    xres = ctypes.CDLL(ctypes.util.find_library("XRes") or "libXRes.so.1")
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xres.XResQueryClientIds.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.POINTER(Spec),
                                      ctypes.POINTER(ctypes.c_long),
                                      ctypes.POINTER(ctypes.POINTER(Value))]
    xres.XResClientIdsDestroy.argtypes = [ctypes.c_long, ctypes.POINTER(Value)]
    display = x11.XOpenDisplay(None)
    if not display:
        raise RuntimeError("Cannot inspect native X11 client peer")
    count, values = ctypes.c_long(), ctypes.POINTER(Value)()
    try:
        spec = Spec(window, 2)  # XRES_CLIENT_ID_PID_MASK
        status = xres.XResQueryClientIds(
            display, 1, ctypes.byref(spec), ctypes.byref(count), ctypes.byref(values))
        if status != 0 or not values or count.value < 1 or count.value > 16:
            raise RuntimeError("XRes native client PID unavailable")
        pids = {ctypes.cast(values[i].value, ctypes.POINTER(ctypes.c_uint32))[0]
                for i in range(count.value) if values[i].spec.mask & 2 and values[i].length >= 4}
        if len(pids) != 1:
            raise RuntimeError("XRes native client PID ambiguous or absent")
        return pids.pop()
    finally:
        if values:
            xres.XResClientIdsDestroy(count, values)
        x11.XCloseDisplay(display)


def notification_presenters(api, daemon, uid, desktop):
    """Resolve a named native presenter, never trust an arbitrary same-UID tree."""
    presenters = [daemon] if daemon else []
    if daemon and desktop == "GNOME" and api.NameHasOwner("org.gnome.Shell"):
        shell_owner = str(api.GetNameOwner("org.gnome.Shell"))
        shell = identity(int(api.GetConnectionUnixProcessID(shell_owner)))
        if shell["uid"] != uid:
            raise RuntimeError("Notification Shell presenter has foreign UID")
        if Path(shell["exe"]).name != "gnome-shell":
            raise RuntimeError("Named Shell presenter is not gnome-shell")
        presenters.append(shell)
    return presenters


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
    import pyatspi
    from gi.repository import GLib

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    api = dbus.Interface(
        bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus"), "org.freedesktop.DBus")
    owner = None
    owner_identity = None
    if api.NameHasOwner("org.freedesktop.Notifications"):
        owner = str(api.GetNameOwner("org.freedesktop.Notifications"))
        owner_identity = identity(int(api.GetConnectionUnixProcessID(owner)))
        if owner_identity["uid"] != account.pw_uid:
            raise RuntimeError("Notification daemon has foreign UID")
    # GNOME's real notification D-Bus service is a GJS forwarding process;
    # its visible banners belong to the independently named native Shell.
    presenters = notification_presenters(
        api, owner_identity, account.pw_uid, os.environ.get("XDG_CURRENT_DESKTOP"))
    address = str(dbus.Interface(bus.get_object("org.a11y.Bus", "/org/a11y/bus"),
                                "org.a11y.Bus").GetAddress())
    a11y_bus = dbus.bus.BusConnection(address)
    a11y_api = dbus.Interface(a11y_bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus"),
                              "org.freedesktop.DBus")

    def accessible_identity(obj):
        return accessible_peer_identity(obj, a11y_api, account.pw_uid)
    signals = []
    observed_menu = {}
    if owner:
        signal_owners = {owner}
        if api.NameHasOwner("org.gnome.Shell") and len(presenters) > 1:
            signal_owners.add(str(api.GetNameOwner("org.gnome.Shell")))

        def action_invoked(nid, action, sender=None):
            if sender in signal_owners:
                signals.append({"id": int(nid), "action": str(action), "sender": str(sender)})

        bus.add_signal_receiver(
            action_invoked,
            signal_name="ActionInvoked", dbus_interface="org.freedesktop.Notifications",
            sender_keyword="sender")
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
        yield from walk_tree(pyatspi.Registry.getDesktop(0))

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

    def activate(obj, index, expected=None):
        record = describe(obj)
        record["process"] = accessible_identity(obj)
        if record["process"]["uid"] != account.pw_uid:
            raise RuntimeError("Native target has foreign UID")
        if expected is not None and record["process"] != expected:
            raise RuntimeError("Native menu peer differs from app identity")
        if not obj.queryAction().doAction(index):
            raise RuntimeError("Native AT-SPI action rejected")
        return {"target": record, "action_index": index, "transport": "AT-SPI"}

    def app_nodes(process):
        desktop = pyatspi.Registry.getDesktop(0)
        for i in range(min(desktop.childCount, 100)):
            try:
                root = desktop[i]
                if accessible_identity(root) == process:
                    yield from walk_tree(root)
            except Exception:
                continue

    def find_item(process, label, seconds=6):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            pump()
            for obj, parents in app_nodes(process):
                try:
                    if opened_item(obj, parents, label, pyatspi.STATE_SHOWING):
                        return obj
                except Exception:
                    continue
            time.sleep(0.1)
        raise RuntimeError("Opened app-owned GTK menu item absent after bounded search")

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
                    owners[name] = {
                        "owner": current,
                        "process": identity(int(api.GetConnectionUnixProcessID(current)))}
            applications = []
            desktop = pyatspi.Registry.getDesktop(0)
            for i in range(min(desktop.childCount, 100)):
                try:
                    applications.append(describe(desktop[i]))
                except Exception:
                    pass
            return {"owners": owners, "applications": applications, "actions": list(signals),
                    "collector": identity(os.getpid()),
                    "session_type": os.environ["XDG_SESSION_TYPE"]}
        if operation == "tray-menu":
            observed_menu.clear()
            process = resolve_inner(request["app_identity"], account.pw_uid)
            before_popups = ({window["window"] for window in x11_owned_windows(process)
                              if window["popup"]}
                             if os.environ["XDG_SESSION_TYPE"] == "x11" else set())
            try:
                obj, _ = find(
                    lambda obj: "odin" in (obj.name + " " + obj.description).lower()
                    and obj.getRoleName() not in ("application", "frame", "menu item", "label")
                    and any("menu" in name.lower() for name in describe(obj)["actions"])
                    and accessible_identity(obj)["uid"] == account.pw_uid,
                    seconds=1)
            except RuntimeError:
                obj = None
            if obj is not None:
                info = describe(obj)
                index = next(i for i, name in enumerate(info["actions"]) if "menu" in name.lower())
                result = activate(obj, index)
            else:
                if os.environ["XDG_SESSION_TYPE"] != "x11":
                    raise RuntimeError(
                        "Wayland tray lacks native AT-SPI menu action; no coordinate fallback")
                icons = [window for window in x11_owned_windows(process) if window["embedded"]]
                if len(icons) != 1:
                    raise RuntimeError("No unique app-owned viewable native XEmbed icon")
                icon = icons[0]
                if (identity(process["pid"]) != process
                        or x11_peer_pid(int(icon["window"], 16)) != process["pid"]):
                    raise RuntimeError("XEmbed owner changed before input")
                x, y, width, height = icon["rectangle"]
                pyatspi.Registry.generateMouseEvent(x + width // 2, y + height // 2, "b3c")
                result = {"process": process, "transport": "native XEmbed X11 right-click",
                          "icon": icon}
            try:
                opened = find_item(process, "Open Odin", seconds=3)
            except RuntimeError:
                if os.environ["XDG_SESSION_TYPE"] != "x11":
                    raise
                popups = [window for window in x11_owned_windows(process)
                          if window["popup"] and window["window"] not in before_popups]
                if len(popups) != 1:
                    raise RuntimeError("No unique newly opened app-owned native GTK popup")
                result["appeared"] = popups[0]
                result["keyboardPopup"] = popups[0]["window"]
            else:
                result["appeared"] = describe(opened)
                if accessible_identity(opened) != process:
                    raise RuntimeError("Opened menu accessibility bus peer is not the app")
            observed_menu.update({"process": process,
                                  "keyboard_popup": result.get("keyboardPopup")})
            return result
        if operation == "tray-action":
            label = request["label"]
            if label not in ("Open Odin", "Exit Odin"):
                raise RuntimeError("Unknown tray action")
            if (not observed_menu
                    or identity(observed_menu["process"]["pid"]) != observed_menu["process"]):
                raise RuntimeError("No fresh live app-owned opened tray menu")
            process = observed_menu["process"]
            popup = observed_menu["keyboard_popup"]
            if popup:
                if os.environ["XDG_SESSION_TYPE"] != "x11":
                    raise RuntimeError("No Wayland keyboard/coordinate fallback")
                windows = [window for window in x11_owned_windows(process)
                           if window["window"] == popup and window["popup"]]
                if len(windows) != 1:
                    raise RuntimeError("Observed GTK popup disappeared before keyboard input")
                subprocess.run(["xdotool", "windowfocus", "--sync", popup], check=True, timeout=2)
                focused = int(subprocess.check_output(
                    ["xdotool", "getwindowfocus"], text=True, timeout=2))
                if focused != int(popup, 16) or x11_peer_pid(focused) != process["pid"]:
                    raise RuntimeError("Native keyboard focus is not the observed app GTK popup")
                # Production menu: first enabled item Open, last enabled item Exit.
                keys = ["Home" if label == "Open Odin" else "End", "Return"]
                subprocess.run(["xdotool", "key", "--clearmodifiers", *keys], check=True, timeout=2)
                observed_menu.clear()
                return {"transport": "native X11 keyboard in observed focused GTK popup",
                        "popup": windows[0], "process": process, "keys": keys,
                        "finalStateRequired": True}
            obj = find_item(process, label)
            actions = describe(obj)["actions"]
            index = next((i for i, name in enumerate(actions)
                          if name.lower() in ("click", "activate", "press", "default")), None)
            if index is None:
                raise RuntimeError("Opened menu item lacks native activation action")
            result = activate(obj, index, process)
            observed_menu.clear()
            return result
        if operation == "notification-click":
            if owner_identity is None:
                raise RuntimeError(
                    "Real desktop notification owner absent; notification row unavailable")
            text = request["text"]
            if not text.startswith("P33 native ") or len(text) > 100:
                raise RuntimeError("Requires qualification notification marker")
            candidates = []

            def owned_marker(obj):
                if text not in obj.name and text not in obj.description:
                    return False
                try:
                    peer = accessible_identity(obj)
                    candidates.append({"node": describe(obj), "peer": peer})
                    return peer in presenters
                except Exception as error:
                    candidates.append({"node": describe(obj), "error": str(error)})
                    return False

            try:
                obj, parents = find(owned_marker)
            except RuntimeError as error:
                detail = f"{error}; presenters={presenters}; markers={candidates[:8]}"
                raise RuntimeError(detail) from error
            appeared = describe(obj)
            appeared["showing"] = obj.getState().contains(pyatspi.STATE_SHOWING)
            appeared["visible"] = obj.getState().contains(pyatspi.STATE_VISIBLE)
            presenter = accessible_identity(obj)
            if presenter not in presenters or identity(presenter["pid"]) != presenter:
                raise RuntimeError("Notification accessible not owned by real daemon")
            for candidate in [obj, *parents[:4]]:
                info = describe(candidate)
                if info["role"] in ("application", "frame"):
                    break
                for i, name in enumerate(info["actions"]):
                    if name.lower() in ("click", "activate", "press", "default", "open"):
                        return {"appeared": appeared, "daemon": owner_identity,
                                "presenter": presenter, **activate(candidate, i, presenter)}
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
                result = handle_request(connection, account.pw_uid, dispatch)
                if result.get("ok") and result.get("result", {}).get("stopped"):
                    break
    finally:
        server.close()
        path.unlink()


if __name__ == "__main__":
    main()
