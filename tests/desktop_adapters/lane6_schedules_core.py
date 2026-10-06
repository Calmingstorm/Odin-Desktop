"""Exact frozen scheduler corpora through real 6B canonical owner services.

Channels below are output observation spies, never authority or messages. The
owner graph fixture composes real engine owners, RequestService and delivery.
"""
from __future__ import annotations

import ast
import hashlib
import json
from contextlib import asynccontextmanager
from contextvars import ContextVar
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest_asyncio

from scripts.maintenance.fixture_corpus import ROOT, corpus, dump, frozen_source, nodes
from src.discord.scheduled_events import ScheduledEventHandlers as RealHandlers
from src.discord.scheduled_events import ScheduledEventsDeps as RealDeps
from src.discord.scheduled_events import _scheduled_execution
from tests.desktop_adapters.test_phase2_runner_characterization import (
    graph as graph,
)
from tests.fakes.discord_objects import FakeChannel
from tests.fakes.llm import FakeLLM as FakeLLM

SUITES = {
    "test_scheduled_events": "71db4d14426cef763211723bc3ed02897c54474dafe1030be70b4881fee1d3d7",
    "characterization/test_scheduled_events": (
        "846efd54be82f42a77bb46987f3c03acc67a434298564a91754d0e0b813dff1b"
    ),
    "test_scheduled_workflow": "7d4e792a9375619f8f8cce7886f9e8d8b7e81ce6188cd30153bda404647a9ce6",
    "test_campaign_scheduler_workflows": (
        "cdb2da7883cba08ef96726fa30efea0af47499e841ff161d6a4067e07db62c2b"
    ),
    "test_scheduled_digest_identity": (
        "fb0c7efc11f59788e4d225906a87f36529808d96e0a676dce2aa47c989d64d82"
    ),
    "test_scheduled_events_digest_failure_summary": (
        "a157ba0734a41c8b43e6ee0418e2c2b0e27db8c2ca686d458b5b5153584ac864"
    ),
}
CORPUS_SELECTIONS = {stem: None for stem in SUITES}
CORPUS_HASHES = {
    "test_scheduled_events": "f9573cfe9fa72c16a0065147cf3a6b3ce5ce214d444aa246315dbbe35b7373a3",
    "characterization/test_scheduled_events": (
        "e792701a2bb04b922829d127e8fb7ebd2623ffbdcee3df9752bc7f11fffb3581"
    ),
    "test_scheduled_workflow": "fc14989ddce1e6a658870485c4de484a541c25e3eae10a99180ede31b64a42e3",
    "test_campaign_scheduler_workflows": (
        "e4ccf3727dfbde5bbc6840394dc22ecae2272b59b0dcae69d83cbdb308cffeac"
    ),
    "test_scheduled_digest_identity": (
        "25c54072d8ffdbbfd413d2b8a63b65d396e9c830ec3d830dbe3a97807790050d"
    ),
    "test_scheduled_events_digest_failure_summary": (
        "8e4cf0e8099155d8af5695086417177e9c8af216a73b322ddb9c6885728d5246"
    ),
}
CORPUS_EXCLUSIONS = {}
REVIEWER = "Claude, review of step 8 part 4"
RETIRED_CASES = {
    "test_scheduled_events": {
        "TestDigest.test_no_channel_id": "Discord channel identifier absence removed.",
        "TestDigest.test_channel_not_found": (
            "Discord channel lookup removed."
        ),
        "TestResolveMentions.test_replaces_known_member": (
            "Discord guild/member mention resolution removed."
        ),
        "TestFormatDigestRaw.test_failed_probe_is_a_collection_failure": (
            "Assertion requires scheduler pseudo-user identity; "
            "multi-user authority removed."
        ),
        "TestWorkflow.test_strict_workflow_stops_on_step_permission_denial": (
            "Assertions require foreign tier user u permission identity; "
            "multi-user authority removed."
        ),
        "TestWorkflow.test_strict_workflow_rejects_missing_skill_name": (
            "Assertions require unauthenticated None tier permission identity; "
            "multi-user authority removed."
        ),
        "TestWorkflow.test_strict_workflow_checks_skill_target_permission": (
            "Assertions require foreign tier user u permission identity; "
            "multi-user authority removed."
        ),
        "TestWorkflow.test_workflow_truncation": (
            "Discord 1900-character workflow message cap removed."
        ),
        "TestWorkflow.test_workflow_send_error_propagates": (
            "Discord send exception contract replaced by nonretryable durable delivery."
        ),
        "TestScheduleFailureAndTask.test_schedule_failure_no_channel": (
            "Discord fallback channel lookup removed."
        ),
        "TestScheduleFailureAndTask.test_task_channel_not_found": (
            "Discord channel lookup removed."
        ),
        "TestScheduleFailureAndTask.test_task_reminder_send_exception": (
            "Discord reminder send exception contract removed."
        ),
        "TestScheduleFailureAndTask.test_task_check_success_send_exception": (
            "Discord send ValueError contract removed; durable publication "
            "is nonretryable."
        ),
        "TestScheduleFailureAndTask.test_task_no_channel_id": (
            "Discord channel identifier absence removed."
        ),
        (
            "TestStructuredCheckReports.test_report_format_dispatches_raw_result_to_pagination_service"
        ): (
            "Discord channel pagination service removed; durable report "
            "service now owns delivery."
        ),
        "TestStructuredCheckReports.test_report_service_unavailable_uses_failure_path": (
            "Discord pagination service unavailable contract removed."
        ),
        "TestStructuredCheckReports.test_renderer_failure_uses_existing_check_failure_path": (
            "Discord pagination renderer exception contract removed."
        ),
        "TestStructuredCheckReports.test_renderer_failure_notice_failure_is_swallowed": (
            "Discord pagination renderer and channel send exception contract removed."
        ),
    },
    "characterization/test_scheduled_events": {
        "TestScheduledTaskRouting.test_missing_channel_id_is_a_delivery_failure": (
            "Discord channel identifier absence removed."
        ),
        "TestScheduledWorkflow.test_truncated_summary_closes_the_cut_code_block": (
            "Discord message cap/code-block truncation removed."
        ),
    },
    "test_scheduled_digest_identity": {
        "test_system_digest_uses_scheduler_identity_and_reports_denied_hosts": (
            "Scheduler pseudo-user identity removed; canonical authenticated "
            "profile owner required."
        ),
        "test_user_digest_runs_as_its_requester": (
            "Foreign multi-user requester authority removed; canonical profile owner required."
        ),
    },
}
DEFERRED_CASES = {
    "test_campaign_scheduler_workflows": {
        "test_delegated_empty_output_obeys_conditions": (
            "Legacy BackgroundTask lacks sealed native RequestService admission; "
            "6B runner refuses direct construction."
        ),
        "test_native_error_aborts_workflow_and_reaches_scheduler_retry_counter": (
            "Standalone frozen Scheduler lacks desktop recovery run_binding required "
            "for real scheduler admission."
        ),
        "test_delegated_invalid_selected_skill_never_executes": (
            "Legacy direct run_background_task lacks sealed native RequestService admission; "
            "6B runner refuses before status mutation."
        ),
        "test_background_actual_executor_prepares_contract_defaults": (
            "Frozen __new__ executor lacks owner and readiness service state; "
            "_execute_tool_captured catches the refusal before _execute_inner, "
            "so a real owner executor setup adapter is required."
        ),
        "test_update_workflow_strict_transport_preserves_condition_and_failure_policy": (
            "Current registry does not expose update_schedule without composed readiness; "
            "owner-bound catalog adapter is required before strict schema lookup."
        ),
    },
}
CORPUS_EXCLUSIONS = {stem: sorted(cases) for stem, cases in RETIRED_CASES.items()}
_graph = ContextVar("lane6_schedules_core_graph", default=None)


@pytest_asyncio.fixture(autouse=True)
async def lane6_schedules_core_graph(graph):
    token = _graph.set(graph)
    try:
        yield graph
    finally:
        _graph.reset(token)


def ScheduledEventsDeps(**values):  # noqa: N802
    return values


class ScheduledEventHandlers(RealHandlers):
    """Only call arguments and source fixture setup are bridged."""

    def __init__(self, values):
        self.graph = _graph.get()
        if self.graph is None:
            raise RuntimeError("real canonical graph fixture required")
        self._get_channel = values.get("get_channel", lambda _cid: FakeChannel(id=1))
        values = {key: value for key, value in values.items()
                  if key not in {"get_channel", "get_guilds"}}
        values["dispatch_tool"] = self._dispatch_fixture
        values["publish_notice"] = self._publish_fixture
        super().__init__(RealDeps(**values))
        self._observer = None

    async def _dispatch_fixture(self, message, name, values):
        from src.desktop.core import CoreService

        # Invoke the production parent-to-child admission seam. The frozen
        # external tool-effect mock remains the dispatch boundary, not authority.
        facade = SimpleNamespace(requests=self.graph.requests,
            engine=SimpleNamespace(runner=SimpleNamespace(
                dispatch_loop_tool=self._tool_loop.dispatch_loop_tool_inner)))
        return await CoreService._dispatch_scheduled_tool(facade, message, name, values)

    async def _publish_fixture(self, message, text):
        self.graph.requests.assert_bound_request(message)
        await self.graph.requests.delivery.send(message.channel, text)
        if self._observer is not None:
            await self._observer.send(text)

    @asynccontextmanager
    async def _admitted(self, observer):
        graph = self.graph
        authority = graph.requests.authority
        message = graph.requests._register_background("schedule", uuid4().hex,
            "Frozen scheduler callback", graph.cid, authority.owner_id)
        self._observer = observer
        async with graph.requests.background_execution(message):
            token = _scheduled_execution.set((self, message))
            try:
                yield message
            finally:
                _scheduled_execution.reset(token)

    def _schedule(self, schedule):
        return {**schedule, "conversation_id": self.graph.cid,
                "requester_id": self.graph.requests.authority.owner_id}

    async def _on_scheduled_digest(self, schedule):
        if _scheduled_execution.get() is not None:
            return await super()._on_scheduled_digest(self._schedule(schedule))
        async with self._admitted(self._get_channel(schedule.get("channel_id"))):
            return await super()._on_scheduled_digest(self._schedule(schedule))

    async def _on_scheduled_task(self, schedule):
        async with self._admitted(self._get_channel(schedule.get("channel_id"))):
            return await super()._on_scheduled_task_inner(self._schedule(schedule))

    async def _format_digest_raw(self, schedule, channel):
        if _scheduled_execution.get() is not None:
            return await super()._format_digest_raw(self._schedule(schedule), self.graph.cid)
        async with self._admitted(channel):
            return await super()._format_digest_raw(self._schedule(schedule), self.graph.cid)

    async def _execute_scheduled_tool(self, tool_name, tool_input, channel,
                                      requester_id, requester_name="scheduler"):
        owner = self.graph.requests.authority.owner_id
        if _scheduled_execution.get() is not None:
            return await super()._execute_scheduled_tool(tool_name, tool_input,
                self.graph.cid, owner, requester_name)
        async with self._admitted(channel):
            return await super()._execute_scheduled_tool(tool_name, tool_input,
                self.graph.cid, owner, requester_name)

    async def _run_scheduled_workflow(self, channel, schedule):
        if _scheduled_execution.get() is not None:
            return await super()._run_scheduled_workflow(self.graph.cid, self._schedule(schedule))
        async with self._admitted(channel):
            return await super()._run_scheduled_workflow(self.graph.cid, self._schedule(schedule))

    async def _on_schedule_failure(self, schedule, consecutive):
        async with self._admitted(self._get_channel(schedule.get("channel_id"))):
            return await super()._on_schedule_failure_inner(self._schedule(schedule), consecutive)


def make_bot(fake_llm=None):
    graph = _graph.get()
    deps = graph.engine.deps
    executor = MagicMock(check_permission=MagicMock(return_value=""),
                         execute=AsyncMock(return_value="done"))
    loop = SimpleNamespace(_tool_catalog=deps.tool_catalog)

    async def dispatch(name, values, message, owner):
        graph.requests.assert_request(message)
        return await executor.execute(name, values, user_id=owner)

    loop.dispatch_loop_tool_inner = dispatch
    bot = SimpleNamespace(tool_executor=executor, get_channel=lambda _cid: FakeChannel(id=1))
    bot.scheduled_events = ScheduledEventHandlers(dict(get_config=deps.get_config,
        get_channel=lambda cid: bot.get_channel(cid), tool_executor=executor,
        audit=MagicMock(log_execution=AsyncMock(), log_event=AsyncMock()),
        llm_gateway=SimpleNamespace(active_client=None), tool_loop=loop,
        agent_task_tools=deps.native_owners["agents"]))
    return bot


def collect_tools(wait_result):
    graph = _graph.get()
    graph.engine.deps.agent_manager.wait_for_agents = AsyncMock(return_value=wait_result)
    return graph.engine.deps.native_owners["agents"]


def _handlers(**values):
    return load_suite("test_scheduled_events")._handlers(**values)


def adapted_tree(stem):
    path = "tests/" + stem + ".py"
    source = frozen_source(path)
    if hashlib.sha256(source).hexdigest() != SUITES[stem]:
        raise AssertionError("frozen source hash changed")
    original = ast.parse(source)
    corpus_digest = hashlib.sha256(
        json.dumps(corpus(original), sort_keys=True).encode()
    ).hexdigest()
    if corpus_digest != CORPUS_HASHES[stem]:
        raise AssertionError("frozen corpus digest changed")
    tree = ast.parse(source)
    hunks = []
    for symbol, node in list(nodes(tree)):
        replacement = None
        if isinstance(node, ast.ImportFrom) and node.module in {
                "src.discord.scheduled_events", "tests.fakes", "tests.test_scheduled_events"}:
            replacement = ast.ImportFrom(module=__name__, names=node.names, level=0)
        is_agent_manager_factory = (
            isinstance(node, ast.FunctionDef)
            and node.name == "_make_tools_with_agent_manager"
        )
        if stem == "test_scheduled_workflow" and is_agent_manager_factory:
            replacement = ast.parse(
                "def _make_tools_with_agent_manager(wait_result: dict):\n"
                "    return collect_tools(wait_result)"
            ).body[0]
            replacement.decorator_list = node.decorator_list
        if replacement is None:
            continue
        hunks.append({"symbol": symbol, "line": node.lineno,
            "before_sha256": hashlib.sha256(dump(node).encode()).hexdigest(),
            "after_sha256": hashlib.sha256(dump(replacement).encode()).hexdigest(),
            "after_source": ast.unparse(replacement)})

        class Replace(ast.NodeTransformer):
            def visit(self, value):
                if value is node:
                    return ast.copy_location(replacement, value)
                return super().visit(value)

        tree = Replace().visit(tree)
    ast.fix_missing_locations(tree)
    report_path = ROOT / "maintenance/lane6-schedules-core-report.json"
    declared = json.loads(report_path.read_text())["hunks"][path]
    if hunks != declared:
        raise AssertionError("exact setup hunks changed")
    if corpus(original) != corpus(tree):
        raise AssertionError("frozen assertion/signature/decorator/parameter corpus changed")
    return source, original, tree, hunks


def load_suite(stem):
    source, original, tree, hunks = adapted_tree(stem)
    module = ModuleType("lane6_schedules_core_" + stem.replace("/", "_"))
    module.__file__ = "tests/" + stem + ".py"
    module.collect_tools = collect_tools
    exec(compile(tree, module.__file__, "exec"), module.__dict__)
    return module


def register_module(namespace, stem):
    module = load_suite(stem)
    excluded = {*RETIRED_CASES.get(stem, {}), *DEFERRED_CASES.get(stem, {})}
    prefix = stem.replace("/", "_")
    for name, value in vars(module).items():
        if name.startswith("test_") and name not in excluded:
            namespace[f"test_lane6_schedules_core_{prefix}__{name}"] = value
        elif name.startswith("Test") and isinstance(value, type):
            copied = {key: val for key, val in vars(value).items()
                      if key not in {"__dict__", "__weakref__"} and
                      (not key.startswith("test_") or name + "." + key not in excluded)}
            if any(key.startswith("test_") for key in copied):
                namespace[f"TestLane6_schedules_core_{prefix}_{name}"] = type(name, (), copied)
    for name, value in vars(module).items():
        is_pytest_fixture = getattr(value, "_pytestfixturefunction", None) is not None
        if is_pytest_fixture or hasattr(value, "_fixture_function"):
            namespace[name] = value


def load(namespace):
    for stem in CORPUS_SELECTIONS:
        register_module(namespace, stem)
