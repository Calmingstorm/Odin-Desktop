"""OS-backed peer identity and no-follow app-created credentials."""
from __future__ import annotations

import errno
import hmac
import os
import re
import socket
import stat
import struct
from pathlib import Path

from .paths import _namespace_directories, _repair_namespace_directory, private_directory
from .platform.variants import windows_variant


def private_parent(path: Path | str, *, create: bool = False) -> tuple[Path, int]:
    """Resolve folder links, then hold the real parent without following leaf links."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or any(ord(c) < 32 for c in str(path)):
        raise ValueError("IPC path must be absolute")
    # Resolve only directories. The token/socket itself retains no-follow checks.
    path = Path(os.path.realpath(path.parent)) / path.name
    if create:
        private_directory(path.parent)
    namespace = _namespace_directories(path.parent)
    current = Path("/")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in path.parent.parts[1:]:
            current /= name
            try:
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except OSError as exc:
                raise OSError(exc.errno, exc.strerror, str(current)) from None
            os.close(fd)
            fd = child
            _repair_namespace_directory(fd, current, namespace, kind="IPC")
            info = os.fstat(fd)
            if info.st_uid not in {0, os.geteuid()}:
                raise PermissionError(errno.EACCES, "foreign IPC ancestor", str(current))
        return path, fd
    except BaseException:
        os.close(fd)
        raise


@windows_variant("src.desktop.platform.windows_desktop:load_token")
def load_token(token_file: Path | str) -> str:
    path, parent = private_parent(token_file)
    try:
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        except OSError as exc:
            raise OSError(exc.errno, exc.strerror, str(path)) from None
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size != 64):
                raise PermissionError(errno.EACCES, "unsafe IPC credential file", str(path))
            data = os.read(fd, 65)
        finally:
            os.close(fd)
    finally:
        os.close(parent)
    if not re.fullmatch(rb"[0-9a-fA-F]{64}", data):
        raise PermissionError(errno.EACCES, "invalid IPC credential", str(path))
    return data.decode("ascii")


read_token = load_token


def token_matches(expected: str, supplied: str) -> bool:
    try:
        candidate = supplied.encode("utf-8")
    except UnicodeError:
        return False
    return hmac.compare_digest(expected.encode("ascii"), candidate)


def peer_uid(sock: socket.socket) -> int:
    """Never consume a client-provided UID."""
    data = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", data)
    return uid


# --- The Windows session (phase 2 plan B2): proofs, keys and sealed frames ------------------
#
# Windows connections never carry the token. A client and the engine prove they hold it
# with role-labelled HMACs over a transcript of the handshake, then seal every later
# frame with AES-256-GCM under per-direction keys. Linux keeps its hello unchanged.
# The literal encodings are pinned by tests/fixtures/windows-session-vectors.json, which
# the app's TypeScript client reads too.

SESSION_LABEL = "odin-desktop/windows-session/v1"
AUTH_VERSION = 1
NONCE_BYTES = 32
TAG_BYTES = 16
SEAL_OVERHEAD = 8 + TAG_BYTES  # the frame counter and the GCM tag
PREAUTH_MAX_FRAME = 4096
CLIENT_TO_SERVER = 0x01
SERVER_TO_CLIENT = 0x02
# Re-handshake well before GCM's limits; a nonce and key pair is never reused.
SESSION_FRAME_LIMIT = 1 << 32
SESSION_BYTE_LIMIT = 1 << 36
_U64_LIMIT = 1 << 64


def _encode_string(value: str) -> bytes:
    from .protocol import ProtocolError

    try:
        data = value.encode("utf-8")
    except UnicodeEncodeError:
        raise ProtocolError("a handshake string is not valid UTF-8") from None
    return struct.pack("!I", len(data)) + data


def _encode_integer(value: int) -> bytes:
    from .protocol import ProtocolError

    if type(value) is not int or not 0 <= value < _U64_LIMIT:
        raise ProtocolError("a handshake integer is out of range")
    return struct.pack("!Q", value)


def session_transcript(*, offered: dict, selected: dict, client: dict, profile_id: str,
                       endpoint: str, client_nonce: bytes, server_nonce: bytes,
                       instance_id: str, max_frame: int, features: list) -> bytes:
    """SHA-256 over the handshake's fields in their fixed order."""
    import hashlib

    parts = [
        _encode_string(SESSION_LABEL), _encode_integer(AUTH_VERSION),
        _encode_integer(offered["major"]), _encode_integer(offered["minor"]),
        _encode_integer(selected["major"]), _encode_integer(selected["minor"]),
        _encode_string(client["name"]), _encode_string(client["version"]),
        _encode_string(profile_id), _encode_string(endpoint),
        client_nonce, server_nonce,
        _encode_string(instance_id), _encode_integer(max_frame),
        struct.pack("!I", len(features)) + b"".join(_encode_string(item) for item in features),
    ]
    return hashlib.sha256(b"".join(parts)).digest()


def _hkdf(material: bytes, salt: bytes, info: bytes) -> bytes:
    """HKDF-SHA256 (RFC 5869) for one 32-byte output block."""
    import hashlib

    key = hmac.new(salt, material, hashlib.sha256).digest()
    return hmac.new(key, info + b"\x01", hashlib.sha256).digest()


def session_keys(token: str, client_nonce: bytes, server_nonce: bytes,
                 transcript: bytes) -> dict[str, bytes]:
    """The proof key and the two directional AEAD keys, from the token's 32 raw bytes."""
    material = bytes.fromhex(token)
    salt = client_nonce + server_nonce
    return {label: _hkdf(material, salt, label.encode("ascii") + transcript)
            for label in ("proof", "c2s", "s2c")}


def session_proof(keys: dict[str, bytes], role: str, transcript: bytes) -> bytes:
    import hashlib

    label = {"server": b"server proof v1", "client": b"client proof v1"}[role]
    return hmac.new(keys["proof"], label + transcript, hashlib.sha256).digest()


def proof_matches(expected: bytes, supplied) -> bool:
    """Constant-time comparison of a hex proof from the wire."""
    if not isinstance(supplied, str) or not re.fullmatch(r"[0-9a-f]{64}", supplied):
        return False
    return hmac.compare_digest(expected, bytes.fromhex(supplied))


def _nonce_from(value) -> bytes:
    from .protocol import ProtocolError

    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ProtocolError("invalid session nonce")
    return bytes.fromhex(value)


class SealedDirection:
    """One direction of a session: its key, its counter and its byte budget."""

    def __init__(self, key: bytes, direction: int):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        self._aead = AESGCM(key)
        self._direction = direction
        self.counter = 0
        self.sealed_bytes = 0

    def _nonce(self, counter: int) -> bytes:
        return b"ODW" + bytes([self._direction]) + struct.pack("!Q", counter)

    def _account(self, size: int) -> None:
        from .protocol import ProtocolError

        if (self.counter >= SESSION_FRAME_LIMIT
                or self.sealed_bytes + size > SESSION_BYTE_LIMIT):
            raise ProtocolError("session key exhausted; reconnect")

    def seal(self, payload: bytes) -> bytes:
        self._account(len(payload))
        nonce = self._nonce(self.counter)
        header = struct.pack("!I", 8 + len(payload) + TAG_BYTES)
        frame = header + struct.pack("!Q", self.counter) + self._aead.encrypt(
            nonce, payload, nonce + header)
        self.counter += 1
        self.sealed_bytes += len(payload)
        return frame

    def open(self, header: bytes, body: bytes) -> bytes:
        from cryptography.exceptions import InvalidTag

        from .protocol import ProtocolError

        if len(body) < SEAL_OVERHEAD or struct.unpack("!Q", body[:8])[0] != self.counter:
            raise ProtocolError("sealed frame out of order")
        self._account(len(body) - SEAL_OVERHEAD)
        nonce = self._nonce(self.counter)
        try:
            payload = self._aead.decrypt(nonce, body[8:], nonce + header)
        except InvalidTag:
            raise ProtocolError("sealed frame rejected") from None
        self.counter += 1
        self.sealed_bytes += len(payload)
        return payload


class SealedReader:
    """Opens sealed frames and serves the plain frame stream that read_frame expects."""

    def __init__(self, reader, direction: SealedDirection, max_frame: int, *,
                 initial: bytes = b""):
        self._reader = reader
        self._direction = direction
        self._max_frame = max_frame
        self._buffer = bytearray(initial)

    async def readexactly(self, n: int) -> bytes:
        import asyncio

        from .protocol import ProtocolError

        while len(self._buffer) < n:
            try:
                header = await self._reader.readexactly(4)
                size = struct.unpack("!I", header)[0]
                # Bounded before anything is read or allocated.
                if not SEAL_OVERHEAD <= size <= self._max_frame + SEAL_OVERHEAD:
                    raise ProtocolError("invalid sealed frame size")
                body = await self._reader.readexactly(size)
            except asyncio.IncompleteReadError as exc:
                raise asyncio.IncompleteReadError(bytes(self._buffer) + exc.partial, n) from None
            payload = self._direction.open(header, body)
            self._buffer += struct.pack("!I", len(payload)) + payload
        data = bytes(self._buffer[:n])
        del self._buffer[:n]
        return data


class SealedWriter:
    """Seals each complete plain frame written to it; one ordered send path."""

    def __init__(self, writer, direction: SealedDirection):
        self._writer = writer
        self._direction = direction
        self._pending = bytearray()

    def write(self, data: bytes) -> None:
        # Counter assignment and the raw write happen in one synchronous step, so
        # concurrent senders can't share or reorder counters.
        self._pending += data
        while len(self._pending) >= 4:
            size = struct.unpack("!I", self._pending[:4])[0]
            if len(self._pending) < 4 + size:
                break
            payload = bytes(self._pending[4:4 + size])
            del self._pending[:4 + size]
            self._writer.write(self._direction.seal(payload))

    async def drain(self) -> None:
        await self._writer.drain()

    def close(self) -> None:
        self._writer.close()

    async def wait_closed(self) -> None:
        await self._writer.wait_closed()

    def is_closing(self) -> bool:
        return self._writer.is_closing()

    def get_extra_info(self, name, default=None):
        return self._writer.get_extra_info(name, default)


def _check_shape(message, keys: dict) -> dict:
    """A pre-auth frame with exactly these fields, each of the given type (a bool is no int)."""
    from .protocol import ProtocolError

    if (not isinstance(message, dict) or set(message) != set(keys)
            or any(not isinstance(message[key], kind)
                   or (kind is int and isinstance(message[key], bool))
                   for key, kind in keys.items())):
        raise ProtocolError("unexpected handshake frame")
    return message


def _check_versions(value) -> dict:
    from .protocol import ProtocolError

    if (not isinstance(value, dict) or set(value) != {"major", "minor"}
            or any(type(value[key]) is not int or not 0 <= value[key] < _U64_LIMIT
                   for key in value)):
        raise ProtocolError("invalid protocol version")
    return value


async def server_session(reader, writer, *, token: str, profile_id: str, endpoint: str,
                         instance_id: str, max_frame: int, selected: dict):
    """The engine's side: verify a token-less hello and the client's proof, then seal.

    Returns the sealed reader and writer. The reader starts with a plain hello carrying
    this engine's own token, so the existing server checks run unchanged on top of it.
    Refusals raise ProtocolError or PermissionError before any welcome is sent.
    """
    import asyncio
    import os

    from .protocol import HANDSHAKE_TIMEOUT, ProtocolError, encode_frame, read_frame

    async with asyncio.timeout(HANDSHAKE_TIMEOUT):
        hello = await read_frame(reader, PREAUTH_MAX_FRAME)
        if "token" in hello:
            raise PermissionError("a Windows hello never carries the token")
        _check_shape(hello, {"t": str, "protocol": dict, "client": dict, "profile_id": str,
                             "features": list, "auth": dict})
        auth = _check_shape(hello["auth"], {"v": int, "client_nonce": str})
        if hello["t"] != "hello" or auth["v"] != AUTH_VERSION:
            raise ProtocolError("unsupported session scheme")
        offered = _check_versions(hello["protocol"])
        client = _check_shape(hello["client"], {"name": str, "version": str})
        if any(not isinstance(item, str) for item in hello["features"]):
            raise ProtocolError("invalid features")
        client_nonce = _nonce_from(auth["client_nonce"])
        server_nonce = os.urandom(NONCE_BYTES)
        transcript = session_transcript(
            offered=offered, selected=selected, client=client, profile_id=hello["profile_id"],
            endpoint=endpoint, client_nonce=client_nonce, server_nonce=server_nonce,
            instance_id=instance_id, max_frame=max_frame, features=hello["features"])
        keys = session_keys(token, client_nonce, server_nonce, transcript)
        writer.write(encode_frame({
            "t": "challenge", "server_nonce": server_nonce.hex(), "protocol": selected,
            "max_frame": max_frame, "core": {"instance_id": instance_id},
            "server_proof": session_proof(keys, "server", transcript).hex()}))
        await writer.drain()
        reply = _check_shape(await read_frame(reader, PREAUTH_MAX_FRAME),
                             {"t": str, "client_proof": str})
        if reply["t"] != "proof":
            raise ProtocolError("unexpected handshake frame")
        if not proof_matches(session_proof(keys, "client", transcript), reply["client_proof"]):
            raise PermissionError("client proof refused")
    plain_hello = {"t": "hello", "protocol": offered, "client": client,
                   "profile_id": hello["profile_id"], "token": token, "features": hello["features"]}
    return (SealedReader(reader, SealedDirection(keys["c2s"], CLIENT_TO_SERVER), max_frame,
                         initial=encode_frame(plain_hello, max_frame)),
            SealedWriter(writer, SealedDirection(keys["s2c"], SERVER_TO_CLIENT)))


async def client_session(reader, writer, *, token: str, profile_id: str, endpoint: str,
                         client: dict, offered: dict, features: list):
    """A client's side: prove the token without sending it, after the engine proves it first."""
    import asyncio
    import os

    from .protocol import HANDSHAKE_TIMEOUT, MAX_FRAME, ProtocolError, encode_frame, read_frame

    client_nonce = os.urandom(NONCE_BYTES)
    async with asyncio.timeout(HANDSHAKE_TIMEOUT):
        writer.write(encode_frame({
            "t": "hello", "protocol": offered, "client": client, "profile_id": profile_id,
            "features": features, "auth": {"v": AUTH_VERSION, "client_nonce": client_nonce.hex()}}))
        await writer.drain()
        challenge = _check_shape(await read_frame(reader, PREAUTH_MAX_FRAME), {
            "t": str, "server_nonce": str, "protocol": dict, "max_frame": int, "core": dict,
            "server_proof": str})
        if challenge["t"] != "challenge":
            raise ProtocolError("unexpected handshake frame")
        selected = _check_versions(challenge["protocol"])
        core = _check_shape(challenge["core"], {"instance_id": str})
        max_frame = challenge["max_frame"]
        if type(max_frame) is not int or not 1 <= max_frame <= MAX_FRAME:
            raise ProtocolError("invalid max_frame")
        server_nonce = _nonce_from(challenge["server_nonce"])
        transcript = session_transcript(
            offered=offered, selected=selected, client=client, profile_id=profile_id,
            endpoint=endpoint, client_nonce=client_nonce, server_nonce=server_nonce,
            instance_id=core["instance_id"], max_frame=max_frame, features=features)
        keys = session_keys(token, client_nonce, server_nonce, transcript)
        if not proof_matches(session_proof(keys, "server", transcript), challenge["server_proof"]):
            raise PermissionError("engine proof refused")
        client_proof = session_proof(keys, "client", transcript).hex()
        writer.write(encode_frame({"t": "proof", "client_proof": client_proof}))
        await writer.drain()
    return (SealedReader(reader, SealedDirection(keys["s2c"], SERVER_TO_CLIENT), max_frame),
            SealedWriter(writer, SealedDirection(keys["c2s"], CLIENT_TO_SERVER)))
