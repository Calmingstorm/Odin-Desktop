"""Offline frozen-fixture provenance and exact AST verification."""

from __future__ import annotations

import ast
import copy
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_SHA256 = "845d783bd4ee46cd44e63d56532512fd9cef10d08b1432e45047d155c6b348d0"
BASELINE = "cd7530906e9cfa10a0fa900247d7ce2a8bb33e25"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def dump(node):
    return ast.dump(node, include_attributes=False)


def frozen_source(path, *, root=ROOT):
    if not path.startswith("tests/") or ".." in Path(path).parts or not path.endswith(".py"):
        raise ValueError("Invalid frozen test path")
    archive = (root / "maintenance/odin-v4.13.0.tar.gz").read_bytes()
    if digest(archive) != ARCHIVE_SHA256:
        raise ValueError("Frozen archive hash changed")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
        members = [m for m in tf if m.name == path]
        if len(members) != 1 or not members[0].isfile():
            raise ValueError("Frozen test must be a unique regular member")
        stream = tf.extractfile(members[0])
        if stream is None:
            raise ValueError("Unreadable frozen test")
        data = stream.read()
    target = root / path
    if any(p.is_symlink() for p in [target, *target.parents]) or target.read_bytes() != data:
        raise ValueError(f"Retained bytes changed: {path}")
    return data


def nodes(tree, symbol="<module>"):
    yield symbol, tree
    for child in ast.iter_child_nodes(tree):
        name = symbol
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = child.name if symbol == "<module>" else f"{symbol}.{child.name}"
        yield from nodes(child, name)


def corpus(tree):
    return {
        "assertions": [(s, dump(n)) for s, n in nodes(tree) if isinstance(n, ast.Assert)],
        "cases": [
            (s, dump(n.args), [dump(d) for d in n.decorator_list])
            for s, n in nodes(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")
        ],
        "classes": [
            (s, [dump(d) for d in n.decorator_list])
            for s, n in nodes(tree)
            if isinstance(n, ast.ClassDef)
        ],
    }


def manifest(root=ROOT):
    data = json.loads((root / "maintenance/fixture-corpus.json").read_text())
    if (
        data["version"] != 1
        or data["baseline"] != BASELINE
        or data["archive_sha256"] != ARCHIVE_SHA256
    ):
        raise ValueError("Fixture manifest identity changed")
    return data


def suite_record(path, root=ROOT):
    matches = [row for row in manifest(root)["suites"] if row["path"] == path]
    if len(matches) != 1:
        raise ValueError(f"Unadmitted or duplicate suite: {path}")
    return matches[0]


def apply_transformations(path, original, *, root=ROOT):
    """Apply only exact symbol/line/whole-node AST hash setup hunks."""
    tree = copy.deepcopy(original)
    for rule in suite_record(path, root)["transformations"]:
        matches = [
            n
            for s, n in nodes(tree)
            if s == rule["symbol"]
            and getattr(n, "lineno", None) == rule["line"]
            and digest(dump(n).encode()) == rule["before_sha256"]
        ]
        if len(matches) != 1:
            raise ValueError("Setup hunk must match exactly once")
        target = matches[0]
        if rule.get("operation") == "remove_config_discord_keyword":
            if (
                not isinstance(target, ast.Call)
                or not isinstance(target.func, ast.Name)
                or target.func.id != "Config"
            ):
                raise ValueError("Expected Config setup call")
            expected = copy.deepcopy(target)
            expected.keywords = [k for k in expected.keywords if k.arg != "discord"]
        elif rule.get("operation") == "documentation_catalog_import":
            if not isinstance(target, ast.ImportFrom) or target.module not in {
                "src.tools",
                "src.tools.registry",
            }:
                raise ValueError("Expected static catalog import")
            expected = copy.deepcopy(target)
            expected.module = "src.tools.registry"
            for alias in expected.names:
                if alias.name == "get_tool_definitions":
                    alias.name, alias.asname = (
                        "get_documentation_tool_definitions",
                        "get_tool_definitions",
                    )
        elif rule.get("operation") == "fixture_import":
            if not isinstance(target, ast.ImportFrom):
                raise ValueError("Expected exact fixture import")
            expected = copy.deepcopy(target)
            if target.module and target.module.startswith("src.discord"):
                expected = []
            elif target.module in {"src.tools", "src.tools.registry"}:
                expected.module = "src.tools.registry"
                for alias in expected.names:
                    if alias.name == "get_tool_definitions":
                        alias.name, alias.asname = (
                            "get_documentation_tool_definitions",
                            "get_tool_definitions",
                        )
            elif target.module in {"src.tools.executor", "src.tools.skill_manager"}:
                name = "ToolExecutor" if target.module.endswith("executor") else "SkillManager"
                swapped = [a for a in expected.names if a.name == name]
                retained = [a for a in expected.names if a.name != name]
                expected = [
                    ast.ImportFrom(
                        module="tests.desktop_adapters.tools_cases", names=swapped, level=0
                    )
                ]
                if retained:
                    expected.append(ast.ImportFrom(module=target.module, names=retained, level=0))
            else:
                raise ValueError("Unapproved fixture import surface")
        elif rule.get("operation") == "owner_setup_call":
            if not isinstance(target, ast.Call):
                raise ValueError("Expected fixture setup call")
            expected = copy.deepcopy(target)
            for keyword in expected.keywords:
                if isinstance(keyword.value, ast.Constant):
                    if keyword.arg == "user_id" and keyword.value.value in {"u", "user"}:
                        keyword.value = ast.parse("desktop_fixture_owner_id()", mode="eval").body
                    elif keyword.arg == "tool_name" and keyword.value.value == "fixture":
                        keyword.value = ast.Constant(value="fetch_url")
        elif rule.get("operation") == "frozen_gate_setup":
            if rule["symbol"] != "<module>" or not isinstance(target, (ast.Assign, ast.Expr)):
                raise ValueError("Expected frozen gate module setup")
            expected = []
        else:
            expected = None
        if expected is None and ("after_sha256" not in rule or "after_source" not in rule):
            raise ValueError("Exact replacement source and hash are mandatory")
        if "after_source" not in rule:
            if expected is None:
                raise ValueError("Undeclared semantic setup operation")
            replacement = expected
        else:
            replacement = (
                ast.parse(rule["after_source"], mode="eval").body
                if rule["kind"] == "expression"
                else ast.parse(rule["after_source"]).body
            )
        representation = (
            dump(replacement)
            if isinstance(replacement, ast.AST)
            else json.dumps([dump(n) for n in replacement])
        )
        if "after_sha256" in rule and digest(representation.encode()) != rule["after_sha256"]:
            raise ValueError("Replacement hunk hash mismatch")
        actual = (
            replacement
            if isinstance(replacement, ast.AST)
            else replacement[0]
            if len(replacement) == 1
            else None
        )
        same = (
            json.dumps([dump(n) for n in expected]) == json.dumps([dump(n) for n in replacement])
            if isinstance(expected, list) and isinstance(replacement, list)
            else actual is not None
            and isinstance(expected, ast.AST)
            and dump(expected) == dump(actual)
        )
        if expected is not None and not same:
            raise ValueError(
                "Declared setup operation changed more than its admitted keyword/import"
            )

        class ExactReplacement(ast.NodeTransformer):
            def visit(self, node):
                if node is target:
                    if isinstance(replacement, list):
                        return [ast.copy_location(copy.deepcopy(n), node) for n in replacement]
                    return ast.copy_location(copy.deepcopy(replacement), node)
                return super().visit(node)

        tree = ExactReplacement().visit(tree)
    ast.fix_missing_locations(tree)
    if corpus(tree) != corpus(original):
        raise ValueError("Setup changed assertion/signature/parameter/decorator AST")
    return tree


def verify_transform(path, original, adapted, *, root=ROOT):
    if corpus(original) != corpus(adapted):
        raise ValueError("Assertion/signature/parameter/decorator AST changed")
    source = frozen_source(path, root=root)
    if digest(source) != suite_record(path, root)["baseline_sha256"] or dump(
        ast.parse(source)
    ) != dump(original):
        raise ValueError("Original AST does not match hash-pinned frozen baseline")
    if dump(apply_transformations(path, original, root=root)) != dump(adapted):
        raise ValueError("AST change outside exact setup hunk allowlist")
    return True


def register_module(namespace, module, *, prefix=None, full_class_name=False, excluded=()):
    """Rebase pytest fixture discovery; original globals retain real factories."""
    excluded = set(excluded)
    for name, value in list(vars(module).items()):
        if name in excluded:
            continue
        if name.startswith("test_") and callable(value):
            value.__module__ = namespace["__name__"]
            namespace[f"test_{prefix}_{name[5:]}" if prefix else name] = value
        elif name.startswith("Test") and isinstance(value, type):
            for method_name in list(vars(value)):
                if f"{name}.{method_name}" in excluded:
                    delattr(value, method_name)
            value.__module__ = namespace["__name__"]
            for method in vars(value).values():
                if isinstance(method, (staticmethod, classmethod)):
                    method = method.__func__
                if callable(method) and hasattr(method, "__module__"):
                    method.__module__ = namespace["__name__"]
            suffix = name if full_class_name else name[4:]
            namespace[f"Test_{prefix}_{suffix}" if prefix else name] = value


def case_mapping(path, tree, adapter_module, prefix=None):
    mapping = []
    for symbol, node in nodes(tree):
        if not isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) or not node.name.startswith("test_"):
            continue
        parts = symbol.split(".")
        if prefix:
            parts[0] = (
                f"Test_{prefix}_{parts[0][4:]}"
                if parts[0].startswith("Test")
                else f"test_{prefix}_{parts[0][5:]}"
            )
        mapping.append(
            {
                "baseline_selector": f"{path}::{symbol.replace('.', '::')}",
                "adapter_module": adapter_module,
                "executable_case": "::".join(parts),
                "assertions_sha256": digest(
                    json.dumps(
                        [dump(n) for n in ast.walk(node) if isinstance(n, ast.Assert)]
                    ).encode()
                ),
                "decorators_sha256": digest(
                    json.dumps([dump(d) for d in node.decorator_list]).encode()
                ),
                "signature_sha256": digest(dump(node.args).encode()),
            }
        )
    return mapping


def verify_record(path, *, root=ROOT):
    """Independent offline association: baseline bytes, adapter bytes and case IDs.

    Adapter hashes are checked only when declared. This does not execute or
    attest to runtime safety of an adapter; it proves the recorded association
    and immutable inherited assertion/parameter corpus.
    """
    row = suite_record(path, root)
    data = frozen_source(path, root=root)
    if digest(data) != row["baseline_sha256"]:
        raise ValueError("Independent baseline hash mismatch")
    original = ast.parse(data)
    adapted = apply_transformations(path, original, root=root)
    verify_transform(path, original, adapted, root=root)
    for adapter in row.get("adapter_hashes", []):
        relative = Path(adapter["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid adapter path")
        target = root / relative
        if (
            any(p.is_symlink() for p in [target, *target.parents])
            or digest(target.read_bytes()) != adapter["sha256"]
        ):
            raise ValueError("Adapter source association hash mismatch")
    return {
        "path": path,
        "baseline_sha256": digest(data),
        "assertions_sha256": digest(json.dumps(corpus(original)["assertions"]).encode()),
        "case_ids": [s.replace(".", "::") for s, _, _ in corpus(original)["cases"]],
        "cases": case_mapping(
            path, adapted, row.get("adapters", ["tests.test_desktop_shared_tools"])[0],
            row.get("prefix"),
        ),
    }


def adapter_case_associations(adapter_path, declaration_path, *, root=ROOT,
                              full_class_name=False):
    """Static original-to-executable selectors, including excluded methods.

    Reads literal declarations only. Never imports adapters, original tests, or
    their runtime dependencies. Frozen baseline bytes are independently checked.
    """
    for path in (adapter_path, declaration_path):
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError("Invalid adapter association path")
    source = (root / declaration_path).read_bytes()
    declaration = ast.parse(source)
    constants = {}
    for node in declaration.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {
                    "CORPUS_SELECTIONS", "CORPUS_EXCLUSIONS"
                }:
                    constants[target.id] = ast.literal_eval(node.value)
    if "CORPUS_SELECTIONS" not in constants:
        raise ValueError("Adapter has no literal case admission declaration")
    result = []
    module_name = adapter_path.removesuffix(".py").replace("/", ".")
    for stem, selected in constants["CORPUS_SELECTIONS"].items():
        path = f"tests/{stem if stem.startswith('test_') else 'test_' + stem}.py"
        data = frozen_source(path, root=root)
        tree = ast.parse(data)
        allowed = None if selected is None else set(selected)
        exclusions = constants.get("CORPUS_EXCLUSIONS", {}).get(stem, ())
        excluded = {row["case"] if isinstance(row, dict) else row for row in exclusions}
        for symbol, node in nodes(tree):
            if (not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    or not node.name.startswith("test_")):
                continue
            parts = symbol.split(".")
            if len(parts) > 2:
                continue
            if (symbol in excluded or allowed is not None
                    and parts[0] not in allowed and symbol not in allowed
                    and symbol.replace(".", "::") not in allowed):
                continue
            entry = case_mapping(path, ast.Module(body=[node], type_ignores=[]), module_name)[0]
            entry["baseline_selector"] = f"{path}::{symbol.replace('.', '::')}"
            if parts[0].startswith("Test"):
                suffix = parts[0] if full_class_name else parts[0][4:]
                head = f"Test_{stem}_{suffix}"
            else:
                head = f"test_{stem}_{parts[0][5:]}"
            entry["executable_selector"] = f"{adapter_path}::" + "::".join([head, *parts[1:]])
            entry["baseline_sha256"] = digest(data)
            result.append(entry)
    return {
        "adapter_path": adapter_path, "declaration_path": declaration_path,
        "adapter_sha256": digest((root / adapter_path).read_bytes()),
        "declaration_sha256": digest(source), "case_count": len(result),
        "mapping_sha256": digest(json.dumps(result, sort_keys=True).encode()),
        "cases": result,
    }
