"""PR34 exact whole-suite carriers; unavailable health parity is not invented."""
from __future__ import annotations

import ast
import asyncio
import contextvars
import copy
import hashlib
import json
import struct
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, nodes, register_module
from src.config.schema import Config, ToolHost, ToolsConfig
from src.desktop import ipc_auth
from src.desktop.ipc import IpcServer
from src.desktop.model_settings import ModelSettingsService
from src.desktop.protocol import encode_frame, read_frame
from src.desktop.services import _ReadyPolicy
from src.desktop.settings import SettingsService
from src.tools.executor import ToolExecutor

ROOT = Path(__file__).resolve().parents[2]
CORPUS_SELECTIONS = {
    "test_campaign_agent_routes_coverage": None,
    "test_output_executor_fences": None,
}
CORPUS_EXCLUSIONS = {}
SUITES = {
    "test_campaign_agent_routes_coverage":
        "3b430120bb2dadec994cc73262dc10b03a9089ce6e0fc35f6653b142a6da49f7",
    "test_output_executor_fences":
        "04d20c34d86cce820027cfcd64490adf39d53d2e4084eef9a2c922ada1699c86",
}
fixture_state = contextvars.ContextVar("step8_review_health_owner", default=None)
HUNKS_SHA256 = "5629dbd30e3c55fc032417441d57ef0d9257af5204cbc283edbbf0fe0a26a09a"


def state():
    value = fixture_state.get()
    if value is None:
        raise RuntimeError("authenticated temporary profile required")
    return value


def fixture_owner_id():
    return state().authority.owner_id


def fixture_policy(executor, *, disabled=()):
    executor.config.disabled_tools = list(disabled)
    return _ReadyPolicy(
        lambda: SimpleNamespace(tools=executor.config),
        get_readiness=state().engine.deps.readiness,
    )


def _owned_executor(config):
    owner = state()
    ex = ToolExecutor(config, profile_paths=owner.paths, permission_manager=owner.manager,
                      memory_path=str(Path(config.audit_log_path).parent / "memory.json"))
    ex.set_user_context(owner.authority.owner_id)
    ex.set_builtin_policy(fixture_policy(ex))
    owner.executors.append(ex)
    return ex


def executor(tmp_path):
    """Execute the pinned inherited helper with only its constructor owner-bound.

    The obsolete helper's other test definitions/imports are not imported. This
    is helper reuse, not restoration or exclusion of that separately remapped suite.
    """
    path = "tests/test_executor_output_retention.py"
    source = frozen_source(path)
    if hashlib.sha256(source).hexdigest() != (
        "c765632aa4d32e059c43d9f4d47af69b3fd8e8bd46d545861e766b4af3ad98c5"
    ):
        raise ValueError("retained helper source changed")
    matches = [n for n in ast.parse(source).body
               if isinstance(n, ast.FunctionDef) and n.name == "executor"]
    if len(matches) != 1:
        raise ValueError("retained helper must match once")
    namespace = {"ToolExecutor": _owned_executor, "ToolsConfig": ToolsConfig,
                 "ToolHost": ToolHost}
    tree = ast.fix_missing_locations(ast.Module(body=matches, type_ignores=[]))
    exec(compile(tree, path, "exec"), namespace)
    return namespace["executor"](tmp_path)


class AgentPolicyCarrier:
    """A real owner-authenticated Unix IPC session, not an HTTP route emulator.

    Only the real protocol_error bye verdict maps to inherited HTTP 400. The
    persistence observer is installed on the actual SettingsService save owner;
    valid writes are not made by this malformed-input test.
    """
    def __init__(self, persist):
        self.persist = persist
        self.owner = state()
        self.settings = SettingsService(self.owner.paths, None, config=Config())
        self.models = ModelSettingsService(self.settings)
        self.dispatched = []

        def reject_save(*args, **kwargs):
            # Preserve the inherited async observer and also fail immediately
            # for the desktop's synchronous save owner if it is ever reached.
            coroutine = persist(*args, **kwargs)
            coroutine.close()
            raise AssertionError("no config mutation")

        self.settings.save_changes = reject_save

    async def __aenter__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pr34-agent-")
        root = Path(self.temp.name)
        credentials = root / "credentials"
        credentials.mkdir(mode=0o700)
        token_file = credentials / "ipc.token"
        token_file.write_text("1" * 64)
        token_file.chmod(0o600)

        async def dispatch(connection, request):
            if not self.owner.authority.accepts(connection.owner_context):
                raise PermissionError("request owner rejected")
            self.dispatched.append(request)
            result = await self.models.handle(request["method"], request["params"])
            return {"t": "res", "id": request["id"], "ok": True, "result": result}

        self.server = IpcServer(
            root / "runtime" / "core.sock", token_file, self.owner.authority.profile_id,
            self.owner.authority,
            lambda: {"core": {"instance_id": self.owner.authority.runtime_id,
                              "version": "fixture"}, "capabilities": ["models.agents.set"],
                     "features": [], "event_high": "0"}, dispatch,
        )
        await self.server.start()
        self.reader, self.writer = await asyncio.open_unix_connection(self.server.socket_path)
        self.writer.write(encode_frame({
            "t": "hello", "protocol": {"major": 0, "minor": 3},
            "client": {"name": "frozen-agent-policy", "version": "0"},
            "profile_id": self.owner.authority.profile_id,
            "token": ipc_auth.load_token(token_file), "features": [],
        }))
        await self.writer.drain()
        welcome = await asyncio.wait_for(read_frame(self.reader), 2)
        if welcome["t"] != "welcome":
            raise RuntimeError("real IPC owner handshake failed")
        return self

    async def put(self, path, *, data):
        if path != "/api/agents/model":
            raise ValueError("undeclared carrier path")
        payload = data.encode("utf-8")
        self.writer.write(struct.pack("!I", len(payload)) + payload)
        await self.writer.drain()
        verdict = await asyncio.wait_for(read_frame(self.reader), 2)
        if verdict != {"t": "bye", "reason": "protocol_error"}:
            raise ValueError("not the inherited malformed JSON refusal")

        async def body():
            return {"error": verdict["reason"]}

        return SimpleNamespace(status=400, json=body, desktop_verdict=verdict)

    async def __aexit__(self, *exc):
        self.writer.close()
        await asyncio.wait_for(self.writer.wait_closed(), 2)
        await self.server.shutdown()
        self.temp.cleanup()
        self.persist.assert_not_called()
        if self.dispatched:
            raise AssertionError("malformed JSON reached model/persistence dispatch")
        if self.owner.paths.config_file.exists():
            raise AssertionError("malformed JSON created configuration")


def records():
    result = json.loads((ROOT / "maintenance/step8-part2-review-health.json").read_text())
    encoded = json.dumps(result["setup_hunks"], sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(encoded).hexdigest() != HUNKS_SHA256:
        raise ValueError("complete admitted hunk inventory seal changed")
    return result


def source_tree(name):
    data = frozen_source(f"tests/{name}.py")
    if hashlib.sha256(data).hexdigest() != SUITES[name]:
        raise ValueError("inherited source hash changed")
    return ast.parse(data)


def _replace(tree, rule):
    before = (ast.parse(rule["before_source"], mode="eval").body
              if rule["kind"] == "expression" else ast.parse(rule["before_source"]).body)
    if isinstance(before, list):
        if len(before) != 1:
            raise ValueError("before hunk must be one complete inherited node")
        before = before[0]
    if hashlib.sha256(dump(before).encode()).hexdigest() != rule["before_sha256"]:
        raise ValueError("inherited hunk seal changed")
    matches = [n for owner, n in nodes(tree)
               if owner == rule["symbol"] and getattr(n, "lineno", None) == rule["line"]
               and hashlib.sha256(dump(n).encode()).hexdigest() == rule["before_sha256"]]
    if len(matches) != 1:
        raise ValueError("exact hunk must match once")
    target = matches[0]
    replacement = (ast.parse(rule["after_source"], mode="eval").body
                   if rule["kind"] == "expression" else ast.parse(rule["after_source"]).body)
    representation = dump(replacement) if isinstance(replacement, ast.AST) else json.dumps(
        [dump(n) for n in replacement])
    if hashlib.sha256(representation.encode()).hexdigest() != rule["after_sha256"]:
        raise ValueError("replacement hunk seal changed")

    class Exact(ast.NodeTransformer):
        def visit(self, node):
            if node is target:
                if isinstance(replacement, list):
                    return [ast.copy_location(copy.deepcopy(n), node) for n in replacement]
                return ast.copy_location(copy.deepcopy(replacement), node)
            return super().visit(node)

    return Exact().visit(tree)


def adapted_tree(name):
    tree = copy.deepcopy(source_tree(name))
    for rule in records()["setup_hunks"]:
        if rule["path"] == f"tests/{name}.py":
            tree = _replace(tree, rule)
    verify_adaptation(name, tree)
    return ast.fix_missing_locations(tree)


def verify_adaptation(name, adapted):
    """Complete expected tree, plus independent approved-owner normalization.

    Every definition, helper, assertion, signature and decorator is retained.
    Only UUID projection within assertions changes their lexical AST.
    """
    original = source_tree(name)
    expected = copy.deepcopy(original)
    for rule in records()["setup_hunks"]:
        if rule["path"] == f"tests/{name}.py":
            expected = _replace(expected, rule)
    if dump(expected) != dump(adapted):
        raise ValueError("undeclared source change or missing inherited case/helper")
    normalized = copy.deepcopy(adapted)

    class OwnerBack(ast.NodeTransformer):
        def visit_Call(self, node):
            if dump(node) == dump(ast.parse("fixture_owner_id()", mode="eval").body):
                return ast.Constant(value="owner")
            return self.generic_visit(node)

    normalized = OwnerBack().visit(normalized)
    if corpus(original) != corpus(normalized):
        raise ValueError("inherited assertion/signature/decorator meaning changed")
    return True


def load(namespace):
    for name in CORPUS_SELECTIONS:
        module = ModuleType(f"desktop_step8_review_health_{name}")
        module.__file__ = str(ROOT / f"tests/{name}.py")
        exec(compile(adapted_tree(name), module.__file__, "exec"), module.__dict__)
        expected = [n.name for n in source_tree(name).body if isinstance(
            n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")]
        actual = [key for key in vars(module) if key.startswith("test_")]
        if sorted(actual) != sorted(expected):
            raise ValueError("incomplete inherited suite export")
        register_module(namespace, module, prefix=name, full_class_name=True)
