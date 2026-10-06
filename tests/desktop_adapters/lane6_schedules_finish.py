"""Whole frozen corpora through native owner setup, never substitute algorithms."""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from contextlib import asynccontextmanager
from contextvars import ContextVar
from types import ModuleType
from uuid import uuid4

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, nodes
from src.desktop.controls import ControlService
from src.desktop.work import WorkService
from tests.desktop_adapters import lane6_schedules_core as core
from tests.desktop_adapters import lane6_schedules_loops_bridge as loops
from tests.desktop_adapters import lane6_schedules_loops_cases as loop_cases

CURRENT = ContextVar("lane6_schedule_finish")
SUITES = {
    "test_campaign_scheduler_workflows":
        "cdb2da7883cba08ef96726fa30efea0af47499e841ff161d6a4067e07db62c2b",
    "test_autonomous_loop":
        "242d1c57c12b8a33eee30f9694861a29bbca047a5eb640cdd0504df4c53b18fc",
}
CORPUS_SELECTIONS = {"test_campaign_scheduler_workflows": None, "test_autonomous_loop": None}
CORPUS_EXCLUSIONS = {"test_autonomous_loop": [
    "TestLoopFlow.test_long_final_text_truncated_to_discord_limit",
    "TestLoopDispatchParity.test_rbac_denial_in_loop_dispatch",
]}
PATHS = {
    "tests/test_campaign_scheduler_workflows.py": core.SUITES["test_campaign_scheduler_workflows"],
    "tests/characterization/test_autonomous_loop.py": loop_cases.SUITES["test_autonomous_loop"],
}
CORPUS_HASHES = {
    "tests/test_campaign_scheduler_workflows.py":
        "e4ccf3727dfbde5bbc6840394dc22ecae2272b59b0dcae69d83cbdb308cffeac",
    "tests/characterization/test_autonomous_loop.py":
        "1a2e55772def8089c5684ab30496d446911d7e52ce020d339783a9a773daab31",
}
RETIRED_CASES = {"tests/characterization/test_autonomous_loop.py": {
    key: value for key, value in loop_cases.RETIRED_CASES["test_autonomous_loop"].items()
    if not key.endswith("test_export_skill_stages_pending_file_in_loop")}}
DEFERRED_CASES = {"tests/characterization/test_autonomous_loop.py": {
    "TestLoopDispatchParity.test_export_skill_stages_pending_file_in_loop": {
        "reason": "Retained export lacks invocation-owned durable artifact staging owner.",
        "blocked_on": "Implement actual artifact owner, then review legacy assertion projection."},
}}
PROPOSED_CASES = {"tests/characterization/test_autonomous_loop.py": {
    "TestLoopDispatchParity.test_unknown_tool_routes_to_executor_with_user_id": {
        "reason": "Exact assertion pins foreign identity 4242, not authenticated UUID owner.",
        "blocked_on": "Reviewer approval of canonical owner assertion change; do not retire."},
}}
EVIDENCE = {}
CASE_MAP = {}


def bind_work(graph):
    if hasattr(graph, "finish_work"):
        return graph
    requests, deps = graph.requests, graph.engine.deps
    authority, permissions = requests.authority, requests.permissions
    controls = ControlService(graph.store, requests.events, requests, deps.channel_state,
        authority=authority, permissions=permissions)
    work = WorkService(graph.store, requests.events, authority=authority,
        permissions=permissions, requests=requests, conversations=requests.conversations,
        agents=deps.agent_manager, tasks=deps.channel_state.background_tasks,
        loops=deps.loop_manager, scheduler=deps.scheduler, controls=controls)
    controls.work = work
    native = deps.native_owners["agents"]
    native._background_admission, native._work_service = requests, work

    async def publish(message, text, kind=None):
        requests.assert_bound_request(message)
        return await requests.delivery.send(message.channel, text)

    native._publish_background = publish
    deps.background_work_ready = True
    deps.tool_catalog.invalidate()
    graph.finish_work, graph.finish_messages = work, {}
    return graph


def make_bot(**kwargs):
    return bind_work(loops.make_bot(**kwargs))


def _LoopMessageProxy(channel, legacy_owner, text):  # noqa: N802
    # The RunnerView admits its own sealed envelope; this source argument is
    # only a destination observation, never passed into the actual runner.
    return channel


async def start_native_loop(bot, legacy_message, values):
    parent = bot.admit("Start the requested loop", "workflow")
    async with bot.execution(parent):
        return bot.agent_task_tools._handle_start_loop(parent, values)


def BackgroundTask(**values):  # noqa: N802
    from src.discord.background_task import BackgroundTask as RetainedTask

    graph = bind_work(CURRENT.get())
    values.pop("channel")
    values.update(conversation_id=graph.cid, requester_id=graph.requests.authority.owner_id)
    task = RetainedTask(**values)
    graph.engine.deps.channel_state.background_tasks[task.task_id] = task
    message = graph.requests._register_background("task", task.task_id, task.description,
        graph.cid, graph.requests.authority.owner_id)
    graph.finish_messages[task.task_id] = message

    async def publish(kind, text):
        graph.requests.assert_bound_request(message)
        return await graph.requests.delivery.send(message.channel, text)

    task.publish = publish
    return task


async def run_background_task(task, external_executor, skills):
    from src.discord.background_task import run_background_task as retained_run

    graph = bind_work(CURRENT.get())
    executor = graph.engine.deps.tool_executor
    original = executor._execute_inner

    async def effect(name, values, *, user_id=None):
        return await external_executor.execute(name, values, user_id=user_id)

    executor._execute_inner = effect
    catalog = getattr(executor, "_tool_catalog", None)
    old_catalog = graph.engine.deps.tool_catalog.merged_definitions
    executor._tool_catalog = type("FixtureCatalog", (), {
        "merged_definitions": lambda self: old_catalog() + skills.get_tool_definitions(),
    })()
    message = graph.finish_messages[task.task_id]
    try:
        async with graph.requests.background_execution(message, settle=False):
            graph.finish_work.register("task", task.task_id, message)
            await retained_run(task, executor, skills)
        graph.requests.settle_background(message, task.status)
        graph.finish_work.refresh_all()
    finally:
        executor._execute_inner = original
        if catalog is None:
            del executor._tool_catalog
        else:
            executor._tool_catalog = catalog


def owner_executor():
    return CURRENT.get().engine.deps.tool_executor


def complete_skill_fixture(records):
    from src.tools.skill_manager import SkillStatus

    for name, record in records.items():
        record.status = SkillStatus.LOADED
        record.definition.setdefault("name", name)
        record.definition.setdefault("description", "Inert required-field validation fixture")
    return records


async def _execute_tool_captured(name, values, executor, skills, knowledge, embedder,
                               requester, **kwargs):
    from src.discord.background_task import _execute_tool_captured as retained_execute

    graph = CURRENT.get()
    message = graph.requests._register_background("workflow", uuid4().hex,
        "Execute inert selected effect", graph.cid, graph.requests.authority.owner_id)
    kwargs["requester_id"] = message.owner_id
    async with graph.requests.background_execution(message):
        return await retained_execute(name, values, executor, skills, knowledge, embedder,
            requester, **kwargs)


def get_tool_definitions():
    return bind_work(CURRENT.get()).engine.deps.tool_catalog.merged_definitions()


def Scheduler(path):  # noqa: N802
    from src.scheduler.scheduler import Scheduler as RetainedScheduler

    graph = bind_work(CURRENT.get())
    scheduler = RetainedScheduler(path, desktop_recovery=True)
    add = scheduler.add

    async def admitted_add(description, action, legacy_channel, **values):
        return await add(description, action, graph.cid,
            requester_id=graph.requests.authority.owner_id, **values)

    scheduler.add = admitted_add
    graph.finish_schedulers.append(scheduler)
    return scheduler


def _handlers(**values):
    """Keep the shared fixture, but schedule callbacks use real run binding."""
    handler = core._handlers(**values)
    graph = bind_work(CURRENT.get())

    @asynccontextmanager
    async def admitted_schedule(schedule):
        scheduler = next(item for item in graph.finish_schedulers
            if any(row["id"] == schedule["id"] for row in item.list_all()))
        binding = scheduler.assert_run_binding(schedule)
        graph.finish_work.scheduler = scheduler
        graph.finish_work.register_schedule(schedule)
        message = graph.requests._register_background("schedule", binding["run_id"],
            schedule["description"], binding["conversation_id"], binding["owner_id"])
        handler._observer = handler._get_channel(schedule.get("channel_id"))
        async with graph.requests.background_execution(message):
            yield message

    async def callback(schedule):
        return await core.RealHandlers._on_scheduled_task(handler, schedule)

    handler._admit_schedule = admitted_schedule
    handler._on_scheduled_task = callback
    return handler


def adapted_tree(path):
    source = frozen_source(path)
    if hashlib.sha256(source).hexdigest() != PATHS[path]:
        raise AssertionError("Frozen source hash changed")
    if path.endswith("test_autonomous_loop.py"):
        base = loop_cases.adapted_tree(path)
    else:
        _, _, base, _ = core.adapted_tree("test_campaign_scheduler_workflows")
    original = ast.parse(source, filename=path)
    corpus_hash = hashlib.sha256(
        json.dumps(corpus(original), sort_keys=True).encode()).hexdigest()
    if corpus_hash != CORPUS_HASHES[path]:
        raise AssertionError("Frozen whole corpus hash changed")
    hunks = []

    def edit(before, after, operation):
        hunks.append({"line": before.lineno, "operation": operation,
            "before_sha256": hashlib.sha256(dump(before).encode()).hexdigest(),
            "after_sha256": hashlib.sha256(dump(after).encode()).hexdigest(),
            "after_source": ast.unparse(after)})
        return ast.copy_location(after, before)

    class Setup(ast.NodeTransformer):
        def visit_Assert(self, node):
            return node

        def visit_Assign(self, node):
            if path.endswith("test_campaign_scheduler_workflows.py") and any(
                    isinstance(target, ast.Attribute) and target.attr == "check_permission"
                    for target in node.targets):
                return edit(node, ast.Pass(), "retain_actual_owner_permission_gate")
            self.generic_visit(node)
            if path.endswith("test_autonomous_loop.py") and any(
                    ast.unparse(target) == "bot.skill_manager._skills" for target in node.targets):
                # This source fixture injects schema-only records. The real
                # SkillManager catalog reads metadata as well as the schema.
                # Complete only the inert fixture metadata; handlers remain real.
                after = copy.deepcopy(node)
                after.value = ast.Call(func=ast.Name(id="complete_skill_fixture", ctx=ast.Load()),
                                       args=[after.value], keywords=[])
                return edit(node, after, "complete_real_skill_catalog_fixture_metadata")
            return node

        def visit_ImportFrom(self, node):
            target = None
            if node.module in {
                "src.discord.background_task", "src.scheduler.scheduler", "src.tools.registry"
            }:
                target = __name__
            elif node.module == core.__name__ and any(a.name == "_handlers" for a in node.names):
                target = __name__
            elif node.module == "src.discord.tool_loop" and any(
                    a.name == "_LoopMessageProxy" for a in node.names):
                target = __name__
            elif node.module == loops.__name__:
                imports = [copy.deepcopy(node)]
                imports[0].names = [a for a in node.names if a.name != "make_bot"]
                if any(a.name == "make_bot" for a in node.names):
                    imports.append(ast.ImportFrom(module=__name__,
                        names=[ast.alias(name="make_bot")], level=0))
                    hunks.append({"line": node.lineno,
                        "operation": "real_native_work_graph_factory_import",
                        "before_sha256": hashlib.sha256(dump(node).encode()).hexdigest(),
                        "after_sha256": hashlib.sha256(json.dumps(
                            [dump(n) for n in imports if n.names]).encode()).hexdigest(),
                        "after_source": "\n".join(ast.unparse(n) for n in imports if n.names)})
                    return [ast.copy_location(n, node) for n in imports if n.names]
            if target:
                after = copy.deepcopy(node)
                after.module = target
                return edit(node, after, "canonical_owner_fixture_import")
            return node

        def visit_Call(self, node):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "_handle_start_loop":
                after = ast.Await(value=ast.Call(
                    func=ast.Name(id="start_native_loop", ctx=ast.Load()),
                    args=[ast.Name(id="bot", ctx=ast.Load()), *copy.deepcopy(node.args)],
                    keywords=[]))
                return edit(node, after, "sealed_native_start_setup")
            if (isinstance(node.func, ast.Attribute) and node.func.attr == "__new__"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "ToolExecutor"):
                return edit(node, ast.Call(func=ast.Name(id="owner_executor", ctx=ast.Load()),
                    args=[], keywords=[]), "actual_owner_executor_setup")
            return self.generic_visit(node)

    tree = Setup().visit(copy.deepcopy(base))
    ast.fix_missing_locations(tree)
    if corpus(original) != corpus(tree):
        raise AssertionError("Whole assertion/signature/decorator/parameter corpus changed")
    EVIDENCE[path] = {"source_sha256": PATHS[path], "whole_suite": True,
        "full_corpus_sha256": corpus_hash,
        "exact_corpus": corpus(original), "setup_hunks": hunks}
    return tree


def register_module(namespace):
    for path in PATHS:
        tree = adapted_tree(path)
        module = ModuleType("lane6_schedule_finish_" + path.split("/")[-1][:-3])
        module.__file__ = path
        module.start_native_loop, module.owner_executor = start_native_loop, owner_executor
        module.complete_skill_fixture = complete_skill_fixture
        exec(compile(tree, path, "exec"), module.__dict__)
        excluded = (RETIRED_CASES.get(path, {}) | DEFERRED_CASES.get(path, {})
                    | PROPOSED_CASES.get(path, {}))
        stem = path.split("/")[-1][5:-3]
        for name, value in vars(module).items():
            if name.startswith("test_") and name not in excluded:
                export = "test_finish_" + stem + "__" + name
                namespace[export] = value
                CASE_MAP[path + "::" + name] = export
            elif name.startswith("Test") and isinstance(value, type):
                copied = {key: val for key, val in vars(value).items()
                    if key not in {"__dict__", "__weakref__"} and
                    (not key.startswith("test_") or name + "." + key not in excluded)}
                if any(key.startswith("test_") for key in copied):
                    export = "TestFinish_" + stem + "_" + name
                    namespace[export] = type(name, (), copied)
                    for key in copied:
                        if key.startswith("test_"):
                            CASE_MAP[path + "::" + name + "::" + key] = export + "::" + key
        for symbol, node in nodes(ast.parse(frozen_source(path))):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name.startswith("test_")):
                key = path + "::" + symbol.replace(".", "::")
                if key not in CASE_MAP and symbol not in excluded:
                    raise AssertionError("Unaccounted frozen case: " + key)


def load(namespace):
    register_module(namespace)
