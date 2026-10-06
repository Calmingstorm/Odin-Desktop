"""Authenticated local diagnostics and guarded prompt replies, never a daemon."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
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


async def _call(client, method, params=None):
    identity = await client.request(method, params)
    while True:
        message = await client.read()
        if message.get("t") == "bye":
            raise ProtocolError("core closed the connection")
        if message.get("t") == "res" and message.get("id") == identity:
            if message.get("ok") is not True:
                raise ProtocolError("core refused the request")
            if type(message.get("result")) is not dict:
                raise ProtocolError("invalid core response")
            return message["result"]


async def _prompt(args, result):
    client = await LocalClient.connect(args.socket, args.token_file, args.profile)
    try:
        cid = args.conversation
        if cid is None:
            created = await _call(client, "conversations.create", {})
            cid = created["conversation"]["id"]
        result["conversation_id"] = cid
        prior = await _call(client, "conversation.snapshot", {
            "conversation_id": cid, "limit": 100,
        })
        old_ids = set()
        page = prior["messages"]
        while True:
            old_ids.update(item["id"] for item in page["items"])
            if not page["has_more"]:
                break
            if not page["items"]:
                raise ProtocolError("invalid transcript pagination")
            page = await _call(client, "messages.list", {
                "conversation_id": cid, "limit": 100, "before": page["items"][0]["id"],
            })
        admitted = await _call(client, "submission.send", {
            "client_submission_id": uuid.uuid4().hex,
            "conversation_id": cid, "text": args.prompt,
        })
        rid = admitted["request_id"]
        result["request_id"] = rid
        if admitted.get("disposition") != "accepted":
            result.update(response="Desktop submission was not accepted; nothing was retried",
                          is_error=True, outcome=admitted.get("disposition", "refused"))
            return
        # Admission may reuse a suspended request older than the bounded prior
        # snapshot. Never infer its generation from missing prior history.
        generation = admitted.get("generation", 1)
        if type(generation) is not int or generation < 1:
            raise ProtocolError("invalid admitted generation")
        result["generation"] = generation
        # Read only committed transcript messages, never tool/progress events or
        # raw model output. RequestService owns admission and final reply guards.
        while True:
            snapshot = await _call(client, "conversation.snapshot", {
                "conversation_id": cid, "limit": 100,
            })
            terminal = next((item for item in snapshot["recent"]
                             if item["request_id"] == rid
                             and item["generation"] == generation), None)
            if terminal is not None:
                outcome = terminal["outcome"]
                replies = [item for item in snapshot["messages"]["items"]
                           if item.get("request_id") == rid
                           and item["id"] not in old_ids
                           and item.get("role") == "assistant"]
                page = snapshot["messages"]
                while not replies and page["has_more"]:
                    if not page["items"]:
                        raise ProtocolError("invalid transcript pagination")
                    page = await _call(client, "messages.list", {
                        "conversation_id": cid, "limit": 100,
                        "before": page["items"][0]["id"],
                    })
                    replies = [item for item in page["items"]
                               if item.get("request_id") == rid
                               and item["id"] not in old_ids
                               and item.get("role") == "assistant"]
                if replies:
                    result.update(response=replies[-1]["text"],
                                  is_error=outcome != "completed", outcome=outcome)
                    return
                if outcome != "completed":
                    result.update(response="Desktop request ended without a guarded reply",
                                  is_error=True, outcome=outcome)
                    return
            # A completed effect may precede reply publication. Missing replies
            # and terminal entries evicted by >20 newer requests are bounded by
            # the user's timeout, never treated as successful empty output.
            await asyncio.sleep(0.05)
    finally:
        await client.close()


async def _run_prompt(args):
    result = {"response": "", "is_error": True}
    try:
        await asyncio.wait_for(_prompt(args, result), args.timeout)
    except TimeoutError:
        result.update(response="Desktop prompt timed out; "
                               "admitted work was not cancelled or retried",
                      outcome="timeout")
    except (OSError, ValueError, KeyError, TypeError, asyncio.IncompleteReadError):
        result.update(response="Desktop core connection failed", outcome="connection_error")
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    elif result["is_error"]:
        print(result["response"], file=sys.stderr)
    else:
        print(result["response"])
    return 1 if result["is_error"] else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Send a prompt over authenticated local IPC, or diagnose the core")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("input", nargs="?")
    parser.add_argument("--method", help="Diagnostic IPC method (no prompt submission)")
    parser.add_argument("--prompt", help="Prompt text, including text matching a diagnostic method")
    parser.add_argument("--conversation",
                        help="Existing profile conversation; otherwise create one")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be a positive finite number")
    if args.prompt is not None and args.input is not None:
        parser.error("use a positional prompt or --prompt, not both")
    diagnostic = args.method is not None or args.input == "status.get"
    if diagnostic:
        if args.prompt is not None or (args.method is not None and args.input is not None):
            parser.error("diagnostic methods cannot be combined with prompts")
        args.method = args.method or args.input
    else:
        args.prompt = args.prompt if args.prompt is not None else args.input
        if args.prompt is None:
            if sys.stdin.isatty():
                args.method = "status.get"
                diagnostic = True
            else:
                try:
                    args.prompt = sys.stdin.read()
                except OSError:
                    args.method = "status.get"
                    diagnostic = True
        if not diagnostic:
            args.prompt = args.prompt.strip()
            if not args.prompt:
                parser.print_help()
                return 1
    try:
        return asyncio.run(_run(args) if diagnostic else _run_prompt(args))
    except (OSError, ValueError, TimeoutError, asyncio.IncompleteReadError):
        print("Desktop core connection failed", file=sys.stderr)
        return 1
