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
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import signal
import socket
import struct
import sys
import uuid
from datetime import datetime, timedelta, timezone

PROTOCOL = {"major": 0, "minor": 3}
MAX_FRAME = 4 * 1024 * 1024
EVENT_RETENTION = 5000
RESULT_CACHE = 2000
RECENT_OUTCOMES = 20
# Read methods are answered fresh every time; only commands that admit or change something keep a receipt.
READ_METHODS = {"status.get", "events.subscribe", "conversations.list", "messages.list", "conversation.snapshot",
                "search.query", "messages.around", "usage.get", "artifacts.read", "reports.page", "work.list",
                "tool.detail", "tool.output", "settings.schema", "codex.accounts.list", "codex.login.poll",
                "models.agents.get"}
# Idempotent by offset, so it keeps no durable receipt (protocol.md, Conventions).
NO_RECEIPT_METHODS = READ_METHODS | {"attachments.chunk"}
CHUNK_BYTES = 512 * 1024
ATTACHMENT_BYTES = 25 * 1024 * 1024
ATTACHMENTS_PER_TURN = 10
MODELS = ["gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-5.6-terra"]
EFFORTS = ["none", "low", "medium", "high", "xhigh", "max"]
# Odin rejects these effort levels for these models (schema.CODEX_MODEL_UNSUPPORTED_EFFORTS).
UNSUPPORTED_EFFORTS = {"gpt-6.1-sol": {"none"}, "gpt-6-astra": {"none"}}


REDACTED = "•" * 8


def field(path: str, kind: str, label: str, default, description: str = "", apply_mode: str = "live_read",
          **extra) -> dict:
    """One setting as Odin's apply registry describes it (GET /api/config/meta), minus its live values."""
    return {"path": path, "type": kind, "label": label, "description": description, "default": default,
            "enum": extra.pop("enum", None), "constraints": extra.pop("constraints", {}), "nullable": False,
            "sensitivity": extra.pop("sensitivity", "public"), "apply_mode": apply_mode,
            "apply_handler": extra.pop("apply_handler", None), "restart_reason": extra.pop("restart_reason", None),
            "activation_policy": extra.pop("activation_policy", None), "consumers": [], **extra}


# Odin's plain sentences for each apply mode (apply_registry._plain_effects), with config.yml read as the profile.
EFFECTS = {
    "live_read": ("Saving updates the profile's settings and takes effect immediately.",
                  "Odin reads this value on its next use."),
    "live_apply": ("Saving updates the profile's settings and reconfigures the running core.", None),
    "live_for_new_work": ("Saving updates the profile's settings and applies to the next spawn or turn.",
                          "Work already running keeps the values it started with."),
    "restart": ("Saving updates the profile's settings. Odin keeps its startup value until restarted.", None),
    "activation_required": ("Saving records your choice, but Odin continues using current behavior until you apply "
                            "it explicitly.", None),
    "dormant": ("Saving updates the profile's settings. This version of Odin does not use this setting. "
                "Restarting will not activate it.", None),
}

# A realistic subset of Odin's configuration.
SETTINGS = [
    field("timezone", "string", "Time zone", "UTC", "IANA name, used by the prompt clock and parse_time."),
    field("learning.enabled", "boolean", "Automatic learning", False, "Lets Odin record lessons from failures."),
    field("llm_provider.model", "string", "Main model", "gpt-6.1-sol", "The model that serves chat.",
          "live_apply", enum=MODELS, apply_handler="models.main.set"),
    field("openai_codex.reasoning_effort", "string", "Reasoning effort", "medium", apply_mode="live_apply",
          enum=EFFORTS, apply_handler="providers.codex.set"),
    field("openai_codex.context_utilization", "integer", "Context utilization (%)", 60,
          "How much of the model's input budget a turn may use.", "live_for_new_work",
          constraints={"minimum": 30, "maximum": 100}, apply_handler="providers.codex.set"),
    field("openai_codex.request_timeout_seconds", "integer", "Request timeout (s)", 600, apply_mode="live_apply",
          constraints={"minimum": 30, "maximum": 7200}, apply_handler="providers.codex.set"),
    field("openai_codex.auxiliary.enabled", "boolean", "Auxiliary model", True,
          "A second model for compaction, reflection and the completion judge.", "live_apply",
          apply_handler="providers.auxiliary.set"),
    field("openai_codex.auxiliary.model", "string", "Auxiliary model name", "gpt-6-sol", apply_mode="live_apply",
          enum=MODELS, apply_handler="providers.auxiliary.set"),
    field("ollama.enabled", "boolean", "Enabled", False, apply_mode="live_apply", apply_handler="providers.ollama.set"),
    field("ollama.base_url", "string", "Base URL", "http://localhost:11434", apply_mode="live_apply",
          apply_handler="providers.ollama.set"),
    field("ollama.model", "string", "Model", "qwen3:8b", apply_mode="live_apply", apply_handler="providers.ollama.set"),
    field("openai_compatible.enabled", "boolean", "Enabled", False, apply_mode="live_apply",
          apply_handler="providers.compat.set"),
    field("openai_compatible.base_url", "string", "Base URL", "https://openrouter.ai/api/v1", apply_mode="live_apply",
          apply_handler="providers.compat.set"),
    field("openai_compatible.api_key", "string", "API key", None, sensitivity="sensitive",
          apply_handler="providers.compat.set"),
    field("image.openai.image_model", "string", "Image model", "gpt-image-2.5-flare",
          "Follows Odin's default unless pinned.", "live_read"),
    field("image.openai.outer_model", "string", "Image host model", "gpt-6-astra",
          "The model that hosts image generation. Follows Odin's default unless pinned.", "live_read"),
    field("context.directory", "string", "Context files", "data/context", "Files added to every prompt.", "restart",
          restart_reason="Prompt sources are assembled when the prompt builder starts."),
    field("agents.model", "string", "Agent model", "inherit", "inherit, auto, or a fixed model.", "live_apply",
          enum=["inherit", "auto", *MODELS], apply_handler="models.agents.set"),
    field("agents.auto_model_allowlist", "array", "Models agents may choose", [], apply_mode="live_apply",
          apply_handler="models.agents.set"),
    field("agents.max_concurrent_agents", "integer", "Agents at once, per conversation", 5,
          constraints={"minimum": 1, "maximum": 25}),
    field("tools.command_shell", "string", "Command shell", "auto", apply_mode="live_for_new_work",
          enum=["auto", "bash", "sh"]),
    field("tools.tool_timeouts", "object", "Per-tool timeouts (s)", {}, 'For example {"run_command": 900}.',
          "live_for_new_work"),
    field("computer.enabled", "boolean", "Computer use", False, apply_mode="activation_required",
          apply_handler="computer.activation.set",
          activation_policy="On activates computer use for the running core; off revokes it."),
    field("graceful_degradation.enabled", "boolean", "Enabled", True, apply_mode="dormant",
          activation_policy="A legacy setting this version keeps loading but does not use."),
]
SETTINGS_FIELDS = {f["path"]: f for f in SETTINGS}
# The settings-shaped methods (protocol.md, Dedicated settings methods): settings.set's params, the owner's transaction.
SETTINGS_SHAPED = ("providers.codex.set", "providers.auxiliary.set", "providers.ollama.set", "providers.compat.set",
                   "computer.activation.set")
IMAGE_LEAVES = ("image_model", "outer_model")


def check_field_value(spec: dict, value) -> str | None:
    """Why `value` doesn't fit the field, or None."""
    kind = spec["type"]
    if value is None:
        return None if spec["nullable"] else "can't be empty"
    if kind == "boolean" and not isinstance(value, bool):
        return "must be true or false"
    if kind in ("integer", "number"):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or (kind == "integer" and not isinstance(value, int)):
            return "must be a whole number" if kind == "integer" else "must be a number"
        low, high = spec["constraints"].get("minimum"), spec["constraints"].get("maximum")
        if low is not None and value < low or high is not None and value > high:
            return f"must be between {low} and {high}"
    if kind == "string":
        if not isinstance(value, str):
            return "must be text"
        if spec["enum"] and value not in spec["enum"]:
            return "must be one of " + ", ".join(spec["enum"])
    if kind == "array" and not isinstance(value, list):
        return "must be a list"
    if kind == "object" and not isinstance(value, dict):
        return "must be an object"
    return None


# A 24x24 PNG in the app's accent colour, for "image" requests.
SAMPLE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAIAAABvFaqvAAAAH0lEQVR4nGO4u8KfKohh1KBRg0YNGjVo1KBRgwbeIABVkx09d147dQAAAABJRU5ErkJggg=="
)
# The development core refuses executables, so the app's "unsupported type" path can be exercised.
UNSUPPORTED_TYPES = {"application/x-msdownload", "application/x-executable"}
SEARCH_LIMIT = 50
AROUND_LIMIT = 50


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def iso_in(seconds: float) -> tuple[datetime, str]:
    at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return at, at.isoformat()


def words(text: str) -> set[str]:
    """Whole lowercase words, for the scripted behaviours below."""
    return set(re.findall(r"[a-z]+", text.lower()))


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def snippet(text: str, start: int, length: int, radius: int = 60) -> str:
    """The match with some context on each side, on one line."""
    left = max(0, start - radius)
    right = min(len(text), start + length + radius)
    body = " ".join(text[left:right].split())
    return ("…" if left > 0 else "") + body + ("…" if right < len(text) else "")


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
        self.unresolved: dict[str, list[dict]] = {}  # conversation_id -> outcomes with unreconciled effects
        self.tools: dict[str, list[dict]] = {}  # request_id -> tool entries
        self.controls: dict[str, dict] = {}  # control_command_id -> latest disposition
        self.submissions: dict[str, dict] = {}
        self.uploads: dict[str, dict] = {}
        self.artifacts: dict[str, dict] = {}  # ref -> {name, mime, data}
        self.reports: dict[str, dict] = {}  # report id -> {conversation_id, pages}
        self.tool_records: dict[str, dict] = {}  # invocation_id -> arguments, previews, retained output
        self.work: dict[str, dict] = {"s_daily": {
            "kind": "schedule", "id": "s_daily", "title": "Daily health report", "state": "active",
            "detail": "Every day at 09:00", "actions": ["pause", "run_now"]}}
        self.background: set[asyncio.Task] = set()
        self.notification_acks: dict[str, str] = {}  # dedupe_key -> what the app did
        self.settings_values = {path: spec["default"] for path, spec in SETTINGS_FIELDS.items()}
        self.boot_values = dict(self.settings_values)  # what restart-mode settings run with until a restart
        self.image_pinned: set[str] = set()  # image model leaves saved explicitly; the rest follow Odin's defaults
        self.secret_values: dict[str, str] = {}  # never echoed
        self.agent_hints: dict[str, str] = {}
        self.codex_accounts = [
            {"label": "Primary", "email": "primary@example.com", "account_id": "acct_1", "plan_type": "pro", "used": 23},
            {"label": "Secondary", "email": "second@example.com", "account_id": "acct_2", "plan_type": "plus", "used": 100},
        ]
        self.codex_current = 0
        self.logins: dict[str, dict] = {}
        self.attachments: dict[str, dict] = {}
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
        if method not in NO_RECEIPT_METHODS:
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
        if method not in NO_RECEIPT_METHODS:
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
        return {
            "phase": "ready", "core_instance_id": self.instance_id, "version": "fixture-0", "capabilities": ["chat"],
            "model": {"main": "fixture-echo", "effort": "none", "provider": "fixture"},
            "providers": [{"name": "fixture", "health": "ok"}],
            "limits": {"chunk_bytes": CHUNK_BYTES, "attachment_bytes": ATTACHMENT_BYTES,
                       "attachments_per_turn": ATTACHMENTS_PER_TURN},
            "summary": f"Development core {self.instance_id[:8]}: echo replies, no model, no tools.",
        }

    def m_usage(self, params: dict, _writer) -> dict:
        period = params.get("period") or "7d"
        if period not in ("24h", "7d", "30d", "all"):
            raise CoreError("bad_request", "usage ranges are 24h, 7d, 30d and all")
        sent = sum(len(r["text"]) for r in self.requests.values())
        tokens = {"value": sent // 4, "kind": "estimated"}
        return {
            "period": period,
            "tokens": tokens,
            "context": {"used": tokens, "budget": {"value": 272000, "kind": "measured"}},
            "quota": [{"account": "fixture", "window": "weekly", "used_percent": {"value": None, "kind": "unknown"},
                       "resets_at": None}],
            "summary": f"Development core: about {tokens['value']} tokens sent, estimated from characters. No quota.",
        }

    def m_reload(self, params: dict, _writer) -> dict:
        return {"disposition": "reloaded", "summary": f"Reloaded {params.get('scope') or 'context'}: nothing to load in the development core."}

    # ----------------------------------------------------------------- work
    def publish_work(self, item: dict) -> None:
        payload = {"kind": item["kind"], "id": item["id"], "state": item["state"]}
        if item.get("conversation_id"):
            payload["conversation_id"] = item["conversation_id"]
        self.emit("work.updated", "work", item["id"], payload)

    def later(self, seconds: float, action) -> None:
        async def run() -> None:
            await asyncio.sleep(seconds)
            action()
        task = asyncio.get_running_loop().create_task(run())
        self.background.add(task)
        task.add_done_callback(self.background.discard)

    def spawn_work(self, kind: str, title: str, req: dict, detail: str, seconds: float) -> None:
        item = {"kind": kind, "id": new_id(kind[0]), "title": title, "state": "running",
                "conversation_id": req["conversation_id"], "request_id": req["id"], "started_at": now(),
                "detail": detail, "actions": ["stop"]}
        self.work[item["id"]] = item
        self.publish_work(item)

        def finish() -> None:
            if item["state"] == "running":
                item.update(state="completed", detail="Finished", actions=[])
                self.publish_work(item)
        self.later(seconds, finish)

    def m_work_list(self, params: dict, _writer) -> dict:
        kind, cid = params.get("kind"), params.get("conversation_id")
        items = [dict(item, actions=list(item["actions"])) for item in self.work.values()
                 if (not kind or item["kind"] == kind) and (not cid or item.get("conversation_id") == cid)]
        return {"items": items}

    def m_work_control(self, params: dict, _writer) -> dict:
        item = self.work.get(str(params.get("id")))
        if item is None or item["kind"] != params.get("kind"):
            raise CoreError("not_found", "that work is no longer listed")
        action = params.get("action")
        if action not in item["actions"]:
            return {"disposition": "not_available"}
        if action in ("stop", "cancel"):
            item.update(state="stopping", actions=[])
            self.publish_work(item)

            def stopped() -> None:
                item.update(state="stopped", detail="Stopped by you")
                self.publish_work(item)
            self.later(0.3, stopped)
            return {"disposition": "requested"}
        if action == "pause":
            item.update(state="paused", actions=["resume", "run_now"])
        elif action == "resume":
            item.update(state="active", actions=["pause", "run_now"])
        elif action == "run_now":
            item["detail"] = f"{item['detail'].split(' · ')[0]} · ran just now"
        self.publish_work(item)
        return {"disposition": "done"}

    def m_tool_detail(self, params: dict, _writer) -> dict:
        record = self.tool_records.get(str(params.get("invocation_id")))
        if record is None or record["request_id"] != params.get("request_id"):
            raise CoreError("not_found", "no such tool call")
        output = {}
        if record["retained"]:
            output = {"cursor": f"out:{params['invocation_id']}:0", "expires_at": record["retained"]["expires_at"]}
        return {"tool": record["tool"], "target": record["target"], "arguments": record["arguments"],
                "previews": record["previews"], "output": output}

    def m_tool_output(self, params: dict, _writer) -> dict:
        try:
            _, invocation_id, offset_text = str(params.get("cursor")).split(":")
            offset = int(offset_text)
        except ValueError:
            raise CoreError("bad_request", "invalid output cursor") from None
        record = self.tool_records.get(invocation_id)
        retained = record and record["retained"]
        if not retained:
            raise CoreError("not_found", "no retained output for that cursor")
        if retained["expires"] <= datetime.now(timezone.utc):
            raise CoreError("expired", "Odin no longer keeps this output.")
        limit = max(1, min(int(params.get("limit") or 65536), 65536))
        text = retained["text"][offset:offset + limit]
        end = offset + len(text)
        result = {"text": text, "attachments": [], "eof": end >= len(retained["text"]),
                  "expires_at": retained["expires_at"]}
        if not result["eof"]:
            result["next_cursor"] = f"out:{invocation_id}:{end}"
        return result

    def m_notification_ack(self, params: dict, _writer) -> dict:
        outcome = params.get("outcome")
        if outcome not in ("shown", "suppressed", "failed") or not params.get("dedupe_key"):
            raise CoreError("bad_request", "an acknowledgement needs a dedupe_key and an outcome")
        self.notification_acks[str(params["dedupe_key"])] = outcome
        return {"disposition": "recorded"}

    # ------------------------------------------------------------- settings
    def settings_revision(self) -> str:
        """A hash of every saved value and secret, as Odin's config_revision hashes the whole configuration."""
        state = {"values": self.settings_values, "secrets": sorted(self.secret_values), "pins": sorted(self.image_pinned)}
        return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()[:16]

    def image_models(self) -> dict:
        """Odin's image_model_defaults: each leaf's effective value, shipped default, and follow or pin."""
        return {leaf: {"effective": self.settings_values[f"image.openai.{leaf}"],
                       "default": SETTINGS_FIELDS[f"image.openai.{leaf}"]["default"],
                       "status": "pin" if leaf in self.image_pinned else "follow"} for leaf in IMAGE_LEAVES}

    def image_models_revision(self) -> str:
        return hashlib.sha256(json.dumps(self.image_models(), sort_keys=True).encode()).hexdigest()[:16]

    def field_record(self, path: str) -> dict:
        spec = SETTINGS_FIELDS[path]
        mode = spec["apply_mode"]
        if spec["sensitivity"] != "public":
            desired = REDACTED if path in self.secret_values else None
            effective, pending = desired, False
        else:
            desired = self.settings_values[path]
            if mode == "restart":
                effective = self.boot_values[path]
                pending = effective != desired
            else:
                effective, pending = desired, False
        if pending:
            state = "pending_restart"
        elif mode == "dormant":
            state = "dormant"
        else:
            state = "applied"
        save_effect, runtime_effect = EFFECTS[mode]
        runtime_effect = spec["restart_reason"] or spec["activation_policy"] or runtime_effect
        return {**spec, "save_effect": save_effect, "runtime_effect": runtime_effect, "desired": desired,
                "effective": effective, "configured": desired not in (None, spec["default"]),
                "pending_restart": pending, "apply_state": state}

    def m_settings_schema(self, _params: dict, _writer) -> dict:
        fields = [self.field_record(path) for path in SETTINGS_FIELDS]
        counts: dict[str, int] = {}
        for record in fields:
            counts[record["apply_state"]] = counts.get(record["apply_state"], 0) + 1
        revision = self.settings_revision()
        return {"schema_version": 1, "revision": revision, "fields": fields,
                "status": {"counts": counts, "desired_revision": revision, "effective_revision": None},
                "image_models": self.image_models(), "image_models_revision": self.image_models_revision()}

    def effort_problem(self, model: str, effort: str) -> str | None:
        if effort in UNSUPPORTED_EFFORTS.get(model, set()):
            return f"{model} doesn't accept effort {effort}"
        return None

    def m_settings_set(self, params: dict, _writer) -> dict:
        return self.save_settings(params, "settings.set")

    def save_settings(self, params: dict, owner: str) -> dict:
        """settings.set and every settings-shaped method: validate as a whole, save, apply; all or nothing."""
        if params.get("expected_revision") != self.settings_revision():
            raise CoreError("stale_binding", "settings changed since you loaded them", "stale_binding")
        changes = params.get("changes") or []
        staged = dict(self.settings_values)
        pins = set(self.image_pinned)
        for change in changes:
            path = change.get("path")
            spec = SETTINGS_FIELDS.get(path)
            if spec is None:
                raise CoreError("bad_request", f"{path}: no such setting")
            if spec["sensitivity"] != "public":
                raise CoreError("bad_request", f"{path}: a secret; use secrets.set")
            if (spec["apply_handler"] or "settings.set") != owner:
                raise CoreError("bad_request", f"{path}: changed through {spec['apply_handler'] or 'settings.set'}")
            leaf = path.removeprefix("image.openai.") if path.startswith("image.openai.") else None
            if change.get("delete"):
                staged[path] = spec["default"]
                pins.discard(leaf)
                continue
            problem = check_field_value(spec, change.get("value"))
            if problem:
                raise CoreError("bad_request", f"{path}: {problem}")
            staged[path] = change["value"]
            # Odin's rule for image models: writing the default keeps following it; anything else pins.
            if leaf and (leaf in pins or change["value"] != spec["default"]):
                pins.add(leaf)
        problem = self.effort_problem(staged["llm_provider.model"], staged["openai_codex.reasoning_effort"])
        if problem:
            raise CoreError("bad_request", f"openai_codex.reasoning_effort: {problem}")
        unreachable = staged.get("ollama.base_url", "") if owner == "providers.ollama.set" else ""
        if "unreachable" in unreachable:
            # The owner's transaction: saved, then applied; a failed apply restores the saved values.
            raise CoreError("bad_request", f"ollama.base_url: couldn't reach {unreachable}; the saved settings were restored")
        self.settings_values = staged  # validated as a whole: all or nothing
        self.image_pinned = pins
        return {"revision": self.settings_revision(),
                "fields": [self.field_record(c["path"]) for c in changes]}

    def m_image_intent(self, params: dict, _writer) -> dict:
        if params.get("expected_revision") != self.image_models_revision():
            raise CoreError("stale_binding", "Image model intent changed; refresh before retrying", "stale_binding")
        operations = params.get("operations")
        if (not isinstance(operations, dict) or not operations or set(operations) - set(IMAGE_LEAVES)
                or any(v not in ("follow", "pin") for v in operations.values())):
            raise CoreError("bad_request", "operations must map image_model and/or outer_model to follow or pin")
        for leaf, operation in operations.items():
            path = f"image.openai.{leaf}"
            if operation == "follow":
                self.image_pinned.discard(leaf)
                self.settings_values[path] = SETTINGS_FIELDS[path]["default"]
            else:
                self.image_pinned.add(leaf)  # the value in effect now, even when it equals the default
        return {"image_models": self.image_models(), "image_models_revision": self.image_models_revision(),
                "revision": self.settings_revision()}

    def require_secret_leaf(self, params: dict) -> str:
        path = params.get("path")
        spec = SETTINGS_FIELDS.get(path)
        if spec is None or spec["sensitivity"] == "public":
            raise CoreError("bad_request", f"{path}: not a secret setting")
        return path

    def m_secret_set(self, params: dict, _writer) -> dict:
        path = self.require_secret_leaf(params)
        value = params.get("value")
        if not isinstance(value, str) or not value:
            raise CoreError("bad_request", f"{path}: a secret can't be empty")
        self.secret_values[path] = value
        return {"set": True}

    def m_secret_clear(self, params: dict, _writer) -> dict:
        path = self.require_secret_leaf(params)
        self.secret_values.pop(path, None)
        return {"set": False}

    def m_models_main_set(self, params: dict, _writer) -> dict:
        model = params.get("model")
        if model not in MODELS:
            raise CoreError("bad_request", "model must be a concrete model reference")
        problem = self.effort_problem(model, self.settings_values["openai_codex.reasoning_effort"])
        if problem:
            raise CoreError("bad_request", f"{problem}; choose another effort first")
        self.settings_values["llm_provider.model"] = model
        return {"status": "switched", "main_model": model, "configured_provider": "codex"}

    def agents_config(self) -> dict:
        return {"model": self.settings_values["agents.model"], "thinking_mode": None,
                "auto_model_allowlist": list(self.settings_values["agents.auto_model_allowlist"]),
                "model_selection_hints": dict(self.agent_hints)}

    def m_models_agents_get(self, _params: dict, _writer) -> dict:
        return self.agents_config()

    def m_models_agents_set(self, params: dict, _writer) -> dict:
        if "model" in params:
            problem = check_field_value(SETTINGS_FIELDS["agents.model"], params["model"])
            if problem:
                raise CoreError("bad_request", f"agents.model: {problem}")
            self.settings_values["agents.model"] = params["model"]
        if "auto_model_allowlist" in params:
            allowlist = params["auto_model_allowlist"]
            if check_field_value(SETTINGS_FIELDS["agents.auto_model_allowlist"], allowlist) or \
                    any(m not in MODELS for m in allowlist):
                raise CoreError("bad_request", "agents.auto_model_allowlist: only known models")
            self.settings_values["agents.auto_model_allowlist"] = list(allowlist)
        return self.agents_config()

    # -------------------------------------------------------- codex accounts
    def codex_index(self, params: dict) -> int:
        index = params.get("index")
        if not isinstance(index, int) or not 0 <= index < len(self.codex_accounts):
            raise CoreError("bad_request", "invalid account index")
        return index

    def m_codex_list(self, _params: dict, _writer) -> dict:
        observed = datetime.now(timezone.utc).timestamp()
        accounts = []
        for i, account in enumerate(self.codex_accounts):
            window = {"used_percent": account["used"], "window_minutes": 10080, "resets_at": observed + 3 * 86400}
            accounts.append({
                "index": i, "label": account["label"], "email": account["email"], "account_id": account["account_id"],
                "plan_type": account["plan_type"], "expires_at": observed + 86400, "expired": False,
                "rate_limited": False, "is_current": i == self.codex_current,
                "quota": {"primary": window, "secondary": None, "observed_at": observed, "limit_reached_type": None},
                "limit_reached": account["used"] >= 100, "quota_check_failed": None,
            })
        return {"configured": True, "account_count": len(accounts), "current_index": self.codex_current,
                "accounts": accounts}

    def m_codex_activate(self, params: dict, _writer) -> dict:
        self.codex_current = self.codex_index(params)
        return {"status": "activated", "active_index": self.codex_current}

    def m_codex_label(self, params: dict, _writer) -> dict:
        index = self.codex_index(params)
        label = params.get("label")
        if not isinstance(label, str):
            raise CoreError("bad_request", "label must be a string")
        self.codex_accounts[index]["label"] = label
        return {"status": "updated", "label": label}

    def m_codex_remove(self, params: dict, _writer) -> dict:
        index = self.codex_index(params)
        removed = self.codex_accounts.pop(index)
        if self.codex_current >= len(self.codex_accounts):
            self.codex_current = max(0, len(self.codex_accounts) - 1)
        return {"status": "deleted", "email": removed["email"]}

    def m_codex_login_begin(self, _params: dict, _writer) -> dict:
        auth_id = new_id("dev")
        code = f"FIX-{uuid.uuid4().hex[:4].upper()}"
        expires, _ = iso_in(900)
        self.logins[auth_id] = {"user_code": code, "polls": 0, "expires": expires, "done": None}
        return {"device_auth_id": auth_id, "user_code": code, "interval": 1,
                "verify_url": "https://auth.openai.com/codex/device"}

    def m_codex_login_poll(self, params: dict, _writer) -> dict:
        login = self.logins.get(str(params.get("device_auth_id")))
        if login is None or login["user_code"] != params.get("user_code"):
            raise CoreError("not_found", "no such login")
        if login["done"]:
            return login["done"]  # the same answer again, so a lost reply can be asked for
        if login["expires"] <= datetime.now(timezone.utc):
            raise CoreError("expired", "The login code expired. Start again.")
        login["polls"] += 1
        if login["polls"] < 2:
            return {"status": "pending"}  # the user approves in the browser on the second check
        number = len(self.codex_accounts) + 1
        account = {"label": "", "email": f"account{number}@example.com", "account_id": f"acct_{number}",
                   "plan_type": "plus", "used": 0}
        self.codex_accounts.append(account)
        login["done"] = {"status": "authenticated", "email": account["email"], "account_id": account["account_id"]}
        return login["done"]

    def m_resume(self, params: dict, _writer) -> dict:
        req = self.requests.get(str(params.get("request_id")))
        if not req or req["conversation_id"] != params.get("conversation_id") or req["generation"] != params.get("generation"):
            raise CoreError("stale_binding", "that is not the preserved request", "stale_binding")
        cid = req["conversation_id"]
        if req["state"] not in ("interrupted", "suspended"):
            return {"disposition": "rejected", "reason": "Only an interrupted or suspended request can resume."}
        if any(o["request_id"] == req["id"] for o in self.unresolved.get(cid, [])):
            return {"disposition": "rejected",
                    "reason": "Odin may have changed something it couldn't confirm. Reconcile that first."}
        if cid in self.active or self.queued.get(cid):
            return {"disposition": "rejected", "reason": "Odin is working in this conversation. Wait, or stop it first."}
        req["generation"] += 1
        req["resumed"] = True
        self.start_request(req["id"])
        return {"disposition": "admitted"}

    def m_artifact_read(self, params: dict, _writer) -> dict:
        artifact = self.artifacts.get(str(params.get("ref")))
        if artifact is None:
            raise CoreError("not_found", "that file is no longer available")
        offset = max(0, int(params.get("offset") or 0))
        length = max(1, min(int(params.get("length") or CHUNK_BYTES), CHUNK_BYTES))
        data = artifact["data"][offset:offset + length]
        return {"data_b64": base64.b64encode(data).decode(), "size": len(artifact["data"]),
                "eof": offset + len(data) >= len(artifact["data"])}

    def m_report_page(self, params: dict, _writer) -> dict:
        report = self.reports.get(str(params.get("report_id")))
        if report is None:
            raise CoreError("not_found", "that report is no longer available")
        pages = report["pages"]
        page = max(1, min(int(params.get("page") or 1), len(pages)))
        return {"page": page, "pages": len(pages), "text": pages[page - 1]}

    def make_artifacts(self, cid: str, text: str) -> list[dict]:
        """Scripted results for tests: whole words in the request ask for a file, an image, a script or a report."""
        words = {w.rstrip("s") for w in re.findall(r"\b(files?|images?|scripts?|reports?|tiffs?)\b", text.lower())}
        made = []
        if "file" in words:
            made.append(("notes.txt", "text/plain", "file", b"Generated notes\nline two\n"))
        if "image" in words:
            made.append(("chart.png", "image/png", "image", SAMPLE_PNG))
        if "tiff" in words:  # a format Chromium can't decode: the window falls back to a file card
            made.append(("scan.tiff", "image/tiff", "image", b"II*\x00not really a tiff"))
        if "script" in words:
            made.append(("cleanup.sh", "text/x-shellscript", "file", b"#!/bin/sh\necho hello\n"))
        result = []
        for name, mime, kind, data in made:
            ref = new_id("f")
            self.artifacts[ref] = {"name": name, "mime": mime, "data": data, "conversation_id": cid}
            result.append({"ref": ref, "name": name, "mime": mime, "size": len(data), "kind": kind, "available": True})
        if "report" in words:
            ref = new_id("rep")
            self.reports[ref] = {"conversation_id": cid,
                                 "pages": [f"## Page {n}\n\nStored result, page {n} of 3." for n in (1, 2, 3)]}
            result.append({"ref": ref, "name": "Health report", "mime": "text/markdown", "size": 0, "kind": "report",
                           "available": True})
        return result

    def m_attach_begin(self, params: dict, _writer) -> dict:
        self.require_conversation(params.get("conversation_id"))
        size = int(params.get("size") or 0)
        if size < 0:
            raise CoreError("bad_request", "an attachment's size can't be negative")  # empty files are fine
        if size > ATTACHMENT_BYTES:
            raise CoreError("too_large", f"attachments are limited to {ATTACHMENT_BYTES // (1024 * 1024)} MiB")
        mime = str(params.get("mime") or "application/octet-stream")
        if mime in UNSUPPORTED_TYPES:
            raise CoreError("unsupported_type", f"{mime} files aren't accepted")
        upload_id = new_id("u")
        self.uploads[upload_id] = {"name": str(params.get("name") or "file")[:255], "size": size, "mime": mime,
                                   "data": bytearray()}
        return {"upload_id": upload_id, "chunk_bytes": CHUNK_BYTES, "expires_at": None}

    def m_attach_chunk(self, params: dict, _writer) -> dict:
        upload = self.uploads.get(str(params.get("upload_id")))
        if upload is None:
            raise CoreError("expired", "that upload is gone")
        try:
            chunk = base64.b64decode(str(params.get("data_b64") or ""), validate=True)
        except (ValueError, binascii.Error):
            raise CoreError("bad_request", "chunk is not base64") from None
        offset = int(params.get("offset") or 0)
        data = upload["data"]
        if offset == len(data):
            if len(data) + len(chunk) > upload["size"] or len(chunk) > CHUNK_BYTES:
                raise CoreError("too_large", "more bytes than the upload declared")
            data.extend(chunk)
        elif offset + len(chunk) > len(data) or bytes(data[offset:offset + len(chunk)]) != chunk:
            raise CoreError("bad_request", "chunks must arrive in order")
        return {"received": len(data)}

    def m_attach_commit(self, params: dict, _writer) -> dict:
        upload = self.uploads.pop(str(params.get("upload_id")), None)
        if upload is None:
            raise CoreError("expired", "that upload is gone")
        data = bytes(upload["data"])
        if len(data) != upload["size"] or hashlib.sha256(data).hexdigest() != params.get("sha256"):
            raise CoreError("bad_request", "the upload doesn't match its size and digest; nothing was kept")
        ref = new_id("a")
        self.attachments[ref] = {"name": upload["name"], "mime": upload["mime"], "size": len(data), "data": data}
        return {"attachment": {"ref": ref, "name": upload["name"], "mime": upload["mime"], "size": len(data)}}

    def m_attach_cancel(self, params: dict, _writer) -> dict:
        self.uploads.pop(str(params.get("upload_id")), None)
        return {"disposition": "cancelled"}

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

    def activity(self, cid: str) -> dict:
        running_id = self.active.get(cid)
        running = None
        if running_id:
            running = {"request_id": running_id, "generation": self.requests[running_id]["generation"]}
        queued = [{"request_id": rid, "generation": self.requests[rid]["generation"]} for rid in self.queued.get(cid, [])]
        return {"running": running, "queued": queued}

    def commit_message(self, cid: str, message: dict, *, unread: bool = True) -> None:
        self.messages[cid].append(message)
        self.emit("message.committed", "message", message["id"], {"conversation_id": cid, "message": message})
        conv = self.conversations[cid]
        conv["updated_at"] = message["created_at"]
        if unread and message["role"] != "user":
            # Unread is not a user-editable field, so it doesn't bump the revision.
            conv["unread"] = conv.get("unread", 0) + 1
            self.emit("conversation.updated", "conversation", cid, {"conversation": conv})

    def require_conversation(self, conversation_id: object) -> dict:
        conv = self.conversations.get(str(conversation_id))
        if conv is None:
            raise CoreError("not_found", "conversation not found")
        return conv

    @staticmethod
    def check_rev(conv: dict, params: dict) -> None:
        if params.get("expected_rev") != conv["rev"]:
            raise CoreError("stale_binding", "conversation changed since it was read", "stale_binding")

    def m_conv_list(self, _params: dict, _writer) -> dict:
        items = [{**conv, "activity": self.activity(conv["id"])}
                 for conv in sorted(self.conversations.values(), key=lambda c: c["updated_at"])]
        return {"items": items, "watermark": str(self.seq)}

    def m_conv_create(self, params: dict, _writer) -> dict:
        title = str(params.get("title") or "Chat")[:200]
        parent = params.get("parent_id")
        inherited = None
        if parent is not None:
            source = self.require_conversation(parent)
            items = self.messages[source["id"]]
            from_id = params.get("from_message_id") or (items[-1]["id"] if items else None)
            if from_id is not None and not any(m["id"] == from_id for m in items):
                raise CoreError("not_found", "that message is not in the parent conversation")
            inherited = {"conversation_id": source["id"], "message_id": from_id, "title": source["title"]}
        conv = {"id": new_id("c"), "title": title, "rev": 1, "parent_id": parent, "inherited_from": inherited,
                "updated_at": now(), "unread": 0, "archived": False}
        self.conversations[conv["id"]] = conv
        self.messages[conv["id"]] = []
        self.emit("conversation.created", "conversation", conv["id"], {"conversation": conv})
        return {"conversation": conv}

    def m_conv_update(self, params: dict, _writer) -> dict:
        conv = self.require_conversation(params.get("id"))
        self.check_rev(conv, params)
        if "title" in params:
            conv["title"] = str(params["title"])[:200]
        if "archived" in params:
            conv["archived"] = bool(params["archived"])
        conv["rev"] += 1
        conv["updated_at"] = now()
        self.emit("conversation.updated", "conversation", conv["id"], {"conversation": conv})
        return {"conversation": conv}

    def m_conv_delete(self, params: dict, _writer) -> dict:
        conv = self.require_conversation(params.get("id"))
        self.check_rev(conv, params)
        cid = conv["id"]
        if cid in self.active or self.queued.get(cid):
            raise CoreError("busy", "Odin is working in this conversation. Stop it first.", "not_dispatched")
        for store in (self.conversations, self.messages, self.recent, self.unresolved, self.queued):
            store.pop(cid, None)
        for files in (self.artifacts, self.reports):
            for ref in [ref for ref, item in files.items() if item["conversation_id"] == cid]:
                del files[ref]
        self.emit("conversation.deleted", "conversation", cid, {"conversation_id": cid})
        return {"disposition": "deleted"}

    def m_conv_reset_context(self, params: dict, _writer) -> dict:
        conv = self.require_conversation(params.get("id"))
        self.check_rev(conv, params)
        cid = conv["id"]
        notice = {"id": new_id("m"), "role": "notice", "created_at": now(),
                  "text": "Context reset. Odin starts fresh from here; everything above stays visible."}
        self.commit_message(cid, notice, unread=False)
        conv["rev"] += 1
        self.emit("conversation.context_reset", "conversation", cid, {"conversation_id": cid, "message_id": notice["id"]})
        self.emit("conversation.updated", "conversation", cid, {"conversation": conv})
        return {"conversation": conv}

    def m_conv_mark_read(self, params: dict, _writer) -> dict:
        conv = self.require_conversation(params.get("id"))
        items = self.messages[conv["id"]]
        index = next((i for i, m in enumerate(items) if m["id"] == params.get("through_message_id")), None)
        if index is None:
            raise CoreError("not_found", "message not found")
        conv["unread"] = sum(1 for m in items[index + 1:] if m["role"] != "user")
        self.emit("conversation.updated", "conversation", conv["id"], {"conversation": conv})
        return {"conversation": conv}

    def m_search(self, params: dict, _writer) -> dict:
        query = str(params.get("query") or "").strip()
        if not query:
            raise CoreError("bad_request", "search needs a query")
        limit = max(1, min(int(params.get("limit") or 20), SEARCH_LIMIT))
        try:
            offset = int(params.get("cursor") or 0)
        except ValueError:
            raise CoreError("bad_request", "invalid search cursor") from None
        only = params.get("conversation_id")
        needle = query.lower()
        hits = []
        for cid, items in self.messages.items():
            if only and cid != only:
                continue
            for m in items:
                # The visible text, then the names of the files it carries.
                for text in [m["text"], *(a["name"] for a in m.get("artifacts", []))]:
                    at = text.lower().find(needle)
                    if at >= 0:
                        hits.append({"conversation_id": cid, "message_id": m["id"], "role": m["role"],
                                     "snippet": snippet(text, at, len(needle)), "created_at": m["created_at"]})
                        break
        hits.sort(key=lambda h: h["created_at"], reverse=True)
        page = hits[offset:offset + limit]
        more = offset + limit < len(hits)
        return {"hits": page, "next_cursor": str(offset + limit) if more else None, "watermark": str(self.seq)}

    def m_around(self, params: dict, _writer) -> dict:
        conv = self.require_conversation(params.get("conversation_id"))
        items = self.messages[conv["id"]]
        index = next((i for i, m in enumerate(items) if m["id"] == params.get("message_id")), None)
        if index is None:
            raise CoreError("not_found", "message not found")
        # 0 is a valid count, so only a missing value takes the default.
        before = max(0, min(int(20 if params.get("before") is None else params["before"]), AROUND_LIMIT))
        after = max(0, min(int(20 if params.get("after") is None else params["after"]), AROUND_LIMIT))
        start, end = max(0, index - before), min(len(items), index + after + 1)
        return {"items": items[start:end], "has_before": start > 0, "has_after": end < len(items)}

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
            "unresolved": list(self.unresolved.get(cid, [])),
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
        chosen = list(params.get("attachments") or [])
        if len(text) > 32000 or (not text.strip() and not chosen):
            raise CoreError("bad_request", "a message needs text or attachments, and at most 32,000 characters")
        if len(chosen) > ATTACHMENTS_PER_TURN:
            raise CoreError("too_large", f"at most {ATTACHMENTS_PER_TURN} attachments per message")
        attached = []
        for item in chosen:
            stored = self.attachments.get(str((item or {}).get("ref")))
            if stored is None:
                raise CoreError("not_found", "an attachment is missing; attach it again")
            attached.append({"ref": item["ref"], "name": stored["name"], "mime": stored["mime"], "size": stored["size"],
                             "add_to_knowledge": bool(item.get("add_to_knowledge"))})
        rid = new_id("r")
        message = {"id": new_id("m"), "role": "user", "text": text, "created_at": now(),
                   "client_submission_id": sub_id, "request_id": rid,
                   "attachments": [{k: a[k] for k in ("ref", "name", "mime", "size")} for a in attached]}
        self.commit_message(cid, message)
        self.requests[rid] = {"id": rid, "conversation_id": cid, "generation": 1, "text": text, "state": "queued",
                              "attachments": attached,
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
                                                       "request_id": req["id"], "generation": req["generation"]})
        record["disposition"] = disposition
        if sequence is not None:
            record["sequence"] = sequence
        if emit:
            self.emit("control.receipt", "control", command_id,
                      {"conversation_id": req["conversation_id"], "request_id": req["id"],
                       "generation": req["generation"], "control_command_id": command_id, "kind": kind,
                       "disposition": disposition})

    def finish(self, req: dict, terminal: str, unknown_effects: int = 0) -> None:
        cid = req["conversation_id"]
        outcome = {"request_id": req["id"], "generation": req["generation"], "outcome": terminal.split(".", 1)[1],
                   "unknown_effects": unknown_effects, "at": now()}
        recent = self.recent.setdefault(cid, [])
        recent.append(outcome)
        del recent[:-RECENT_OUTCOMES]
        if outcome["unknown_effects"]:
            # Kept until reconciled; later outcomes never push it out.
            self.unresolved.setdefault(cid, []).append(dict(outcome))
        self.emit(terminal, "request", req["id"],
                  {"conversation_id": cid, "request_id": req["id"], "generation": req["generation"],
                   "unknown_effects": unknown_effects})

    def start_request(self, rid: str) -> None:
        req = self.requests[rid]
        req["state"] = "running"
        req["started_at"] = now()
        self.active[req["conversation_id"]] = rid
        self.emit("request.started", "request", rid,
                  {"conversation_id": req["conversation_id"], "request_id": rid, "generation": req["generation"]})
        req["task"] = asyncio.get_running_loop().create_task(self.run_request(req))

    @staticmethod
    def tool_record(rid: str, text: str, said: set[str]) -> dict:
        """What tool.detail shows: scrubbed arguments, labeled previews, and retained output on request."""
        scrubbed = re.sub(r"(?i)\b(password|token|secret)=\S+", r"\1=•••", text)
        retained = None
        if "output" in said:
            body = "\n".join(f"build step {n}: ok" for n in range(1, 2001))
            expires, expires_at = iso_in(-60 if "expire" in said else 86400)
            retained = {"text": body, "expires": expires, "expires_at": expires_at}
            previews = [{"label": "Output, first 5 lines", "text": "\n".join(body.split("\n")[:5]), "truncated": True}]
        else:
            previews = [{"label": "Output", "text": f"Echoed {len(text)} characters.", "truncated": False}]
        return {"request_id": rid, "tool": "echo", "target": "localhost", "arguments": {"text": scrubbed},
                "previews": previews, "retained": retained}

    async def run_request(self, req: dict) -> None:
        cid, rid = req["conversation_id"], req["id"]
        said = words(req["text"])
        scripted = not req.get("resumed")  # a resumed request runs to completion
        inv = new_id("i")
        entry = {"invocation_id": inv, "tool": "echo", "target": "localhost",
                 "summary": f"echo {len(req['text'])} characters"}
        self.tools.setdefault(rid, []).append(entry)
        self.tool_records[inv] = self.tool_record(rid, req["text"], said)
        self.emit("tool.started", "invocation", inv, {"conversation_id": cid, "request_id": rid, **entry})
        if scripted and "agent" in said:
            self.spawn_work("agent", "Research agent", req, "Iteration 1 of 120", 8)
        if scripted and "process" in said:
            self.spawn_work("process", "tail -f build.log", req, "Running on localhost", 600)
        await asyncio.sleep(0.3)
        unknown = scripted and "unknown" in said
        settled = {"outcome": "unknown", "duration_ms": 300} if unknown else \
            {"outcome": "success", "exit_code": 0, "duration_ms": 300}
        entry.update(settled)
        self.emit("tool.settled", "invocation", inv, {"conversation_id": cid, "request_id": rid, "invocation_id": inv,
                                                     **settled})
        if scripted and ("interrupt" in said or unknown):
            # As if the core stopped mid-turn: the request is preserved for a guarded resume.
            req["state"] = "interrupted"
            self.finish(req, "request.interrupted", unknown_effects=1 if unknown else 0)
            self.active.pop(cid, None)
            queue = self.queued.get(cid) or []
            if queue and not self.stopping.is_set():
                self.start_request(queue.pop(0))
            return
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
            if req.get("attachments"):
                lines = [f"- {a['name']} ({a['size']} bytes)" + (", added to knowledge" if a["add_to_knowledge"] else "")
                         for a in req["attachments"]]
                reply += "\n\nReceived:\n" + "\n".join(lines)
            if consumed:
                reply += "\n\nSteered with: " + "; ".join(consumed)
            if re.search(r"\blong\b", req["text"].lower()):
                reply += "\n\n" + "\n\n".join(f"Paragraph {n}: the long reply keeps going so the window has to stay "
                                                 f"quick with thousands of blocks." for n in range(1, 2001))
                reply += "\n\n```text\n" + "\n".join(f"log line {n}" for n in range(1, 5001)) + "\n```"
            message = {"id": new_id("m"), "role": "assistant", "text": reply, "created_at": now(), "request_id": rid}
            artifacts = self.make_artifacts(cid, req["text"])
            if artifacts:
                message["artifacts"] = artifacts
            self.commit_message(cid, message)
            # Only a committed, guarded reply is announced (D9), and the preview is cut short, never the full text.
            self.emit("notification.intent", "notification", message["id"],
                      {"conversation_id": cid, "message_id": message["id"], "category": "reply",
                       "preview": re.sub(r"(?i)\b(password|token|secret)=\S+", r"\1=•••", reply)[:240],
                       "dedupe_key": f"reply:{message['id']}"})
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
    "conversations.delete": Core.m_conv_delete,
    "conversations.reset_context": Core.m_conv_reset_context,
    "conversations.mark_read": Core.m_conv_mark_read,
    "search.query": Core.m_search,
    "messages.around": Core.m_around,
    "usage.get": Core.m_usage,
    "artifacts.read": Core.m_artifact_read,
    "reports.page": Core.m_report_page,
    "work.list": Core.m_work_list,
    "work.control": Core.m_work_control,
    "tool.detail": Core.m_tool_detail,
    "tool.output": Core.m_tool_output,
    "control.resume": Core.m_resume,
    "notifications.ack": Core.m_notification_ack,
    "settings.schema": Core.m_settings_schema,
    "settings.set": Core.m_settings_set,
    **{name: (lambda owner: lambda core, params, writer: core.save_settings(params, owner))(name) for name in SETTINGS_SHAPED},
    "models.image.intent": Core.m_image_intent,
    "secrets.set": Core.m_secret_set,
    "secrets.clear": Core.m_secret_clear,
    "models.main.set": Core.m_models_main_set,
    "models.agents.get": Core.m_models_agents_get,
    "models.agents.set": Core.m_models_agents_set,
    "codex.accounts.list": Core.m_codex_list,
    "codex.accounts.activate": Core.m_codex_activate,
    "codex.accounts.label": Core.m_codex_label,
    "codex.accounts.remove": Core.m_codex_remove,
    "codex.login.begin": Core.m_codex_login_begin,
    "codex.login.poll": Core.m_codex_login_poll,
    "runtime.reload": Core.m_reload,
    "attachments.begin": Core.m_attach_begin,
    "attachments.chunk": Core.m_attach_chunk,
    "attachments.commit": Core.m_attach_commit,
    "attachments.cancel": Core.m_attach_cancel,
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
