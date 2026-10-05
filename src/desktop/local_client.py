"""Small authenticated local client for CLI diagnostics and event reading."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
import sys
import uuid
from pathlib import Path

from .ipc_auth import load_token, peer_uid, private_parent
from .protocol import HANDSHAKE_TIMEOUT, MAX_FRAME, ProtocolError, encode_frame, read_frame


class LocalClient:
    def __init__(self, reader, writer, welcome):
        self.reader = reader
        self.writer = writer
        self.welcome = welcome
        self.max_frame = welcome["max_frame"]

    @classmethod
    async def connect(cls, socket_path: Path | str, token_file: Path | str,
                      profile_id: str = "default") -> LocalClient:
        token = load_token(token_file)
        path, parent = private_parent(socket_path)
        try:
            info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600):
                raise PermissionError("unsafe IPC socket")
            reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(
                f"/proc/self/fd/{parent}/{path.name}"), HANDSHAKE_TIMEOUT)
        finally:
            os.close(parent)
        try:
            if peer_uid(writer.get_extra_info("socket")) != os.geteuid():
                raise PermissionError("foreign IPC listener")
            writer.write(encode_frame({"t": "hello", "protocol": {"major": 0, "minor": 2},
                                       "client": {"name": "odin-cli", "version": "0"},
                                       "profile_id": profile_id, "token": token, "features": []}))
            await asyncio.wait_for(writer.drain(), HANDSHAKE_TIMEOUT)
            welcome = await asyncio.wait_for(read_frame(reader), HANDSHAKE_TIMEOUT)
            protocol = welcome.get("protocol")
            if (welcome.get("t") != "welcome" or not isinstance(protocol, dict)
                    or type(protocol.get("major")) is not int or protocol["major"] != 0
                    or welcome.get("profile_id") != profile_id
                    or type(welcome.get("max_frame")) is not int
                    or not 1 <= welcome["max_frame"] <= MAX_FRAME):
                raise ProtocolError("local handshake refused")
            return cls(reader, writer, welcome)
        except BaseException:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), HANDSHAKE_TIMEOUT)
            except (OSError, TimeoutError):
                pass
            raise

    async def send(self, message: dict) -> None:
        self.writer.write(encode_frame(message, self.max_frame))
        await asyncio.wait_for(self.writer.drain(), HANDSHAKE_TIMEOUT)

    async def request(self, method: str, params: dict | None = None,
                      *, request_id: str | None = None) -> str:
        identity = request_id or str(uuid.uuid4())
        await self.send({"t": "req", "id": identity, "method": method,
                         "params": {} if params is None else params})
        return identity

    async def ping(self, n=0) -> None:
        await self.send({"t": "ping", "n": n})

    async def read(self) -> dict:
        return await read_frame(self.reader, self.max_frame)

    async def close(self) -> None:
        self.writer.close()
        try:
            await asyncio.wait_for(self.writer.wait_closed(), HANDSHAKE_TIMEOUT)
        except (OSError, TimeoutError):
            pass


async def _run(args) -> int:
    client = await LocalClient.connect(args.socket, args.token_file, args.profile)
    try:
        identity = await client.request(args.method)
        while True:
            message = await asyncio.wait_for(client.read(), HANDSHAKE_TIMEOUT)
            if message.get("t") == "res" and message.get("id") == identity:
                print(json.dumps(message, ensure_ascii=False))
                return 0 if message.get("ok") is True else 1
            if message.get("t") == "bye":
                return 1
    finally:
        await client.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Authenticated desktop-core diagnostics")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("method", nargs="?", default="status.get")
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except (OSError, ValueError, TimeoutError, asyncio.IncompleteReadError):
        print("Desktop core connection failed", file=sys.stderr)
        return 1
