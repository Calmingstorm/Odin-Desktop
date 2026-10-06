"""Whole frozen agent policy corpus through the real desktop service owner."""

from __future__ import annotations

import ast
import copy
import hashlib
from contextvars import ContextVar
from types import ModuleType, SimpleNamespace

from scripts.maintenance.fixture_corpus import corpus, frozen_source

lane6_agents_tasks_graph_context = ContextVar("lane6_agents_tasks_graph", default=None)
lane6_agents_tasks_path = "tests/test_agents_tasks_provider_paths.py"
lane6_agents_tasks_source_sha256 = (
    "28fc3d89c78cb86d5138eeee1f74bb8b4229dfd188f60f1e9d464380237f89a2"
)
SUITES = {
    "test_agents_tasks_provider_paths": (
        "28fc3d89c78cb86d5138eeee1f74bb8b4229dfd188f60f1e9d464380237f89a2"
    ),
    "test_wait_stuck_integration": (
        "437d3ef88266cab7e4988ccedae19b72887411f7384e029dd155e152814e3a59"
    ),
}
CORPUS_SELECTIONS = {"test_agents_tasks_provider_paths": None, "test_wait_stuck_integration": None}
CORPUS_EXCLUSIONS = {}
lane6_agents_tasks_corpus_sha256 = {
    "tests/test_agents_tasks_provider_paths.py": (
        "55ca8fb36dcdbbcde41a4889d0eb0f3126395023086665e405f097fad5a445fc"
    ),
    "tests/test_wait_stuck_integration.py": (
        "1903149639a189adcf1cc222b74e3f92d64a7da2ede950a469d8bbe1b6f0c2f4"
    ),
}
lane6_agents_tasks_evidence = {}
lane6_agents_tasks_case_map = {}
EVIDENCE = lane6_agents_tasks_evidence
CASE_MAP = lane6_agents_tasks_case_map


def lane6_agents_tasks_make_bot(*, fake_llm, config_overrides=None):
    graph = lane6_agents_tasks_graph_context.get()
    if graph is None:
        raise RuntimeError("Canonical desktop graph fixture is required")
    if config_overrides:
        raise RuntimeError("Config overrides require reviewed canonical setup")
    # Retained scripted transport predates the provider drainage seam. Its
    # close() is the real fake-resource cleanup, not a weakened engine guard.
    fake_llm.drain_and_close = fake_llm.close
    graph.engine.deps.llm_gateway.compatible_client = fake_llm
    graph.engine.deps.background_work_ready = True
    return SimpleNamespace(
        tool_loop=graph.engine.runner,
        tool_executor=graph.engine.deps.tool_executor,
        native_tools=graph.engine.deps.native_tools,
        llm_gateway=graph.engine.deps.llm_gateway,
    )


def lane6_agents_tasks_message(content):
    """Input only. Authority comes from RequestService, never this object."""
    return SimpleNamespace(content=content)


async def lane6_agents_tasks_wait_run_loop(bot, msg):
    graph = lane6_agents_tasks_graph_context.get()
    requests = graph.requests
    message = requests._register_background(
        "task", "wait-characterization", msg.content, graph.cid, requests.authority.owner_id
    )
    async with requests.background_execution(message):
        return await bot.tool_loop.run(message, history=[], system_prompt_override=None)


def lane6_agents_tasks_native_owner():
    graph = lane6_agents_tasks_graph_context.get()
    if graph is None:
        raise RuntimeError("Canonical desktop graph fixture is required")
    return graph.engine.deps.native_owners["agents"]


def lane6_agents_tasks_adapted_tree():
    source = frozen_source(lane6_agents_tasks_path)
    if hashlib.sha256(source).hexdigest() != lane6_agents_tasks_source_sha256:
        raise AssertionError("Frozen provider-path suite hash changed")
    original = ast.parse(source, filename=lane6_agents_tasks_path)
    edits = []

    class Setup(ast.NodeTransformer):
        def visit_Call(self, node):
            if ast.unparse(node) == "object.__new__(mod.AgentTaskTools)":
                edits.append(
                    {
                        "line": node.lineno,
                        "operation": "canonical_native_owner",
                        "before_sha256": hashlib.sha256(
                            ast.dump(node, include_attributes=False).encode()
                        ).hexdigest(),
                    }
                )
                return ast.copy_location(
                    ast.Call(
                        func=ast.Name(id="lane6_agents_tasks_native_owner", ctx=ast.Load()),
                        args=[],
                        keywords=[],
                    ),
                    node,
                )
            return self.generic_visit(node)

    adapted = Setup().visit(copy.deepcopy(original))
    ast.fix_missing_locations(adapted)
    if len(edits) != 3:
        raise AssertionError("Unexpected provider-path constructor setup corpus")
    if corpus(original) != corpus(adapted):
        raise AssertionError("Frozen assertion/signature/decorator/parameter AST changed")
    if (
        hashlib.sha256(repr(corpus(original)).encode()).hexdigest()
        != lane6_agents_tasks_corpus_sha256[lane6_agents_tasks_path]
    ):
        raise AssertionError("Pinned full provider-path corpus changed")
    lane6_agents_tasks_evidence[lane6_agents_tasks_path] = {
        "source_sha256": lane6_agents_tasks_source_sha256,
        "corpus_sha256": hashlib.sha256(repr(corpus(original)).encode()).hexdigest(),
        "whole_suite": True,
        "setup_edits": edits,
    }
    return adapted


def lane6_agents_tasks_wait_tree():
    path = "tests/test_wait_stuck_integration.py"
    source = frozen_source(path)
    expected = "437d3ef88266cab7e4988ccedae19b72887411f7384e029dd155e152814e3a59"
    if hashlib.sha256(source).hexdigest() != expected:
        raise AssertionError("Frozen wait suite hash changed")
    original = ast.parse(source, filename=path)
    edits = []

    class Setup(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.module == "tests.fakes":
                swapped = [
                    alias for alias in node.names if alias.name in {"make_bot", "FakeMessage"}
                ]
                retained = [alias for alias in node.names if alias not in swapped]
                edits.append({"line": node.lineno, "operation": "canonical_owner_input_setup"})
                bridge = ast.ImportFrom(
                    module=__name__,
                    names=[
                        ast.alias(
                            name="lane6_agents_tasks_make_bot"
                            if alias.name == "make_bot"
                            else "lane6_agents_tasks_message",
                            asname=alias.asname or alias.name,
                        )
                        for alias in swapped
                    ],
                    level=0,
                )
                return [
                    ast.copy_location(bridge, node),
                    ast.copy_location(
                        ast.ImportFrom(module=node.module, names=retained, level=0), node
                    ),
                ]
            return node

        def visit_AsyncFunctionDef(self, node):
            if node.name == "run_loop":
                edits.append({"line": node.lineno, "operation": "bound_request_runner_setup"})
                return ast.copy_location(
                    ast.ImportFrom(
                        module=__name__,
                        names=[
                            ast.alias(name="lane6_agents_tasks_wait_run_loop", asname="run_loop")
                        ],
                        level=0,
                    ),
                    node,
                )
            return self.generic_visit(node)

    adapted = Setup().visit(copy.deepcopy(original))
    ast.fix_missing_locations(adapted)
    if len(edits) != 2 or corpus(original) != corpus(adapted):
        raise AssertionError("Whole wait corpus or exact setup changed")
    if (
        hashlib.sha256(repr(corpus(original)).encode()).hexdigest()
        != lane6_agents_tasks_corpus_sha256[path]
    ):
        raise AssertionError("Pinned full wait corpus changed")
    lane6_agents_tasks_evidence[path] = {
        "source_sha256": expected,
        "corpus_sha256": hashlib.sha256(repr(corpus(original)).encode()).hexdigest(),
        "whole_suite": True,
        "setup_edits": edits,
    }
    return adapted


def register_module(namespace, suite="test_agents_tasks_provider_paths"):
    if suite not in SUITES:
        raise ValueError("Unadmitted frozen suite")
    tree = (
        lane6_agents_tasks_adapted_tree()
        if suite == "test_agents_tasks_provider_paths"
        else lane6_agents_tasks_wait_tree()
    )
    path = "tests/" + suite + ".py"
    module = ModuleType("lane6_agents_tasks_" + suite)
    module.__file__ = path
    module.lane6_agents_tasks_native_owner = lane6_agents_tasks_native_owner
    exec(compile(tree, module.__file__, "exec"), module.__dict__)
    for node in tree.body:
        name = getattr(node, "name", "")
        if name.startswith("test_"):
            target = "test_lane6_agents_tasks_" + name[5:]
            namespace[target] = getattr(module, name)
            lane6_agents_tasks_case_map[f"{path}::{name}"] = target
        elif name.startswith("Test"):
            target = "TestLane6_agents_tasks_" + name[4:]
            namespace[target] = getattr(module, name)
            for child in node.body:
                case = getattr(child, "name", "")
                if case.startswith("test_"):
                    lane6_agents_tasks_case_map[f"{path}::{name}::{case}"] = f"{target}::{case}"
        elif any(
            isinstance(d, ast.Call) and ast.unparse(d.func) == "pytest.fixture"
            for d in getattr(node, "decorator_list", [])
        ):
            namespace["lane6_agents_tasks_fixture_" + name] = getattr(module, name)


def load(namespace, suite="test_agents_tasks_provider_paths"):
    register_module(namespace, suite)
