"""Hash-bound WHOLE inherited trees, corpus proof before case projection."""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from types import ModuleType

from scripts.maintenance.fixture_corpus import (
    ROOT,
    corpus,
    dump,
    frozen_source,
    nodes,
    register_module,
)

BRIDGE = "tests.desktop_adapters.lane6_schedules_loops_bridge"
SUITES = {
    "test_autonomous_loop": "242d1c57c12b8a33eee30f9694861a29bbca047a5eb640cdd0504df4c53b18fc",
    "test_campaign_loops": "a719fd8104bd2917381bbb754ead2aebbf91271fba9546e4397da51525a91ed6",
    "test_turn_recorder_loop_reflection": (
        "25b8057e064f795d2b7105ffac039d96c299d4e8ccbe1c4eea257ef2656bdc36"
    ),
}
CORPUS_SELECTIONS = {"test_autonomous_loop": None, "test_campaign_loops": None,
                     "test_turn_recorder_loop_reflection": None}
CORPUS_EXCLUSIONS = {"test_autonomous_loop": [
    "TestLoopFlow.test_long_final_text_truncated_to_discord_limit",
    "TestLoopDispatchParity.test_rbac_denial_in_loop_dispatch",
    "TestLoopDispatchParity.test_export_skill_stages_pending_file_in_loop"]}
RETIRED_CASES = {"test_autonomous_loop": {
    "TestLoopFlow.test_long_final_text_truncated_to_discord_limit": {
        "reason": "Removed Discord output-length formatting surface.",
        "reviewer": "Claude, review of step 8 part 4"},
    "TestLoopDispatchParity.test_rbac_denial_in_loop_dispatch": {
        "reason": "Removed multi-user RBAC tier denial surface.",
        "reviewer": "Claude, review of step 8 part 4"},
    "TestLoopDispatchParity.test_export_skill_stages_pending_file_in_loop": {
        "reason": "Removed Discord channel-keyed file staging surface.",
        "reviewer": "Claude, review of step 8 part 4"}}}
DEFERRED_CASES = {"test_autonomous_loop": {
    "TestLoopFlow.test_stop_loop_tool_self_stop_settles_without_cancellation_cycle": {
        "reason": (
            "Frozen synchronous FakeMessage startup requires sealed native background admission "
            "and actual WorkService/ControlService binding; adapter cannot mint that context "
            "from FakeMessage."
        ),
        "blocked_on": (
            "Exact native synchronous-start setup adapter over real background/work/control "
            "services"
        ),
    },
    "TestLoopDispatchParity.test_unknown_tool_routes_to_executor_with_user_id": {
        "reason": (
            "Exact assertion pins user_id 4242; actual RequestService requires UUID canonical "
            "owner equality. No foreign-owner dispatch or weakened admission is acceptable."
        ),
        "blocked_on": "Reviewer decision on the inherited foreign identity assertion"},
    "TestLoopDispatchParity.test_skill_crud_rebuilds_prompt_in_loop": {
        "reason": (
            "Actual EngineServices readiness omits create_skill despite bound "
            "SkillManager/dispatcher. Runtime delivery refuses Output capability unavailable."
        ),
        "blocked_on": "Coordinated production correction of native skill readiness"},
    "TestLoopDispatchParity.test_invoke_skill_missing_required_fields_errors": {
        "reason": (
            "Actual EngineServices readiness omits invoke_skill despite bound "
            "SkillManager/dispatcher. Runtime output retention authority refuses that capability."
        ),
        "blocked_on": "Coordinated production correction of native skill readiness"}}}
PATHS = ("tests/characterization/test_autonomous_loop.py", "tests/test_campaign_loops.py",
         "tests/test_turn_recorder_loop_reflection.py")
RETIRED = {
    "test_long_final_text_truncated_to_discord_limit": (
        "Removed Discord output limit; local conversation formatter has its own retained size "
        "contract."
    ),
    "test_rbac_denial_in_loop_dispatch": (
        "Removed multi-user RBAC tier denial; canonical profile owner permission is exercised "
        "by real service admission."
    ),
    "test_export_skill_stages_pending_file_in_loop": (
        "Removed Discord channel attachment staging keyed by channel 777; local artifact "
        "publication replaces this surface."
    ),
}
DEFERRED = {
    "test_stop_loop_tool_self_stop_settles_without_cancellation_cycle": (
        "Frozen synchronous FakeMessage start needs sealed native admission and real "
        "ControlService work registration; asynchronous native tool context cannot be obtained "
        "from that message unchanged."
    ),
    "test_unknown_tool_routes_to_executor_with_user_id": (
        "Frozen assertion pins foreign user_id 4242, whereas run_autonomous and RequestService "
        "require authenticated UUID owner equality; exact assertion cannot be preserved with "
        "canonical-owner dispatch."
    ),
    "test_skill_crud_rebuilds_prompt_in_loop": (
        "Real service readiness() in src/desktop/services.py omits create_skill despite real "
        "SkillManager and dispatcher; runtime_delivery rejects output with Output capability "
        "unavailable. Coordinated production readiness correction required."
    ),
    "test_invoke_skill_missing_required_fields_errors": (
        "Real service readiness() in src/desktop/services.py omits invoke_skill despite real "
        "SkillManager and dispatcher; canonical output retention authority refuses capability. "
        "Coordinated production readiness correction required."
    ),
}
EVIDENCE = {}
CASE_MAP = {}


def adapted_tree(path):
    source = frozen_source(path)
    if hashlib.sha256(source).hexdigest() != SUITES[path.split("/")[-1][:-3]]:
        raise AssertionError("Frozen suite hash changed")
    original = ast.parse(source, filename=path)
    hunks = []

    def record(before, after, operation):
        hunks.append({"line": before.lineno, "operation": operation,
            "before_sha256": hashlib.sha256(dump(before).encode()).hexdigest(),
            "after_sha256": hashlib.sha256(dump(after).encode()).hexdigest(),
            "before_ast": dump(before), "after_ast": dump(after)})
        return ast.copy_location(after, before)

    class Setup(ast.NodeTransformer):
        def visit_Assert(self, node):
            return node

        def visit_ImportFrom(self, node):
            if node.module == "tests.fakes":
                names = [a for a in node.names if a.name in {"FakeChannel", "make_bot", "FakeLLM"}]
                kept = [a for a in node.names if a not in names]
                result = [
                    ast.ImportFrom(
                        module=BRIDGE,
                        names=[
                            ast.alias(name="Channel", asname="FakeChannel")
                            if alias.name == "FakeChannel"
                            else alias
                            for alias in names
                        ],
                        level=0,
                    )
                ] if names else []
                if kept:
                    result.append(ast.ImportFrom(module=node.module, names=kept, level=0))
                replacement = "\n".join(ast.unparse(n) for n in result)
                if [dump(n) for n in ast.parse(replacement).body] != [dump(n) for n in result]:
                    raise AssertionError("Split import reconstruction changed")
                hunks.append(
                    {"line": node.lineno, "operation": "real_graph_factory_or_transcript_view",
                    "before_sha256": hashlib.sha256(dump(node).encode()).hexdigest(),
                    "after_sha256": hashlib.sha256(
                        json.dumps([dump(n) for n in result]).encode()
                    ).hexdigest(),
                    "before_ast": dump(node), "after_ast": [dump(n) for n in result],
                     "after_source": replacement, "kind": "statement"}
                )
                return [ast.copy_location(n, node) for n in result]
            if node.module == "tests.characterization.test_autonomous_loop":
                after = copy.deepcopy(node)
                after.module = "tests.desktop_adapters.lane6_schedules_loops_cases"
                return record(node, after, "frozen_adapted_helper_import")
            if (
                node.module == "src.tools.autonomous_loop"
                and path.endswith("test_campaign_loops.py")
            ):
                after = copy.deepcopy(node)
                after.module = BRIDGE
                return record(node, after, "real_graph_loop_manager_factory")
            return node

        def visit_FunctionDef(self, node):
            if (
                path.endswith("test_turn_recorder_loop_reflection.py")
                and node.name in {"_bot", "_recorder"}
            ):
                after = ast.parse(f"from {BRIDGE} import {node.name}").body[0]
                return record(node, after, "real_service_recorder_fixture")
            return self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node):
            if path.endswith("test_autonomous_loop.py") and node.name == "run_iteration":
                after = ast.parse(f"from {BRIDGE} import run_iteration").body[0]
                return record(node, after, "sealed_background_iteration_fixture")
            return self.generic_visit(node)

        def visit_Call(self, node):
            before = copy.deepcopy(node)
            self.generic_visit(node)
            if (isinstance(node.func, ast.Attribute) and node.func.attr == "start_loop"
                    and path.endswith("test_campaign_loops.py")):
                node.args.insert(0, node.func.value)
                node.func = ast.Name(id="lane6_start_loop", ctx=ast.Load())
                record(before, node, "durable_admitted_loop_start")
            return node

    tree = Setup().visit(copy.deepcopy(original))
    if corpus(original) != corpus(tree):
        raise AssertionError("WHOLE assertion/signature/decorator/parameter corpus changed")
    EVIDENCE[path] = {"source_sha256": SUITES[path.split("/")[-1][:-3]], "whole_suite": True,
        "full_corpus_sha256": hashlib.sha256(repr(corpus(original)).encode()).hexdigest(),
        "exact_corpus": corpus(original), "setup_hunks": hunks,
        "cases": [
            s.replace(".", "::")
            for s, n in nodes(original)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name.startswith("test_")
        ],
    }
    return tree


def load(namespace):
    global build, run_iteration
    for path in PATHS:
        tree = adapted_tree(path)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                node.body = [
                    n for n in node.body if getattr(n, "name", "") not in RETIRED | DEFERRED
                ]
        tree.body = [
            n for n in tree.body if getattr(n, "name", "") not in RETIRED | DEFERRED
        ]
        start_loop_import = ast.parse(
            f"from {BRIDGE} import start_loop as lane6_start_loop"
        ).body[0]
        tree.body.insert(0, start_loop_import)
        # Future imports must remain the first executable statements.
        tree.body.sort(
            key=lambda n: 0
            if isinstance(n, ast.ImportFrom) and n.module == "__future__"
            else 1
        )
        ast.fix_missing_locations(tree)
        module = ModuleType("lane6_schedules_loops_" + path.split("/")[-1][:-3])
        module.__file__ = str(ROOT / path)
        exec(compile(tree, module.__file__, "exec"), module.__dict__)
        if path.endswith("test_autonomous_loop.py"):
            build, run_iteration = module.build, module.run_iteration
        stem = path.split("/")[-1][5:-3]
        prefix = "lane6_loops_" + stem
        register_module(namespace, module, prefix=prefix, full_class_name=True)
        for name, value in vars(module).items():
            if name.startswith("test_") or name.startswith("Test"):
                exported = (
                    "Test_" + prefix + "_" + name
                    if name.startswith("Test")
                    else "test_" + prefix + "_" + name[5:]
                )
                if name.startswith("Test"):
                    for case in vars(value):
                        if case.startswith("test_"):
                            CASE_MAP[f"{path}::{name}::{case}"] = f"{exported}::{case}"
                else:
                    CASE_MAP[f"{path}::{name}"] = exported
            elif any(isinstance(d, ast.Call) and ast.unparse(d.func) == "pytest.fixture"
                     for n in tree.body if getattr(n, "name", "") == name
                     for d in getattr(n, "decorator_list", [])):
                namespace["fixture_lane6_loops_" + stem + name] = value
