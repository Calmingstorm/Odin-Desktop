"""Exact cancellation corpus through canonical task admission and publication."""
import ast
import copy
import hashlib
import uuid
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from tests.desktop_adapters.lane6_agents_tasks import lane6_agents_tasks_graph_context

SUITES = {
    "test_background_task_cancel": "e5addb75a7446519d799c6a6087f7142749e0496f1c6ef4e48b1012ab4528aec",
    "test_background_task_failure_visibility": "30720be2e4e3b64bbc7e97d8932d7e5e328ae43c055670da3897fcf92addcd78",
    "test_chat_tool_loop": "26ddac3a5df6fd9128e4cf18a0afd7f41590232f6389c803abbb953bf3aa6608",
}
CORPUS_SELECTIONS = {"test_background_task_cancel": None,
                     "test_background_task_failure_visibility": None,
                     "test_chat_tool_loop": None}
CORPUS_EXCLUSIONS = {}
EVIDENCE = {}
CASE_MAP = {}


class lane6_agents_tasks_retention:
    @property
    def _builtin_policy(self):
        return getattr(self, "lane6_agents_tasks_policy", None) or lane6_agents_tasks_graph_context.get().engine.deps.tool_executor._builtin_policy

    @_builtin_policy.setter
    def _builtin_policy(self, value):
        self.lane6_agents_tasks_policy = value

    def deliver_output(self, text, **kwargs):
        executor = lane6_agents_tasks_graph_context.get().engine.deps.tool_executor
        return executor.deliver_output(text, **kwargs)


def lane6_agents_tasks_background_task(**kwargs):
    from src.discord.background_task import BackgroundTask
    graph = lane6_agents_tasks_graph_context.get()
    channel = kwargs.pop("channel")
    kwargs["conversation_id"] = graph.cid
    kwargs["requester_id"] = graph.requests.authority.owner_id
    task = BackgroundTask(**kwargs)
    message = graph.requests._register_background("task", task.task_id,
        task.description, graph.cid, graph.requests.authority.owner_id)
    graph.engine.deps.channel_state.background_tasks[task.task_id] = task
    graph.lane6_agents_tasks_messages[task.task_id] = message

    async def publish(kind, text):
        receipt = await graph.requests.delivery.send(message.channel, text)
        if receipt is not None:
            channel.sent.append({"content": receipt["text"], "files": None})

    task.publish = publish
    return task


async def lane6_agents_tasks_run_background(task, *args, **kwargs):
    from src.discord.background_task import run_background_task
    graph = lane6_agents_tasks_graph_context.get()
    message = graph.lane6_agents_tasks_messages[task.task_id]
    async with graph.requests.background_execution(message):
        graph.work.register("task", task.task_id, message)
        return await run_background_task(task, *args, **kwargs)


class lane6_agents_tasks_cancel_owner:
    @property
    def _channel_state(self):
        return lane6_agents_tasks_graph_context.get().engine.deps.channel_state

    @_channel_state.setter
    def _channel_state(self, value):
        self._channel_state.background_tasks.update(value.background_tasks)

    async def _handle_cancel_task(self, inp):
        import json
        graph = lane6_agents_tasks_graph_context.get()
        task = self._channel_state.background_tasks.get(inp.get("task_id"))
        if task is None:
            return "No task found"
        if task.status != "running":
            return "Task is not running"
        message = graph.requests._register_background("workflow", uuid.uuid4().hex,
            "cancel retained task", graph.cid, graph.requests.authority.owner_id)
        async with graph.requests.background_execution(message):
            result = await graph.engine.deps.native_owners["agents"]._handle_cancel_task(message, inp)
        receipt = graph.store.connection.execute(
            "SELECT response FROM desktop_controls ORDER BY created_at DESC LIMIT 1").fetchone()
        if receipt is None:
            raise AssertionError("ControlService receipt was not committed")
        if json.loads(receipt[0])["result"]["disposition"] not in {"done", "requested"}:
            raise AssertionError("Cancellation was not dispatched")
        # Retained prose is an observation of the actual manager terminal state,
        # after authenticated durable control, not a substitute cancellation.
        return task.status + ": " + result


async def lane6_agents_tasks_send_progress(task, *args, **kwargs):
    from src.discord.background_task import _send_progress
    graph = lane6_agents_tasks_graph_context.get()
    message = graph.lane6_agents_tasks_messages[task.task_id]
    async with graph.requests.background_execution(message):
        graph.work.register("task", task.task_id, message)
        return await _send_progress(task, *args, **kwargs)


def register_module(namespace, suite="test_background_task_cancel"):
    path = ("tests/characterization/" if suite == "test_chat_tool_loop" else "tests/") + suite + ".py"
    source = frozen_source(path)
    if hashlib.sha256(source).hexdigest() != SUITES[suite]:
        raise AssertionError("Frozen cancellation source changed")
    original = ast.parse(source, filename=path)
    edits = []

    class Setup(ast.NodeTransformer):
        def visit_AsyncFunctionDef(self, node):
            if suite == "test_chat_tool_loop" and node.name == "run_loop":
                edits.append({"line": node.lineno, "operation": "canonical_bound_runner_setup"})
                return ast.copy_location(ast.ImportFrom(module=__name__, level=0, names=[
                    ast.alias(name="lane6_agents_tasks_chat_run", asname="run_loop")]), node)
            return self.generic_visit(node)

        def visit_ClassDef(self, node):
            if node.name in {"_InstantExecutor", "_BlockingExecutor", "_CancelThenRaise", "_FakeExecutor"}:
                edits.append({"line": node.lineno, "operation": "authenticated_executor_retention_setup"})
                node.bases.append(ast.Name(id="lane6_agents_tasks_retention", ctx=ast.Load()))
            return self.generic_visit(node)

        def visit_ImportFrom(self, node):
            replacements = {}
            if node.module == "src.discord.background_task":
                replacements = {"BackgroundTask": "lane6_agents_tasks_background_task",
                                "run_background_task": "lane6_agents_tasks_run_background",
                                "_send_progress": "lane6_agents_tasks_send_progress"}
            elif node.module == "src.discord.native_tools.agents_tasks":
                replacements = {"AgentTaskTools": "lane6_agents_tasks_cancel_owner"}
            elif suite == "test_chat_tool_loop" and node.module == "tests.fakes":
                replacements = {"FakeMessage": "lane6_agents_tasks_chat_message",
                                "make_bot": "lane6_agents_tasks_chat_bot"}
            swapped = [a for a in node.names if a.name in replacements]
            if not swapped:
                return node
            edits.append({"line": node.lineno, "operation": "canonical_task_control_publication_setup"})
            result = [ast.copy_location(ast.ImportFrom(module=__name__, level=0, names=[
                ast.alias(name=replacements[a.name], asname=a.asname or a.name)
                for a in swapped]), node)]
            retained = [a for a in node.names if a.name not in replacements]
            if retained:
                result.append(ast.copy_location(ast.ImportFrom(module=node.module,
                    level=node.level, names=retained), node))
            return result

    adapted = Setup().visit(copy.deepcopy(original))
    ast.fix_missing_locations(adapted)
    if len(edits) != (5 if suite == "test_background_task_cancel" else 2) or corpus(original) != corpus(adapted):
        raise AssertionError("Cancellation exact corpus changed")
    digest = hashlib.sha256(repr(corpus(original)).encode()).hexdigest()
    expected_corpus = ("17d42efcc12a836a1495684a6a7fd4cf674d8e8fff0c8f0676ae22fd7e834819"
        if suite == "test_background_task_cancel" else
        "76c08be68b5ca6c22d407ebd6854ae72e58fd201fdc683fb850e909dc28988a7"
        if suite == "test_chat_tool_loop" else
        "42c91ca115a6a1472a0e7cd58df6b352492d3e70399b681f2d92396698afebd2")
    if digest != expected_corpus:
        raise AssertionError("Pinned cancellation corpus changed")
    EVIDENCE[path] = {"source_sha256": SUITES[suite],
        "corpus_sha256": digest, "whole_suite": True, "setup_edits": edits}
    module = ModuleType("lane6_agents_tasks_cancel_frozen")
    module.lane6_agents_tasks_retention = lane6_agents_tasks_retention
    exec(compile(adapted, path, "exec"), module.__dict__)
    for node in adapted.body:
        name = getattr(node, "name", "")
        if name.startswith("Test"):
            target = "TestLane6_agents_tasks_" + name[4:]
            namespace[target] = getattr(module, name)
            for child in node.body:
                case = getattr(child, "name", "")
                if case.startswith("test_"):
                    CASE_MAP[path + "::" + name + "::" + case] = target + "::" + case
        elif name.startswith("test_"):
            target = "test_lane6_agents_tasks_" + name[5:]
            namespace[target] = getattr(module, name)
            CASE_MAP[path + "::" + name] = target
        elif any(isinstance(d, ast.Call) and ast.unparse(d.func) == "pytest.fixture"
                 for d in getattr(node, "decorator_list", [])):
            namespace["lane6_agents_tasks_fixture_" + name] = getattr(module, name)


def load(namespace, suite="test_background_task_cancel"):
    register_module(namespace, suite)


def lane6_agents_tasks_chat_message(content="", **kwargs):
    from types import SimpleNamespace
    graph = lane6_agents_tasks_graph_context.get()
    sealed = graph.requests._register_background("workflow", uuid.uuid4().hex,
        content, graph.cid, graph.requests.authority.owner_id)
    # Numeric transport IDs are inert fixture input, never owner authority.
    # Install a caller's observation identity durably before fetching its seal.
    if kwargs.get("id") is not None:
        identity = str(kwargs["id"])
        with graph.store.transaction() as db:
            db.execute("UPDATE desktop_requests SET request_id=? WHERE request_id=?", (identity, sealed.request_id))
            db.execute("UPDATE desktop_background_requests SET request_id=? WHERE request_id=?", (identity, sealed.request_id))
            db.execute("UPDATE desktop_request_context SET request_id=? WHERE request_id=?", (identity, sealed.request_id))
        sealed = graph.requests.fetch_request(graph.cid, identity)
    return SimpleNamespace(content=content, channel=SimpleNamespace(id=99),
        author=sealed.author, id=sealed.id, lane6_agents_tasks_sealed=sealed)


def lane6_agents_tasks_chat_bot(*, fake_llm, config_overrides=None):
    from types import SimpleNamespace
    from src.config.schema import Config
    graph = lane6_agents_tasks_graph_context.get()
    cfg = graph.config
    def merge(base, override):
        for name, value in override.items():
            if isinstance(value, dict) and isinstance(base.get(name), dict):
                merge(base[name], value)
            else:
                base[name] = value
    values = cfg.model_dump()
    merge(values, config_overrides or {})
    parsed = Config(**values)
    for field in type(cfg).model_fields:
        setattr(cfg, field, getattr(parsed, field))
    cfg.openai_compatible.enabled = True
    cfg.llm_provider.model = "compat:fixture"
    fake_llm.drain_and_close = fake_llm.close
    graph.engine.deps.llm_gateway.compatible_client = fake_llm
    deps = graph.engine.deps
    if graph.cid != "99":
        import json
        record = graph.requests.conversations.create()["conversation"]
        original = record["id"]
        record["id"] = "99"
        with graph.store.transaction() as db:
            db.execute("UPDATE desktop_conversations SET id=?,record=? WHERE id=?",
                ("99", json.dumps(record), original))
        graph.cid = "99"
    return SimpleNamespace(tool_loop=graph.engine.runner, tool_executor=deps.tool_executor,
        llm_gateway=deps.llm_gateway, channel_state=deps.channel_state, native_tools=deps.native_tools,
        turn_recorder=deps.turn_recorder, completion_classifier=deps.completion_classifier,
        skill_manager=deps.skill_manager, prompt_builder=deps.prompt_builder,
        tool_catalog=deps.tool_catalog, media_tools=deps.native_owners["media"],
        config=cfg, housekeeping=deps.housekeeping, sessions=deps.sessions)


async def lane6_agents_tasks_chat_run(bot, msg, history=None):
    graph = lane6_agents_tasks_graph_context.get()
    sealed = msg.lane6_agents_tasks_sealed
    async with graph.requests.background_execution(sealed):
        return await bot.tool_loop.run(sealed,
            history if history is not None else [{"role": "user", "content": msg.content}])
