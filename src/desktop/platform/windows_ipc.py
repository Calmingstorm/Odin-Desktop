"""Windows: the app-to-engine transport (phase 2 plan B1, B2).

An owner-only named pipe: created as the first instance of its name (a squatter
makes the engine's start fail rather than sit in front of it), rejecting remote
clients, in byte mode, under a protected DACL that admits only this user. Each
end checks the user of the process at the other end. Over it runs the sealed
session (`ipc_auth.server_session` / `client_session`): the token never crosses
the pipe, and every frame after the proofs is sealed.
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
from asyncio import windows_events, windows_utils

from . import win32
from .windows_files import user_sid

PIPE_PREFIX = "\\\\.\\pipe\\odin-desktop-"
_STREAM_LIMIT = 1 << 16


def pipe_name(profile_id: str, sid: str | None = None) -> str:
    """``\\\\.\\pipe\\odin-desktop-<16 hex of SHA-256(user SID)>-<profile>`` (protocol doc)."""
    owner = hashlib.sha256((sid or user_sid()).encode("utf-8")).hexdigest()[:16]
    return f"{PIPE_PREFIX}{owner}-{profile_id}"


def endpoint_text(path) -> str:
    """The exact endpoint string both proofs bind."""
    return str(path)


class _OwnerOnlyPipeServer(windows_events.PipeServer):
    """asyncio's pipe server with our own handles: owner-only, local only, byte mode."""

    def __init__(self, address: str, descriptor: win32.SecurityDescriptor):
        self._descriptor = descriptor
        super().__init__(address)

    def _server_pipe_handle(self, first):
        if self.closed():
            return None
        flags = win32.PIPE_ACCESS_DUPLEX | win32.FILE_FLAG_OVERLAPPED
        if first:
            flags |= win32.FILE_FLAG_FIRST_PIPE_INSTANCE
        mode = (win32.PIPE_TYPE_BYTE | win32.PIPE_READMODE_BYTE | win32.PIPE_WAIT
                | win32.PIPE_REJECT_REMOTE_CLIENTS)
        attributes = self._descriptor.attributes()
        handle = win32.CreateNamedPipeW(self._address, flags, mode, win32.PIPE_UNLIMITED_INSTANCES,
                                        windows_utils.BUFSIZE, windows_utils.BUFSIZE, 0, attributes)
        if handle in (None, win32.INVALID_HANDLE_VALUE):
            raise win32.error(filename=self._address)
        pipe = windows_utils.PipeHandle(handle)
        self._free_instances.add(pipe)
        return pipe


class _Listening:
    """What ``listen`` returns: closes the pipe server; connections belong to their owner."""

    def __init__(self, server: _OwnerOnlyPipeServer, descriptor: win32.SecurityDescriptor):
        self._server = server
        self._descriptor = descriptor

    def close(self) -> None:
        self._server.close()
        self._descriptor.close()

    async def wait_closed(self) -> None:
        return None


class NamedPipeEndpoint:
    """The engine's listener. ``listen`` either serves the name or acquires nothing."""

    def __init__(self, path):
        self.name = endpoint_text(path)
        self._listening: _Listening | None = None

    async def listen(self, accept) -> _Listening:
        loop = asyncio.get_running_loop()
        if not isinstance(loop, windows_events.ProactorEventLoop):
            raise RuntimeError("the Windows transport needs the proactor event loop")
        descriptor = win32.SecurityDescriptor(f"D:P(A;;GA;;;{user_sid()})")
        try:
            server = _OwnerOnlyPipeServer(self.name, descriptor)
        except BaseException:
            descriptor.close()
            raise
        listening = _Listening(server, descriptor)

        def serve(pipe) -> None:
            reader = asyncio.StreamReader(limit=_STREAM_LIMIT, loop=loop)
            protocol = asyncio.StreamReaderProtocol(reader, accept, loop=loop)
            loop._make_duplex_pipe_transport(pipe, protocol, extra={"addr": self.name})

        def accept_next(future=None) -> None:
            # asyncio's own start_serving_pipe loop, around our pipe server.
            pipe = None
            try:
                if future is not None:
                    pipe = future.result()
                    server._free_instances.discard(pipe)
                    if server.closed():
                        pipe.close()
                        return
                    serve(pipe)
                pipe = server._get_unconnected_pipe()
                if pipe is None:
                    return
                future = loop._proactor.accept_pipe(pipe)
            except BrokenPipeError:
                if pipe and pipe.fileno() != -1:
                    pipe.close()
                loop.call_soon(accept_next)
            except OSError as exc:
                if pipe and pipe.fileno() != -1:
                    loop.call_exception_handler({"message": "Pipe accept failed",
                                                 "exception": exc, "pipe": pipe})
                    pipe.close()
                loop.call_soon(accept_next)
            except asyncio.CancelledError:
                if pipe:
                    pipe.close()
            else:
                server._accept_pipe_future = future
                future.add_done_callback(accept_next)

        loop.call_soon(accept_next)
        self._listening = listening
        return listening

    def close(self) -> None:
        if self._listening is not None:
            self._listening.close()
            self._listening = None


class WindowsIpc:
    """The transport members ``IpcServer`` and clients use on Windows."""

    @property
    def owner(self) -> str:
        return user_sid()

    @staticmethod
    def load_token(token_file) -> str:
        from .. import ipc_auth

        return ipc_auth.load_token(token_file)

    endpoint = NamedPipeEndpoint

    async def connect(self, path):
        """Open the pipe and check its server is this user's process before any byte is sent."""
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=_STREAM_LIMIT, loop=loop)
        protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
        transport, _ = await loop.create_pipe_connection(lambda: protocol, endpoint_text(path))
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        try:
            if self.peer(writer, client=False) != self.owner:
                raise PermissionError("foreign IPC listener")
        except BaseException:
            writer.close()
            raise
        return reader, writer

    @staticmethod
    def peer(writer, *, client: bool = True) -> str:
        """The user SID of the process at the other end, from the OS, never the peer."""
        pipe = writer.get_extra_info("pipe")
        return win32.pipe_peer_sid(pipe.handle, client=client)


# --- Routed variants ----------------------------------------------------------------------------


async def ipc_server_start(self) -> None:
    """``IpcServer.start`` on Windows: the same token, then a sealed session per connection.

    A connection reaches the shared serving path (``_accept`` → ``_serve``) only after
    its peer check and both proofs. ``_serve`` then reads a plain hello carrying this
    engine's own token, so its checks run unchanged.
    """
    from ..ipc_auth import server_session
    from ..protocol import PROTOCOL_MAJOR, PROTOCOL_MINOR, ProtocolError, encode_frame

    if self._server is not None or self._closing:
        raise RuntimeError("IPC server already started or closed")
    self._token = self._ipc.load_token(self.token_file)
    name = endpoint_text(self.socket_path)

    async def refuse(writer, reason: str) -> None:
        try:
            writer.write(encode_frame({"t": "bye", "reason": reason}))
            await asyncio.wait_for(writer.drain(), 1.0)
        except (OSError, TimeoutError, ProtocolError):
            pass
        writer.close()

    async def session(reader, writer) -> None:
        try:
            if self._ipc.peer(writer) != self._ipc.owner:
                await refuse(writer, "unauthorized")
                return
            sealed = await server_session(
                reader, writer, token=self._token, profile_id=self.profile_id, endpoint=name,
                instance_id=self.welcome()["core"]["instance_id"], max_frame=self.max_frame,
                selected={"major": PROTOCOL_MAJOR, "minor": PROTOCOL_MINOR})
        except PermissionError:
            await refuse(writer, "unauthorized")
            return
        except (ProtocolError, TimeoutError):
            await refuse(writer, "protocol_error")
            return
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            writer.close()
            return
        finally:
            self._writers.discard(writer)
        self._accept(*sealed)

    def accept(reader, writer) -> None:
        if self._closing:
            writer.close()
            return
        self._writers.add(writer)
        task = asyncio.create_task(session(reader, writer))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    try:
        self._server = await self.endpoint.listen(accept)
    except BaseException:
        self._token = None
        raise


async def local_client_connect(cls, socket_path, token_file, profile_id: str = "default"):
    """``LocalClient.connect`` on Windows: proofs instead of the token, then sealed frames."""
    from .. import platform
    from ..ipc_auth import client_session
    from ..protocol import HANDSHAKE_TIMEOUT, MAX_FRAME, ProtocolError, read_frame

    ipc = platform.current_platform().ipc
    token = ipc.load_token(token_file)
    reader, writer = await ipc.connect(socket_path)
    try:
        sealed_reader, sealed_writer = await client_session(
            reader, writer, token=token, profile_id=profile_id, endpoint=endpoint_text(socket_path),
            client={"name": "odin-cli", "version": "0"}, offered={"major": 0, "minor": 2},
            features=[])
        welcome = await asyncio.wait_for(read_frame(sealed_reader), HANDSHAKE_TIMEOUT)
        protocol = welcome.get("protocol")
        if (welcome.get("t") != "welcome" or not isinstance(protocol, dict)
                or type(protocol.get("major")) is not int or protocol["major"] != 0
                or welcome.get("profile_id") != profile_id
                or type(welcome.get("max_frame")) is not int
                or not 1 <= welcome["max_frame"] <= MAX_FRAME):
            raise ProtocolError("local handshake refused")
        return cls(sealed_reader, sealed_writer, welcome)
    except BaseException:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), HANDSHAKE_TIMEOUT)
        except (OSError, TimeoutError):
            pass
        raise


def parse_core_args(argv=None):
    """``parse_core_args`` on Windows: the endpoint must be this user's pipe for the profile."""
    from src.cli import parse_core_args as routed

    options = routed.linux_original(argv)
    if endpoint_text(options.socket) != pipe_name(options.paths.profile_id):
        sys.stderr.write("error: --socket must be this profile's named pipe\n")
        raise SystemExit(2)
    return options
