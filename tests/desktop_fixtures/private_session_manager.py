"""Fake GNOME/cinnamon-session bus service; no logout operation on any desktop."""
# D-Bus decorators use signature strings, not Python annotations.
# ruff: noqa: N802, F722, F821
import asyncio
import json
import sys

from dbus_next import NameFlag, RequestNameReply
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, method, signal

NAME = "org.gnome.SessionManager"
PATH = "/org/gnome/SessionManager"
CLIENT_PATH = PATH + "/Client1"


class Client(ServiceInterface):
    def __init__(self):
        super().__init__(NAME + ".ClientPrivate")
        self.responses = []

    @method()
    def EndSessionResponse(self, ok: 'b', reason: 's'):
        self.responses.append([ok, reason])

    @signal()
    def QueryEndSession(self, flags=0) -> 'u':
        return flags

    @signal()
    def EndSession(self, flags=0) -> 'u':
        return flags

    @signal()
    def CancelEndSession(self):
        return None

    @signal()
    def Stop(self):
        return None


class Manager(ServiceInterface):
    def __init__(self):
        super().__init__(NAME)
        self.clients = []

    @method()
    def RegisterClient(self, app: 's', startup: 's') -> 'o':
        self.clients.append([app, startup])
        return CLIENT_PATH


async def serve():
    from tests.desktop_fixtures.private_notification_server import assert_isolated

    assert_isolated()
    bus = await MessageBus().connect()
    client, manager = Client(), Manager()
    bus.export(PATH, manager)
    bus.export(CLIENT_PATH, client)
    if await bus.request_name(NAME, NameFlag.DO_NOT_QUEUE) != RequestNameReply.PRIMARY_OWNER:
        raise RuntimeError("Private session-manager name already owned")
    print(json.dumps({"ready": True}), flush=True)
    reader = asyncio.StreamReader()
    transport, _ = await asyncio.get_running_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    try:
        while line := await reader.readline():
            action = json.loads(line)["action"]
            if action == "query":
                client.QueryEndSession(0)
            elif action == "cancel":
                client.CancelEndSession()
            elif action == "end":
                client.EndSession(0)
            elif action == "stop":
                client.Stop()
            elif action == "close":
                break
            state = {"clients": manager.clients, "responses": client.responses}
            print(json.dumps(state), flush=True)
    finally:
        transport.close()
        bus.disconnect()


if __name__ == "__main__":
    asyncio.run(serve())
