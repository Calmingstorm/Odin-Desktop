"""Exact frozen historical cases: setup-only adaptation, never live admission."""

from __future__ import annotations

import ast
import asyncio
import copy
import hashlib
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from src.tools.autonomous_loop import LoopInfo
from tests.desktop_adapters.tools_cases import ROOT

SELECTIONS = {
    "test_strict_tool_adapter": [
        "test_forced_values_and_nested_omission",
        "test_resolution_logging_is_process_memoized_and_builtin_warnings_repeat",
        "test_probe_headers_lowered_after_wire_validation",
        "test_spawn_policy_wire_omissions_preserve_presence_checks",
    ],
    "test_process_read_leases": ["test_acquired_lease_must_match_persisted_binding"],
    "test_evaluative_discipline_prompt": [
        "test_system_prompt_and_workspace_share_runtime_install_root"
    ],
    "test_loop_error_sanitization": [
        "TestLoopManagerErrorTextSanitized.test_history_and_channel_posts_carry_no_markup"
    ],
    "test_scheduler_agents_reliability": [
        "test_shutdown_cancels_and_awaits_loop_tasks",
        "test_stop_waits_until_inflight_iteration_is_cancelled_and_settled",
        "test_self_stop_single_direct_callback_uses_logical_owner",
        "test_stop_all_from_one_loop_cancels_and_awaits_other_loops",
        "test_self_stop_all_never_awaits_its_own_manager_task",
    ],
}
REPLACEMENT_SUITES = [
    "test_audit_config_reliability",
    "test_codex_55_retirement",
    "test_handlers_files_docs",
    "test_legacy_constants_contract",
    "test_pr356_environment_compatibility",
]


def seed_neutral_callback_task(manager, **kwargs):
    """Seed coroutine algorithm state, NOT an admission or owner fixture.

    This fixture deliberately never calls or replaces start_loop. Its inert
    callback/sink are local algorithm inputs; no request, privileged tool,
    persistence, control-plane intake or real conversation can be admitted.
    The separate negative boundary test pins actual start_loop refusal.
    """
    channel = kwargs.pop("channel")
    callback = kwargs.pop("iteration_callback")
    identifier = f"neutral-callback-{len(manager._loops)}"
    info = LoopInfo(
        id=identifier,
        channel_id="inert-test-sink",
        mode=kwargs.pop("mode", "notify"),
        stop_condition=kwargs.pop("stop_condition", None),
        **kwargs,
    )
    manager._loops[identifier] = info
    async def local_algorithm_sink(_info, text):
        await channel.send(text)
    # This sink belongs only to the frozen algorithm fixture. It supplies no
    # admission, requester, scope, or production conversation authority.
    info._publish = local_algorithm_sink
    info._task = asyncio.create_task(manager._run_loop(info, channel, callback))
    return identifier


class SetupOnly(ast.NodeTransformer):
    def __init__(self, suite):
        self.suite = suite
        self.symbol = "<module>"
        self.hunks = []

    def record(self, before, after, operation):
        if ast.dump(before) != ast.dump(after):
            self.hunks.append({
                "symbol": self.symbol,
                "line": before.lineno,
                "operation": operation,
                "before_sha256": hashlib.sha256(ast.dump(before).encode()).hexdigest(),
                "after_sha256": hashlib.sha256(ast.dump(after).encode()).hexdigest(),
                "after_source": ast.unparse(after),
            })
        return ast.copy_location(after, before)

    def visit_Assert(self, node):
        return node

    def visit_FunctionDef(self, node):
        previous = self.symbol
        self.symbol = node.name if previous == "<module>" else previous + "." + node.name
        node.body = [self.visit(child) for child in node.body]
        self.symbol = previous
        return node

    def visit_AsyncFunctionDef(self, node):
        return self.visit_FunctionDef(node)

    def visit_ClassDef(self, node):
        previous = self.symbol
        self.symbol = node.name
        node.body = [self.visit(child) for child in node.body]
        self.symbol = previous
        return node

    def visit_ImportFrom(self, node):
        before = copy.deepcopy(node)
        if self.suite == "test_strict_tool_adapter" and node.module == "src.tools.registry":
            for alias in node.names:
                if alias.name == "get_tool_definitions":
                    alias.name = "get_documentation_tool_definitions"
                    alias.asname = "get_tool_definitions"
        return self.record(before, node, "documentation_catalog_import")

    def visit_Call(self, node):
        before = copy.deepcopy(node)
        if self.suite == "test_process_read_leases" and (
            isinstance(node.func, ast.Name) and node.func.id == "HostRegistry"
            and not any(k.arg in {"trust_dir", "profile_paths"} for k in node.keywords)
        ):
            node.keywords.append(ast.keyword(
                arg="trust_dir",
                value=ast.parse("h.hosts._trust_dir / 'other-registry'", mode="eval").body,
            ))
            return self.record(before, node, "explicit_private_host_registry_storage")
        if self.suite in {"test_loop_error_sanitization", "test_scheduler_agents_reliability"}:
            if isinstance(node.func, ast.Attribute) and node.func.attr == "start_loop":
                node.args.insert(0, node.func.value)
                node.func = ast.Name(id="seed_neutral_callback_task", ctx=ast.Load())
                return self.record(before, node, "neutral_coroutine_state_not_admission")
        return self.generic_visit(node)


def transformed_tree(suite):
    path = f"tests/{suite}.py"
    source = frozen_source(path)
    original = ast.parse(source, filename=path)
    transformer = SetupOnly(suite)
    adapted = transformer.visit(copy.deepcopy(original))
    ast.fix_missing_locations(adapted)
    # Verify the ENTIRE tree before projecting methods. Assertions, fixtures'
    # assertions, parameters, signatures and decorators must be unchanged.
    # This worker cannot mutate the parent's fixture admission manifest. The
    # frozen archive helper proves byte identity; exact setup hunks are sealed
    # in our own triage for independent parent admission, never self-approved.
    assert corpus(original) == corpus(adapted)
    return adapted, transformer.hunks


def export_suite(namespace, suite):
    tree, _ = transformed_tree(suite)
    selected = SELECTIONS[suite]
    body = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_") and node.name not in selected:
                continue
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            methods = [n for n in node.body if not (
                isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name.startswith("test_")
                and f"{node.name}.{n.name}" not in selected
            )]
            if not any(f"{node.name}.{getattr(n, 'name', '')}" in selected for n in methods):
                continue
            node.body = methods
        body.append(node)
    tree.body = body
    module = ModuleType(f"desktop_final_{suite}")
    module.__file__ = str(ROOT / f"tests/{suite}.py")
    module.seed_neutral_callback_task = seed_neutral_callback_task
    exec(compile(tree, module.__file__, "exec"), module.__dict__)
    for name, value in vars(module).items():
        if name.startswith("test_"):
            value.__module__ = namespace["__name__"]
            exported = f"test_final_{suite[5:]}__{name[5:]}"
            namespace[exported] = value
        elif name.startswith("Test"):
            value.__module__ = namespace["__name__"]
            for method in vars(value).values():
                if callable(method) and hasattr(method, "__module__"):
                    method.__module__ = namespace["__name__"]
            exported = f"TestFinal_{suite[5:]}_{name[4:]}"
            namespace[exported] = value
        elif (
            getattr(value, "_pytestfixturefunction", None) is not None
            or getattr(value, "_fixture_function_marker", None) is not None
        ):
            value.__module__ = namespace["__name__"]
            namespace[name] = value


def executable(suite, symbol):
    if "." in symbol:
        cls, method = symbol.split(".")
        name = f"TestFinal_{suite[5:]}_{cls[4:]}::{method}"
    else:
        name = f"test_final_{suite[5:]}__{symbol[5:]}"
    return f"tests/test_desktop_final_history.py::{name}"


CASE_MAP = {
    executable(suite, symbol): f"tests/{suite}.py::" + symbol.replace(".", "::")
    for suite, symbols in SELECTIONS.items()
    for symbol in symbols
    if suite not in {"test_loop_error_sanitization", "test_scheduler_agents_reliability"}
}
