"""Frozen retirement corpus with exact inert YAML setup removal only.

The completed-image-upgrade case uses the actual selected owner profile. Other
loader cases remain explicit external reads, with runtime-only normalization.
No schema substitutes, production monkeypatches, or assertion edits are used.
"""

import ast
import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source

ROOT = Path(__file__).resolve().parents[1]
ORIGINALS = {}
CASE_MAP = {}
CORPUS_SELECTIONS = {"codex_55_retirement": None, "codex_spark_retirement": None}
CORPUS_EXCLUSIONS = {
    "codex_55_retirement": ["test_active_ui_does_not_offer_retired_model"],
}
_PROFILE_CASE = "test_retired_image_pin_after_completed_image_upgrade_is_migrated"
_profile_paths = None


@pytest.fixture(autouse=True)
def retirement_profile_environment(tmp_path, monkeypatch):
    """Disposable XDG roots; provision only the case needing durable completion."""
    global _profile_paths
    from src.config import schema

    old_active = schema.active_config_path()
    old_launch = schema.active_config_launch_path()
    for key, suffix in (("XDG_CONFIG_HOME", "config"),
                        ("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache")):
        monkeypatch.setenv(key, str(tmp_path / suffix))
    monkeypatch.setenv("ODIN_DESKTOP_PROFILE", "retirement-case")
    _profile_paths = None
    schema.set_active_config_path(None)
    try:
        yield
    finally:
        _profile_paths = None
        schema.set_active_config_path(old_launch or old_active)


def _retirement_profile_config():
    global _profile_paths
    from src.desktop.authority import OwnerAuthority
    from src.runtime_paths import runtime_profile_paths

    if _profile_paths is None:
        _profile_paths = runtime_profile_paths()
        OwnerAuthority(_profile_paths)
    return _profile_paths.config_file


def _register(stem):
    path = f"tests/test_{stem}.py"
    source_bytes = frozen_source(path)
    source = source_bytes.decode()
    original = ast.parse(source, filename=str(ROOT / path))
    tree = copy.deepcopy(original)
    rules = []

    def edit(node, replacement, symbol, operation):
        rules.append({
            "operation": operation, "symbol": symbol, "line": node.lineno,
            "before_sha256": hashlib.sha256(dump(node).encode()).hexdigest(),
            "kind": "expression", "after_source": ast.unparse(replacement),
            "after_sha256": hashlib.sha256(dump(replacement).encode()).hexdigest(),
        })
        return ast.copy_location(replacement, node)

    class Setup(ast.NodeTransformer):
        symbol = "<module>"

        def visit_FunctionDef(self, node):
            old = self.symbol
            self.symbol = node.name
            self.generic_visit(node)
            self.symbol = old
            return node

        def visit_Assert(self, node):
            # Includes source equality assertions referencing edited setup vars.
            return node

        def visit_Constant(self, node):
            if not isinstance(node.value, str):
                return node
            prefixes = ("discord: {token: test}\n", "discord:\n  token: test\n")
            for prefix in prefixes:
                if node.value.startswith(prefix):
                    # A setup-only literal prefix, never a model/parameter enum.
                    text = node.value[len(prefix):]
                    if not text:
                        text = "{}\n"
                    return edit(node, ast.Constant(value=text), self.symbol,
                                "remove_inert_discord_yaml_prefix")
            return node

        def visit_BinOp(self, node):
            if (self.symbol == _PROFILE_CASE and isinstance(node.op, ast.Div)
                    and isinstance(node.left, ast.Name) and node.left.id == "tmp_path"
                    and isinstance(node.right, ast.Constant)
                    and node.right.value == "config.yml"):
                return edit(node, ast.parse("_retirement_profile_config()", mode="eval").body,
                            self.symbol, "genuine_selected_owner_profile_config")
            return self.generic_visit(node)

    tree = Setup().visit(tree)
    ast.fix_missing_locations(tree)
    if corpus(tree) != corpus(original):
        raise ValueError(f"Frozen assertions/signatures/parameters changed: {path}")
    # Independently replay every exact setup hunk against the FULL baseline AST
    # before excluding even the one retired frontend inspection.
    replay = copy.deepcopy(original)
    for rule in rules:
        matches = []
        def locate(node, symbol="<module>"):
            if isinstance(node, ast.FunctionDef):
                symbol = node.name
            if (symbol == rule["symbol"]
                    and getattr(node, "lineno", None) == rule["line"]
                    and hashlib.sha256(dump(node).encode()).hexdigest()
                    == rule["before_sha256"]):
                matches.append(node)
            for child in ast.iter_child_nodes(node):
                locate(child, symbol)
        locate(replay)
        if len(matches) != 1:
            raise ValueError("Setup rule is not unique in full frozen tree")
        replacement = ast.parse(rule["after_source"], mode="eval").body
        if hashlib.sha256(dump(replacement).encode()).hexdigest() != rule["after_sha256"]:
            raise ValueError("Setup replacement hash changed")
        target = matches[0]
        class Exact(ast.NodeTransformer):
            def visit(self, node):
                if node is target:
                    return ast.copy_location(copy.deepcopy(replacement), node)
                return super().visit(node)
        replay = Exact().visit(replay)
    if dump(replay) != dump(tree) or corpus(replay) != corpus(original):
        raise ValueError("Change outside recorded full-tree setup allowlist")
    ORIGINALS[path] = {
        "sha256": hashlib.sha256(source_bytes).hexdigest(),
        "edits": rules,
        "setup_rules_sha256": hashlib.sha256(
            json.dumps(rules, sort_keys=True).encode()
        ).hexdigest(),
        "assert_case_ast_preserved": True,
        "full_tree_verified_before_selection": True,
    }
    excluded = set(CORPUS_EXCLUSIONS.get(stem, ()))
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.FunctionDef) and node.name in excluded)]
    namespace = {"__name__": __name__, "__file__": str(ROOT / path),
                 "_retirement_profile_config": _retirement_profile_config}
    exec(compile(tree, str(ROOT / path), "exec"), namespace)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            exported = f"test_{stem}__{node.name[5:]}"
            globals()[exported] = namespace[node.name]
            CASE_MAP[f"{path}::{node.name}"] = exported


for _stem in CORPUS_SELECTIONS:
    _register(_stem)


def test_selected_profile_retirement_serving_preserves_operator_alias_namespaces():
    """Supplemental Desktop serving case, not attributed to the frozen corpus."""
    from src.config.schema import active_config_path, load_config

    path = _retirement_profile_config()
    path.write_text("{}\n")
    load_config(path)
    marker_dir = _profile_paths.data_dir / "config_migrations"
    markers = {p.name: p.read_bytes() for p in marker_dir.iterdir() if p.is_file()}
    assert markers
    original = (
        "openai_codex: &shared {model: gpt-5.3-codex-spark}\n"
        "ollama: *shared\n"
        "image: {openai: {outer_model: gpt-5.5}}\n"
    )
    path.write_text(original)
    cfg = load_config(path)
    assert active_config_path() == path.resolve()
    assert cfg.openai_codex.model == "gpt-6-sol"
    assert cfg.ollama.model == "gpt-5.3-codex-spark"
    assert cfg.image.openai.outer_model == "gpt-6-astra"
    assert path.read_text() == original
    assert {p.name: p.read_bytes() for p in marker_dir.iterdir() if p.is_file()} == markers
    assert load_config(path).openai_codex == cfg.openai_codex
    assert path.read_text() == original


def test_retirement_adapter_full_tree_provenance_and_case_accounting():
    """Additional audit, not an invented inherited retirement case."""
    record = json.loads((ROOT / "maintenance/retirement-suite-triage.json").read_text())
    assert record["adapter_sha256"] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    assert record["state"] == "focused-proof-full-gate-and-independent-review-pending"
    assert record["case_map_sha256"] == hashlib.sha256(
        json.dumps(CASE_MAP, sort_keys=True).encode()
    ).hexdigest()
    assert record["suites"] == {
        path: {"baseline_sha256": evidence["sha256"],
               "setup_rule_count": len(evidence["edits"]),
               "setup_rules_sha256": evidence["setup_rules_sha256"]}
        for path, evidence in ORIGINALS.items()
    }
    inherited_total = 0
    for path, evidence in ORIGINALS.items():
        original = ast.parse(frozen_source(path))
        functions = {n.name: n for n in original.body if isinstance(n, ast.FunctionDef)}
        inherited_total += len(functions)
        assert evidence["full_tree_verified_before_selection"]
        assert evidence["assert_case_ast_preserved"]
        for rule in evidence["edits"]:
            candidates = [
                n for n in ast.walk(functions[rule["symbol"]])
                if getattr(n, "lineno", None) == rule["line"]
                and hashlib.sha256(dump(n).encode()).hexdigest() == rule["before_sha256"]
            ]
            assert len(candidates) == 1
            target = candidates[0]
            replacement = ast.parse(rule["after_source"], mode="eval").body
            if rule["operation"] == "remove_inert_discord_yaml_prefix":
                assert isinstance(target, ast.Constant) and isinstance(target.value, str)
                prefix = next(p for p in ("discord: {token: test}\n", "discord:\n  token: test\n")
                              if target.value.startswith(p))
                assert dump(replacement) == dump(
                    ast.Constant(target.value[len(prefix):] or "{}\n")
                )
            else:
                assert rule["operation"] == "genuine_selected_owner_profile_config"
                assert rule["symbol"] == _PROFILE_CASE
                assert dump(target) == dump(
                    ast.parse('tmp_path / "config.yml"', mode="eval").body
                )
                assert dump(replacement) == dump(
                    ast.parse("_retirement_profile_config()", mode="eval").body
                )
    # Parameterization expands 20 functions to 31 upstream cases. One frontend
    # inspection is excluded: 30 inherited executable cases, one supplemental
    # genuine Desktop serving case, and this separate provenance audit.
    assert inherited_total == 20
    assert len(CASE_MAP) == 19
    assert record["inherited_cases_passed"] == 30
    assert record["supplemental_retirement_cases_passed"] == 1
    assert record["retirement_cases_passed"] == 31
    assert record["audit_cases_passed"] == 1
    assert record["excluded_cases"] == [{
        "original": ("tests/test_codex_55_retirement.py::"
                     "test_active_ui_does_not_offer_retired_model"),
        "reason": ("Reads retired server ui/js/pages/llm-config.js; exact frontend "
                   "inspection has no Desktop application route."),
    }]
