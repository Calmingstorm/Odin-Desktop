"""Exact foundation cases, projected only after full assertion/parameter proof.

This does not restore a transport renderer or invent an execution admission.
Only constructor imports, owner identity and two inert YAML prefixes change.
"""
from __future__ import annotations

import ast
import copy
import hashlib
from types import ModuleType

from scripts.maintenance.fixture_corpus import ROOT, corpus, frozen_source
from src.tools.hosts import HostRegistry as EngineHostRegistry
from tests.desktop_adapters.tools_cases import ImportSurfaces, _fixture, owner_id

SELECTIONS = {
    "test_agent_campaign": [
        "test_full_canonical_digest_ignores_fresh_retention_ids",
        "test_same_preview_different_hidden_evidence_resets_guard",
        "test_binary_retention_digest_compares_full_bytes_not_manifest_ids",
        "test_ranked_canonical_digest_uses_full_matches_not_summary",
        "test_cancel_before_coroutine_entry_settles_and_persists",
    ],
    "test_config_persistence": [
        "TestAliasAwareness::test_legacy_config_round_trips_to_the_same_effective_value",
        "TestDualSpellings::test_dual_spelling_file_reloads_with_the_new_value",
    ],
    "test_tool_timeouts": [
        "TestExecutorConfigIntegration::test_executor_reads_config_tool_timeouts",
        "TestExecutorConfigIntegration::test_executor_config_change_reflected_immediately",
    ],
    "test_image_defaults_core": ["test_cancelled_pin_settles_before_return"],
    "test_config_schema_validators": [
        "TestFieldValidators::test_invalid_value_rejected",
        "test_removed_claude_code_settings_are_tolerated",
        "test_pre_control_plane_host_inventory_shapes_boot_without_rewrite",
    ],
    "test_tool_listing_contracts": [
        "test_skill_listing_loaded_disabled_and_load_error",
        "test_rejected_create_or_edit_does_not_add_failed_listing",
        "test_module_load_failures_are_visible_without_exposing_source",
        "test_agent_listing_models_and_effort_from_real_records",
        "test_executed_agent_missing_provenance_never_falls_back_to_requested",
    ],
}

YAML_PREFIX = "discord:\n  token: x\n"
RULES = {
    ("test_config_persistence", 534): (YAML_PREFIX + "search:\n  chromadb_path: /old\n"),
    ("test_config_persistence", 596): (
        YAML_PREFIX + "search:\n  search_db_path: /old\n  chromadb_path: /old\n"
    ),
    ("test_config_schema_validators", 495): "discord:\n  token: legacy\n",
    ("test_config_schema_validators", 547): (
        "discord:\n  token: legacy\ntools:\n  default_host: removed host\n"
        "  governor:\n    host_overrides:\n      removed host: allow\n  hosts:\n"
        "    1box:\n      address: example.invalid\n      os: windows\n"
        "    host with space:\n      address: other.invalid\n      os: Linux\n"
    ),
}
EVIDENCE = {}
CASE_MAP = {}


class HostRegistry(EngineHostRegistry):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("profile_paths", _fixture.get().paths)
        super().__init__(*args, **kwargs)


def adapted_tree(stem):
    path = f"tests/{stem}.py"
    source = frozen_source(path)
    original = ast.parse(source, filename=path)
    edits = []

    class Setup(ImportSurfaces):
        def visit_ImportFrom(self, node):  # noqa: N802 - AST visitor protocol
            if node.module == "src.tools.hosts" and any(
                    a.name == "HostRegistry" for a in node.names):
                node = copy.deepcopy(node)
                node.module = "tests.desktop_adapters.final_config"
            if stem == "test_config_schema_validators" and node.module == "src.config.schema":
                node = copy.deepcopy(node)
                node.names = [a for a in node.names
                              if a.name not in {"ApiTokenIdentity", "WebConfig"}]
            return super().visit_ImportFrom(node)

        def visit_Assert(self, node):  # noqa: N802 - AST visitor protocol
            return node

        def visit_Call(self, node):  # noqa: N802 - AST visitor protocol
            self.generic_visit(node)
            if (stem == "test_tool_listing_contracts" and isinstance(node.func, ast.Name)
                    and node.func.id == "Config"):
                for keyword in list(node.keywords):
                    if keyword.arg == "discord":
                        value = keyword.value
                        if (not isinstance(value, ast.Dict) or len(value.keys) != 1
                                or value.keys[0].value != "token"
                                or not isinstance(value.values[0], ast.Constant)):
                            raise ValueError("only inert Config transport token admitted")
                        node.keywords.remove(keyword)
                        edits.append({"line": node.lineno,
                                      "operation": "remove_inert_config_transport_keyword"})
            return node

        def visit_Constant(self, node):  # noqa: N802 - AST visitor protocol
            key = (stem, node.lineno)
            if key in RULES:
                # Python concatenates adjacent strings into one Constant. Seal
                # the exact original literal, not any arbitrary YAML transport.
                expected = RULES[key]
                if key == ("test_config_schema_validators", 495):
                    expected += (
                        "tools:\n  command_timeout_seconds: 123\n"
                        "  claude_code_host: localhost\n  claude_code_user: odin\n"
                        "  claude_code_dir: /old/project\n"
                    )
                if node.value != expected:
                    raise ValueError("sealed YAML fixture changed")
                edits.append({"line": node.lineno, "before_sha256": hashlib.sha256(
                    node.value.encode()).hexdigest(), "operation": "remove_inert_yaml_transport"})
                replacement = node.value.split("\n", 2)[2]
                return ast.copy_location(ast.Constant(value=replacement), node)
            return node

    adapted = Setup().visit(copy.deepcopy(original))
    # The entire corpus is compared BEFORE selecting tests or parameter rows.
    if corpus(original) != corpus(adapted):
        raise ValueError("full assertion/signature/decorator/parameter AST changed")
    EVIDENCE[path] = {
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "full_corpus_sha256": hashlib.sha256(repr(corpus(original)).encode()).hexdigest(),
        "full_assert_parameter_ast_preserved_before_projection": True,
        "sealed_fixture_edits": edits,
    }
    return adapted


def export_cases(namespace, stem):
    tree = adapted_tree(stem)
    selected = SELECTIONS[stem]
    projected = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            methods = {s.split("::")[1] for s in selected if s.startswith(node.name + "::")}
            if not methods:
                continue
            node.body = [n for n in node.body if not (
                isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name.startswith("test_") and n.name not in methods
            )]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_") and node.name not in selected:
                continue
        projected.append(node)
    tree.body = projected
    if stem == "test_config_schema_validators":
        method = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        case = next(n for n in method.body
                    if getattr(n, "name", "") == "test_invalid_value_rejected")
        rows = case.decorator_list[0].args[1]
        if len(rows.elts) != 14:
            raise ValueError("invalid-value parameter population changed")
        for row in rows.elts[12:]:
            if not isinstance(row, ast.Lambda) or row.body.func.id != "WebConfig":
                raise ValueError("only exact removed WebConfig rows may be projected")
        rows.elts = rows.elts[:12]
    ast.fix_missing_locations(tree)
    module = ModuleType(f"desktop_final_{stem}")
    module.__file__ = str(ROOT / f"tests/{stem}.py")
    module.desktop_fixture_owner_id = owner_id
    exec(compile(tree, module.__file__, "exec"), module.__dict__)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            name = f"TestFinal_{stem}_{node.name[4:]}"
            namespace[name] = vars(module)[node.name]
            for child in node.body:
                if getattr(child, "name", "").startswith("test_"):
                    original = f"tests/{stem}.py::{node.name}::{child.name}"
                    CASE_MAP[original] = f"{name}::{child.name}"
        elif (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
              and node.name.startswith("test_")):
            name = f"test_final_{stem}_{node.name[5:]}"
            namespace[name] = vars(module)[node.name]
            CASE_MAP[f"tests/{stem}.py::{node.name}"] = name
