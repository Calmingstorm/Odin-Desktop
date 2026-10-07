"""Optional GNOME/cinnamon-session client. Query is not an Exit request.

No inhibitors, no session launch, and no registration failure can gate startup.
The live signal is deliberately not journalled: an old session cannot end a new app.
"""
import asyncio
import os
import sys

from dbus_next import Message, MessageType
from dbus_next.aio import MessageBus

NAME = "org.gnome.SessionManager"
PATH = "/org/gnome/SessionManager"
CLIENT = "org.gnome.SessionManager.ClientPrivate"
CALL_BOUND = 0.5


class SessionEndMonitor:
    def __init__(self, on_end):
        self.on_end = on_end
        self.bus = None
        self.owner = None
        self.client_path = None
        self.ending = False
        self.tasks = set()
        self.startup = None
        self.finished = asyncio.Event()

    def start(self):
        if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            self.startup = asyncio.create_task(self._start())

    async def _call(self, destination, path, interface, member, signature="", body=None):
        reply = await asyncio.wait_for(self.bus.call(Message(
            destination=destination, path=path, interface=interface, member=member,
            signature=signature, body=body or [],
        )), CALL_BOUND)
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError("Session manager unavailable")
        return reply

    async def _start(self):
        try:
            self.bus = await asyncio.wait_for(MessageBus().connect(), CALL_BOUND)
            reply = await self._call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                     "org.freedesktop.DBus", "GetNameOwner", "s", [NAME])
            self.owner = reply.body[0]
            self.bus.add_message_handler(self._signal)
            # Install the match before registering, so no client signal is missed.
            await self._call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                             "org.freedesktop.DBus", "AddMatch", "s", [
                                 f"type='signal',sender='{self.owner}',interface='{CLIENT}'"])
            reply = await self._call(self.owner, PATH, NAME, "RegisterClient", "ss",
                                     ["odin-desktop", os.environ.get("DESKTOP_AUTOSTART_ID", "")])
            self.client_path = reply.body[0]
        except Exception:
            # Optional desktop integration must fail open, including a wedged bus.
            if self.bus:
                self.bus.disconnect()
            self.bus = None

    def _spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def _signal(self, message):
        if (message.message_type != MessageType.SIGNAL or message.sender != self.owner
                or message.path != self.client_path or message.interface != CLIENT):
            return
        if message.member == "QueryEndSession" and message.signature == "u":
            self._spawn(self._respond())
        elif ((message.member == "EndSession" and message.signature == "u")
              or (message.member == "Stop" and message.signature == "")):
            if not self.ending:
                self.ending = True
                self._spawn(self._end())
        # CancelEndSession has nothing to undo: Query never quiesced the app.

    async def _respond(self):
        try:
            await self._call(self.owner, self.client_path, CLIENT,
                             "EndSessionResponse", "bs", [True, ""])
        except Exception:
            pass

    async def _end(self):
        try:
            await asyncio.wait_for(self.on_end(), CALL_BOUND)
        except Exception:
            pass
        # The app closes our parent pipe only AFTER persisting its Exit receipt.
        # A hung app cannot hold the session longer than eight seconds.
        try:
            await asyncio.wait_for(self.finished.wait(), 8)
        except TimeoutError:
            pass
        await self._respond()

    async def close(self):
        self.finished.set()
        if self.ending:
            # Let EndSession's one response settle before dropping registration.
            await asyncio.sleep(0)
            if self.tasks:
                await asyncio.wait(self.tasks, timeout=CALL_BOUND + 0.1)
        tasks = [*self.tasks, *([self.startup] if self.startup else [])]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.bus:
            self.bus.remove_message_handler(self._signal)
            # Disconnect unregisters this unique client; no extra logout delay.
            self.bus.disconnect()
            self.bus = None


async def run():
    async def end():
        print("session-ending", flush=True)

    monitor = SessionEndMonitor(end)
    monitor.start()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    transport, _ = await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin)
    try:
        await reader.read()
    finally:
        await monitor.close()
        transport.close()


if __name__ == "__main__":
    asyncio.run(run())
