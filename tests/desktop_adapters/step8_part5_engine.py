"""Frozen engine cases, with exact, audited setup-only Desktop imports.

Never import the obsolete gateway/main fixtures. Keep the real containment
barriers, process-level probes and all selected assertion/parameter ASTs.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from types import ModuleType

from scripts.maintenance.fixture_corpus import ROOT, corpus, dump, frozen_source, nodes

WORKSPACE_REMOVED = {
    "test_updater_passes_lexical_install_root_to_shared_derivation",
    "test_every_install_path_provisions_the_workspace",
    "test_every_upgrade_path_provisions_the_workspace",
    "test_incus_deployment_path_provisions_the_workspace",
    "test_preflight_uses_the_live_config_not_a_reparsed_file",
    "test_preflight_refuses_a_workspace_the_runtime_would_reject",
    "test_preflight_falls_back_to_the_schema_default_without_a_bot",
    "test_preflight_validates_the_exact_live_value_never_a_substitute",
    "test_preflight_uses_the_schema_default_only_when_there_is_no_live_config",
    "test_self_update_preflight_rejects_a_workspace_beside_relocated_live_memory",
}
WORKSPACE_DEFERRED = {
    "test_blank_workspace_normalizes_to_the_default_at_the_boundary",
    "test_relocated_state_file_protects_its_directory",
    "test_every_declared_state_path_is_covered",
    "test_startup_migration_provisions_before_commands_are_served",
    "test_python_m_src_provisions_the_workspace_before_the_bot_exists",
    "test_startup_migration_rejects_a_workspace_beside_relocated_live_memory",
    "test_all_three_callers_share_one_protected_root_derivation",
    "test_wiring_supplies_the_full_config_to_the_executor",
    "test_every_local_execution_route_is_classified",
    "test_wiring_hardcoded_state_paths_are_all_covered",
    "test_every_command_caller_is_classified",
    "test_tracked_config_template_documents_the_workspace",
}
MAIN_CLASSES = {"TestFinalizeLoop", "TestUncleanBarrierExit", "TestFinalizeHardDeadline"}
SETUP_RULES_SHA256 = {
    "test_fd_health": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
    "test_local_workspace": "be027b8153c7bbd7eac0cc5f22fc9712df8c18159ad9362af414856174c5fad3",
    "test_main_exit_codes": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
    "test_restart": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
}


def source_cases(tree):
    return {
        symbol: node for symbol, node in nodes(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }


def selection(name, tree):
    cases = source_cases(tree)
    if name == "test_fd_health":
        return set(cases) - {"test_packaged_systemd_unit_sets_raised_nofile_limit"}
    if name == "test_local_workspace":
        return set(cases) - WORKSPACE_REMOVED - WORKSPACE_DEFERRED
    if name == "test_main_exit_codes":
        return {case for case in cases if case.split(".")[0] in MAIN_CLASSES}
    if name == "test_restart":
        return {"TestReexecVetoInMain.test_veto_state_round_trips"}
    raise ValueError("unadmitted suite")


def verified_tree(name):
    """Check frozen bytes and invariant corpus before selecting any definition.

    The only transformations: exact ToolExecutor import nodes to the existing
    authentic owner fixture; exact Config(..., discord=...) setup keywords
    removed because Desktop has no DiscordConfig. Rules record symbol, line,
    complete before/after AST SHA-256 and operation for independent audit.
    """
    path = f"tests/{name}.py"
    original = ast.parse(frozen_source(path), filename=path)
    tree = copy.deepcopy(original)
    rules = []
    replacements = {}
    if name == "test_local_workspace":
        for symbol, node in nodes(tree):
            after = None
            operation = None
            if isinstance(node, ast.ImportFrom) and node.module == "src.tools.executor":
                if [a.name for a in node.names] != ["ToolExecutor"]:
                    raise ValueError("unexpected executor import")
                after = copy.deepcopy(node)
                after.module = "tests.desktop_adapters.tools_cases"
                operation = "authentic_owner_executor_import"
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "Config" and any(k.arg == "discord" for k in node.keywords):
                    after = copy.deepcopy(node)
                    after.keywords = [k for k in after.keywords if k.arg != "discord"]
                    operation = "remove_obsolete_config_discord_setup_keyword"
            elif (
                symbol in {
                    "test_skill_run_on_host_replays_the_incident_safely",
                    "test_skill_run_on_host_fails_closed_on_an_invalid_workspace",
                }
                and isinstance(node, ast.Assign)
                and dump(node) == (
                    "Assign(targets=[Attribute(value=Name(id='ctx', ctx=Load()), "
                    "attr='_executor', ctx=Store())], value=Name(id='executor', ctx=Load()))"
                )
            ):
                after = ast.parse(
                    "ctx = SkillContext(tool_executor=executor, skill_name='workspace-fixture', "
                    "requester_id=executor._permission_manager.authority.owner_id)"
                ).body[0]
                operation = "initialize_real_skill_context_with_fixture_owner"
            if after is not None:
                rules.append({
                    "symbol": symbol, "line": node.lineno, "operation": operation,
                    "before_sha256": hashlib.sha256(dump(node).encode()).hexdigest(),
                    "after_sha256": hashlib.sha256(dump(after).encode()).hexdigest(),
                    "after_source": ast.unparse(after),
                })
                replacements[id(node)] = ast.copy_location(after, node)

    class ExactSetup(ast.NodeTransformer):
        def visit(self, node):
            return replacements[id(node)] if id(node) in replacements else super().visit(node)

    rule_digest = hashlib.sha256(
        json.dumps(rules, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if rule_digest != SETUP_RULES_SHA256[name]:
        raise ValueError("exact setup rule admission changed")
    tree = ExactSetup().visit(tree)
    # Independent inverse replay proves ALL nonassert test/helper body AST,
    # not merely the assertion corpus. Each pinned replacement must occur once.
    reverse = copy.deepcopy(tree)
    for rule in reversed(rules):
        matches = [
            node for symbol, node in nodes(reverse)
            if symbol == rule["symbol"] and getattr(node, "lineno", None) == rule["line"]
            and hashlib.sha256(dump(node).encode()).hexdigest() == rule["after_sha256"]
        ]
        originals = [
            node for symbol, node in nodes(original)
            if symbol == rule["symbol"] and getattr(node, "lineno", None) == rule["line"]
            and hashlib.sha256(dump(node).encode()).hexdigest() == rule["before_sha256"]
        ]
        if len(matches) != 1 or len(originals) != 1:
            raise ValueError("inverse hunk is not exact and unique")
        target, before = matches[0], originals[0]

        class ReverseOne(ast.NodeTransformer):
            def visit(self, node):
                return copy.deepcopy(before) if node is target else super().visit(node)

        reverse = ReverseOne().visit(reverse)
    if dump(reverse) != dump(original):
        raise ValueError("unadmitted full-AST change")
    if corpus(original) != corpus(tree):
        raise ValueError("assertion/signature/decorator/parameter corpus changed")
    return original, tree, rules


def selected_tree(name):
    original, tree, rules = verified_tree(name)
    admitted = selection(name, original)
    body = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module in {
            "src.discord.connection_supervisor", "tests.test_main_exit_codes",
        }:
            # No selected definition uses these removed gateway fixtures.
            continue
        if isinstance(node, ast.ClassDef):
            selected = {case for case in admitted if case.startswith(node.name + ".")}
            if selected:
                node.body = [method for method in node.body if not (
                    isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and method.name.startswith("test_")
                    and f"{node.name}.{method.name}" not in selected
                )]
                body.append(node)
            elif name == "test_local_workspace" and not node.name.startswith("Test"):
                body.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                if node.name in admitted:
                    body.append(node)
            elif name == "test_local_workspace":
                body.append(node)
        else:
            body.append(node)
    tree.body = body
    if set(source_cases(tree)) != admitted:
        raise ValueError("selected definitions differ from exact allowlist")
    for symbol, node in source_cases(tree).items():
        before = source_cases(original)[symbol]
        if corpus(ast.Module(body=[before], type_ignores=[])) != corpus(
            ast.Module(body=[node], type_ignores=[])
        ):
            raise ValueError("selected case corpus changed")
    return ast.fix_missing_locations(tree), rules


def export_suite(namespace, name):
    tree, _ = selected_tree(name)
    module = ModuleType(f"step8_part5_engine_frozen_{name}")
    module.__file__ = str(ROOT / f"tests/{name}.py")
    exec(compile(tree, module.__file__, "exec"), module.__dict__)
    # Fixture decorators and helper globals belong to the loaded frozen module.
    for key, value in vars(module).items():
        if key.startswith("test_"):
            namespace[f"test_{name}_{key[5:]}"] = value
        elif key.startswith("Test"):
            alias = f"Test_{name}_{key}"
            value.__name__ = value.__qualname__ = alias
            value.__module__ = namespace["__name__"]
            namespace[alias] = value
        elif (
            getattr(value, "_pytestfixturefunction", None) is not None
            or getattr(value, "_fixture_function", None) is not None
        ):
            namespace[key] = value
