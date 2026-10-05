#!/usr/bin/env python3
"""Development stand-in for Odin's core. Speaks protocol v0 (docs/design/protocol.md). Never ships.

It runs no tools and calls no model. Replies are scripted echoes and tool events are simulated, so the app can be
built and tested before Odin's real engine is wired in (Phase 2). Standard library only.

Scripted behaviour, for tests:
- every request emits one simulated tool call, then an assistant reply "Echo: <text>";
- a message containing "slow" keeps working in 0.25 s steps for about 15 s, so stop and steer can be exercised.

Unlike the real core, it keeps everything in memory, including command receipts, so it does not meet the protocol's
receipt-durability rule across its own restarts.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import signal
import socket
import struct
import sys
import uuid
from datetime import datetime, timezone

PROTOCOL = {"major": 0, "minor": 1}
MAX_FRAME = 4 * 1024 * 1024
EVENT_RETENTION = 5000
RESULT_CACHE = 2000
RECENT_OUTCOMES = 20
# Read methods are answered fresh every time; only commands that admit or change something keep a receipt.
READ_METHODS = {"status.get", "events.subscribe", "conversations.list", "messages.list", "conversation.snapshot"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def binding(method: object, params: dict) -> str:
    """A command ID is bound to its method and canonical params."""
    canonical = json.dumps({"method": method, "params": params}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class CoreError(Exception):
    def __init__(self, code: str, message: str, disposition: str = "rejected") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.disposition = disposition


def encode(frame: dict) -> bytes:
    body = json.dumps(frame, separators=(",", ":")).encode()
    if len(body) > MAX_FRAME:
        raise CoreError("internal", "frame too large")
    return struct.pack(">I", len(body)) + body


async def read_frame(reader: asyncio.StreamReader) -> dict | None:
    try:
        header = await reader.readexactly(4)
    except (asyncio.IncompleteReadError, ConnectionError):
        return None
    (length,) = struct.unpack(">I", header)
    if length > MAX_FRAME:
        raise CoreError("bad_request", "frame too large")
    body = await reader.readexactly(length)
    frame = json.loads(body)
    if not isinstance(frame, dict):
        raise CoreError("bad_request", "frame is not an object")
    return frame


class Core:
    def __init__(self, token: str, profile: str) -> None:
        self.token = token
        self.profile = profile
        self.instance_id = uuid.uuid4().hex
        self.seq = 0
        self.events: list[dict] = []
        self.subscribers: set[asyncio.StreamWriter] = set()
        self.conversations: dict[str, dict] = {}
        self.messages: dict[str, list[dict]] = {}
        self.requests: dict[str, dict] = {}
        self.active: dict[str, str] = {}  # conversation_id -> request_id
        self.queued: dict[str, list[str]] = {}
        self.recent: dict[str, list[dict]] = {}  # conversation_id -> latest terminal outcomes
        self.tools: dict[str, list[dict]] = {}  # request_id -> tool entries
        self.controls: dict[str, dict] = {}  # control_command_id -> latest disposition
        self.submissions: dict[str, dict] = {}
        self.results: dict[str, tuple[str, dict]] = {}  # command ID -> (binding, response)
        self.tombstones: dict[str, str] = {}  # pruned command ID -> binding
        self.stopping = asyncio.Event()

    # ---------------------------------------------------------------- events
    def emit(self, type_: str, kind: str, entity_id: str, payload: dict) -> None:
        self.seq += 1
        event = {
            "t": "evt",
            "seq": self.seq,
            "cursor": str(self.seq),
            "type": type_,
            "entity": {"kind": kind, "id": entity_id},
            "at": now(),
            "payload": payload,
        }
        self.events.append(event)
        del self.events[:-EVENT_RETENTION]
        data = encode(event)
        for writer in list(self.subscribers):
            if writer.is_closing():
                self.subscribers.discard(writer)
            else:
                writer.write(data)

    # ----------------------------------------------------------- connection
    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        sock = writer.get_extra_info("socket")
        try:
            creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            _pid, uid, _gid = struct.unpack("3i", creds)
            if uid != os.getuid():
                writer.close()
                return
            hello = await asyncio.wait_for(read_frame(reader), timeout=5)
        except (asyncio.TimeoutError, CoreError, ValueError, OSError):
            writer.close()
            return
        reason = self.check_hello(hello)
        if reason:
            writer.write(encode({"t": "bye", "reason": reason}))
            await writer.drain()
            writer.close()
            return
        writer.write(encode({
            "t": "welcome",
            "protocol": PROTOCOL,
            "core": {"instance_id": self.instance_id, "version": "fixture-0"},
            "profile_id": self.profile,
            "capabilities": ["chat"],
            "features": [],
            "max_frame": MAX_FRAME,
            "event_high": str(self.seq),
        }))
        try:
            while not self.stopping.is_set():
                try:
                    frame = await read_frame(reader)
                except (CoreError, ValueError):
                    writer.write(encode({"t": "bye", "reason": "protocol_error"}))
                    break
                if frame is None:
                    break
                kind = frame.get("t")
                if kind == "ping":
                    writer.write(encode({"t": "pong", "n": frame.get("n")}))
                elif kind == "req":
                    self.dispatch(writer, frame)
                else:
                    writer.write(encode({"t": "bye", "reason": "protocol_error"}))
                    break
        finally:
            self.subscribers.discard(writer)
            writer.close()

    def check_hello(self, hello: dict | None) -> str | None:
        if not hello or hello.get("t") != "hello":
            return "protocol_error"
        if not hmac.compare_digest(str(hello.get("token", "")).encode(), self.token.encode()):
            return "unauthorized"
        if (hello.get("protocol") or {}).get("major") != PROTOCOL["major"]:
            return "incompatible"
        if hello.get("profile_id") != self.profile:
            return "wrong_profile"
        return None

    def dispatch(self, writer: asyncio.StreamWriter, frame: dict) -> None:
        req_id = str(frame.get("id", ""))
        method = frame.get("method")
        params = frame.get("params") or {}
        if method not in READ_METHODS:
            bound = binding(method, params)
            if req_id in self.results:  # the same command ID always gets its original answer
                original_binding, original = self.results[req_id]
                if original_binding == bound:
                    writer.write(encode(original))
                else:
                    writer.write(encode(self.error(req_id, CoreError(
                        "id_conflict", "that command ID was already used for a different command"))))
                return
            if req_id in self.tombstones:
                writer.write(encode(self.error(req_id, CoreError(
                    "receipt_expired", "that command ID was used before; its outcome is unknown",
                    "outcome_unknown"))))
                return
        try:
            handler = METHODS.get(method)
            if handler is None:
                raise CoreError("bad_request", f"unknown method {method}")
            result = handler(self, params, writer)
            response = {"t": "res", "id": req_id, "ok": True, "result": result}
        except CoreError as error:
            response = self.error(req_id, error)
        if method not in READ_METHODS:
            self.results[req_id] = (binding(method, params), response)
            if len(self.results) > RESULT_CACHE:
                oldest = next(iter(self.results))
                self.tombstones[oldest] = self.results.pop(oldest)[0]
        writer.write(encode(response))
        if method == "events.subscribe" and response["ok"]:
            after = params.get("after")
            if after is not None and not response["result"]["reset_required"]:
                for event in self.events:
                    if event["seq"] > int(after):
                        writer.write(encode(event))
            self.subscribers.add(writer)

    @staticmethod
    def error(req_id: str, error: CoreError) -> dict:
        return {"t": "res", "id": req_id, "ok": False,
                "error": {"code": error.code, "message": error.message, "disposition": error.disposition}}

    # -------------------------------------------------------------- methods
    def m_status(self, _params: dict, _writer) -> dict:
        return {"phase": "ready", "core_instance_id": self.instance_id, "version": "fixture-0", "capabilities": ["chat"]}

    def m_subscribe(self, params: dict, _writer) -> dict:
        after = params.get("after")
        reset = False
        if after is not None:
            try:
                after_seq = int(after)
            except (TypeError, ValueError):
                after_seq = -1
            oldest = self.events[0]["seq"] if self.events else self.seq + 1
            reset = after_seq < 0 or after_seq > self.seq or (after_seq < oldest - 1)
        return {"event_high": str(self.seq), "reset_required": reset}

    def m_conv_list(self, _params: dict, _writer) -> dict:
        items = sorted(self.conversations.values(), key=lambda c: c["updated_at"])
        return {"items": items}

    def m_conv_create(self, params: dict, _writer) -> dict:
        title = str(params.get("title") or "Chat")[:200]
        parent = params.get("parent_id")
        if parent is not None and parent not in self.conversations:
            raise CoreError("not_found", "parent conversation not found")
        conv = {"id": new_id("c"), "title": title, "rev": 1, "parent_id": parent,
                "updated_at": now(), "unread": 0, "archived": False}
        self.conversations[conv["id"]] = conv
        self.messages[conv["id"]] = []
        self.emit("conversation.created", "conversation", conv["id"], {"conversation": conv})
        return {"conversation": conv}

    def m_conv_update(self, params: dict, _writer) -> dict:
        conv = self.conversations.get(str(params.get("id")))
        if not conv:
            raise CoreError("not_found", "conversation not found")
        if params.get("expected_rev") != conv["rev"]:
            raise CoreError("stale_binding", "conversation changed since it was read", "stale_binding")
        if "title" in params:
            conv["title"] = str(params["title"])[:200]
        if "archived" in params:
            conv["archived"] = bool(params["archived"])
        conv["rev"] += 1
        conv["updated_at"] = now()
        self.emit("conversation.updated", "conversation", conv["id"], {"conversation": conv})
        return {"conversation": conv}

    def m_messages(self, params: dict, _writer) -> dict:
        cid = str(params.get("conversation_id"))
        if cid not in self.messages:
            raise CoreError("not_found", "conversation not found")
        items = self.messages[cid]
        before = params.get("before")
        if before:
            index = next((i for i, m in enumerate(items) if m["id"] == before), len(items))
            items = items[:index]
        limit = max(1, min(int(params.get("limit") or 100), 100))
        return {"items": items[-limit:], "has_more": len(items) > limit, "watermark": str(self.seq)}

    def m_snapshot(self, params: dict, _writer) -> dict:
        cid = str(params.get("conversation_id"))
        conv = self.conversations.get(cid)
        if conv is None:
            raise CoreError("not_found", "conversation not found")
        limit = max(1, min(int(params.get("limit") or 100), 100))
        items = self.messages[cid]
        page = items[-limit:]
        running_id = self.active.get(cid)
        running = None
        if running_id:
            req = self.requests[running_id]
            running = {"request_id": running_id, "generation": req["generation"], "started_at": req["started_at"]}
        queued = [{"request_id": rid, "generation": self.requests[rid]["generation"],
                   "message_id": self.requests[rid]["message_id"]} for rid in self.queued.get(cid, [])]
        shown = {m["request_id"] for m in page if m.get("request_id")}
        if running_id:
            shown.add(running_id)
        bound = {q["request_id"] for q in queued} | ({running_id} if running_id else set())
        return {
            "watermark": str(self.seq),
            "conversation": conv,
            "messages": {"items": page, "has_more": len(items) > limit},
            "running": running,
            "queued": queued,
            "recent": list(self.recent.get(cid, [])),
            "tools": {rid: [dict(t) for t in self.tools[rid]] for rid in sorted(shown) if self.tools.get(rid)},
            "controls": [dict(c) for c in self.controls.values() if c["request_id"] in bound],
        }

    def m_submit(self, params: dict, _writer) -> dict:
        sub_id = str(params.get("client_submission_id", ""))
        if sub_id in self.submissions:
            return self.submissions[sub_id]
        cid = str(params.get("conversation_id"))
        if cid not in self.conversations:
            raise CoreError("not_found", "conversation not found")
        text = str(params.get("text", ""))
        if not text or len(text) > 32000:
            raise CoreError("bad_request", "text must be 1 to 32,000 characters")
        rid = new_id("r")
        message = {"id": new_id("m"), "role": "user", "text": text, "created_at": now(),
                   "client_submission_id": sub_id, "request_id": rid}
        self.messages[cid].append(message)
        self.emit("message.committed", "message", message["id"], {"conversation_id": cid, "message": message})
        self.requests[rid] = {"id": rid, "conversation_id": cid, "generation": 1, "text": text, "state": "queued",
                              "steers": [], "stop_commands": [], "task": None, "message_id": message["id"],
                              "started_at": None}
        if cid in self.active:
            self.queued.setdefault(cid, []).append(rid)
            self.emit("request.queued", "request", rid,
                      {"conversation_id": cid, "request_id": rid, "generation": 1, "message_id": message["id"]})
        else:
            self.start_request(rid)
        result = {"disposition": "accepted", "request_id": rid, "message_id": message["id"]}
        self.submissions[sub_id] = result
        return result

    def check_target(self, params: dict) -> dict:
        req = self.requests.get(str(params.get("request_id")))
        if not req or req["conversation_id"] != params.get("conversation_id") or req["generation"] != params.get("generation"):
            raise CoreError("stale_binding", "that task is not the one running here", "stale_binding")
        return req

    def m_stop(self, params: dict, _writer) -> dict:
        req = self.check_target(params)
        command_id = str(params.get("control_command_id"))
        if req["state"] not in ("running", "queued"):
            return {"disposition": "not_running"}
        self.record_control(command_id, "stop", req, "requested", emit=False)
        if req["state"] == "queued":
            # It never started, so it is withdrawn outright and can't start later.
            self.queued[req["conversation_id"]].remove(req["id"])
            req["state"] = "cancelled"
            self.record_control(command_id, "stop", req, "confirmed")
            self.finish(req, "request.cancelled")
            return {"disposition": "requested"}
        req["stop_commands"].append(command_id)
        req["state"] = "stop_requested"
        return {"disposition": "requested"}

    def m_steer(self, params: dict, _writer) -> dict:
        req = self.check_target(params)
        command_id = str(params.get("control_command_id"))
        if req["state"] != "running":
            return {"disposition": "closed"}
        req["steers"].append((command_id, str(params.get("text", ""))[:4000]))
        sequence = len(req["steers"])
        self.record_control(command_id, "steer", req, "queued", emit=False, sequence=sequence)
        return {"disposition": "queued", "sequence": sequence}

    def m_shutdown(self, _params: dict, _writer) -> dict:
        asyncio.get_running_loop().call_soon(self.request_stop)
        return {"disposition": "accepted"}

    # ------------------------------------------------------------- requests
    def record_control(self, command_id: str, kind: str, req: dict, disposition: str, *, emit: bool = True,
                       sequence: int | None = None) -> None:
        record = self.controls.setdefault(command_id, {"control_command_id": command_id, "kind": kind,
                                                       "request_id": req["id"]})
        record["disposition"] = disposition
        if sequence is not None:
            record["sequence"] = sequence
        if emit:
            self.emit("control.receipt", "control", command_id,
                      {"conversation_id": req["conversation_id"], "request_id": req["id"],
                       "control_command_id": command_id, "kind": kind, "disposition": disposition})

    def finish(self, req: dict, terminal: str) -> None:
        cid = req["conversation_id"]
        outcome = {"request_id": req["id"], "generation": req["generation"], "outcome": terminal.split(".", 1)[1],
                   "unknown_effects": 0, "at": now()}
        recent = self.recent.setdefault(cid, [])
        recent.append(outcome)
        del recent[:-RECENT_OUTCOMES]
        self.emit(terminal, "request", req["id"],
                  {"conversation_id": cid, "request_id": req["id"], "generation": req["generation"],
                   "unknown_effects": 0})

    def start_request(self, rid: str) -> None:
        req = self.requests[rid]
        req["state"] = "running"
        req["started_at"] = now()
        self.active[req["conversation_id"]] = rid
        self.emit("request.started", "request", rid,
                  {"conversation_id": req["conversation_id"], "request_id": rid, "generation": req["generation"]})
        req["task"] = asyncio.get_running_loop().create_task(self.run_request(req))

    async def run_request(self, req: dict) -> None:
        cid, rid = req["conversation_id"], req["id"]
        inv = new_id("i")
        entry = {"invocation_id": inv, "tool": "echo", "target": "localhost",
                 "summary": f"echo {len(req['text'])} characters"}
        self.tools.setdefault(rid, []).append(entry)
        self.emit("tool.started", "invocation", inv, {"conversation_id": cid, "request_id": rid, **entry})
        await asyncio.sleep(0.3)
        entry.update({"outcome": "success", "exit_code": 0, "duration_ms": 300})
        self.emit("tool.settled", "invocation", inv, {"conversation_id": cid, "request_id": rid, "invocation_id": inv,
                                                     "outcome": "success", "exit_code": 0, "duration_ms": 300})
        consumed: list[str] = []
        steps = 60 if "slow" in req["text"] else 1
        for _ in range(steps):
            if req["state"] == "stop_requested" or self.stopping.is_set():
                break
            while req["steers"]:
                command_id, text = req["steers"].pop(0)
                consumed.append(text)
                self.record_control(command_id, "steer", req, "consumed")
            await asyncio.sleep(0.25)
        for command_id, _text in req["steers"]:
            self.record_control(command_id, "steer", req, "closed")
        req["steers"].clear()
        if req["state"] == "stop_requested" or self.stopping.is_set():
            terminal = "request.cancelled" if req["state"] == "stop_requested" else "request.interrupted"
            req["state"] = "cancelled"
            for command_id in req["stop_commands"]:
                self.record_control(command_id, "stop", req, "confirmed")
            self.finish(req, terminal)
        else:
            reply = f"Echo: {req['text']}"
            if consumed:
                reply += "\n\nSteered with: " + "; ".join(consumed)
            message = {"id": new_id("m"), "role": "assistant", "text": reply, "created_at": now(), "request_id": rid}
            self.messages[cid].append(message)
            self.emit("message.committed", "message", message["id"], {"conversation_id": cid, "message": message})
            req["state"] = "completed"
            self.finish(req, "request.completed")
        self.active.pop(cid, None)
        queue = self.queued.get(cid) or []
        if queue and not self.stopping.is_set():
            self.start_request(queue.pop(0))

    def request_stop(self) -> None:
        if not self.stopping.is_set():
            self.stopping.set()


METHODS = {
    "status.get": Core.m_status,
    "events.subscribe": Core.m_subscribe,
    "conversations.list": Core.m_conv_list,
    "conversations.create": Core.m_conv_create,
    "conversations.update": Core.m_conv_update,
    "messages.list": Core.m_messages,
    "conversation.snapshot": Core.m_snapshot,
    "submission.send": Core.m_submit,
    "control.stop": Core.m_stop,
    "control.steer": Core.m_steer,
    "runtime.shutdown": Core.m_shutdown,
}


def read_token(path: str) -> str:
    with open(path, encoding="ascii") as handle:
        token = handle.read().strip()
    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        raise SystemExit("fixture-core: token file is malformed")
    return token


def prepare_socket(path: str) -> None:
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    os.chmod(os.path.dirname(path), 0o700)
    if os.path.exists(path):
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.connect(path)
        except OSError:
            os.unlink(path)  # stale socket: nothing is listening
        else:
            probe.close()
            raise SystemExit(3)  # another core already serves this profile
        finally:
            probe.close()


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--data-dir", required=False)
    args = parser.parse_args()

    core = Core(read_token(args.token_file), args.profile)
    prepare_socket(args.socket)
    server = await asyncio.start_unix_server(core.handle, path=args.socket)
    os.chmod(args.socket, 0o600)
    loop = asyncio.get_running_loop()

    # Parent link: EOF on stdin means the app is gone, so shut down rather than linger as a daemon.
    def on_stdin() -> None:
        try:
            data = os.read(sys.stdin.fileno(), 4096)
        except OSError:
            data = b""
        if not data:
            loop.remove_reader(sys.stdin.fileno())
            core.request_stop()

    loop.add_reader(sys.stdin.fileno(), on_stdin)
    loop.add_signal_handler(signal.SIGTERM, core.request_stop)
    loop.add_signal_handler(signal.SIGINT, core.request_stop)
    print(f"fixture-core ready instance={core.instance_id}", file=sys.stderr, flush=True)

    await core.stopping.wait()
    for req in list(core.requests.values()):
        task = req.get("task")
        if task and not task.done():
            await asyncio.wait({task}, timeout=2)
    server.close()
    for writer in list(core.subscribers):
        writer.write(encode({"t": "bye", "reason": "shutdown"}))
        writer.close()
    await server.wait_closed()
    try:
        os.unlink(args.socket)
    except FileNotFoundError:
        pass
    print("fixture-core stopped", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
