"""Whole frozen snapshot/tail suites, with exact temporary-owner setup hunks.

No HTTP listener is recreated. Snapshot responses project the real authenticated
named-command result. Process capture, supervision, settlement and delivery are
the actual retained engines, including the remote supervisor running locally.
"""
from __future__ import annotations

import ast
import asyncio
import contextvars
import copy
import hashlib
import secrets
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, register_module
from src.config.schema import ToolsConfig
from src.desktop.commands import CommandJournal, JournalStore
from src.desktop.core import CoreService
from src.desktop.events import EventJournal
from src.desktop.ipc import IpcServer
from src.desktop.knowledge import KnowledgeService
from src.desktop.local_client import LocalClient
from src.desktop.management import ManagementService
from src.permissions.persistence import write_private_atomic
from src.tools.builtin_policy import BuiltinToolPolicy
from src.tools.executor import ToolExecutor
from src.tools.workspace import resolve_workspace
from tests.desktop_adapters.process_cases import temporary_owner

CORPUS_SELECTIONS = {
    "test_knowledge_snapshot_campaign": None,
    "test_process_tail_correctness": None,
}
CORPUS_EXCLUSIONS = {}
SUITES = {
    "test_knowledge_snapshot_campaign": (
        "9558df8f435566d712ddb9793533031aa6352e7714f804fb67e5bf8933cc2949"
    ),
    "test_process_tail_correctness": (
        "1fa6fdfcfb7281790748fe5b6ace0cedae94f7c5e36eb9da97ba95413b37f880"
    ),
}
_owner = contextvars.ContextVar("step8_runtime_d_owner", default=None)


@contextmanager
def runtime_owner(tmp_path):
    with temporary_owner(tmp_path) as state:
        token = _owner.set(state)
        try:
            yield state
        finally:
            _owner.reset(token)


def owner_id():
    state = _owner.get()
    if state is None or not state.manager.is_owner(state.authority.owner_id):
        raise PermissionError("authenticated temporary owner required")
    return state.authority.owner_id


def executor(tmp_path):
    """Actual executor, profile authority and validated private workspace."""
    state = _owner.get()
    owner_id()
    workspace = resolve_workspace(
        str(state.workspace), protected_roots=[state.paths.config_dir,
            state.paths.data_dir, state.paths.cache_dir], create_if_missing=False,
    )
    ex = ToolExecutor(
        ToolsConfig(local_working_dir=str(workspace),
                    audit_log_path=str(state.paths.data_dir / "audit.jsonl"),
                    trajectory_path=str(state.paths.data_dir / "trajectory.jsonl"),
                    ssh_key_path=str(state.paths.config_dir / "unused-ssh-key"),
                    ssh_known_hosts_path=str(state.paths.config_dir / "known_hosts"),
                    hosts={"testhost": {"address": "127.0.0.1", "ssh_user": "odin"}},
                    ssh_pool={"enabled": False}),
        profile_paths=state.paths, permission_manager=state.manager,
        memory_path=str(state.paths.data_dir / "memory.json"),
    )
    ex.set_user_context(owner_id())
    state.executors.append(ex)
    # Advertise ONLY the actual wired process handler. No globally ready policy,
    # _protected_roots, permission, host lookup or process-method override.
    def process_readiness():
        return {"manage_process": (
            callable(ex._resolve_handler("manage_process"))
            and state.manager.is_owner(state.authority.owner_id)
            and ex.host_registry.get("testhost", targetable_only=True) is not None
            and ex._ensure_local_workspace() == str(workspace)
        )}

    ex.set_builtin_policy(BuiltinToolPolicy(
        lambda: SimpleNamespace(tools=ex.config), process_readiness))
    if ex._ensure_local_workspace() != str(workspace):
        raise RuntimeError("actual executor rejected the protected workspace")
    return ex


class CommandResponse:
    """Only the inherited response carrier, not a manufactured domain outcome."""
    def __init__(self, frame):
        self.frame = frame
        if frame["ok"]:
            self.status = 200
            self.body = frame["result"]
        else:
            # This adapter serves only reingest. Unknown refusals must fail,
            # never silently become the expected status or successful result.
            self.status = {"conflict": 409, "not_found": 404,
                           "bad_request": 400}[frame["error"]["code"]]
            self.body = {"error": frame["error"]["message"]}

    async def json(self):
        return self.body


class KnowledgeCommandClient:
    """Real private Unix transport, owner admission, journal and domain service.

    No HTTP server, native desktop, parent watcher or runtime graph is started.
    IpcServer authenticates the actual OS peer and temporary handshake credential.
    """
    def __init__(self, store):
        state = _owner.get()
        owner_id()
        # Unix pathname length is bounded independently of long pytest paths.
        self.transport_dir = tempfile.TemporaryDirectory(prefix="step8d-ipc-")
        root = Path(self.transport_dir.name)
        self.core = CoreService(state.paths, root / "runtime" / "core.sock",
                                root / "ipc.token")
        if not write_private_atomic(self.core.token_file, secrets.token_hex(32)):
            raise RuntimeError("temporary handshake credential durability failed")
        self.core.authority = state.authority
        self.core.permissions = state.manager
        self.core.store = JournalStore(
            state.paths.data_dir / "snapshot-transport.sqlite3", state.paths.profile_id,
            identity=f"{state.authority.installation_id}:{state.authority.owner_id}",
        )
        self.core.commands = CommandJournal(self.core.store)
        self.core.events = EventJournal(self.core.store)
        self.service = KnowledgeService(state.paths, store=store)
        self.core.management = ManagementService(
            self.core, services=[self.service], identity_key=secrets.token_bytes(32),
        )
        self.core.capabilities = tuple(self.core.management.methods)
        self.server = IpcServer(self.core.socket_path, self.core.token_file,
                                state.paths.profile_id, state.authority,
                                self.core.welcome, self.core.dispatch)
        self.client = None
        self.sequence = 0

    async def __aenter__(self):
        await self.server.start()
        self.client = await LocalClient.connect(
            self.core.socket_path, self.core.token_file, self.core.paths.profile_id)
        return self

    async def __aexit__(self, *exc):
        if self.client is not None:
            await self.client.close()
        await self.server.shutdown()
        await self.core.management.close()
        self.core.store.close()
        self.core.lifetime.close()
        self.transport_dir.cleanup()

    async def post(self, path):
        if path != "/api/knowledge/document/reingest":
            raise ValueError("unmapped inherited request")
        self.sequence += 1
        identity = str(uuid.uuid4())
        self.last_command_id = identity
        await self.client.request("knowledge.reingest", {"source": "document"},
                                  request_id=identity)
        frame = await asyncio.wait_for(self.client.read(), 5)
        if frame.get("t") != "res" or frame.get("id") != identity:
            raise RuntimeError("actual transport refused or mismatched command")
        return CommandResponse(frame)


# Each key is (source line, node kind, exact original AST SHA). Replacement is
# a single node (or removal), never a blanket textual or assertion rewrite.
SETUP_HUNKS = {
    "test_knowledge_snapshot_campaign": [
        (4, "ImportFrom", "3d8c3610792369d562462f782609dfc65e70367a4cfe745f783096882dc296a2", None),
        (5, "ImportFrom", "a4c9ffaa0ad4b0d5f73d26288eb4909a6de85c114195ec40be4767111b566dfd", None),
        (8, "ImportFrom", "156ed0697e1c25d1b7e05f884bf45b33b77b9cc639cd3385e0c675367610802c", None),
        (18, "Assign", "44862e19cc905146ed2094aca53206aa13f53afd1ca14bbd88ea805deb6d0978",
         "client = KnowledgeCommandClient(store)"),
        (19, "Expr", "3c7f7fbe881aaba445f6c10d1b29689616e7a8bc9429b06f2f1d1f0f782da771", None),
        (20, "Assign", "69f35dfba906ad798d1d10e0110f4dd7628c776efb25849c4d8b37ecac48549e", None),
        (21, "Expr", "66e865709bfa2f9eb627517073676aa184b891a4d03e5152242438a0c54d3454", None),
        (22, "Call", "4f2becb0c34fc0b2d6f3d130e1261605777a86a0e60dbec50028ab4a8ded5502", "client"),
        (48, "Assign", "44862e19cc905146ed2094aca53206aa13f53afd1ca14bbd88ea805deb6d0978",
         "client = KnowledgeCommandClient(store)"),
        (49, "Expr", "3c7f7fbe881aaba445f6c10d1b29689616e7a8bc9429b06f2f1d1f0f782da771", None),
        (50, "Assign", "69f35dfba906ad798d1d10e0110f4dd7628c776efb25849c4d8b37ecac48549e", None),
        (51, "Expr", "66e865709bfa2f9eb627517073676aa184b891a4d03e5152242438a0c54d3454", None),
        (52, "Call", "4f2becb0c34fc0b2d6f3d130e1261605777a86a0e60dbec50028ab4a8ded5502", "client"),
    ],
    "test_process_tail_correctness": [
        (17, "ImportFrom", "8dce3e2a05cc244e733c19f4bc147ac405041272953870af6f871eadf49345ce",
         "from tests.desktop_adapters.step8_runtime_d import executor"),
        *[(line, "Constant", "b2de7a0b892c7480fc8487adc4adac61e17adca8ef942042af20476268fc4836",
           "owner_id()")
          for line in (29, 36, 51, 68, 106, 109)],
    ],
}


def transform(stem):
    source = frozen_source(f"tests/{stem}.py")
    if hashlib.sha256(source).hexdigest() != SUITES[stem]:
        raise ValueError("runtime D frozen source changed")
    original = ast.parse(source)
    tree = copy.deepcopy(original)
    rules = SETUP_HUNKS[stem]
    locations = []

    def locate(node, path=()):
        for field, value in ast.iter_fields(node):
            if isinstance(value, list):
                for index, child in enumerate(value):
                    if isinstance(child, ast.AST):
                        locate(child, (*path, field, index))
            elif isinstance(value, ast.AST):
                locate(value, (*path, field))
        for index, (line, kind, digest, replacement) in enumerate(rules):
            if (getattr(node, "lineno", None) == line and type(node).__name__ == kind
                    and hashlib.sha256(dump(node).encode()).hexdigest() == digest):
                locations.append((index, path, copy.deepcopy(node)))

    locate(original)
    if sorted(i for i, _, _ in locations) != list(range(len(rules))):
        raise ValueError("runtime D setup hunk must match exactly once")
    # Apply deep/rightmost paths first so sibling removals cannot shift targets.
    for index, path, node in sorted(locations, key=lambda item: item[1], reverse=True):
        parent = tree
        for part in path[:-1]:
            parent = parent[part] if isinstance(part, int) else getattr(parent, part)
        replacement = rules[index][3]
        new = None if replacement is None else (
            ast.parse(replacement).body[0] if isinstance(node, ast.stmt)
            else ast.parse(replacement, mode="eval").body)
        if new is not None:
            ast.copy_location(new, node)
        if isinstance(path[-1], int):
            if new is None:
                del parent[path[-1]]
            else:
                parent[path[-1]] = new
        else:
            setattr(parent, path[-1], new)
    ast.fix_missing_locations(tree)
    if corpus(original) != corpus(tree):
        raise ValueError("runtime D assertion/signature/parameter corpus changed")
    # Reverse every admitted edit in forward path order. Compare the COMPLETE
    # original module AST, including helper assertions and all non-test setup.
    restored = copy.deepcopy(tree)
    for index, path, node in sorted(locations, key=lambda item: item[1]):
        parent = restored
        for part in path[:-1]:
            parent = parent[part] if isinstance(part, int) else getattr(parent, part)
        if isinstance(path[-1], int):
            if rules[index][3] is None:
                parent.insert(path[-1], node)
            else:
                parent[path[-1]] = node
        else:
            setattr(parent, path[-1], node)
    if dump(restored) != dump(original):
        raise ValueError("runtime D whole-module reverse replay failed")
    return original, tree


def load(namespace):
    # This inherited transport helper contains real _REMOTE_SUPERVISOR execution
    # and process-group cleanup. Pin the entire retained helper before importing.
    frozen_source("tests/test_remote_process_streaming.py")
    result = {}
    for stem in CORPUS_SELECTIONS:
        original, tree = transform(stem)
        module = ModuleType(f"frozen_{stem}")
        module.__dict__.update(KnowledgeCommandClient=KnowledgeCommandClient,
                               owner_id=owner_id)
        exec(compile(tree, f"tests/{stem}.py", "exec"), module.__dict__)
        register_module(namespace, module, prefix=stem[5:])
        if stem == "test_process_tail_correctness":
            namespace["no_background"] = module.no_background
        result[stem] = (original, tree, module)
    return result
