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
                "models.agents.get", "tools.list", "tools.timeouts.get", "skills.list", "skills.get", "skills.validate",
                "skills.config.get", "mcp.status", "mcp.tools", "hosts.list", "hosts.public_key", "hosts.references",
                "schedules.list", "schedules.history", "schedules.validate_cron", "personality.get", "memory.list",
                "memory.get", "lists.list", "lists.get", "knowledge.list", "knowledge.search", "knowledge.versions",
                "audit.query", "audit.verify", "health.get", "logs.search", "turn_state.list", "computer.status"}
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
    field("tools.tool_timeouts", "object", "Per-tool timeouts (s)", {"run_command": 900},
          'For example {"run_command": 900}.', "live_apply", apply_handler="tools.timeouts.set"),
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


# Built-in tools: (name, description, core). A subset of Odin's 67, in Odin's inventory shape.
BUILTIN_TOOLS = [
    ("run_command", "Run a shell command on a host.", True),
    ("read_file", "Read a file from a host.", True),
    ("write_file", "Write a file on a host.", True),
    ("apply_patch", "Apply a patch to files on a host.", True),
    ("manage_process", "Start, poll, write to or stop a background process.", True),
    ("web_search", "Search the web.", False),
    ("fetch_url", "Fetch a web page or file.", False),
    ("generate_image", "Generate an image from a prompt.", False),
    ("spawn_agent", "Start an agent on a goal.", False),
    ("memory_manage", "Read and write persistent memory.", False),
    ("schedule_task", "Schedule a task or a check.", False),
    ("email_send", "Send an email.", False),
    ("computer_act", "Act on the desktop: click, type, scroll.", False),
]
WEATHER_SKILL = '''"""Weather lookup."""
SKILL_DEFINITION = {
    "name": "weather",
    "description": "Look up the weather for a city.",
    "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
}


async def execute(inp, context):
    return f"Weather for {inp.get('city', 'nowhere')}: fine."
'''


def validate_skill(code: str) -> dict:
    """Odin's validate_skill_code report: compiled, never run."""
    errors, warnings = [], []
    try:
        compile(code, "<skill>", "exec")
    except SyntaxError as exc:
        return {"valid": False, "errors": [f"Syntax error at line {exc.lineno}: {exc.msg}"], "warnings": [],
                "metadata": None, "definition_keys": []}
    if "SKILL_DEFINITION" not in code:
        errors.append("SKILL_DEFINITION is missing.")
    if "def execute" not in code:
        errors.append("execute() is missing.")
    elif "async def execute" not in code:
        warnings.append("execute() is not async. It should be 'async def execute(inp, context)'.")
    return {"valid": not errors, "errors": errors, "warnings": warnings, "metadata": None,
            "definition_keys": ["name", "description", "input_schema"] if not errors else []}


MCP_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
HOST_ALIAS = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")


# Odin's own rule (src/tools/ssh.py): exactly these addresses are this computer.
LOCAL_ADDRESSES = frozenset({"127.0.0.1", "localhost", "::1"})


def fingerprint_of(address: str) -> str:
    """A stable stand-in for scanning a host's key: OpenSSH's SHA256: form."""
    return "SHA256:" + base64.b64encode(hashlib.sha256(address.encode()).digest()).decode().rstrip("=")


def cron_matches(field: str, value: int) -> bool:
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            step = int(step_text)
        if part == "*":
            low, high = 0, 10**6
        elif "-" in part:
            low, high = (int(x) for x in part.split("-", 1))
        else:
            low = high = int(part)
        if low <= value <= high and (value - (low if part != "*" else 0)) % step == 0:
            return True
    return False


def next_cron_runs(expression: str, count: int = 3) -> list[str]:
    """The next runs of a five-field cron expression, in UTC: enough for the fixture's checks."""
    fields = expression.split()
    if len(fields) != 5 or any(not re.fullmatch(r"[0-9*/,\-]+", f) for f in fields):
        raise ValueError("a cron expression has five fields: minute hour day month weekday")
    minute, hour, day, month, weekday = fields
    at = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    runs = []
    for _ in range(60 * 24 * 32):
        at += timedelta(minutes=1)
        if (cron_matches(minute, at.minute) and cron_matches(hour, at.hour) and cron_matches(day, at.day)
                and cron_matches(month, at.month) and cron_matches(weekday, (at.weekday() + 1) % 7)):
            runs.append(at.isoformat())
            if len(runs) == count:
                break
    return runs


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
        self.personality = {"preset": "odin", "custom_name": "", "custom_identity": "", "custom_voice": ""}
        self.user_presets: dict[str, dict] = {}
        self.memory: dict[str, dict] = {"global": {"deploy_window": "Deploys happen after 18:00."},
                                        "owner": {"preferred_editor": "Uses VS Code."}}
        self.lists: dict[str, dict] = {"groceries": {"items": ["milk", "eggs", "coffee"], "updated_at": now()}}
        self.knowledge: dict[str, dict] = {}
        self.knowledge_versions: dict[str, list[dict]] = {}
        self.audit: list[dict] = [{"timestamp": now(), "type": "tool", "tool_name": "run_command", "user_id": "owner",
                                   "tool_input": {"host": "localhost", "command": "uptime"}, "approved": True,
                                   "result_summary": "up 3 days", "execution_time_ms": 42, "error": None, "host": "localhost"}]
        self.logs: list[dict] = [{"timestamp": now(), "level": "INFO", "message": "Core started.", "tool": None},
                                 {"timestamp": now(), "level": "ERROR", "message": "MCP server Grafana: disabled.", "tool": None}]
        # Odin's computer use is one lifecycle at a time. This one was left quarantined: its input release couldn't be
        # verified. What inspecting it finds decides what reconciling can do, as in Odin's controller.
        self.computer: dict = {"state": "quarantined", "session_id": "cs_7f3a", "generation": 1, "session_generation": 3,
                               "last_action": "click", "last_verification": "release_unverified",
                               "recovery": {"status": "operator_reconciliation_required", "reason": "controller_lost",
                                            "complete": False}}
        self.computer_inspection = os.environ.get("ODIN_FIXTURE_COMPUTER_INSPECTION", "attestation_eligible")
        self.work: dict[str, dict] = {}  # agents, processes and the like; schedules come from self.schedules
        self.schedules: dict[str, dict] = {"5d0a7c21": {
            "id": "5d0a7c21", "description": "Post the daily status to the dashboard", "action": "webhook",
            "channel_id": "", "created_at": now(), "last_run": None, "paused": False, "cron": "0 9 * * *",
            "one_time": False, "timezone": "UTC", "next_run": next_cron_runs("0 9 * * *", 1)[0],
            "webhook_config": {"url": "https://status.example.net/hook", "method": "POST"},
            "max_retries": 0, "retry_backoff_seconds": 60, "consecutive_failures": 0, "retry_count": 0,
            "last_error": None, "last_error_at": None}}
        self.schedule_runs: list[dict] = []
        self.hosts: dict[str, dict] = {
            "localhost": {"address": "127.0.0.1", "ssh_user": "odin", "os": "linux", "port": 22,
                          "description": "The machine Odin runs on.", "enabled": True, "trust_mode": "legacy",
                          "fingerprints": []},
            "build_box": {"address": "10.0.0.5", "ssh_user": "deploy", "os": "linux", "port": 22,
                          "description": "8 cores, 32 GB.", "enabled": True, "trust_mode": "pinned",
                          "fingerprints": [fingerprint_of("10.0.0.5")]},
        }
        self.default_host = "localhost"
        self.allow_host_tofu = False
        self.host_candidates: dict[str, dict] = {}
        self.host_generation = 1
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
        self.disabled_tools = {"email_send"}
        self.default_timeout = 300
        self.skills = {
            "weather": {"code": WEATHER_SKILL, "status": "loaded", "description": "Look up the weather for a city.",
                        "version": "1.2.0", "author": "odin", "tags": ["web"], "executions": 4,
                        "config_schema": {"type": "object", "properties": {
                            "units": {"type": "string", "enum": ["metric", "imperial"], "default": "metric"},
                            "days": {"type": "integer", "minimum": 1, "maximum": 14, "default": 3}}},
                        "config": {"units": "metric", "days": 3}},
            "broken_sync": {"code": "def broken(:\n    pass\n", "status": "error",
                            "description": "Syntax error at line 1: invalid syntax", "version": "0.0.0",
                            "author": "", "tags": [], "executions": 0, "config_schema": {}, "config": {}},
        }
        self.mcp = {"enabled": True, "max_published_tools_per_server": 40, "max_published_tools_global": 40}
        self.mcp_servers = {
            "LMMS": {"transport": "stdio", "command": "/opt/lmms-mcp/run", "args": [], "cwd": None, "url": None,
                     "timeout_seconds": 360, "enabled": True, "tool_allowlist": None, "headers": {},
                     "env": {"LMMS_HOME": "/srv/lmms"}, "state": "connected", "last_error": "",
                     "tools": ["create_track", "add_note", "export_song"]},
            "Grafana": {"transport": "http", "command": None, "args": [], "cwd": None,
                        "url": "https://grafana.example/mcp", "timeout_seconds": 60, "enabled": False,
                        "tool_allowlist": None, "headers": {"Authorization": "Bearer secret"}, "env": {},
                        "state": "disabled", "last_error": "", "tools": ["query_dashboards"]},
        }
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
            "capabilities": ["chat", "skills.test"],
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
            "phase": "ready", "core_instance_id": self.instance_id, "version": "fixture-0", "capabilities": ["chat", "skills.test"],
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

    @staticmethod
    def schedule_item(row: dict) -> dict:
        """A schedule as the Work panel lists it."""
        if row.get("inert_reason"):
            state, actions = "inert", []
        elif row.get("paused"):
            state, actions = "paused", ["resume", "run_now"]
        else:
            state, actions = "active", ["pause", "run_now"]
        when = f"cron {row['cron']} ({row.get('timezone') or 'UTC'})" if row.get("cron") else f"once at {row.get('run_at')}"
        item = {"kind": "schedule", "id": row["id"], "title": row["description"], "state": state,
                "detail": when + (" · ran just now" if row.get("last_run") else ""), "actions": actions}
        if row.get("channel_id"):
            item["conversation_id"] = row["channel_id"]
        return item

    def m_work_list(self, params: dict, _writer) -> dict:
        self.settle_due_schedules()
        kind, cid = params.get("kind"), params.get("conversation_id")
        everything = [*self.work.values(), *(self.schedule_item(row) for row in self.schedules.values())]
        items = [dict(item, actions=list(item["actions"])) for item in everything
                 if (not kind or item["kind"] == kind) and (not cid or item.get("conversation_id") == cid)]
        return {"items": items}

    def m_work_control(self, params: dict, _writer) -> dict:
        if params.get("kind") == "schedule":
            row = self.schedules.get(str(params.get("id")))
            if row is None:
                raise CoreError("not_found", "that work is no longer listed")
            action = params.get("action")
            if action not in self.schedule_item(row)["actions"]:
                return {"disposition": "not_available"}
            if action in ("pause", "resume"):
                row["paused"] = action == "pause"
            else:
                self.run_schedule(row, manual=True)
            self.publish_work(self.schedule_item(row))
            return {"disposition": "done"}
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

    # ---------------------------------------------------------------- tools
    def tool_inventory(self) -> dict:
        tools = []
        for name, description, core in BUILTIN_TOOLS:
            enabled = name not in self.disabled_tools
            hidden = name.startswith("computer_") and not self.settings_values["computer.enabled"]
            state = "disabled" if not enabled else "unavailable" if hidden else "available"
            tools.append({"name": name, "description": description, "is_core": core, "enabled": enabled,
                          "state": state, "input_schema": {"type": "object", "properties": {}}})
        return {"global_enabled": True, "disabled_count": len(self.disabled_tools), "tools": tools}

    def m_tools_list(self, _params: dict, _writer) -> dict:
        return self.tool_inventory()

    def m_tools_set_enabled(self, params: dict, _writer) -> dict:
        name = params.get("name")
        if name not in {t[0] for t in BUILTIN_TOOLS}:
            raise CoreError("not_found", f"'{name}' is not a built-in tool")
        if not isinstance(params.get("enabled"), bool):
            raise CoreError("bad_request", "enabled must be a boolean")
        (self.disabled_tools.discard if params["enabled"] else self.disabled_tools.add)(name)
        return self.tool_inventory()

    def m_tools_timeouts_get(self, _params: dict, _writer) -> dict:
        return {"default_timeout": self.default_timeout, "overrides": dict(self.settings_values["tools.tool_timeouts"])}

    def m_tools_timeouts_set(self, params: dict, _writer) -> dict:
        overrides = params.get("overrides")
        default = params.get("default_timeout")
        if overrides is not None:
            if not isinstance(overrides, dict):
                raise CoreError("bad_request", "overrides must be a dict")
            for key, value in overrides.items():
                if type(value) is not int or value <= 0:
                    raise CoreError("bad_request", f"invalid timeout for '{key}': must be a positive integer")
        if default is not None and (type(default) is not int or default <= 0):
            raise CoreError("bad_request", "default_timeout must be a positive integer")
        if overrides is not None:
            self.settings_values["tools.tool_timeouts"] = dict(overrides)
        if default is not None:
            self.default_timeout = default
        return self.m_tools_timeouts_get({}, _writer)

    # --------------------------------------------------------------- skills
    def require_skill(self, params: dict) -> tuple[str, dict]:
        name = params.get("name")
        skill = self.skills.get(name)
        if skill is None:
            raise CoreError("not_found", "skill not found")
        return name, skill

    def skill_summary(self, name: str, skill: dict) -> dict:
        diagnostics = [{"level": "error", "message": skill["description"]}] if skill["status"] == "error" else []
        return {"name": name, "description": skill["description"], "loaded_at": "2026-10-05T09:00:00+00:00",
                "status": skill["status"], "version": skill["version"], "author": skill["author"],
                "tags": skill["tags"], "dependencies": [], "has_config": bool(skill["config_schema"]),
                "diagnostics": diagnostics, "total_executions": skill["executions"], "last_execution": None,
                "code": skill["code"], "execution_count": skill["executions"]}

    def m_skills_list(self, _params: dict, _writer) -> list:
        return [self.skill_summary(name, skill) for name, skill in self.skills.items()]

    def m_skills_get(self, params: dict, _writer) -> dict:
        name, skill = self.require_skill(params)
        if skill["status"] == "error":
            raise CoreError("not_found", "skill not found")  # as Odin: a module that failed to load has no detail
        return {**self.skill_summary(name, skill), "input_schema": {"type": "object", "properties": {}},
                "file_path": f"skills/{name}.py", "handoff_to_codex": False, "config": dict(skill["config"]),
                "metadata": {"version": skill["version"], "author": skill["author"], "homepage": "",
                             "tags": skill["tags"], "dependencies": [], "has_config": bool(skill["config_schema"]),
                             "config_schema": skill["config_schema"]}}

    def m_skills_validate(self, params: dict, _writer) -> dict:
        code = str(params.get("code") or "").strip()
        if not code:
            raise CoreError("bad_request", "code is required")
        return validate_skill(code)

    def m_skills_save(self, params: dict, _writer) -> dict:
        name, code = str(params.get("name") or "").strip(), str(params.get("code") or "").strip()
        if not name or not code:
            raise CoreError("bad_request", "name and code are required")
        exists = name in self.skills
        if params.get("create") and exists:
            raise CoreError("bad_request", f"Skill '{name}' already exists.")
        if not params.get("create") and not exists:
            raise CoreError("not_found", "skill not found")
        report = validate_skill(code)
        if not report["valid"]:
            raise CoreError("bad_request", f"Skill '{name}' failed to load: " + "; ".join(report["errors"]))
        previous = self.skills.get(name, {})
        self.skills[name] = {"code": code, "status": "loaded", "description": f"Skill {name}.",
                             "version": previous.get("version", "0.1.0"), "author": previous.get("author", ""),
                             "tags": previous.get("tags", []), "executions": previous.get("executions", 0),
                             "config_schema": previous.get("config_schema", {}), "config": previous.get("config", {})}
        return {"result": f"Skill '{name}' {'created' if not exists else 'updated'}."}

    def m_skills_test(self, params: dict, _writer) -> dict:
        name, skill = self.require_skill(params)
        if skill["status"] != "loaded":
            return {"result": f"Skill '{name}' is {skill['status']}.", "is_error": True}
        skill["executions"] += 1
        return {"result": f"{name} ran with empty input: fine.", "is_error": False}

    def m_skills_set_enabled(self, params: dict, _writer) -> dict:
        name, skill = self.require_skill(params)
        if skill["status"] == "error":
            raise CoreError("bad_request", f"Skill '{name}' failed to load; fix it before enabling it.")
        skill["status"] = "loaded" if params.get("enabled") else "disabled"
        return {"result": f"Skill '{name}' {'enabled' if params.get('enabled') else 'disabled'}."}

    def m_skills_delete(self, params: dict, _writer) -> dict:
        name, _skill = self.require_skill(params)
        del self.skills[name]
        return {"result": f"Skill '{name}' deleted."}

    def m_skills_config_get(self, params: dict, _writer) -> dict:
        _name, skill = self.require_skill(params)
        return {"config": dict(skill["config"]), "schema": skill["config_schema"]}

    def m_skills_config_set(self, params: dict, _writer) -> dict:
        _name, skill = self.require_skill(params)
        config = params.get("config")
        if not isinstance(config, dict):
            raise CoreError("bad_request", "config must be an object")
        properties = skill["config_schema"].get("properties", {})
        for key, value in config.items():
            spec = properties.get(key)
            if spec is None:
                raise CoreError("bad_request", f"{key}: not a setting of this skill")
            if "enum" in spec and value not in spec["enum"]:
                raise CoreError("bad_request", f"{key}: must be one of {', '.join(spec['enum'])}")
            if spec.get("type") == "integer" and (type(value) is not int or not spec.get("minimum", value) <= value <= spec.get("maximum", value)):
                raise CoreError("bad_request", f"{key}: must be a whole number from {spec.get('minimum')} to {spec.get('maximum')}")
        skill["config"].update(config)
        return {"config": dict(skill["config"])}

    # ------------------------------------------------------------------ mcp
    def require_mcp(self, params: dict) -> tuple[str, dict]:
        name = params.get("name")
        server = self.mcp_servers.get(name)
        if server is None:
            raise CoreError("not_found", "server not found")
        return name, server

    @staticmethod
    def mcp_allowed(server: dict, tool: str) -> bool:
        """As Odin: with an allowlist, a tool not on it is excluded; without one, every tool is offered."""
        allow = server.get("tool_allowlist")
        return allow is None or tool in allow

    def mcp_row(self, name: str, server: dict) -> dict:
        discovered = server["tools"] if server["state"] == "connected" else []
        published = [tool for tool in discovered if self.mcp_allowed(server, tool)]
        return {"name": name, "transport": server["transport"], "enabled": server["enabled"], "state": server["state"],
                "discovered_count": len(discovered),
                "published_count": len(published), "excluded_count": len(discovered) - len(published),
                "published_tools": sorted(published),
                "original_tools": list(server["tools"]), "last_error": server["last_error"], "blocked_reason": "",
                "last_refresh_age_seconds": 12 if server["state"] == "connected" else None, "stderr_tail": "",
                "generation": 1, "header_keys": sorted(server["headers"]), "env_keys": sorted(server["env"]),
                "url_display": re.sub(r"//[^/]+", "//•••", server["url"]) if server["transport"] == "http" else None,
                "instructions": ""}

    def mcp_status(self) -> dict:
        rows = [self.mcp_row(name, server) for name, server in self.mcp_servers.items()]
        return {**self.mcp, "server_count": len(rows), "enabled_server_count": sum(r["enabled"] for r in rows),
                "connected_count": sum(r["state"] == "connected" for r in rows),
                "published_tool_count": sum(r["published_count"] for r in rows), "servers": rows}

    def mcp_mutation(self, name: str) -> dict:
        server = self.mcp_servers.get(name)
        state = server["state"] if server else "unknown"
        return {"saved": True, "connected": state == "connected", "state": state,
                "last_error": server["last_error"] if server else ""}

    def m_mcp_status(self, _params: dict, _writer) -> dict:
        return self.mcp_status()

    def m_mcp_save(self, params: dict, _writer) -> dict:
        name = str(params.get("name") or "")
        if not MCP_NAME.match(name) or len(name) > 128:
            raise CoreError("bad_request", f"invalid server name {name!r}: letters, digits, underscores, no leading digit")
        exists = name in self.mcp_servers
        if params.get("create") and exists:
            raise CoreError("bad_request", f"server '{name}' already exists")
        if not params.get("create") and not exists:
            raise CoreError("not_found", "server not found")
        base = dict(self.mcp_servers.get(name) or {"transport": "stdio", "command": None, "args": [], "cwd": None,
                                                    "url": None, "timeout_seconds": 60, "enabled": True,
                                                    "tool_allowlist": None, "headers": {}, "env": {},
                                                    "last_error": "", "tools": ["echo"]})
        for key in ("transport", "command", "args", "url", "cwd", "timeout_seconds", "enabled", "tool_allowlist"):
            if key in params:
                base[key] = params[key]
        for field_name in ("headers", "env"):
            mapping = dict(base[field_name])
            for key, value in (params.get(f"{field_name}_set") or {}).items():
                if value == REDACTED:
                    raise CoreError("bad_request", f"{field_name}_set contains a redaction mask; secrets must be re-entered")
                mapping[key] = value
            for key in params.get(f"{field_name}_remove") or []:
                mapping.pop(key, None)
            base[field_name] = mapping
        if base["transport"] not in ("stdio", "http"):
            raise CoreError("bad_request", f"{name}: transport must be 'stdio' or 'http'")
        if base["transport"] == "stdio" and not base.get("command"):
            raise CoreError("bad_request", f"{name}: stdio transport requires 'command'")
        if base["transport"] == "http" and not re.match(r"^https?://", str(base.get("url") or "")):
            raise CoreError("bad_request", f"{name}: http transport requires an http(s) 'url'")
        base["state"] = "connected" if base["enabled"] and self.mcp["enabled"] else "disabled"
        self.mcp_servers[name] = base
        return self.mcp_mutation(name)

    def m_mcp_set_enabled(self, params: dict, _writer) -> dict:
        name, server = self.require_mcp(params)
        server["enabled"] = bool(params.get("enabled"))
        server["state"] = "connected" if server["enabled"] and self.mcp["enabled"] else "disabled"
        return self.mcp_status()  # Odin's per-server switch answers the whole status

    def m_mcp_delete(self, params: dict, _writer) -> dict:
        name, _server = self.require_mcp(params)
        del self.mcp_servers[name]
        return {"saved": True, "connected": False, "state": "removed", "last_error": ""}

    def m_mcp_reconnect(self, params: dict, _writer) -> dict:
        name, server = self.require_mcp(params)
        if server["enabled"] and self.mcp["enabled"]:
            server["state"], server["last_error"] = "connected", ""
        return self.mcp_mutation(name)

    def m_mcp_refresh_tools(self, params: dict, _writer) -> dict:
        name, _server = self.require_mcp(params)
        return self.mcp_mutation(name)

    def m_mcp_tools(self, params: dict, _writer) -> dict:
        name, server = self.require_mcp(params)
        connected = server["state"] == "connected"
        return {"server": name, "tools": [
            {"original_name": tool, "published_name": f"mcp_{name}_{tool}",
             "published": connected and self.mcp_allowed(server, tool), "excluded": not self.mcp_allowed(server, tool),
             "exclusion_reason": "" if self.mcp_allowed(server, tool) else "not in the tool allowlist",
             "description": f"{tool.replace('_', ' ').capitalize()}."}
            for tool in server["tools"]]}

    def m_mcp_set_global_enabled(self, params: dict, _writer) -> dict:
        self.mcp["enabled"] = bool(params.get("enabled"))
        for server in self.mcp_servers.values():
            server["state"] = "connected" if server["enabled"] and self.mcp["enabled"] else "disabled"
        status = self.mcp_status()
        return {"saved": True, "enabled": status["enabled"], "connected_count": status["connected_count"]}  # Odin's answer

    def m_mcp_set_limits(self, params: dict, _writer) -> dict:
        for key in ("max_published_tools_per_server", "max_published_tools_global"):
            if key in params:
                if type(params[key]) is not int or params[key] < 0:
                    raise CoreError("bad_request", "publication limits must be integers")
                self.mcp[key] = params[key]
        return {"saved": True, **self.mcp_status()}

    # ---------------------------------------------------------------- hosts
    def host_row(self, alias: str, host: dict) -> dict:
        local = host["address"] in LOCAL_ADDRESSES  # as Odin's registry: by address, whatever its trust mode
        return {"alias": alias, "host_id": f"h_{hashlib.sha256(alias.encode()).hexdigest()[:8]}",
                "address": host["address"], "ssh_user": host["ssh_user"], "os": host["os"], "port": host["port"],
                "description": host["description"], "enabled": host["enabled"], "active": host["enabled"],
                "targetable": host["enabled"], "trust_mode": host["trust_mode"],
                "trust_state": "local" if local else "trusted",
                "last_test": {"ok": True, "at": now(), "detail": "connected"}, "diagnostic": None,
                "draining": False, "generation": self.host_generation}

    def m_hosts_list(self, _params: dict, _writer) -> dict:
        return {"hosts": [self.host_row(alias, host) for alias, host in self.hosts.items()],
                "default_host": self.default_host, "generation": self.host_generation,
                "tofu_enabled": self.allow_host_tofu}

    def m_hosts_settings(self, params: dict, _writer) -> dict:
        if set(params) - {"default_host", "allow_host_tofu"}:
            raise CoreError("bad_request", "only default_host and allow_host_tofu may be changed")
        default = params.get("default_host", self.default_host)
        if not isinstance(default, str):
            raise CoreError("bad_request", "default_host must be a string")
        default = default.strip()
        if default and default not in self.hosts:  # empty: every command names its host
            raise CoreError("bad_request", "default_host must name a configured host")
        tofu = params.get("allow_host_tofu", self.allow_host_tofu)
        if not isinstance(tofu, bool):
            raise CoreError("bad_request", "allow_host_tofu must be boolean")
        old = (self.default_host, self.allow_host_tofu)
        self.default_host, self.allow_host_tofu = default, tofu
        return {"result": "saved", "old_default_host": old[0], "new_default_host": default,
                "old_allow_host_tofu": old[1], "new_allow_host_tofu": tofu}

    def m_hosts_public_key(self, _params: dict, _writer) -> dict:
        key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFixtureKeyForTheDevelopmentCore odin@desktop"
        return {"public_key": key, "fingerprint": fingerprint_of(key),
                "authorized_keys_command": f"mkdir -p ~/.ssh && echo '{key}' >> ~/.ssh/authorized_keys",
                "permissions": "~/.ssh permissions must be 0700 and authorized_keys 0600",
                "effective_key_path": "keys/id_ed25519", "desired_key_path": "keys/id_ed25519",
                "restart_pending": False}

    def m_hosts_prepare(self, params: dict, _writer) -> dict:
        alias = str(params.get("alias") or "")
        if not HOST_ALIAS.fullmatch(alias):
            raise CoreError("bad_request", "alias must start with a letter and use letters, digits, . _ or -")
        address = str(params.get("address") or "").strip()
        if not address or " " in address:
            raise CoreError("bad_request", "address is not a plain hostname or IP address")
        if params.get("os", "linux") not in ("linux", "macos"):
            raise CoreError("bad_request", "os must be 'linux' or 'macos'")
        port = params.get("port", 22)
        if type(port) is not int or not 1 <= port <= 65535:
            raise CoreError("bad_request", "port must be an integer between 1 and 65535")
        local = address in LOCAL_ADDRESSES
        if local and params.get("confirm_local") is not True:
            raise CoreError("bad_request", "local targets execute inside Odin and require confirm_local=true")
        mode = params.get("trust_mode")
        scanned = [] if local else [fingerprint_of(address)]
        confirmed = False
        if local:
            mode = "legacy"  # as Odin: this computer has no host key to check, whatever was asked for
        elif mode in ("pinned", "ca"):
            expected = params.get("expected_fingerprints") or []
            if not expected:
                raise CoreError("bad_request", "expected_fingerprints is required")
            if any(not str(e).startswith("SHA256:") for e in expected):
                raise CoreError("bad_request", "expected fingerprint must use OpenSSH SHA256: form")
            if not set(expected) & set(scanned):
                raise CoreError("bad_request", "scanned host key does not match the expected fingerprint")
        elif mode == "tofu":
            if not self.allow_host_tofu:
                raise CoreError("bad_request", "TOFU is disabled by configuration")
            offered = params.get("candidate_fingerprints")
            if offered:
                if params.get("confirm_tofu") is not True or list(offered) != scanned:
                    raise CoreError("bad_request", "TOFU requires confirm_tofu=true bound to the exact candidate_fingerprints")
                confirmed = True
        else:
            raise CoreError("bad_request", "trust_mode must be legacy, pinned, ca, or tofu")
        token = str(uuid.uuid4())
        self.host_candidates[token] = {"alias": alias, "address": address, "ssh_user": str(params.get("ssh_user") or ""),
                                       "os": params.get("os", "linux"), "port": port,
                                       "description": str(params.get("description") or ""), "trust_mode": mode,
                                       "fingerprints": scanned, "tested": False, "tofu_confirmed": confirmed}
        return {"candidate_token": token, "alias": alias, "host_id": f"h_{hashlib.sha256(alias.encode()).hexdigest()[:8]}",
                "fingerprints": scanned, "trust_mode": mode, "tested": False}

    def require_candidate(self, params: dict) -> dict:
        candidate = self.host_candidates.get(str(params.get("token")))
        if candidate is None:
            raise CoreError("not_found", "unknown or expired candidate")
        return candidate

    def m_hosts_test(self, params: dict, _writer) -> dict:
        candidate = self.require_candidate(params)
        ok = "unreachable" not in candidate["address"]
        candidate["tested"] = ok
        result = {"candidate_token": params["token"], "tested": ok,
                  "last_test": {"ok": ok, "at": now(), "detail": "connected" if ok else "connection refused"}}
        if not ok:
            result["error"] = "connection refused"
        return result

    def m_hosts_commit(self, params: dict, _writer) -> dict:
        candidate = self.require_candidate(params)
        if not candidate["tested"]:
            raise CoreError("bad_request", "candidate must pass the connection test before activation")
        if candidate["trust_mode"] == "tofu" and not candidate["tofu_confirmed"]:
            raise CoreError("bad_request", "TOFU candidate requires a second confirmation bound to its exact fingerprints")
        alias = candidate["alias"]
        self.hosts[alias] = {key: candidate[key] for key in ("address", "ssh_user", "os", "port", "description", "trust_mode", "fingerprints")}
        self.hosts[alias]["enabled"] = True
        del self.host_candidates[params["token"]]
        self.host_generation += 1
        return {"result": "saved", "alias": alias, "host_id": self.host_row(alias, self.hosts[alias])["host_id"]}

    def require_host(self, params: dict) -> tuple[str, dict]:
        alias = params.get("alias")
        host = self.hosts.get(alias)
        if host is None:
            raise CoreError("not_found", "host not found")
        return alias, host

    def host_references(self, alias: str) -> list[dict]:
        refs = []
        if self.default_host == alias:
            refs.append({"kind": "default_host", "location": "tools.default_host"})
        for row in self.schedules.values():
            if (row.get("tool_input") or {}).get("host") == alias:
                refs.append({"kind": "schedule", "location": f"schedule {row['id']}: {row['description']}"})
        return refs

    def m_hosts_set_enabled(self, params: dict, _writer) -> dict:
        alias, host = self.require_host(params)
        host["enabled"] = bool(params.get("enabled"))
        self.host_generation += 1
        return {"result": "saved", "alias": alias, "host_id": self.host_row(alias, host)["host_id"]}

    def m_hosts_references(self, params: dict, _writer) -> dict:
        alias, _host = self.require_host(params)
        return {"alias": alias, "references": self.host_references(alias)}

    def m_hosts_delete(self, params: dict, _writer) -> dict:
        alias, host = self.require_host(params)
        refs = self.host_references(alias)
        if refs:
            raise CoreError("bad_request", "host deletion is blocked by configured references: "
                            + "; ".join(r["location"] for r in refs))
        row = self.host_row(alias, host)
        del self.hosts[alias]
        self.host_generation += 1
        return {"result": "saved", "alias": alias, "host_id": row["host_id"]}

    def m_hosts_force_revoke(self, params: dict, _writer) -> dict:
        _alias, _host = self.require_host(params)
        revoked = [self.host_generation]
        self.host_generation += 1
        return {"result": "revoked", "leases_interrupted": 0, "processes": {"attempted": 0, "killed": 0, "unknown": 0},
                "process_outcome": "none", "revoked_generations": revoked, "registry_generation": self.host_generation}

    # ------------------------------------------------------------ schedules
    ALLOWED_CHECK_TOOLS = ("run_command", "run_command_multi", "run_script")
    REPORT_FORMATS = ("paginated_embed_v1",)
    WEBHOOK_METHODS = ("POST", "PUT", "PATCH", "GET", "DELETE")

    def settle_due_schedules(self) -> None:
        """What time passing does: a one-time run whose time came fires once and goes, or goes inert if paused."""
        at = datetime.now(timezone.utc)
        for row in list(self.schedules.values()):
            if not row.get("one_time") or row.get("inert_reason"):
                continue
            if datetime.fromisoformat(row["run_at"]) > at:
                continue
            if row.get("paused"):
                row["inert_reason"] = "Its one-time run time passed while it was paused. Set a new time to re-arm it."
                row["next_run"] = None
            else:
                self.run_schedule(row)
                del self.schedules[row["id"]]
        for row in self.schedules.values():
            if row.get("cron") and row.get("next_run") and datetime.fromisoformat(row["next_run"]) <= at:
                row["next_run"] = next_cron_runs(row["cron"], 1)[0]

    def run_schedule(self, row: dict, manual: bool = False) -> dict:
        started = datetime.now(timezone.utc)
        url = str((row.get("webhook_config") or {}).get("url") or "")
        error = "HTTP 500 from the webhook" if row["action"] == "webhook" and "/fail" in url else None
        row["last_run"] = started.isoformat()
        if error:
            row["consecutive_failures"] = row.get("consecutive_failures", 0) + 1
            row.update(last_error=error, last_error_at=started.isoformat())
        else:
            row["consecutive_failures"] = 0
        entry = {"timestamp": started.isoformat(), "schedule_id": row["id"], "description": row["description"],
                 "action": row["action"], "status": "failure" if error else "success", "duration_ms": 40}
        if error:
            entry["error"] = error
        self.schedule_runs.insert(0, entry)
        return entry

    def require_schedule(self, params: dict) -> dict:
        self.settle_due_schedules()
        row = self.schedules.get(str(params.get("id")))
        if row is None:
            raise CoreError("not_found", f"Schedule '{params.get('id')}' not found")
        return row

    @staticmethod
    def instant(value: object) -> str:
        """run_at is an explicit instant: a time with its UTC offset."""
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            raise CoreError("bad_request", "run_at must be an ISO 8601 time") from None
        if parsed.tzinfo is None:
            raise CoreError("bad_request", "run_at needs its UTC offset, such as 2026-10-05T09:00:00-04:00")
        if parsed <= datetime.now(timezone.utc):
            raise CoreError("bad_request", "run_at must be in the future")
        return parsed.astimezone(timezone.utc).isoformat()

    def check_action_fields(self, action: str, fields: dict) -> None:
        if "retry_backoff_seconds" in fields and fields["retry_backoff_seconds"] < 1:
            raise CoreError("bad_request", "retry_backoff_seconds must be >= 1")
        for key, owner in (("message", "reminder"), ("tool_name", "check"), ("tool_input", "check"),
                           ("report_format", "check"), ("steps", "workflow"), ("webhook_config", "webhook")):
            if fields.get(key) not in (None, "", {}) and action != owner:
                raise CoreError("bad_request", f"{key} is only valid for '{owner}' actions")
        if fields.get("report_format") and fields["report_format"] not in self.REPORT_FORMATS:
            raise CoreError("bad_request", f"Unsupported scheduled report format: {fields['report_format']}")
        if "tool_name" in fields and action == "check" and fields["tool_name"] not in self.ALLOWED_CHECK_TOOLS:
            raise CoreError("bad_request", f"Tool '{fields['tool_name']}' is not allowed for scheduled checks. "
                                           f"Allowed: {', '.join(sorted(self.ALLOWED_CHECK_TOOLS))}")
        if "steps" in fields and action == "workflow":
            steps = fields["steps"]
            if not isinstance(steps, list) or not steps:
                raise CoreError("bad_request", "'steps' (list) is required for 'workflow' actions")
            for i, step in enumerate(steps):
                if not isinstance(step, dict) or not step.get("tool_name"):
                    raise CoreError("bad_request", f"Step {i}: must be a dict with 'tool_name'")
                if step.get("on_failure", "abort") not in ("abort", "continue"):
                    raise CoreError("bad_request", f"Step {i}: on_failure is abort or continue")
        if "webhook_config" in fields and action == "webhook":
            config = fields["webhook_config"]
            if not isinstance(config, dict):
                raise CoreError("bad_request", "'webhook_config' (dict) is required for 'webhook' actions")
            if not str(config.get("url") or "").startswith(("http://", "https://")):
                raise CoreError("bad_request", "webhook_config.url must be an http or https URL")
            if config.get("method", "POST") not in self.WEBHOOK_METHODS:
                raise CoreError("bad_request", f"webhook_config.method must be one of {', '.join(self.WEBHOOK_METHODS)}")

    def apply_timing(self, row: dict, fields: dict) -> None:
        """Changing the timing replaces the old timing, as in Odin."""
        if fields.get("cron") and fields.get("run_at"):
            raise CoreError("bad_request", "Choose either cron or run_at, not both")
        if fields.get("cron"):
            try:
                next_run = next_cron_runs(fields["cron"], 1)[0]
            except (ValueError, IndexError) as exc:
                raise CoreError("bad_request", f"Invalid cron expression: {exc}") from None
            row.update(cron=fields["cron"], run_at=None, one_time=False, next_run=next_run, inert_reason=None)
            row["timezone"] = fields.get("cron_timezone") or row.get("timezone") or "UTC"
        elif fields.get("run_at"):
            at = self.instant(fields["run_at"])
            row.update(run_at=at, next_run=at, cron=None, one_time=True, inert_reason=None)
            row.pop("timezone", None)
        elif fields.get("cron_timezone") and row.get("cron"):
            row["timezone"] = fields["cron_timezone"]

    FIELDS = ("description", "channel_id", "cron", "run_at", "cron_timezone", "message", "tool_name", "tool_input",
              "report_format", "steps", "webhook_config", "max_retries", "retry_backoff_seconds")

    def m_schedules_list(self, _params: dict, _writer) -> list:
        self.settle_due_schedules()
        return [dict(row) for row in self.schedules.values()]

    def m_schedules_save(self, params: dict, _writer) -> dict:
        fields = {key: params[key] for key in self.FIELDS if key in params}
        if "description" in fields:
            fields["description"] = str(fields["description"]).strip()
            if not fields["description"]:
                raise CoreError("bad_request", "description is required")
        if params.get("id"):
            if "action" in params:
                raise CoreError("bad_request", "A schedule's action is set when it is created")
            row = self.require_schedule(params)
            self.check_action_fields(row["action"], fields)
            changed = dict(row)
            self.apply_timing(changed, fields)
            for key in ("description", "channel_id", "message", "tool_name", "tool_input", "report_format", "steps",
                        "webhook_config", "max_retries", "retry_backoff_seconds"):
                if key in fields:
                    changed[key] = fields[key]
            if fields.get("report_format") == "":
                changed.pop("report_format", None)
            if changed["action"] != "webhook" and not changed.get("channel_id"):
                raise CoreError("bad_request", "channel_id is required")
            if "paused" in params:
                changed["paused"] = bool(params["paused"])
            self.schedules[row["id"]] = changed
            self.publish_work(self.schedule_item(changed))
            return dict(changed)
        action = params.get("action", "reminder")
        if action not in ("reminder", "check", "workflow", "webhook"):
            raise CoreError("bad_request", f"Unknown action: {action}")
        if not fields.get("description") or (action != "webhook" and not str(fields.get("channel_id") or "").strip()):
            raise CoreError("bad_request", "description is required" if action == "webhook"
                            else "description and channel_id are required")
        if not fields.get("cron") and not fields.get("run_at"):
            raise CoreError("bad_request", "Either cron or run_at is required")
        if action == "check" and not fields.get("tool_name"):
            raise CoreError("bad_request", "tool_name is required for 'check' actions")
        if action == "workflow" and "steps" not in fields:
            raise CoreError("bad_request", "'steps' (list) is required for 'workflow' actions")
        if action == "webhook" and "webhook_config" not in fields:
            raise CoreError("bad_request", "'webhook_config' (dict) is required for 'webhook' actions")
        self.check_action_fields(action, fields)
        row = {"id": uuid.uuid4().hex[:8], "description": fields["description"], "action": action,
               "channel_id": str(fields.get("channel_id") or ""), "created_at": now(), "last_run": None,
               "paused": False}
        self.apply_timing(row, fields)
        if action == "reminder":
            row["message"] = fields.get("message") or fields["description"]
        elif action == "check":
            row.update(tool_name=fields["tool_name"], tool_input=fields.get("tool_input") or {})
            if fields.get("report_format"):
                row["report_format"] = fields["report_format"]
        elif action == "workflow":
            row["steps"] = fields["steps"]
        else:
            row["webhook_config"] = fields["webhook_config"]
        row.update(max_retries=fields.get("max_retries", 0), retry_backoff_seconds=fields.get("retry_backoff_seconds", 60),
                   consecutive_failures=0, retry_count=0, last_error=None, last_error_at=None)
        self.schedules[row["id"]] = row
        self.publish_work(self.schedule_item(row))
        return dict(row)

    def m_schedules_delete(self, params: dict, _writer) -> dict:
        row = self.require_schedule(params)
        del self.schedules[row["id"]]
        self.emit("work.updated", "work", row["id"], {"kind": "schedule", "id": row["id"], "state": "deleted"})
        return {"status": "deleted"}

    def m_schedules_run(self, params: dict, _writer) -> dict:
        row = self.require_schedule(params)
        if row.get("inert_reason"):
            raise CoreError("bad_request", row["inert_reason"])
        entry = self.run_schedule(row, manual=True)
        self.publish_work(self.schedule_item(row))
        result = {"status": entry["status"], "schedule_id": row["id"]}
        if entry.get("error"):
            result["error"] = entry["error"]
        if row.get("paused"):
            result["warning"] = "schedule is paused — this was a manual override"
        return result

    def m_schedules_reset_failures(self, params: dict, _writer) -> dict:
        row = self.require_schedule(params)
        row.update(consecutive_failures=0, retry_count=0, last_error=None, last_error_at=None)
        row.pop("retry_at", None)
        return dict(row)

    def m_schedules_history(self, params: dict, _writer) -> list:
        entries = [e for e in self.schedule_runs if not params.get("id") or e["schedule_id"] == params["id"]]
        return entries[: int(params.get("limit") or 50)]

    def m_schedules_validate_cron(self, params: dict, _writer) -> dict:
        try:
            return {"valid": True, "next_runs": next_cron_runs(str(params.get("expression") or ""), 5)}
        except ValueError as exc:
            raise CoreError("bad_request", f"Invalid cron expression: {exc}") from None

    # ---------------------------------------------------------------- personality
    BUILTIN_PRESETS = {
        "odin": {"name": "Odin, the All-Father", "identity": "A wise old god, patient with mortal machines.",
                 "voice": "Dry wit, short sentences, never cruel."},
        "professional": {"name": "Mimir", "identity": "A precise, reliable operations assistant.",
                         "voice": "Concise and professional."},
        "friendly": {"name": "Bragi", "identity": "A helpful, approachable assistant.", "voice": "Warm and conversational."},
    }

    def m_personality_get(self, _params: dict, _writer) -> dict:
        return {**self.personality, "presets": {**self.BUILTIN_PRESETS, **self.user_presets},
                "builtin_presets": list(self.BUILTIN_PRESETS), "user_presets": list(self.user_presets)}

    def m_personality_set(self, params: dict, _writer) -> dict:
        preset = str(params.get("preset") or "odin")
        if preset != "custom" and preset not in self.BUILTIN_PRESETS and preset not in self.user_presets:
            raise CoreError("bad_request", f"unknown preset '{preset}'")
        self.personality = {"preset": preset, "custom_name": str(params.get("custom_name", "")),
                            "custom_identity": str(params.get("custom_identity", "")),
                            "custom_voice": str(params.get("custom_voice", ""))}
        return {"status": "updated", "preset": preset}

    def m_personality_presets_save(self, params: dict, _writer) -> dict:
        name = str(params.get("name") or "").strip().lower().replace(" ", "_")
        if not name:
            raise CoreError("bad_request", "name is required")
        if not re.fullmatch(r"[a-z0-9_-]+", name):
            raise CoreError("bad_request", "preset name must contain only lowercase letters, numbers, hyphens, and underscores")
        if name in self.BUILTIN_PRESETS:
            raise CoreError("bad_request", f"cannot overwrite built-in preset '{name}'")
        identity, voice = str(params.get("identity", "")), str(params.get("voice", ""))
        if not identity and not voice:
            raise CoreError("bad_request", "identity or voice is required")
        self.user_presets[name] = {"name": str(params.get("display_name") or name), "identity": identity, "voice": voice}
        return {"status": "saved", "name": name}

    def m_personality_presets_delete(self, params: dict, _writer) -> dict:
        name = str(params.get("name") or "")
        if name in self.BUILTIN_PRESETS:
            raise CoreError("bad_request", f"cannot delete built-in preset '{name}'")
        if name not in self.user_presets:
            raise CoreError("not_found", "preset not found")
        del self.user_presets[name]
        if self.personality["preset"] == name:
            self.personality["preset"] = "odin"
        return {"status": "deleted", "name": name}

    # ---------------------------------------------------------------- memory and lists
    def m_memory_list(self, _params: dict, _writer) -> dict:
        return {scope: {"keys": list(entries), "count": len(entries)} for scope, entries in self.memory.items()}

    def m_memory_get(self, params: dict, _writer) -> dict:
        scope = str(params.get("scope"))
        if scope not in self.memory:
            raise CoreError("not_found", "scope not found")
        key = params.get("key")
        if key is None:
            return {"scope": scope, "entries": dict(self.memory[scope])}
        if key not in self.memory[scope]:
            raise CoreError("not_found", "key not found")
        return {"scope": scope, "key": key, "value": self.memory[scope][key]}

    def m_memory_set(self, params: dict, _writer) -> dict:
        if params.get("value") is None:
            raise CoreError("bad_request", "value is required")
        scope, key = str(params.get("scope")), str(params.get("key"))
        self.memory.setdefault(scope, {})[key] = params["value"]
        return {"status": "saved", "scope": scope, "key": key}

    def m_memory_delete(self, params: dict, _writer) -> dict:
        scope, key = str(params.get("scope")), str(params.get("key"))
        if key not in self.memory.get(scope, {}):
            raise CoreError("not_found", "key not found")
        del self.memory[scope][key]
        return {"status": "deleted", "scope": scope, "key": key}

    def m_memory_bulk_delete(self, params: dict, _writer) -> dict:
        entries = params.get("entries")
        if not isinstance(entries, list) or not entries:
            raise CoreError("bad_request", "entries must be a non-empty list of {scope, key}")
        deleted = 0
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("scope") or not entry.get("key"):
                raise CoreError("bad_request", "each entry must contain a scope and key")
        for entry in entries:
            if self.memory.get(entry["scope"], {}).pop(entry["key"], None) is not None:
                deleted += 1
        return {"status": "deleted", "count": deleted}

    def m_lists_list(self, _params: dict, _writer) -> dict:
        return {"items": [{"name": name, "count": len(data["items"]), "updated_at": data["updated_at"]}
                          for name, data in self.lists.items()]}

    def m_lists_get(self, params: dict, _writer) -> dict:
        name = str(params.get("name"))
        if name not in self.lists:
            raise CoreError("not_found", "list not found")
        return {"name": name, "items": list(self.lists[name]["items"])}

    def m_lists_delete(self, params: dict, _writer) -> dict:
        name = str(params.get("name"))
        if self.lists.pop(name, None) is None:
            raise CoreError("not_found", "list not found")
        return {"status": "deleted", "name": name}

    # ---------------------------------------------------------------- knowledge
    @staticmethod
    def chunked(content: str) -> list[str]:
        return [content[i:i + 400] for i in range(0, len(content), 400)] or [content]

    def knowledge_version(self, source: str, action: str, content: str, summary: str) -> None:
        versions = self.knowledge_versions.setdefault(source, [])
        versions.append({"id": sum(len(v) for v in self.knowledge_versions.values()) + 1, "version": len(versions) + 1,
                         "content_hash": hashlib.sha256(content.encode()).hexdigest()[:16],
                         "chunk_count": len(self.chunked(content)), "uploader": "owner", "action": action,
                         "created_at": now(), "diff_summary": summary, "content": content})

    def store_knowledge(self, source: str, content: str, action: str) -> dict:
        digest = hashlib.sha256(content.encode()).hexdigest()[:16]
        current = self.knowledge.get(source)
        if current and current["content_hash"] == digest:
            return {"source": source, "chunks": len(current["chunks"]), "status": "already stored, unchanged",
                    "outcome": "unchanged"}
        for other, data in self.knowledge.items():
            if other == source:
                continue
            if data["content_hash"] == digest:
                return {"source": source, "status": "identical content already stored elsewhere; not ingested",
                        "outcome": "duplicate", "duplicate_of": other,
                        "message": f"Identical content is already stored as '{other}'; no new source was created."}
            if data["content"][:200] == content[:200]:
                return {"source": source, "status": "near-duplicate of existing knowledge; not stored",
                        "outcome": "conflict", "duplicate_of": other,
                        "message": f"Near-duplicate content conflicts with '{other}'; the new content was not stored."}
        chunks = self.chunked(content)
        self.knowledge[source] = {"content": content, "content_hash": digest, "chunks": chunks, "ingested_at": now()}
        self.knowledge_version(source, action, content, f"{len(chunks)} chunks")
        return {"source": source, "chunks": len(chunks), "status": "stored", "outcome": "created"}

    def m_knowledge_list(self, _params: dict, _writer) -> list:
        return [{"source": source, "chunks": len(data["chunks"]), "uploader": "owner", "ingested_at": data["ingested_at"],
                 "content_hash": data["content_hash"],
                 "preview": data["content"][:200] + ("..." if len(data["content"]) > 200 else "")}
                for source, data in self.knowledge.items()]

    def m_knowledge_search(self, params: dict, _writer) -> list:
        words = str(params.get("q") or "").lower().split()
        if not words:
            raise CoreError("bad_request", "q parameter required")
        hits = []
        for source, data in self.knowledge.items():
            for index, chunk in enumerate(data["chunks"]):
                found = sum(word in chunk.lower() for word in words)
                if found:
                    hits.append({"chunk_id": f"{source}:{index}", "content": chunk, "source": source,
                                 "score": round(found / len(words), 3), "chunk_index": index})
        hits.sort(key=lambda h: -h["score"])
        return hits[: int(params.get("limit") or 10)]

    def m_knowledge_ingest(self, params: dict, _writer) -> dict:
        source, content = str(params.get("source") or "").strip(), str(params.get("content") or "").strip()
        if not source or not content:
            raise CoreError("bad_request", "source and content are required")
        return self.store_knowledge(source, content, "ingest")

    def require_source(self, params: dict) -> tuple[str, dict]:
        source = str(params.get("source"))
        if source not in self.knowledge:
            raise CoreError("not_found", "source not found")
        return source, self.knowledge[source]

    def m_knowledge_reingest(self, params: dict, _writer) -> dict:
        source, data = self.require_source(params)
        return {"source": source, "chunks": len(data["chunks"]), "status": "already stored, unchanged", "outcome": "unchanged"}

    def m_knowledge_delete(self, params: dict, _writer) -> dict:
        source, data = self.require_source(params)
        del self.knowledge[source]
        return {"status": "deleted", "chunks_removed": len(data["chunks"])}

    def m_knowledge_versions(self, params: dict, _writer) -> list:
        source = str(params.get("source"))
        return [{k: v for k, v in version.items() if k != "content"} for version in self.knowledge_versions.get(source, [])]

    def m_knowledge_restore(self, params: dict, _writer) -> dict:
        source, version = str(params.get("source")), params.get("version")
        found = next((v for v in self.knowledge_versions.get(source, []) if v["version"] == version), None)
        if found is None:
            raise CoreError("not_found", "version not found")
        chunks = self.chunked(found["content"])
        self.knowledge[source] = {"content": found["content"], "content_hash": found["content_hash"], "chunks": chunks,
                                  "ingested_at": now()}
        self.knowledge_version(source, "restore", found["content"], f"restored version {version}")
        return {"status": "restored", "source": source, "version": version, "chunks": len(chunks)}

    # ---------------------------------------------------------------- records
    def m_audit_query(self, params: dict, _writer) -> list:
        entries = list(reversed(self.audit))
        if params.get("tool"):
            entries = [e for e in entries if e["tool_name"] == params["tool"]]
        if params.get("host"):
            entries = [e for e in entries if e.get("host") == params["host"]]
        if params.get("q"):
            needle = str(params["q"]).lower()
            entries = [e for e in entries if needle in json.dumps(e).lower()]
        if params.get("error_only"):
            entries = [e for e in entries if e.get("error")]
        return entries[: int(params.get("limit") or 100)]

    def m_audit_verify(self, _params: dict, _writer) -> dict:
        return {"valid": True, "total": len(self.audit), "verified": len(self.audit), "first_bad": None,
                "status": "verified", "segments": 1}

    def m_health_get(self, _params: dict, _writer) -> dict:
        mcp = self.m_mcp_status({}, None)
        components = [
            {"name": "core", "healthy": True, "status": "healthy", "detail": "Running."},
            {"name": "codex", "healthy": True, "status": "healthy", "detail": "2 accounts, Primary in use."},
            {"name": "knowledge", "healthy": True, "status": "healthy", "detail": f"{len(self.knowledge)} sources."},
            {"name": "mcp", "healthy": mcp["connected_count"] == mcp["server_count"],
             "status": "healthy" if mcp["connected_count"] == mcp["server_count"] else "degraded",
             "detail": f"{mcp['connected_count']} of {mcp['server_count']} servers connected."},
            {"name": "computer", "healthy": False, "status": "unconfigured", "detail": "Computer use is off."},
        ]
        count = lambda status: sum(1 for c in components if c["status"] == status)  # noqa: E731
        overall = "healthy" if all(c["status"] in ("healthy", "unconfigured") for c in components) else "degraded"
        return {"overall": overall, "components": components, "healthy_count": count("healthy"),
                "degraded_count": count("degraded"), "down_count": count("down"),
                "unconfigured_count": count("unconfigured"), "total": len(components), "checked_at": now()}

    def m_logs_search(self, params: dict, _writer) -> dict:
        level = params.get("level") or "all"
        if level not in ("error", "info", "all"):
            raise CoreError("bad_request", "level must be 'error', 'info', or 'all'")
        entries = list(reversed(self.logs))
        if level == "error":
            entries = [e for e in entries if e["level"] == "ERROR"]
        elif level == "info":
            entries = [e for e in entries if e["level"] == "INFO"]
        if params.get("tool"):
            entries = [e for e in entries if e.get("tool") == params["tool"]]
        if params.get("q"):
            entries = [e for e in entries if str(params["q"]).lower() in e["message"].lower()]
        entries = entries[: int(params.get("limit") or 100)]
        return {"entries": entries, "count": len(entries)}

    def m_turn_state_list(self, params: dict, _writer) -> dict:
        turns = []
        for req in self.requests.values():
            unknown = sum(o.get("unknown_effects", 0) for o in self.unresolved.get(req["conversation_id"], [])
                          if o.get("request_id") == req["id"])
            if req["state"] not in ("interrupted", "suspended", "running") and not unknown:
                continue
            turns.append({"conversation_id": req["conversation_id"], "request_id": req["id"],
                          "turn_generation": req["generation"], "status": req["state"].upper(),
                          "created_at": req.get("started_at") or now(), "last_progress_at": req.get("started_at"),
                          "suspended_at": None, "has_checkpoint": req["state"] in ("interrupted", "suspended"),
                          "manual_resolution_operations": 0, "outcome_unknown_operations": unknown,
                          "attention": req["state"] == "suspended"})
        turns = turns[: int(params.get("limit") or 50)]
        return {"schema_version": 1, "availability": "available", "observed_at": now(),
                "data": {"total_matching": len(turns), "attention_count": sum(t["attention"] for t in turns), "turns": turns}}

    def computer_status(self) -> dict:
        enabled = bool(self.settings_values.get("computer.enabled"))
        return {"available": True, "enabled": enabled, "configured_enabled": enabled, "runtime_enabled": enabled,
                **{key: value for key, value in self.computer.items() if key != "recovery"},
                "recovery": dict(self.computer["recovery"])}

    def m_computer_status(self, _params: dict, _writer) -> dict:
        return self.computer_status()

    def m_computer_reconcile(self, params: dict, _writer) -> dict:
        """Odin's operator_reconcile: an acknowledgment frees admission; it is never a claim of clean release."""
        session_id = params.get("session_id")
        if params.get("acknowledgment") != f"ACKNOWLEDGE UNVERIFIED CLEANUP {session_id}":
            raise CoreError("bad_request", "explicit_acknowledgment_required")
        if session_id != self.computer["session_id"]:
            raise CoreError("not_found", "not_found")
        if params.get("generation") != self.computer["session_generation"]:
            raise CoreError("stale_binding", "stale_generation", "stale_binding")
        if self.computer["state"] != "quarantined":
            raise CoreError("bad_request", "recovery_unavailable")
        if self.computer_inspection == "attestation_eligible":
            self.computer["state"] = "closed"
            self.computer["recovery"] = {"status": "operator_acknowledged_unverified",
                                         "reason": "operator_verified_external_cleanup", "complete": False}
        else:
            self.computer["recovery"] = {"status": "unknown", "reason": self.computer_inspection, "complete": False}
        return self.computer_status()

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
        if before is not None:
            index = next((i for i, m in enumerate(items) if m["id"] == before), None)
            if index is None:
                raise CoreError("not_found", "message not found")
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
        record = self.tool_records[inv]
        self.audit.append({"timestamp": now(), "type": "tool", "tool_name": record["tool"], "user_id": "owner",
                           "tool_input": record["arguments"], "approved": True,
                           "result_summary": record["previews"][0]["text"][:200], "execution_time_ms": 3, "error": None,
                           "host": record["target"]})
        self.logs.append({"timestamp": now(), "level": "INFO", "message": f"Tool {record['tool']} ran.", "tool": record["tool"]})
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
    "tools.list": Core.m_tools_list,
    "tools.set_enabled": Core.m_tools_set_enabled,
    "tools.timeouts.get": Core.m_tools_timeouts_get,
    "tools.timeouts.set": Core.m_tools_timeouts_set,
    "skills.list": Core.m_skills_list,
    "skills.get": Core.m_skills_get,
    "skills.validate": Core.m_skills_validate,
    "skills.save": Core.m_skills_save,
    "skills.test": Core.m_skills_test,
    "skills.set_enabled": Core.m_skills_set_enabled,
    "skills.delete": Core.m_skills_delete,
    "skills.config.get": Core.m_skills_config_get,
    "skills.config.set": Core.m_skills_config_set,
    "mcp.status": Core.m_mcp_status,
    "mcp.save": Core.m_mcp_save,
    "mcp.set_enabled": Core.m_mcp_set_enabled,
    "mcp.delete": Core.m_mcp_delete,
    "mcp.reconnect": Core.m_mcp_reconnect,
    "mcp.refresh_tools": Core.m_mcp_refresh_tools,
    "mcp.tools": Core.m_mcp_tools,
    "mcp.set_global_enabled": Core.m_mcp_set_global_enabled,
    "mcp.set_limits": Core.m_mcp_set_limits,
    "hosts.list": Core.m_hosts_list,
    "hosts.settings": Core.m_hosts_settings,
    "hosts.public_key": Core.m_hosts_public_key,
    "hosts.prepare": Core.m_hosts_prepare,
    "hosts.test": Core.m_hosts_test,
    "hosts.commit": Core.m_hosts_commit,
    "hosts.set_enabled": Core.m_hosts_set_enabled,
    "hosts.references": Core.m_hosts_references,
    "hosts.delete": Core.m_hosts_delete,
    "hosts.force_revoke": Core.m_hosts_force_revoke,
    "schedules.list": Core.m_schedules_list,
    "schedules.save": Core.m_schedules_save,
    "schedules.delete": Core.m_schedules_delete,
    "schedules.run": Core.m_schedules_run,
    "schedules.reset_failures": Core.m_schedules_reset_failures,
    "schedules.history": Core.m_schedules_history,
    "schedules.validate_cron": Core.m_schedules_validate_cron,
    "personality.get": Core.m_personality_get,
    "personality.set": Core.m_personality_set,
    "personality.presets.save": Core.m_personality_presets_save,
    "personality.presets.delete": Core.m_personality_presets_delete,
    "memory.list": Core.m_memory_list,
    "memory.get": Core.m_memory_get,
    "memory.set": Core.m_memory_set,
    "memory.delete": Core.m_memory_delete,
    "memory.bulk_delete": Core.m_memory_bulk_delete,
    "lists.list": Core.m_lists_list,
    "lists.get": Core.m_lists_get,
    "lists.delete": Core.m_lists_delete,
    "knowledge.list": Core.m_knowledge_list,
    "knowledge.search": Core.m_knowledge_search,
    "knowledge.ingest": Core.m_knowledge_ingest,
    "knowledge.reingest": Core.m_knowledge_reingest,
    "knowledge.delete": Core.m_knowledge_delete,
    "knowledge.versions": Core.m_knowledge_versions,
    "knowledge.restore": Core.m_knowledge_restore,
    "audit.query": Core.m_audit_query,
    "audit.verify": Core.m_audit_verify,
    "health.get": Core.m_health_get,
    "logs.search": Core.m_logs_search,
    "turn_state.list": Core.m_turn_state_list,
    "computer.status": Core.m_computer_status,
    "computer.reconcile": Core.m_computer_reconcile,
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
