"""Owner-authenticated Unix transport, independent of core method policy.

Core serializes subscribe response + replay + setting subscribed and publish with
its journal lock. A dispatcher returning None has already sent its own response.
The transport reads requests sequentially per connection. Step-one CoreService
also serializes dispatch across all connections, including awaited replay sends.
Future long-running methods need safe per-request concurrency without weakening
command admission or snapshot/replay/publication ordering.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from . import ipc_auth
from .authority import OwnerAuthority, OwnerContext
from .platform import current_platform
from .platform.variants import windows_variant
from .protocol import (
    HANDSHAKE_TIMEOUT,
    MAX_FRAME,
    PROTOCOL_MAJOR,
    PROTOCOL_MINOR,
    ProtocolError,
    encode_frame,
    read_frame,
    validate_hello,
    validate_max_frame,
    validate_request,
)

_BYE_REASONS = {"unauthorized", "incompatible", "wrong_profile", "protocol_error",
                "shutdown", "parent_lost", "internal_error"}


class Connection:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                 owner: OwnerContext, max_frame: int = MAX_FRAME):
        self.reader = reader
        self.writer = writer
        self.owner_context = owner
        self.owner = owner
        self.max_frame = max_frame
        self.subscribed = False
        self.event_seq = 0
        self._send_lock = asyncio.Lock()

    async def send(self, message: dict) -> None:
        frame = encode_frame(message, self.max_frame)
        async with self._send_lock:
            self.writer.write(frame)
            await asyncio.wait_for(self.writer.drain(), HANDSHAKE_TIMEOUT)


class IpcServer:
    def __init__(self, socket_path: Path | str, token_file: Path | str, profile_id: str,
                 authority: OwnerAuthority, welcome: Callable[[], dict],
                 dispatch: Callable[[Connection, dict], Awaitable[dict | None]],
                 *, max_frame: int = MAX_FRAME):
        if authority.profile_id != profile_id:
            raise ValueError("IPC authority profile mismatch")
        self.socket_path = Path(socket_path)
        self.token_file = Path(token_file)
        self.profile_id = profile_id
        self.authority = authority
        self.welcome = welcome
        self.dispatch = dispatch
        self.max_frame = validate_max_frame(max_frame)
        self.connections: set[Connection] = set()
        self._tasks: set[asyncio.Task] = set()
        self._writers: set[asyncio.StreamWriter] = set()
        self._server = None
        self._ipc = current_platform().ipc
        self.endpoint = self._ipc.endpoint(self.socket_path)
        self._token = None
        self._closing = False

    @windows_variant("src.desktop.platform.windows_ipc:ipc_server_start")
    async def start(self) -> None:
        if self._server is not None or self._closing:
            raise RuntimeError("IPC server already started or closed")
        self._token = self._ipc.load_token(self.token_file)
        try:
            self._server = await self.endpoint.listen(self._accept)
        except BaseException:
            self._token = None
            raise

    def _accept(self, reader, writer):
        if self._closing:
            writer.close()
            return
        self._writers.add(writer)
        task = asyncio.create_task(self._serve(reader, writer))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _bye(self, writer, reason):
        reason = reason if reason in _BYE_REASONS else "shutdown"
        try:
            writer.write(encode_frame({"t": "bye", "reason": reason}, self.max_frame))
            await asyncio.wait_for(writer.drain(), HANDSHAKE_TIMEOUT)
        except (OSError, TimeoutError, ProtocolError):
            pass

    async def _serve(self, reader, writer):
        connection = None
        unlock_tasks = set()
        try:
            uid = self._ipc.peer(writer)
            if uid != self._ipc.owner:
                await self._bye(writer, "unauthorized")
                return
            hello = await asyncio.wait_for(read_frame(reader, self.max_frame), HANDSHAKE_TIMEOUT)
            validate_hello(hello)
            if not ipc_auth.token_matches(self._token, hello["token"]):
                await self._bye(writer, "unauthorized")
                return
            if hello["protocol"]["major"] != PROTOCOL_MAJOR:
                await self._bye(writer, "incompatible")
                return
            if hello["profile_id"] != self.profile_id:
                await self._bye(writer, "wrong_profile")
                return
            owner = self.authority.authenticate_local(peer_uid=uid)
            connection = Connection(reader, writer, owner, self.max_frame)
            welcome = dict(self.welcome())
            welcome.update(t="welcome", protocol={"major": PROTOCOL_MAJOR, "minor": PROTOCOL_MINOR},
                           profile_id=self.profile_id, max_frame=self.max_frame)
            await connection.send(welcome)
            self.connections.add(connection)
            while not self._closing:
                message = await read_frame(reader, self.max_frame)
                if not self.authority.accepts(owner):
                    await self._bye(writer, "unauthorized")
                    return
                if self._closing:
                    return
                if message.get("t") == "ping" and "n" in message:
                    await connection.send({"t": "pong", "n": message["n"]})
                elif message.get("t") == "req":
                    validate_request(message)
                    if message["method"] == "secrets.unlock":
                        # Only this named human-prompt operation is concurrent.
                        # Ordinary requests retain their ordered serving path.
                        task = asyncio.create_task(self._unlock_request(connection, message))
                        unlock_tasks.add(task)
                        self._tasks.add(task)
                        task.add_done_callback(unlock_tasks.discard)
                        task.add_done_callback(self._tasks.discard)
                        await asyncio.sleep(0)
                        continue
                    response = await self.dispatch(connection, message)
                    if response is not None:
                        await connection.send(response)
                else:
                    raise ProtocolError("unknown message type")
        except (ProtocolError, TimeoutError):
            await self._bye(writer, "protocol_error")
        except PermissionError:
            await self._bye(writer, "unauthorized")
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        except Exception:
            # Never log exception text: callback/payload errors may contain credentials.
            await self._bye(writer, "internal_error")
        finally:
            for task in tuple(unlock_tasks):
                task.cancel()
            await asyncio.gather(*unlock_tasks, return_exceptions=True)
            if connection is not None:
                self.connections.discard(connection)
            self._writers.discard(writer)
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), HANDSHAKE_TIMEOUT)
            except (OSError, TimeoutError):
                pass

    async def _unlock_request(self, connection, message):
        try:
            response = await self.dispatch(connection, message)
            if not self.authority.accepts(connection.owner_context):
                raise PermissionError
            if response is not None:
                await connection.send(response)
        except (ConnectionError, OSError, PermissionError):
            connection.writer.close()
        except Exception:
            # Detached dispatch must not leak an unobserved secret-bearing
            # traceback; match the ordinary serving path's scrubbed refusal.
            await self._bye(connection.writer, "internal_error")
            connection.writer.close()

    async def publish(self, event: dict) -> None:
        """Call under core's subscription/replay serialization, after journal append."""
        async def deliver(connection):
            if not self.authority.accepts(connection.owner_context):
                await self._bye(connection.writer, "unauthorized")
                connection.writer.close()
                return
            if connection.subscribed and event["seq"] > connection.event_seq:
                try:
                    await connection.send(event)
                    connection.event_seq = event["seq"]
                except (OSError, TimeoutError):
                    connection.writer.close()
        await asyncio.gather(*(deliver(connection) for connection in tuple(self.connections)))

    async def close_listener(self) -> None:
        """Stop admission without disconnecting subscribers before quiesce publication."""
        self._closing = True
        if self._server is not None:
            self._server.close()
            # Python 3.12 wait_closed also waits for accepted transports. Keep
            # them alive here so core can publish quiescing before disconnect.

    async def shutdown(self, reason: str = "shutdown") -> None:
        await self.close_listener()
        await asyncio.gather(*(self._bye(c.writer, reason) for c in tuple(self.connections)))
        for writer in tuple(self._writers):
            writer.close()
        current = asyncio.current_task()
        tasks = [task for task in self._tasks if task is not current]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._server is not None:
            try:
                await asyncio.wait_for(self._server.wait_closed(), HANDSHAKE_TIMEOUT)
            finally:
                self._server = None
                self._cleanup_socket()
        else:
            self._cleanup_socket()

    def _cleanup_socket(self) -> None:
        try:
            self.endpoint.close()
        finally:
            self._token = None
