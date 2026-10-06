"""Exact frozen agent trajectories and production-retained tool-loop corpus.

Desktop composes these same manager, dispatcher and runner owners. Obsolete
WebUI cases are projected individually, never implemented as fake routes.
"""
from __future__ import annotations

import ast
import copy
import hashlib
from types import ModuleType

from scripts.maintenance.fixture_corpus import ROOT, corpus, frozen_source
from tests.desktop_adapters.lane6_agents_lineage_owner import (
    lane6_agents_lineage_executor, lane6_agents_lineage_message,
    lane6_agents_lineage_owner_id, lane6_agents_lineage_runner,
    lane6_agents_lineage_lifecycle_runner,
)

lane6_agents_lineage_suites = {
    "test_agent_trajectory": "2159b565d648189872a1f4acb8bbfb41aaaddddda173f1762ec914d86e2e3b33",
    "test_tool_lifecycle_correlation": "3b8fc0e50882c50aa0e22bb3c154a1a1373fd116ffc085ce1c404c1ba5b97277",
    "test_tool_loop_provenance": "ae40015bf21a1f7bdb4e654a55bb425df6c0b0632877ebdf21f92093713b320b",
}
SUITES = {
    "test_agent_trajectory": "2159b565d648189872a1f4acb8bbfb41aaaddddda173f1762ec914d86e2e3b33",
    "test_tool_lifecycle_correlation": "3b8fc0e50882c50aa0e22bb3c154a1a1373fd116ffc085ce1c404c1ba5b97277",
    "test_tool_loop_provenance": "ae40015bf21a1f7bdb4e654a55bb425df6c0b0632877ebdf21f92093713b320b",
}
lane6_agents_lineage_evidence = {}
lane6_agents_lineage_case_map = {}
lane6_agents_lineage_retired_cases = {}
CORPUS_SELECTIONS = {
    "test_agent_trajectory": None,
    "test_tool_lifecycle_correlation": None,
    "test_tool_loop_provenance": None,
}
CORPUS_EXCLUSIONS = {
    "test_agent_trajectory": [
        "TestAgentTrajectoryAPI.test_list_no_saver",
        "TestAgentTrajectoryAPI.test_list_with_saver",
        "TestAgentTrajectoryAPI.test_find_by_agent_id",
        "TestAgentTrajectoryAPI.test_find_agent_not_found",
        "TestAgentTrajectoryAPI.test_search_endpoint",
        "TestAgentTrajectoryAPI.test_search_no_saver",
        "TestAgentTrajectoryAPI.test_read_file_endpoint",
        "TestAgentTrajectoryAPI.test_read_file_invalid_name",
        "TestAgentTrajectoryAPI.test_read_file_no_saver",
    ],
}
RETIRED_CASES = {
    f"test_agent_trajectory.{case}": {
        "source_sha256": "2159b565d648189872a1f4acb8bbfb41aaaddddda173f1762ec914d86e2e3b33",
        "reason": "Removed Odin WebUI HTTP agent-trajectory endpoint",
        "reviewer": "Claude, review of step 8 part 4",
    }
    for case in CORPUS_EXCLUSIONS["test_agent_trajectory"]
}
DEFERRED_CASES = {}
# Historical inert default import, not a replacement saver or production path.
lane6_agents_lineage_historical_directory = "./data/trajectories/agents"


def lane6_agents_lineage_adapted_tree(stem):
    path = f"tests/{stem}.py"
    source = frozen_source(path)
    if hashlib.sha256(source).hexdigest() != lane6_agents_lineage_suites[stem]:
        raise ValueError("Frozen lineage suite hash changed")
    original = ast.parse(source, filename=path)
    adapted = copy.deepcopy(original)
    changes = []

    class lane6_agents_lineage_imports(ast.NodeTransformer):
        def visit_Call(self, node):
            self.generic_visit(node)
            if stem == "test_tool_lifecycle_correlation":
                if ast.unparse(node.func) == "object.__new__":
                    changes.append({"line": node.lineno,"operation":"composed_lifecycle_runner_setup"})
                    return ast.copy_location(ast.Call(func=ast.Name(
                        id="lane6_agents_lineage_lifecycle_runner",ctx=ast.Load()),args=[],keywords=[]),node)
                for keyword in node.keywords:
                    if keyword.arg in {"user_id","requester_id"} and isinstance(keyword.value,ast.Constant):
                        keyword.value=ast.Call(func=ast.Name(id="lane6_agents_lineage_owner_id",ctx=ast.Load()),args=[],keywords=[])
            if stem == "test_tool_loop_provenance":
                if ast.unparse(node.func) == "ToolLoopRunner.__new__":
                    changes.append({"line": node.lineno, "operation": "composed_runner_setup"})
                    return ast.copy_location(ast.Call(
                        func=ast.Name(id="lane6_agents_lineage_runner", ctx=ast.Load()),
                        args=[], keywords=[]), node)
                for keyword in node.keywords:
                    if keyword.arg == "user_id" and isinstance(keyword.value, ast.Constant):
                        changes.append({"line": keyword.value.lineno,
                                        "operation": "authenticated_owner_setup"})
                        keyword.value = ast.Call(func=ast.Name(
                            id="lane6_agents_lineage_owner_id", ctx=ast.Load()), args=[], keywords=[])
                    if keyword.arg == "msg_proxy":
                        changes.append({"line": keyword.value.lineno,
                                        "operation": "bound_request_setup"})
                        keyword.value = ast.Call(func=ast.Name(
                            id="lane6_agents_lineage_message", ctx=ast.Load()), args=[], keywords=[])
            return node

        def visit_Assign(self, node):
            self.generic_visit(node)
            if stem in {"test_tool_loop_provenance", "test_tool_lifecycle_correlation"} and any(
                    isinstance(target, ast.Attribute) and target.attr == "_tool_executor"
                    for target in node.targets):
                changes.append({"line": node.lineno, "operation": "canonical_executor_setup"})
                node.value = ast.Call(func=ast.Name(
                    id="lane6_agents_lineage_executor", ctx=ast.Load()),
                    args=[node.value], keywords=[])
            return node

        def visit_ImportFrom(self, node):
            if node.module == "src.agents.trajectory":
                defaults = [alias for alias in node.names
                            if alias.name == "DEFAULT_AGENT_TRAJECTORY_DIR"]
                if defaults:
                    other = [alias for alias in node.names if alias not in defaults]
                    changes.append({"line": node.lineno,
                                    "operation": "historical_inert_default_import"})
                    result = [ast.copy_location(ast.ImportFrom(
                        module="tests.desktop_adapters.lane6_agents_lineage_retained",
                        names=[ast.alias(name="lane6_agents_lineage_historical_directory",
                                         asname="DEFAULT_AGENT_TRAJECTORY_DIR")], level=0), node)]
                    if other:
                        result.insert(0, ast.copy_location(ast.ImportFrom(
                            module=node.module, names=other, level=0), node))
                    return result
            if node.module == "src.tools.registry":
                for alias in node.names:
                    if alias.name == "get_tool_definitions":
                        alias.name = "get_documentation_tool_definitions"
                        alias.asname = "get_tool_definitions"
                        changes.append({"line": node.lineno,
                                        "operation": "static_documentation_catalog_import"})
            return node

    adapted = lane6_agents_lineage_imports().visit(adapted)
    if corpus(original) != corpus(adapted):
        raise ValueError("Full assertion/signature/decorator/parameter corpus changed")
    full = corpus(original)
    retired = []
    for node in adapted.body:
        if isinstance(node, ast.ClassDef) and node.name == "TestAgentTrajectoryAPI":
            for child in node.body:
                if getattr(child, "name", "").startswith("test_"):
                    original_id = f"{path}::{node.name}::{child.name}"
                    retired.append(original_id)
                    lane6_agents_lineage_retired_cases[original_id] = {
                        "source_sha256": lane6_agents_lineage_suites[stem],
                        "reason": "Removed Odin WebUI HTTP agent-trajectory endpoint",
                        "reviewer": "Claude, review of step 8 part 4",
                    }
    if stem == "test_tool_lifecycle_correlation":
        for node in adapted.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                DEFERRED_CASES[f"{stem}.{node.name}"] = {
                    "source_sha256": lane6_agents_lineage_suites[stem],
                    "reason": "Frozen harness replaces the authenticated executor consumer with a "
                              "SimpleNamespace and uses an unsealed message proxy. Background dispatch "
                              "requires RequestService task-bound admission; retained output requires "
                              "the real executor owner. Native parameters also reference removed "
                              "read_channel. No assertion-compatible canonical harness bridge qualified.",
                    "reviewer": "Odin: concrete canonical admission/retention fixture blocker",
                }
        DEFERRED_CASES[f"{stem}.test_foreground_timeout_during_start_audit_never_dispatches"]["reason"] = (
            "Retained pre-dispatch audit cancellation passes in the unqualified frozen harness, "
            "but that harness has no authenticated executor consumer or sealed RequestService "
            "message. Whole-suite canonical owner bridge remains unqualified; no case sampling.")
        DEFERRED_CASES[f"{stem}.test_adapter_marker_reaches_native_dispatch_by_identity"]["reason"] = (
            "Native marker identity corpus dispatches mocked owners from an unsealed proxy; "
            "agent/autonomous routes now require RequestService.assert_bound_request and an "
            "authenticated executor for retention. Real durable scheduling/task owner fixture "
            "bridge preserving all nine parameter assertions is not qualified.")
        for name in ("test_rejected_post_action_image_keeps_single_failed_receipt",
                     "test_post_action_image_preserves_private_audit_metadata"):
            DEFERRED_CASES[f"{stem}.{name}"]["reason"] = (
                "Hermetic computer receipt rejection uses a fake native dispatcher and "
                "SimpleNamespace executor lacking retained authenticated output authority. "
                "Canonical admitted request/executor fixture preserving receipt audit "
                "assertions is not qualified; this is not a native-display qualification claim.")
    lane6_agents_lineage_evidence[path] = {
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "full_corpus_sha256": hashlib.sha256(repr(full).encode()).hexdigest(),
        "full_assert_parameter_ast_preserved_before_projection": True,
        "whole_suite": True, "sealed_fixture_edits": changes,
        "retired_cases": retired,
        "adapted_corpus_sha256": hashlib.sha256(repr(corpus(adapted)).encode()).hexdigest(),
    }
    if stem == "test_tool_lifecycle_correlation":
        DEFERRED_CASES.clear()
        for failure in ("None", "failure1"):
            for route in ("foreground", "autonomous", "agent"):
                case = f"{stem}.test_real_execution_has_one_correlated_canonical_record[{failure}-True-{route}]"
                RETIRED_CASES[case] = {
                    "source_sha256": SUITES[stem],
                    "reason": "Removed read_channel native Discord surface, exact native=True parameter only",
                    "reviewer": "Claude, review of step 8 part 4",
                }
    return ast.fix_missing_locations(adapted)


def lane6_agents_lineage_register_module(namespace, stem, tree, module):
    # Export original fixture names and signatures without wrapping bodies.
    for name, value in vars(module).items():
        if hasattr(value, "_pytestfixturefunction"):
            if name in namespace and namespace[name] is not value:
                raise ValueError("Conflicting lineage fixture export")
            namespace[name] = value
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            if node.name == "TestAgentTrajectoryAPI":
                continue
            exported = f"Test_lane6_agents_lineage_{stem}_{node.name[4:]}"
            namespace[exported] = vars(module)[node.name]
            for child in node.body:
                if getattr(child, "name", "").startswith("test_"):
                    lane6_agents_lineage_case_map[
                        f"tests/{stem}.py::{node.name}::{child.name}"] = (
                            f"{exported}::{child.name}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                exported = f"test_lane6_agents_lineage_{stem}_{node.name[5:]}"
                namespace[exported] = vars(module)[node.name]
                lane6_agents_lineage_case_map[f"tests/{stem}.py::{node.name}"] = exported


register_module = lane6_agents_lineage_register_module


def lane6_agents_lineage_load(namespace):
    for stem in CORPUS_SELECTIONS:
        tree = lane6_agents_lineage_adapted_tree(stem)
        module = ModuleType(f"lane6_agents_lineage_{stem}")
        module.__file__ = str(ROOT / f"tests/{stem}.py")
        module.lane6_agents_lineage_runner = lane6_agents_lineage_runner
        module.lane6_agents_lineage_lifecycle_runner = lane6_agents_lineage_lifecycle_runner
        module.lane6_agents_lineage_executor = lane6_agents_lineage_executor
        module.lane6_agents_lineage_owner_id = lane6_agents_lineage_owner_id
        module.lane6_agents_lineage_message = lane6_agents_lineage_message
        exec(compile(tree, module.__file__, "exec"), module.__dict__)
        register_module(namespace, stem, tree, module)


load = lane6_agents_lineage_load


def pytest_collection_modifyitems(config, items):
    lane6_agents_lineage_removed = []
    for item in list(items):
        if "test_tool_lifecycle_correlation_real_execution_has_one_correlated_canonical_record" in item.nodeid:
            if item.callspec.params.get("native") is True:
                items.remove(item)
                lane6_agents_lineage_removed.append(item)
    if lane6_agents_lineage_removed:
        config.hook.pytest_deselected(items=lane6_agents_lineage_removed)
