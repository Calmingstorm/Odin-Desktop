"""Whole frozen agent trajectory corpus over the retained Desktop read owner.

Only obsolete transport imports and inert historical setup defaults change.
The facade never opens a listener and never implements a saver algorithm.
In particular, a missing named finder must fail rather than be synthesized.
"""
from __future__ import annotations

import ast
import copy
import hashlib
from types import ModuleType

from aiohttp import web

from scripts.maintenance.fixture_corpus import ROOT, corpus, frozen_source
from src.desktop.trajectories import TrajectoriesService
from tests.desktop_adapters.step5_traces import TestClient as TestClient
from tests.desktop_adapters.step5_traces import TestServer as TestServer
from tests.desktop_adapters.step5_traces import _invoke

SOURCE_PATH = "tests/test_agent_trajectory.py"
SOURCE_SHA256 = "2159b565d648189872a1f4acb8bbfb41aaaddddda173f1762ec914d86e2e3b33"
SUITES = {
    "test_agent_trajectory": "2159b565d648189872a1f4acb8bbfb41aaaddddda173f1762ec914d86e2e3b33",
}
CORPUS_SELECTIONS = {"test_agent_trajectory": None}
CORPUS_EXCLUSIONS = {}
RETIRED_CASES = {}
DEFERRED_CASES = {}
EVIDENCE = {}
CASE_MAP = {}
DEFAULT_AGENT_TRAJECTORY_DIR = "./data/trajectories/agents"
WRAPPER = "tests/test_desktop_lane6_trajectory_endpoint_parity.py"
ENDPOINT_CASES = (
    "test_list_no_saver", "test_list_with_saver", "test_find_by_agent_id",
    "test_find_agent_not_found", "test_search_endpoint", "test_search_no_saver",
    "test_read_file_endpoint", "test_read_file_invalid_name", "test_read_file_no_saver",
)
NAMED_METHODS = {
    "test_list_no_saver": "trajectories.list",
    "test_list_with_saver": "trajectories.list",
    "test_find_by_agent_id": "trajectories.agent",
    "test_find_agent_not_found": "trajectories.agent",
    "test_search_endpoint": "trajectories.search",
    "test_search_no_saver": "trajectories.search",
    "test_read_file_endpoint": "trajectories.read",
    "test_read_file_invalid_name": "trajectories.read",
    "test_read_file_no_saver": "trajectories.read",
}


def create_api_routes(bot):
    """Adapt the frozen URL-shaped fixture to actual named service methods."""
    service = TrajectoriesService(saver=getattr(bot, "agent_trajectory_saver", None))
    routes = web.RouteTableDef()

    @routes.get("/api/agent-trajectories")
    async def files(request):
        return await _invoke(service, "trajectories.list", {})

    @routes.get("/api/agent-trajectories/agent/{agent_id}")
    async def finder(request):
        return await _invoke(service, "trajectories.agent", dict(request.match_info))

    @routes.get("/api/agent-trajectories/search/query")
    async def search(request):
        return await _invoke(service, "trajectories.search", dict(request.query))

    @routes.get("/api/agent-trajectories/{filename}")
    async def read(request):
        return await _invoke(service, "trajectories.read", {
            **request.query, "filename": request.match_info["filename"],
        })

    return routes


def adapted_tree():
    source = frozen_source(SOURCE_PATH)
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("Frozen agent trajectory suite hash changed")
    original = ast.parse(source, filename=SOURCE_PATH)
    adapted = copy.deepcopy(original)
    changes = []

    class Imports(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.module in {"aiohttp.test_utils", "src.web.api"}:
                allowed = {"TestClient", "TestServer", "create_api_routes"}
                if not all(alias.name in allowed for alias in node.names):
                    raise ValueError("Unexpected frozen transport import")
                changes.append({"line": node.lineno, "operation": "named_read_transport_import",
                                "from": node.module})
                node.module = "tests.desktop_adapters.lane6_trajectory_endpoint_parity"
            elif node.module == "src.agents.trajectory":
                historical = [alias for alias in node.names
                              if alias.name == "DEFAULT_AGENT_TRAJECTORY_DIR"]
                if historical:
                    retained = [alias for alias in node.names if alias not in historical]
                    changes.append({"line": node.lineno,
                                    "operation": "historical_inert_default_import"})
                    imports = [ast.copy_location(ast.ImportFrom(
                        module="tests.desktop_adapters.lane6_trajectory_endpoint_parity",
                        names=historical, level=0), node)]
                    if retained:
                        imports.insert(0, ast.copy_location(ast.ImportFrom(
                            module=node.module, names=retained, level=0), node))
                    return imports
            elif node.module == "src.tools.registry":
                for alias in node.names:
                    if alias.name == "get_tool_definitions":
                        alias.name = "get_documentation_tool_definitions"
                        alias.asname = "get_tool_definitions"
                        changes.append({"line": node.lineno,
                                        "operation": "static_documentation_catalog_import"})
            return node

    adapted = Imports().visit(adapted)
    if corpus(original) != corpus(adapted):
        raise ValueError("Whole assertion/signature/decorator/parameter corpus changed")
    endpoint_class = next(node for node in adapted.body
                          if isinstance(node, ast.ClassDef)
                          and node.name == "TestAgentTrajectoryAPI")
    actual = tuple(node.name for node in endpoint_class.body
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and node.name.startswith("test_"))
    if actual != ENDPOINT_CASES:
        raise ValueError("The nine retained endpoint identities changed")
    EVIDENCE[SOURCE_PATH] = {
        "source_sha256": SOURCE_SHA256,
        "full_corpus_sha256": hashlib.sha256(repr(corpus(original)).encode()).hexdigest(),
        "adapted_corpus_sha256": hashlib.sha256(repr(corpus(adapted)).encode()).hexdigest(),
        "whole_suite": True, "full_assert_parameter_ast_preserved_before_projection": True,
        "sealed_fixture_edits": changes,
        "retired_cases": [], "deferred_cases": [],
    }
    return ast.fix_missing_locations(adapted)


def register_module(namespace, tree, module):
    """Export every source test class/function, including the nine endpoints."""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            exported = f"TestLane6Trajectory_{node.name[4:]}"
            namespace[exported] = vars(module)[node.name]
            for child in node.body:
                if getattr(child, "name", "").startswith("test_"):
                    CASE_MAP[f"{SOURCE_PATH}::{node.name}::{child.name}"] = (
                        f"{WRAPPER}::{exported}::{child.name}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                exported = f"test_lane6_trajectory_{node.name[5:]}"
                namespace[exported] = vars(module)[node.name]
                CASE_MAP[f"{SOURCE_PATH}::{node.name}"] = f"{WRAPPER}::{exported}"


def load(namespace):
    tree = adapted_tree()
    module = ModuleType("desktop_lane6_trajectory_test_agent_trajectory")
    module.__file__ = str(ROOT / SOURCE_PATH)
    exec(compile(tree, module.__file__, "exec"), module.__dict__)
    register_module(namespace, tree, module)
