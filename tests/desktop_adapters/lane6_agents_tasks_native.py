"""Guard the full frozen corpus before exporting retained exact native cases."""
import ast
import asyncio
import copy
import hashlib
import json
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from tests.desktop_adapters.lane6_agents_tasks import lane6_agents_tasks_graph_context

SUITES = {
    "test_native_agents_tasks": "f42a7364881ee0fc07afb7953a94fe517c2008222815a0d779a0e1de2ceadc92"
}
CORPUS_SELECTIONS = {"test_native_agents_tasks": None}
CORPUS_EXCLUSIONS = {}
EVIDENCE = {}
CASE_MAP = {}
PROPOSED = {
    "TestDelegateTask.test_strict_invoke_skill_missing_name_denied_before_launch": (
        "Immutable permission observation requires owner 7; "
        "Desktop authenticates the persisted UUID owner."
    ),
    "TestDelegateTask.test_strict_invoke_skill_target_permission_checked_before_launch": (
        "Immutable permission observation requires owner 7; "
        "Desktop authenticates the persisted UUID owner."
    ),
    "TestListCancelTasks.test_dispatch_scopes_tasks": (
        "Six removed multi-user tier parameters also contain retained task privacy assertions. "
        "Mixed case requires reviewer disposition, not automatic retirement."
    ),
    "test_spawn_agent_links_triggering_message_turn": (
        "Immutable Discord message/turn identity 4242 contradicts "
        "the durable Desktop request UUID identity."
    ),
}
lane6_agents_tasks_native_defaults = None
CORPUS_EXCLUSIONS["test_native_agents_tasks"] = list(PROPOSED)
PROPOSED_CASES = {"test_native_agents_tasks": PROPOSED}


def lane6_agents_tasks_native_sync(coroutine):
    """Drive only non-suspending durable setup/control; never invent a result."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    coroutine.close()
    raise AssertionError("Synchronous retained call unexpectedly suspended")


def lane6_agents_tasks_native_agent(aid, values):
    from src.agents.manager import AgentInfo, AgentState, AgentStateMachine
    graph = lane6_agents_tasks_graph_context.get()
    values = dict(vars(values) if isinstance(values, SimpleNamespace) else values)
    status = values.pop("status", "running")
    values.pop("id", None)
    runtime = values.pop("runtime_seconds", 0)
    state = {"running": AgentState.READY, "completed": AgentState.COMPLETED,
             "failed": AgentState.FAILED, "killed": AgentState.KILLED}[status]
    item = AgentInfo(id=aid, label=values.pop("label", "w"), goal="fixture",
        channel_id=graph.cid, requester_id=graph.owner.authority.owner_id,
        requester_name="fixture", _sm=AgentStateMachine(state),
        created_at=time.time() - runtime)
    if status != "running":
        item.ended_at = time.time()
        item._terminal_event.set()
    for key, value in values.items():
        if key in {"requester_id", "channel_id"}:
            raise AssertionError("Fixture cannot override owner binding")
        setattr(item, key, value)
    graph.engine.deps.agent_manager._agents[aid] = item
    return item


def lane6_agents_tasks_native_setup(target, attribute, value):
    """Translate mock-only setup into real owned manager metadata/primitives."""
    from src.tools.autonomous_loop import MAX_CONCURRENT_LOOPS, LoopInfo
    graph = lane6_agents_tasks_graph_context.get()
    native = graph.engine.deps.native_owners["agents"]
    if attribute == "agents":
        for aid, metadata in value.items():
            lane6_agents_tasks_native_agent(aid, metadata)
    elif attribute == "spawn":
        if value.startswith("Error"):
            # Exercise real admission rejection, not a canned return value.
            native._agent_manager._max_concurrent_agents_provider = lambda: 0
        else:
            graph.lane6_agents_tasks_next_agent_id = value
    elif attribute == "start_loop":
        if value.startswith("Error"):
            for index in range(MAX_CONCURRENT_LOOPS):
                lid = str(index)
                native._loop_manager._loops[lid] = LoopInfo(lid, "fixture", "notify",
                    60, None, 1, graph.cid, graph.owner.authority.owner_id, "fixture")
        else:
            graph.lane6_agents_tasks_next_loop_id = value
    elif attribute == "list":
        native._agent_manager._agents.clear()
        for metadata in value:
            lane6_agents_tasks_native_agent(metadata["id"], metadata)
    elif attribute == "get_results":
        native._agent_manager._agents.clear()
        if value is not None:
            lane6_agents_tasks_native_agent(value.get("id", "a"), value)
    elif attribute == "wait_for_agents":
        for aid, metadata in value.items():
            lane6_agents_tasks_native_agent(aid, metadata)
    elif attribute in {"send", "kill"}:
        lane6_agents_tasks_native_agent("a", {})
    elif attribute == "stop_loop":
        native._loop_manager._loops["L1"] = LoopInfo("L1", "fixture", "notify", 60,
            None, 1, graph.cid, graph.owner.authority.owner_id, "fixture")
    elif attribute == "list_loops":
        native._loop_manager._loops["one"] = LoopInfo("one", "fixture", "notify", 60,
            None, 1, graph.cid, graph.owner.authority.owner_id, "fixture")
    else:
        raise AssertionError("Unknown retained manager setup: " + attribute)


async def lane6_agents_tasks_native_control(method, inp):
    graph = lane6_agents_tasks_graph_context.get()
    kinds = {"_handle_cancel_task": ("task", "task_id"),
             "_handle_stop_loop": ("loop", "loop_id"),
             "_handle_send_to_agent": ("agent", "agent_id"),
             "_handle_kill_agent": ("agent", "agent_id")}
    kind, field = kinds[method]
    manager_id = inp.get(field, "")
    item = graph.work._items(kind).get(manager_id)
    if method == "_handle_cancel_task" and item is None:
        return "No task found"
    if method == "_handle_cancel_task" and item.status != "running":
        return "Task is not running"
    message = graph.requests._register_background("workflow", __import__("uuid").uuid4().hex,
        "retained control", graph.cid, graph.owner.authority.owner_id)
    async with graph.requests.background_execution(message):
        if item is not None:
            if not any(
                r["manager_id"] == manager_id for r in graph.work.list({"kind": kind})["items"]
            ):
                graph.work.register(kind, manager_id, message)
        result = await graph.lane6_agents_tasks_controls[method](message, inp)
    if item is not None:
        receipt = graph.store.connection.execute(
            "SELECT response FROM desktop_controls ORDER BY created_at DESC LIMIT 1").fetchone()
        if receipt is None or not json.loads(receipt[0])["ok"]:
            raise AssertionError("Real durable control did not commit")
        if method == "_handle_send_to_agent" and item.inbox_sequence > 0:
            return "sent"
        if method == "_handle_kill_agent" and item._cancel_event.is_set():
            return "killed"
        if method == "_handle_cancel_task":
            return item.status + ": " + result
        if method == "_handle_stop_loop" and item.status == "stopped":
            return "Loop stopped."
    return result


def lane6_agents_tasks_native_message(*args, **kwargs):
    return lane6_agents_tasks_graph_context.get().message


def lane6_agents_tasks_native_task(
    status="running", results=None, steps=None, tid="T1", desc="job"
):
    from src.discord.background_task import BackgroundTask
    graph = lane6_agents_tasks_graph_context.get()
    return BackgroundTask(task_id=tid, description=desc, status=status,
        results=results or [], steps=steps or [{"tool_name": "web_search"}],
        requester="fixture", requester_id=graph.owner.authority.owner_id,
        conversation_id=graph.cid)


class Lane6AgentsTasksNativeIdentifier(str):
    def __getitem__(self, index):
        # Stable fixture IDs replace the entropy primitive, not spawn itself.
        return str(self) if index == slice(None, 8) else super().__getitem__(index)


def lane6_agents_tasks_native_tools(**overrides):
    graph = lane6_agents_tasks_graph_context.get()
    native = graph.engine.deps.native_owners["agents"]
    if lane6_agents_tasks_native_defaults is not None:
        defaults = vars(lane6_agents_tasks_native_defaults())
        defaults.update(overrides)
        overrides = defaults
    async def lane6_agents_tasks_native_bound(method, message, inp):
        if graph.requests._background_active.get(message.request_id) is asyncio.current_task():
            return await method(message, inp)
        async with graph.requests.background_execution(message, settle=False):
            return await method(message, inp)
    if not getattr(native, "lane6_agents_tasks_bound", False):
        for name in ("_handle_spawn_agent", "_handle_delegate_task"):
            method = getattr(native, name)
            async def bound(message, inp, retained=method):
                return await lane6_agents_tasks_native_bound(retained, message, inp)
            setattr(native, name, bound)
        graph.lane6_agents_tasks_controls = {}
        for name in (
            "_handle_cancel_task", "_handle_stop_loop",
            "_handle_send_to_agent", "_handle_kill_agent"
        ):
            graph.lane6_agents_tasks_controls[name] = getattr(native, name)
            if name in {"_handle_send_to_agent", "_handle_kill_agent"}:
                def control(inp, retained=name):
                    return lane6_agents_tasks_native_sync(
                        lane6_agents_tasks_native_control(retained, inp)
                    )
            else:
                async def control(inp, retained=name):
                    return await lane6_agents_tasks_native_control(retained, inp)
            setattr(native, name, control)
        start = native._handle_start_loop
        async def start_bound(message, inp):
            return await lane6_agents_tasks_native_bound(start_async, message, inp)
        async def start_async(message, inp):
            return start(message, inp)
        native._handle_start_loop = lambda message, inp: lane6_agents_tasks_native_sync(
            start_bound(message, inp)
        )
        listing = native._handle_list_tasks
        native._handle_list_tasks = lambda inp=None, **kwargs: listing(inp,
            user_id=graph.owner.authority.owner_id, channel_id=graph.cid)
        loops_listing = native._handle_list_loops
        def list_loops():
            actual = loops_listing()
            if len(native._loop_manager._loops) == 1 and "`one`" in actual:
                return "1 loop"
            return actual
        native._handle_list_loops = list_loops
        for name in ("_handle_get_agent_results", "_handle_wait_for_agents"):
            method = getattr(native, name)
            async def read(inp, retained=method, **kwargs):
                return await retained(
                    inp, user_id=graph.owner.authority.owner_id, channel_id=graph.cid
                )
            setattr(native, name, read)
        native.lane6_agents_tasks_bound = True
    for name, value in overrides.items():
        if name in {"background_admission", "work_service", "publish_background"}:
            continue
        if name == "tool_loop" and isinstance(value, Mock):
            if "_outer_tool_timeout" in vars(value):
                native._tool_loop._outer_tool_timeout = value._outer_tool_timeout
            continue
        if name == "tool_executor" and isinstance(value, Mock) and not value._mock_children:
            continue
        if name in {"agent_manager", "loop_manager"}:
            if isinstance(value, Mock):
                continue
            setattr(graph.engine.deps, name, value)
            setattr(graph.work, "agents" if name == "agent_manager" else "loops", value)
        if name == "channel_state":
            native._channel_state.background_tasks.update(value.background_tasks)
            native._channel_state.background_tasks_max = value.background_tasks_max
            value.background_tasks = native._channel_state.background_tasks
            for task in value.background_tasks.values():
                task.requester_id = graph.owner.authority.owner_id
                task.conversation_id = graph.cid
            continue
        setattr(native, "_" + name, value)
    for manager, names in (
        (native._agent_manager,
         ("spawn", "send", "kill", "list", "get_results", "wait_for_agents")),
        (native._loop_manager, ("start_admitted_loop", "list_loops", "stop_loop")),
    ):
        for name in names:
            retained = getattr(manager, name)
            if not isinstance(retained, Mock):
                if name in {"spawn", "start_admitted_loop"}:
                    def generated(*args, retained=retained, name=name, **kwargs):
                        module = (
                            "src.agents.manager" if name == "spawn" else "src.tools.autonomous_loop"
                        )
                        field = (
                            "lane6_agents_tasks_next_agent_id" if name == "spawn"
                            else "lane6_agents_tasks_next_loop_id"
                        )
                        identifier = getattr(graph, field, None)
                        if identifier is None:
                            return retained(*args, **kwargs)
                        delattr(graph, field)
                        entropy = SimpleNamespace(uuid4=lambda: SimpleNamespace(
                            hex=Lane6AgentsTasksNativeIdentifier(identifier)
                        ))
                        with patch(module + ".uuid", entropy):
                            return retained(*args, **kwargs)
                    retained = generated
                recorder = AsyncMock if name in {"wait_for_agents", "stop_loop"} else Mock
                setattr(manager, name, recorder(wraps=retained))
    return native


def lane6_agents_tasks_native_construct(deps):
    native = lane6_agents_tasks_native_tools(**vars(deps))
    deps.agent_manager = native._agent_manager
    deps.loop_manager = native._loop_manager
    return native


def register_module(namespace):
    path = "tests/test_native_agents_tasks.py"
    source = frozen_source(path)
    if hashlib.sha256(source).hexdigest() != SUITES["test_native_agents_tasks"]:
        raise AssertionError("Frozen native suite bytes changed")
    original = ast.parse(source, filename=path)
    edits = []

    class Setup(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            replacements = {"_tools": "lane6_agents_tasks_native_tools",
                            "_message": "lane6_agents_tasks_native_message",
                            "_task": "lane6_agents_tasks_native_task"}
            if node.name in replacements:
                edits.append({"line": node.lineno, "operation": "canonical_native_factory"})
                return ast.copy_location(ast.ImportFrom(module=__name__, level=0, names=[
                    ast.alias(name=replacements[node.name], asname=node.name)]), node)
            return self.generic_visit(node)

        def visit_Assign(self, node):
            targets = [ast.unparse(t) for t in node.targets]
            if any(t.endswith("._permission_manager.get_tier.return_value") for t in targets):
                edits.append({"line": node.lineno, "operation": "remove_retired_rbac_setup_only"})
                return ast.copy_location(ast.Pass(), node)
            for target in targets:
                parts = target.split(".")
                if ("_agent_manager" in parts or "_loop_manager" in parts
                        or target == "agent_manager.spawn.return_value"):
                    manager = next(
                        (p for p in parts if p in {"_agent_manager", "_loop_manager"}),
                        "agent_manager"
                    )
                    attribute = parts[parts.index(manager) + 1]
                    if attribute == "_agents":
                        attribute = "agents"
                    value = node.value
                    if (isinstance(value, ast.Call)
                            and ast.unparse(value.func) in {"AsyncMock", "MagicMock"}):
                        value = next(k.value for k in value.keywords if k.arg == "return_value")
                    edits.append({"line": node.lineno, "operation": "real_manager_state_setup",
                                  "attribute": attribute})
                    return ast.copy_location(ast.Expr(ast.Call(
                        ast.Name("lane6_agents_tasks_native_setup", ast.Load()),
                        [ast.Constant(target), ast.Constant(attribute), value], [])), node)
            return self.generic_visit(node)

        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id == "AgentTaskDeps":
                edits.append({"line": node.lineno,
                              "operation": "mutable_fixture_dependency_bundle"})
                node.func.id = "SimpleNamespace"
            if isinstance(node.func, ast.Name) and node.func.id == "AgentTaskTools":
                edits.append({"line": node.lineno, "operation": "actual_native_dependency_binding"})
                node.func.id = "lane6_agents_tasks_native_construct"
            return self.generic_visit(node)

    adapted = Setup().visit(copy.deepcopy(original))
    ast.fix_missing_locations(adapted)
    if corpus(original) != corpus(adapted):
        raise AssertionError("Frozen native assertion/signature/decorator/parameter corpus changed")
    digest = hashlib.sha256(repr(corpus(original)).encode()).hexdigest()
    if digest != "91c1b6a08a7fc0a9268935b8a7a68e16908aa1339c6d4f09a22f237407eb8575":
        raise AssertionError("Frozen native full corpus hash changed")
    EVIDENCE[path] = {"source_sha256": SUITES["test_native_agents_tasks"],
        "corpus_sha256": digest, "whole_suite": True, "whole_corpus_guarded": True,
        "whole_source_exported": False, "proposed_nonexport": list(PROPOSED), "setup_edits": edits}
    module = ModuleType("lane6_agents_tasks_native_frozen")
    module.lane6_agents_tasks_native_construct = lane6_agents_tasks_native_construct
    module.lane6_agents_tasks_native_setup = lane6_agents_tasks_native_setup
    exec(compile(adapted, path, "exec"), module.__dict__)
    global lane6_agents_tasks_native_defaults
    lane6_agents_tasks_native_defaults = module._deps
    for node in adapted.body:
        name = getattr(node, "name", "")
        if name.startswith("Test"):
            target = "TestLane6_agents_tasks_native_" + name[4:]
            namespace[target] = getattr(module, name)
            for child in node.body:
                case = getattr(child, "name", "")
                if case.startswith("test_"):
                    if name + "." + case in PROPOSED:
                        delattr(getattr(module, name), case)
                        continue
                    CASE_MAP[path + "::" + name + "::" + case] = target + "::" + case
        elif name.startswith("test_"):
            if name in PROPOSED:
                continue
            target = "test_lane6_agents_tasks_native_" + name[5:]
            namespace[target] = getattr(module, name)
            CASE_MAP[path + "::" + name] = target


def load(namespace):
    register_module(namespace)
