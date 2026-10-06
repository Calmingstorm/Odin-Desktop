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
import errno
import os
import socket
import stat
from collections.abc import Awaitable, Callable
from pathlib import Path

from . import ipc_auth
from .authority import OwnerAuthority, OwnerContext
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
        self._parent_fd = None
        self._socket_identity = None
        self._token = None
        self._closing = False

    async def start(self) -> None:
        if self._server is not None or self._closing:
            raise RuntimeError("IPC server already started or closed")
        self._token = ipc_auth.load_token(self.token_file)
        path, parent = ipc_auth.private_parent(self.socket_path, create=True)
        self._parent_fd = parent
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            if len(os.fsencode(path)) > 107:
                raise ValueError("IPC socket path too long")
            await self._remove_stale_socket()
            # Descriptor-relative bind prevents parent-link replacement during startup.
            sock.bind(f"/proc/self/fd/{parent}/{path.name}")
            info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            self._socket_identity = (info.st_dev, info.st_ino)
            os.chmod(path.name, 0o600, dir_fd=parent, follow_symlinks=False)
            sock.listen(socket.SOMAXCONN)
            sock.setblocking(False)
            self._server = await asyncio.start_unix_server(self._accept, sock=sock)
        except BaseException:
            sock.close()
            self._unlink_owned_socket()
            os.close(parent)
            self._parent_fd = None
            self._token = None
            raise

    async def _remove_stale_socket(self) -> None:
        try:
            info = os.stat(self.socket_path.name, dir_fd=self._parent_fd,
                           follow_symlinks=False)
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
            raise PermissionError("existing IPC path is not an owned socket")
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.setblocking(False)
        try:
            try:
                await asyncio.wait_for(asyncio.get_running_loop().sock_connect(
                    probe, f"/proc/self/fd/{self._parent_fd}/{self.socket_path.name}"), 1.0)
            except OSError as error:
                if error.errno != errno.ECONNREFUSED:
                    raise RuntimeError("IPC listener state unproven") from None
            except TimeoutError:
                raise RuntimeError("IPC listener state unproven") from None
            else:
                # Any live listener is protected, without needing its protocol/token.
                raise RuntimeError("IPC listener already active")
        finally:
            probe.close()
        current = os.stat(self.socket_path.name, dir_fd=self._parent_fd,
                          follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise RuntimeError("IPC socket changed during probe")
        os.unlink(self.socket_path.name, dir_fd=self._parent_fd)

    def _unlink_owned_socket(self) -> None:
        if self._parent_fd is None or self._socket_identity is None:
            return
        try:
            info = os.stat(self.socket_path.name, dir_fd=self._parent_fd,
                           follow_symlinks=False)
            if stat.S_ISSOCK(info.st_mode) and (info.st_dev, info.st_ino) == self._socket_identity:
                os.unlink(self.socket_path.name, dir_fd=self._parent_fd)
        except FileNotFoundError:
            pass
        self._socket_identity = None

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
            uid = ipc_auth.peer_uid(writer.get_extra_info("socket"))
            if uid != os.geteuid():
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
            self._unlink_owned_socket()
        finally:
            if self._parent_fd is not None:
                os.close(self._parent_fd)
                self._parent_fd = None
            self._token = None
