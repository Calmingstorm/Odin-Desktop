"""Frozen pure controller fixtures, never transport or native admission shims.

The controller's real authorizer, disabled state and ownership policy are retained.
Only an explicit Desktop surface on synthetic RequestContext construction and the
single neutral resume context are changed. Removed web-operator cases have exact
separate mappings and denial replacements, not weakened assertions.
"""

from __future__ import annotations

import ast
import copy
import json
from types import ModuleType

from scripts.maintenance.fixture_corpus import (
    ROOT,
    corpus,
    digest,
    dump,
    frozen_source,
    nodes,
)

REMOVED = {
    "test_computer_recovery_r5": {
        "test_operator_absence_unblocks_without_replay",
        "test_legacy_explicit_acknowledgment_is_not_clean",
        "test_recovery_operator_binding",
        "test_recovery_rechecks_auth_and_generation",
        "test_constructor_does_not_inspect_and_recovery_is_bounded",
    },
    "test_computer_recovery_reopen_campaign": {
        "test_terminal_fallback_reopens_with_resolution_and_history",
        "test_unknown_inspection_keeps_fence_and_admission_blocked",
    },
    "test_computer_local_recovery": {"test_closed_store_and_controller"},
    "test_computer_orchestration_coverage_r10": {
        "test_resume_rebinds_turn_consent_and_exports_evidence",
        "test_operator_authority_and_export",
    },
    "test_hyprland_recovery_controller": {
        "test_emergency_owned_release_resolves_only_released_input_on_reopen",
    },
    "test_hyprland_reconnect_protocol": set(),
    "test_computer_gui_actions_r5": {
        "test_web_operator_owner_read_cross_channel_not_model_authority",
    },
}
CORPUS_SELECTIONS = {name: None for name in REMOVED}
HELPERS = {"test_computer_actions_r4", "test_hyprland_durable_recovery"}
MODULES = {}
PROOFS = {}


def adapt(name):
    if name not in CORPUS_SELECTIONS and name not in HELPERS:
        raise ValueError("Computer fixture suite has not been audited")
    path = f"tests/{name}.py"
    source = frozen_source(path)
    original = ast.parse(source, filename=path)
    adapted = copy.deepcopy(original)
    edits = []

    class Setup(ast.NodeTransformer):
        def visit_Assert(self, node):
            return node

        def visit_FunctionDef(self, node):
            decorators = node.decorator_list
            node.decorator_list = []
            self.generic_visit(node)
            node.decorator_list = decorators
            return node

        def visit_AsyncFunctionDef(self, node):
            return self.visit_FunctionDef(node)

        def visit_Call(self, node):
            before = dump(node)
            if (
                name not in HELPERS
                or (name == "test_computer_actions_r4" and node.lineno == 91)
                or (name == "test_hyprland_durable_recovery" and node.lineno == 29)
            ) and (isinstance(node.func, ast.Name) and node.func.id == "RequestContext"):
                if not any(k.arg == "surface" for k in node.keywords):
                    if len(node.args) != 4 or any(k.arg is None for k in node.keywords):
                        raise ValueError("Unexpected synthetic context signature")
                    node.keywords.append(ast.keyword(arg="surface", value=ast.Constant("desktop")))
            if (
                name == "test_hyprland_recovery_controller"
                and node.lineno == 275
                and isinstance(node.func, ast.Name)
                and node.func.id == "replace"
            ):
                keywords = {k.arg: k for k in node.keywords}
                if dump(keywords["surface"].value) != dump(ast.Constant("webui")):
                    raise ValueError("Neutral resume surface hunk changed")
                keywords["surface"].value = ast.Constant("desktop")
            if dump(node) != before:
                edits.append(
                    {
                        "line": node.lineno,
                        "before_sha256": digest(before.encode()),
                        "after_sha256": digest(dump(node).encode()),
                        "after_source": ast.unparse(node),
                        "kind": "expression",
                    }
                )
            return node

        def visit_ImportFrom(self, node):
            substitutions = {
                ("tests.test_computer_actions_r4", "setup"): "fixture_setup",
                ("tests.test_hyprland_durable_recovery", "recovered"): "fixture_recovered",
            }
            result = []
            retained = []
            for alias in node.names:
                replacement = substitutions.get((node.module, alias.name))
                if replacement:
                    result.append(
                        ast.copy_location(
                            ast.ImportFrom(
                                module="tests.desktop_adapters.computer_cases",
                                names=[
                                    ast.alias(name=replacement, asname=alias.asname or alias.name)
                                ],
                                level=0,
                            ),
                            node,
                        )
                    )
                else:
                    retained.append(alias)
            if not result:
                return node
            if retained:
                result.insert(
                    0,
                    ast.copy_location(
                        ast.ImportFrom(module=node.module, names=retained, level=node.level), node
                    ),
                )
            edits.append(
                {
                    "line": node.lineno,
                    "kind": "import",
                    "before_sha256": digest(dump(node).encode()),
                    "after_sha256": digest(str([dump(n) for n in result]).encode()),
                    "after_source": "\n".join(ast.unparse(n) for n in result),
                }
            )
            return result

    adapted = Setup().visit(adapted)
    if corpus(original) != corpus(adapted):
        raise ValueError("Computer assertion, signature, decorator or parameter corpus changed")
    symbols = {id(n): s for s, n in nodes(original)}
    for edit in edits:
        matches = [
            n
            for _, n in nodes(original)
            if getattr(n, "lineno", None) == edit["line"]
            and digest(dump(n).encode()) == edit["before_sha256"]
        ]
        if len(matches) != 1:
            raise ValueError("Setup hunk did not match exactly one frozen node")
        edit["symbol"] = symbols[id(matches[0])]
    excluded = REMOVED.get(name, set())
    cases = [
        symbol
        for symbol, node in nodes(original)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]
    mappings = {case: f"Test_{name}::{case}" for case in cases if case not in excluded}
    if name in HELPERS:
        mappings = {}
    PROOFS[path] = {
        "path": path,
        "source_sha256": digest(source),
        "assert_case_ast_preserved": True,
        "transformations": edits,
        "original_ast_sha256": digest(dump(original).encode()),
        "adapted_ast_sha256": digest(dump(adapted).encode()),
        "corpus_sha256": digest(str(corpus(original)).encode()),
        "case_mapping": mappings,
        "helper_only": name in HELPERS,
    }
    PROOFS[path]["removed_cases"] = sorted(excluded)
    adapted.body = [
        n
        for n in adapted.body
        if not (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in excluded)
    ]
    return ast.fix_missing_locations(adapted)


def load(name):
    if name not in MODULES:
        tree = adapt(name)
        records = json.loads((ROOT / "maintenance/computer-suite-triage.json").read_text())
        proof = PROOFS[f"tests/{name}.py"]
        matches = [row for row in records["suites"] if row["path"] == proof["path"]]
        if len(matches) != 1 or matches[0]["proof_sha256"] != digest(
            json.dumps(proof, sort_keys=True).encode()
        ):
            raise ValueError("Computer fixture differs from exact frozen setup allowlist")
        module = ModuleType(f"desktop_frozen_{name}")
        module.__file__ = str(ROOT / f"tests/{name}.py")
        exec(compile(tree, module.__file__, "exec"), module.__dict__)
        MODULES[name] = module
    return MODULES[name]


fixture_setup = load("test_computer_actions_r4").setup
fixture_recovered = load("test_hyprland_durable_recovery").recovered


def export(namespace, name):
    module = load(name)
    members = {"__module__": namespace["__name__"]}
    for key, value in vars(module).items():
        if key.startswith("test_") or type(value).__name__ == "FixtureFunctionDefinition":
            members[key] = staticmethod(value)
    namespace[f"Test_{name}"] = type(f"Test_{name}", (), members)
