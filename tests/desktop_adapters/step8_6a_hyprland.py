"""Exact frozen Hyprland cases, retained engines, no fabricated foreground runner."""
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

RECORD = "maintenance/step8-part4-hyprland-candidates.json"
CORPUS_SELECTIONS = {
    "test_hyprland_discovery_campaign": None,
    "test_computer_hyprland_integration_r32": None,
}
CORPUS_EXCLUSIONS = {"test_computer_hyprland_integration_r32": [
    {
        "case": "test_operator_recovery_fences_and_preserves_truth",
        "reviewer": "Claude, review of step 8 part 4",
        "reason": "Removed explicit webui RequestContext operator recovery; Desktop uses "
                  "sealed owner ManagementContext, not web operator authority.",
        "source_path": "tests/test_computer_hyprland_integration_r32.py",
        "source_sha256": "d314119fb1cadd3e70d754d68abc9c883c7ffeec3b903a324a155d8d2278452e",
    },
    {
        "case": "test_recovery_api_auth_and_truth",
        "reviewer": "Claude, review of step 8 part 4",
        "reason": "Removed HTTP /api/computer/release_owned_input, bearer browser sessions "
                  "and multi-user tiers.",
        "source_path": "tests/test_computer_hyprland_integration_r32.py",
        "source_sha256": "d314119fb1cadd3e70d754d68abc9c883c7ffeec3b903a324a155d8d2278452e",
    },
    {
        "case": "test_recovery_api_no_target_override",
        "reviewer": "Claude, review of step 8 part 4",
        "reason": "Removed HTTP /api/computer/release_owned_input route body validation.",
        "source_path": "tests/test_computer_hyprland_integration_r32.py",
        "source_sha256": "d314119fb1cadd3e70d754d68abc9c883c7ffeec3b903a324a155d8d2278452e",
    },
]}
SUITES = {
    "test_computer_hyprland_app_group_controller":
        "7cd016dbd6c71f40230f8b0c0066de18a9c856b09a66f40fe2bdce73da1e824a",
    "test_computer_hyprland_dialog_scope_r35":
        "58914febf57a8660e7d0a81cbbee61bf4cd715dc3264055d292200f4acaa38e0",
    "test_computer_hyprland_durable_fence_r42":
        "329499d39c7fce30524220a4b107bd3e656afce03877a5f57c48914487288024",
    "test_computer_hyprland_failure_r38":
        "ae9b034c0a799da1c300776f5bc6df2dc1961c3c34eec92fe89a70a0dcbad6e2",
    "test_computer_hyprland_failure_r41":
        "7b43167c9a26b3a46e5e4861087a3c02c25bd4a9bea75ed87c4d4b0fe8a3cb96",
    "test_computer_hyprland_integration_r32":
        "d314119fb1cadd3e70d754d68abc9c883c7ffeec3b903a324a155d8d2278452e",
    "test_computer_hyprland_receipts_r33":
        "4f959d278c7091e25a3a0a7eb4421df9f0cace52f68f567e41cb7fc184db9045",
    "test_computer_hyprland_settling_r35":
        "b86501febf3bbe5224d80c4a82baf5e862651f1282f524ca145f639b32a64bbf",
    "test_computer_hyprland_turnloop_r33":
        "529dee92a822edef1da3dad73245be1c4815ed06f12a187651a5ea8f98a051ed",
    "test_hyprland_clean_interruption_continuity":
        "a7a16d5d09fb8bccfa22c879785bcab7b89fa38f275303fb57c66af57b2e324c",
    "test_hyprland_discovery_campaign":
        "702606233a69db0b2793ce4a6a0d104dd17e66cd87a4c3c644531c6ee10e2f88",
    "test_hyprland_keyboard_raster_grounding":
        "e28f5918b6b1f4db887a85e34d170145210cb7ac23502a75268f2b9d4aa36ce8",
    "test_hyprland_multiturn_drawing":
        "e8b5288290ebed4db9d25938ac913f82b3ee8039dfdf821f8036c3c4a0db6bca",
    "test_hyprland_normal_turn_wire_r33":
        "9277c54475cead8f7a5a00d8a0d064841fdfa53a82b40d42af55f53720f7c462",
    "test_hyprland_popup_focus_working_paths":
        "b5e02b392381ced2541ca7d05eb347815d82258ac8012a9f68e77a7be37bd0ec",
    "test_hyprland_release_outcomes_regression":
        "fec2f274c5b9f98ef361fe27fca59984424ad4362445d23d393e12236c550c7b",
}
PROOFS = {}


def records():
    return json.loads((ROOT / RECORD).read_text())["suites"]


def adapted(name):
    path = f"tests/{name}.py"
    source = frozen_source(path)
    if hashlib.sha256(source).hexdigest() != SUITES[name]:
        raise ValueError("Hyprland frozen source byte hash changed")
    original = ast.parse(source, filename=path)
    adapted = copy.deepcopy(original)
    edits = []
    if name == "test_computer_hyprland_integration_r32":
        exact = {
            157: (
                "443203dffc610c84e54d987e3af22ec7fbf769bbd78aa34ec0e264874a358971",
                "ComputerController(store, lambda _: backend, desktop_authorize, enabled=True)",
            ),
            158: (
                "614adf04ac29a4f69c0ffbf2adcd139b6b619e791718ff62b92183a43d3f2643",
                "RequestContext(desktop_owner_id(), 'c', 't', 'h', surface='desktop')",
            ),
        }
        for line, (before_hash, replacement_source) in exact.items():
            matches = [(symbol, node) for symbol, node in nodes(adapted)
                       if symbol == "test_native_detach_certificate_keeps_ack_and_residual"
                       and getattr(node, "lineno", None) == line
                       and hashlib.sha256(dump(node).encode()).hexdigest() == before_hash]
            if len(matches) != 1:
                raise ValueError("Controller setup must match one frozen exact node")
            symbol, target = matches[0]
            replacement = ast.parse(replacement_source, mode="eval").body
            edits.append({"symbol": symbol, "line": line, "kind": "expression",
                          "before_sha256": before_hash,
                          "after_sha256": hashlib.sha256(dump(replacement).encode()).hexdigest(),
                          "after_source": replacement_source})

            class Exact(ast.NodeTransformer):
                def visit(self, node):
                    if node is target:
                        return ast.copy_location(copy.deepcopy(replacement), node)
                    return super().visit(node)

            adapted = Exact().visit(adapted)
        ast.fix_missing_locations(adapted)
        imports = [node for node in adapted.body if isinstance(node, ast.ImportFrom)
                   and node.module == "tests.test_computer_api"]
        if len(imports) != 1 or hashlib.sha256(dump(imports[0]).encode()).hexdigest() != (
            "97e01536494b3c6dc48c305a4cc12b16ff4e94fb7cb609e9eefd1c2db4fbd894"
        ):
            raise ValueError("Frozen HTTP-only helper import changed")
        adapted.body.remove(imports[0])
        edits.append({
            "symbol": "<module>", "line": 15, "kind": "import",
            "before_sha256": "97e01536494b3c6dc48c305a4cc12b16ff4e94fb7cb609e9eefd1c2db4fbd894",
            "after_sha256": hashlib.sha256(json.dumps([]).encode()).hexdigest(),
            "after_source": "",
        })
    if corpus(original) != corpus(adapted):
        raise ValueError("Hyprland assertion/signature/decorator/parameter corpus changed")
    PROOFS[path] = {"path": path, "source_sha256": SUITES[name],
                    "corpus_sha256": hashlib.sha256(str(corpus(original)).encode()).hexdigest(),
                    "original_ast_sha256": hashlib.sha256(dump(original).encode()).hexdigest(),
                    "adapted_ast_sha256": hashlib.sha256(dump(adapted).encode()).hexdigest(),
                    "assert_case_ast_preserved": True, "transformations": edits}
    if name in CORPUS_SELECTIONS:
        entry = next(item for item in json.loads((ROOT / RECORD).read_text())["entries"]
                     if item["path"] == path)
        if (entry["adapted_ast_sha256"] != PROOFS[path]["adapted_ast_sha256"]
                or entry["corpus_sha256"] != PROOFS[path]["corpus_sha256"]
                or entry["transformations"] != edits):
            raise ValueError("Hyprland exact audited setup/corpus manifest drift")
    return original, adapted


def project(tree, selected):
    """Only dependency projection for support evidence, never replacement logic."""
    bindings = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bindings[node.name] = node
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bindings[alias.asname or alias.name] = node
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bindings[alias.asname or alias.name.split(".")[0]] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for child in ast.walk(target):
                    if isinstance(child, ast.Name):
                        bindings[child.id] = node
    needed, queue = set(), list(selected)
    while queue:
        name = queue.pop()
        if name not in bindings:
            continue
        node = bindings[name]
        if id(node) in needed:
            continue
        needed.add(id(node))
        queue.extend(n.id for n in ast.walk(node)
                     if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load))
    return ast.fix_missing_locations(ast.Module(
        body=[node for node in tree.body if id(node) in needed], type_ignores=[]))


def _module(name, selected):
    original, adapted = globals()["adapted"](name)
    if name in CORPUS_SELECTIONS:
        projected = copy.deepcopy(adapted)
    else:
        projected = project(adapted, selected)
    module = ModuleType(f"desktop_step8_6a_hyprland_{name}")
    module.__file__ = str(ROOT / f"tests/{name}.py")
    # Only frozen R38 DETAIL is required by the selected pure R41 cases.
    if name == "test_computer_hyprland_failure_r41":
        imports = [node for node in projected.body if isinstance(node, ast.ImportFrom)
                   and node.module == "tests.test_computer_hyprland_failure_r38"]
        if len(imports) != 1 or [(a.name, a.asname) for a in imports[0].names] != [
                ("DETAIL", None), ("assert_revoked_owned_cleanup", None)]:
            raise ValueError("R41 frozen helper import changed")
        helper = _module("test_computer_hyprland_failure_r38", ["DETAIL"])
        module.__dict__["DETAIL"] = helper.DETAIL
        projected.body.remove(imports[0])
    if name == "test_computer_hyprland_integration_r32":
        from tests.desktop_adapters.step8_6a_computer import desktop_authorize, desktop_owner_id
        module.__dict__.update(
            desktop_owner_id=desktop_owner_id, desktop_authorize=desktop_authorize,
        )
        # The original HTTP-only Controller is an inherited pure fake, not
        # production policy. Load its exact closure so the complete original
        # RecoveryAPI class/cases compile, but never construct the HTTP listener.
        api_source = frozen_source("tests/test_computer_api.py")
        api_tree = ast.parse(api_source)
        api_helper = ModuleType("desktop_step8_hyprland_retired_api_helper")
        exec(compile(project(api_tree, ["Controller"]), "tests/test_computer_api.py", "exec"),
             api_helper.__dict__)
        module.__dict__["Controller"] = api_helper.Controller
        if corpus(projected) != corpus(adapted):
            raise ValueError("Full remaining corpus was not compiled")
    exec(compile(projected, module.__file__, "exec"), module.__dict__)
    return module


def load(namespace):
    for name in CORPUS_SELECTIONS:
        excluded = [item["case"] for item in CORPUS_EXCLUSIONS.get(name, ())]
        original, _ = adapted(name)
        selected = [
            symbol for symbol, n in nodes(original)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name.startswith("test_") and symbol not in excluded
        ]
        module = _module(name, selected)
        register_module(
            namespace, module, prefix=name,
            excluded=[item['case'] for item in CORPUS_EXCLUSIONS.get(name, ())],
        )
        for key, value in vars(module).items():
            if type(value).__name__ == "FixtureFunctionDefinition":
                namespace[key] = value


def load_support(namespace):
    for row in records():
        selected = row.get("support_cases", [])
        if not selected:
            continue
        name = row["path"].split("/")[-1][:-3]
        module = _module(name, selected)
        register_module(namespace, module, prefix=name)
        for key, value in vars(module).items():
            if type(value).__name__ == "FixtureFunctionDefinition":
                namespace[key] = value
