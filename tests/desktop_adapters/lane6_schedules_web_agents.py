"""Retained frozen agent display cases through 6B WorkService projections."""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace

from scripts.maintenance.fixture_corpus import corpus, frozen_source, nodes
from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.events import EventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.work import WorkService
from src.permissions.manager import PermissionManager
from tests.desktop_adapters.lane6_schedules_web import (
    Application as Application,
)
from tests.desktop_adapters.lane6_schedules_web import (
    Response,
)
from tests.desktop_adapters.lane6_schedules_web import (
    TestServer as TestServer,
)
from tests.desktop_adapters.lane6_schedules_web import (
    web as web,
)

PATH = "tests/test_web_api_agents_loops.py"
SOURCE_HASHES = {
    PATH: "5a11f1688a846b9a521c16e85d9fdb8ce9c9820f03636d10d81b8a102bafbaeb"
}
SUITES = {
    "test_web_api_agents_loops": "5a11f1688a846b9a521c16e85d9fdb8ce9c9820f03636d10d81b8a102bafbaeb"
}
CORPUS_SELECTIONS = {"test_web_api_agents_loops": None}
CORPUS_EXCLUSIONS = {}
RETIRED_CASES = {}
LOOP_BLOCKER = (
    "6B WorkService exposes bound loop state/stop only; no exact loop create/restart, "
    "callback, trajectory paging or context-history detail methods. Needs canonical "
    "owner-bound method/projection, not original web registrar."
)
AGENT_BLOCKER = (
    "6B WorkService agent projection lacks full goal/result/tool-count/activity/list-vs-detail "
    "shaping and legacy kill/children/status/fallback envelopes. Exact setup-only bridge "
    "absent; retained behavior is deferred, not retired."
)
SETTINGS_BLOCKER = (
    "Frozen tests patch removed web persistence hook and obsolete Config.discord; exact "
    "SettingsService/ModelSettingsService setup-only bridge not implemented in this batch."
)
PROCESS_BLOCKER = (
    "6B process controls require immutable work/generation binding; legacy PID-only HTTP "
    "list/kill contracts need reviewed exact projection bridge, not control bypass."
)
DEFERRED_CASES = {"test_web_api_agents_loops": {
    "TestLoops.test_list_loops": LOOP_BLOCKER,
    "TestLoops.test_loop_detail_uses_durable_trajectory_history": LOOP_BLOCKER,
    "TestLoops.test_loop_detail_reports_paging_truthfully": LOOP_BLOCKER,
    "TestLoops.test_loop_detail_missing_and_unavailable_history": LOOP_BLOCKER,
    "TestLoops.test_loop_detail_storage_failure_preserves_live_record": LOOP_BLOCKER,
    "TestLoops.test_start_loop_validation": LOOP_BLOCKER,
    "TestLoops.test_start_loop_channel_not_found": LOOP_BLOCKER,
    "TestLoops.test_start_loop_goal_too_long": LOOP_BLOCKER,
    "TestLoops.test_start_loop_non_numeric_channel": LOOP_BLOCKER,
    "TestLoops.test_start_loop_success": LOOP_BLOCKER,
    "TestLoops.test_start_loop_manager_error": LOOP_BLOCKER,
    "TestLoops.test_stop_loop_found_and_missing": LOOP_BLOCKER,
    "TestLoops.test_restart_missing_loop": LOOP_BLOCKER,
    "TestLoops.test_restart_success": LOOP_BLOCKER,
    "TestLoops.test_restart_lock_is_pruned_after_request": LOOP_BLOCKER,
    "TestLoops.test_restart_lock_survives_waiter_cancellation_and_serializes": LOOP_BLOCKER,
    "TestLoops.test_restart_callback_accepts_manager_invocation_shape": LOOP_BLOCKER,
    "TestLoops.test_create_callback_accepts_manager_invocation_shape": LOOP_BLOCKER,
    "TestLoops.test_restart_channel_gone": LOOP_BLOCKER,
    "TestLoops.test_restart_missing_channel_preserves_running_loop": LOOP_BLOCKER,
    "TestLoops.test_restart_rejects_reused_channel_identity_before_stop": LOOP_BLOCKER,
    "TestLoops.test_restart_rejects_invalid_persisted_configuration_before_stop": LOOP_BLOCKER,
    "TestLoops.test_restart_manager_error": LOOP_BLOCKER,
    "TestAgents.test_agent_model_policy_reports_validation_errors": SETTINGS_BLOCKER,
    "TestAgents.test_agent_model_policy_get_and_put": SETTINGS_BLOCKER,
    "TestAgents.test_agent_model_policy_rejects_invalid_and_surfaces_save_failure": (
        SETTINGS_BLOCKER
    ),
    "TestAgents.test_agent_model_policy_propagates_cancelled_persistence": SETTINGS_BLOCKER,
    "TestAgents.test_list_agents": AGENT_BLOCKER,
    "TestAgents.test_list_agents_no_manager": AGENT_BLOCKER,
    "TestAgents.test_kill_agent_found_and_missing": AGENT_BLOCKER,
    "TestAgents.test_children_lineage_descendants": AGENT_BLOCKER,
    "TestAgents.test_kill_agent_non_dict_registry": AGENT_BLOCKER,
    "TestAgents.test_no_agent_manager_fallbacks": AGENT_BLOCKER,
    "TestProcesses.test_list_processes": PROCESS_BLOCKER,
    "TestProcesses.test_list_processes_no_registry": PROCESS_BLOCKER,
    "TestProcesses.test_kill_process": PROCESS_BLOCKER,
    "TestProcesses.test_kill_process_no_registry": PROCESS_BLOCKER,
    "TestAgentDisplayPolicy.test_native_agent_activity_and_string_results": AGENT_BLOCKER,
    "TestAgentListCorrections.test_tool_count_is_full_not_preview_slice": AGENT_BLOCKER,
    "TestAgentListCorrections.test_max_iterations_exposed_for_honest_progress": AGENT_BLOCKER,
    "TestAgentDetail.test_detail_returns_untruncated_fields": AGENT_BLOCKER,
    "TestAgentDetail.test_detail_list_truncation_still_applies": AGENT_BLOCKER,
    "TestAgentDetail.test_detail_carries_overrides_separately_from_execution": AGENT_BLOCKER,
    "TestAgentDetail.test_detail_unknown_agent_404": AGENT_BLOCKER,
    "TestAgentDetail.test_detail_no_manager_404": AGENT_BLOCKER,
}}
DISPLAY_CLASSES = {"TestAgentDisplayPolicy", "TestDisplayPolicyProviderAwareness",
                   "TestDisplayPolicyPerAxisSources", "TestDisplayPolicyExecutionTruth"}
CASE_MAP = {}
SETUP_HUNKS = {}
_LOOP_RESTART_LOCKS = {}


def register_agents(routes, bot):
    routes.append(bot)


def register_loops(routes, bot):
    raise NotImplementedError("Legacy restart/history projections are not desktop work methods")


def register_processes(routes, bot):
    raise NotImplementedError("Legacy process HTTP projections are not desktop work methods")


class Admissions:
    def __init__(self, message):
        self.message = message

    def assert_bound_request(self, value):
        if value is not self.message:
            raise PermissionError("Unadmitted test request")


class TestClient:
    __test__ = False

    def __init__(self, server):
        self.server = server

    async def __aenter__(self):
        self.temp = TemporaryDirectory(prefix="lane6_schedules_agents_")
        paths = ProfilePaths.from_xdg("fixture", home=Path(self.temp.name), environ={})
        self.authority = OwnerAuthority(paths)
        self.owner = self.authority.authenticate_local(peer_uid=self.authority.owner_uid)
        self.permissions = PermissionManager(self.authority)
        self.token = self.permissions.set_request_owner(self.owner)
        self.store = JournalStore(paths.data_dir / "journal.sqlite3", "fixture")
        events = EventJournal(self.store)
        conversations = ConversationStore(self.store, events)
        cid = conversations.create()["conversation"]["id"]
        message = SimpleNamespace(
            owner_id=self.owner.owner_id,
            conversation_id=cid,
            request_id="fixture-run",
            generation=1,
        )
        self.bot = self.server.app.routes[0]
        manager = self.bot.agent_manager
        manager.get_descendants.return_value = []
        self.service = WorkService(
            self.store,
            events,
            authority=self.authority,
            permissions=self.permissions,
            requests=Admissions(message),
            conversations=conversations,
            agents=manager,
            display_config=self.bot,
        )
        for id, item in manager._agents.items():
            item.requester_id, item.channel_id = self.owner.owner_id, cid
            self.service.register("agent", id, message)
        return self

    async def __aexit__(self, *args):
        self.store.close()
        self.permissions.reset_request_owner(self.token)
        self.authority.release_runtime()
        self.temp.cleanup()

    async def get(self, path, **kwargs):
        if path != "/api/agents":
            raise NotImplementedError("Full agent-detail projection is not built")
        return Response(
            [record["detail"] for record in self.service.list({"kind": "agent"})["items"]]
        )


def selected(symbol):
    return (symbol.split(".")[0] in DISPLAY_CLASSES
            and symbol != "TestAgentDisplayPolicy.test_native_agent_activity_and_string_results")


def transformed_tree():
    source = frozen_source(PATH)
    assert hashlib.sha256(source).hexdigest() == SOURCE_HASHES[PATH]
    original = ast.parse(source)
    tree = copy.deepcopy(original)
    hunks = []
    for symbol, node in nodes(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {
            "aiohttp", "aiohttp.test_utils", "src.web.api.agents_loops"
        }:
            before = ast.dump(node)
            node.module = __name__
            after = ast.dump(node)
            hunks.append({"symbol": symbol, "line": node.lineno,
                "operation": "lane6_schedules_work_owner_import", "kind": "statement",
                "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
                "after_sha256": hashlib.sha256(json.dumps([after]).encode()).hexdigest(),
                "after_source": ast.unparse(node)})
    assert corpus(original) == corpus(tree)
    expected = copy.deepcopy(original)
    for hunk in hunks:
        matches = [n for symbol, n in nodes(expected) if symbol == hunk["symbol"]
                   and getattr(n, "lineno", None) == hunk["line"]
                   and hashlib.sha256(ast.dump(n).encode()).hexdigest() == hunk["before_sha256"]]
        assert len(matches) == 1
        assert isinstance(matches[0], ast.ImportFrom)
        matches[0].module = __name__
        assert (
            hashlib.sha256(json.dumps([ast.dump(matches[0])]).encode()).hexdigest()
            == hunk["after_sha256"]
        )
    assert ast.dump(expected) == ast.dump(tree)
    SETUP_HUNKS[PATH] = hunks
    return ast.fix_missing_locations(tree)


def load(namespace):
    module = ModuleType("lane6_schedules_agents_frozen")
    module.__file__ = str(Path(__file__).parents[2] / PATH)
    tree = transformed_tree()
    exec(compile(tree, module.__file__, "exec"), module.__dict__)
    register_module(namespace, "test_web_api_agents_loops", module)


def register_module(namespace, suite, module):
    tree = transformed_tree()
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name not in DISPLAY_CLASSES:
            continue
        cls = getattr(module, node.name)
        for method in list(vars(cls)):
            if method.startswith("test_") and not selected(f"{node.name}.{method}"):
                delattr(cls, method)
        exported = "TestLane6SchedulesWebAgents_" + node.name[4:]
        cls.__module__ = namespace["__name__"]
        namespace[exported] = cls
        for method in vars(cls):
            if method.startswith("test_"):
                CASE_MAP[f"{PATH}::{node.name}::{method}"] = f"{exported}::{method}"
