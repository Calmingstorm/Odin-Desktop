"""Owned org.freedesktop.Notifications receiver, never a desktop notification daemon.

This records Electron's *native* D-Bus calls and emits a real ActionInvoked signal.
It does not paint notifications, prove human appearance, or implement core delivery.
Control requests use a private Unix socket, not a renderer IPC capability.
"""
# Exact freedesktop names/signatures are required by dbus-next; these are not Python type hints.
# ruff: noqa: N802, F722, F821
import argparse
import asyncio
import json
import os
import signal as os_signal
from pathlib import Path

from dbus_next import DBusError, NameFlag, RequestNameReply
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, method, signal


def assert_isolated():
    root = os.environ.get("ODIN_REAL_CORE_ROOT", "")
    outer = os.environ.get("ODIN_REAL_CORE_OUTER_PID_NS")
    if (os.getuid() == 0 or not outer or os.readlink("/proc/self/ns/pid") == outer
            or not root.startswith("/tmp/odrc-") or os.environ.get("HOME") != root
            or os.environ.get("ODIN_APP_E2E") != "1"
            or not os.environ.get("DBUS_SESSION_BUS_ADDRESS")):
        raise RuntimeError("Notification receiver requires the private app E2E PID/HOME/bus runner")
    return Path(root)


class Notifications(ServiceInterface):
    def __init__(self):
        super().__init__("org.freedesktop.Notifications")
        self.requests = []
        self.actions = []
        self.closes = []
        self.reject = False
        self.next_id = 1

    @method()
    def GetCapabilities(self) -> 'as':
        return ["actions", "body", "body-markup", "persistence"]

    @method()
    def GetServerInformation(self) -> 'ssss':
        return ["Odin private qualification receiver", "Odin Desktop tests", "1.0", "1.2"]

    @method()
    def Notify(self, app_name: 's', replaces_id: 'u', app_icon: 's', summary: 's',
               body: 's', actions: 'as', hints: 'a{sv}', expire_timeout: 'i') -> 'u':
        identity = self.next_id
        self.next_id += 1
        self.requests.append({"id": identity, "app_name": app_name, "replaces_id": replaces_id,
                              "summary": summary, "body": body, "actions": actions,
                              "expire_timeout": expire_timeout, "accepted": not self.reject})
        if self.reject:
            raise DBusError(
                "org.freedesktop.Notifications.Error.Failed", "Owned fixture rejected Notify"
            )
        return identity

    @method()
    def CloseNotification(self, identity: 'u'):
        self.closes.append(identity)
        self.NotificationClosed(identity, 3)

    @signal()
    def ActionInvoked(self, identity, action) -> 'us':
        return [identity, action]

    @signal()
    def NotificationClosed(self, identity, reason) -> 'uu':
        return [identity, reason]

    def snapshot(self):
        return {"pid": os.getpid(), "pid_namespace": os.readlink("/proc/self/ns/pid"),
                "requests": self.requests, "actions": self.actions, "closes": self.closes}


async def run(socket_path):
    root = assert_isolated()
    path = Path(socket_path)
    if not path.is_relative_to(root) or path.exists():
        raise RuntimeError("Control socket must be a fresh owned path in throwaway HOME")
    notifications = Notifications()
    bus = await MessageBus().connect()
    bus.export("/org/freedesktop/Notifications", notifications)
    claimed = await bus.request_name("org.freedesktop.Notifications", NameFlag.DO_NOT_QUEUE)
    if claimed != RequestNameReply.PRIMARY_OWNER:
        raise RuntimeError("Private notification name already occupied; refusing replacement")
    stopped = asyncio.Event()

    async def control(reader, writer):
        try:
            request = json.loads(await asyncio.wait_for(reader.readline(), timeout=5))
            action = request.get("action")
            if action == "snapshot":
                result = notifications.snapshot()
            elif action == "reject":
                notifications.reject = bool(request["enabled"])
                result = {"reject": notifications.reject}
            elif action == "release_name":
                await bus.release_name("org.freedesktop.Notifications")
                result = {"released": True}
            elif action == "click":
                identity = int(request["id"])
                item = next(
                    item for item in notifications.requests
                    if item["id"] == identity and item["accepted"]
                )
                # Action IDs were received from Electron, never invented to drive main JS directly.
                keys = item["actions"][::2]
                key = request.get("key", "default")
                if key not in keys:
                    raise ValueError(f"Action {key} not offered by Electron: {keys}")
                notifications.actions.append({"id": identity, "key": key})
                notifications.ActionInvoked(identity, key)
                result = {"emitted": True}
            elif action == "stop":
                result = {"cleanup": "bus disconnect and owned socket unlink requested"}
                stopped.set()
            else:
                raise ValueError("Unknown receiver control")
            response = {"ok": True, "result": result}
        except Exception as error:
            response = {"ok": False, "error": str(error)}
        writer.write(json.dumps(response).encode() + b"\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_unix_server(control, path=path)
    os.chmod(path, 0o600)
    for sig in (os_signal.SIGINT, os_signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stopped.set)
    print(json.dumps({"ready": True, **notifications.snapshot()}), flush=True)
    try:
        await stopped.wait()
    finally:
        server.close()
        await server.wait_closed()
        await bus.release_name("org.freedesktop.Notifications")
        bus.disconnect()
        await bus.wait_for_disconnect()
        path.unlink(missing_ok=True)
        print(json.dumps({"cleanup": "confirmed", "owned_socket_removed": not path.exists(),
                          "bus_disconnected": True, "pid": os.getpid()}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    asyncio.run(run(parser.parse_args().socket))
