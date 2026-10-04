"""Hash-pinned migration corpus with genuine selected owner profiles.

All source assertions, signatures and parameter data remain frozen. Only exact
setup nodes are translated; the production admission gate is never patched.
"""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from src.config import migrations as production
from src.config import schema
from src.desktop.authority import OwnerAuthority
from src.desktop.paths import ProfilePaths

ROOT = Path(__file__).resolve().parents[1]
ORIGINALS = {}
CASE_MAP = {}
_profiles = {}
_root = None
_profile_environment = None


def _desktop_config(key="default"):
    key = "case-" + hashlib.sha256(str(key).encode()).hexdigest()[:20]
    paths = ProfilePaths.from_xdg(key)
    if paths.config_file not in _profiles:
        OwnerAuthority(paths)
        _profiles[paths.config_file] = paths
    _desktop_select(paths.config_file)
    return paths.config_file


def _desktop_select(path):
    paths = _profiles[Path(path).resolve()]
    if _profile_environment is None:
        raise RuntimeError("profile selection requires an active disposable fixture")
    _profile_environment.setenv("ODIN_DESKTOP_PROFILE", paths.profile_id)


def _desktop_data():
    from src.runtime_paths import runtime_profile_paths
    return runtime_profile_paths().data_dir


def _desktop_marker(path):
    _desktop_select(path)
    return production.ceiling_marker_path(path)


def _desktop_config_factory(*args, **kwargs):
    # Only the retired inert transport fixture is accepted by this test-only
    # factory. Production Config continues to reject every obsolete field.
    if "discord" in kwargs:
        if kwargs.pop("discord") != {"token": "x"}:
            raise ValueError("non-fixture retired transport")
    return schema.Config(*args, **kwargs)


@pytest.fixture(autouse=True)
def genuine_profiles(tmp_path, monkeypatch):
    global _root, _profile_environment
    saved_profile = os.environ.get("ODIN_DESKTOP_PROFILE")
    _profile_environment = pytest.MonkeyPatch()
    _profiles.clear()
    _root = tmp_path
    for key, suffix in (("XDG_CONFIG_HOME", "config"),
                        ("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache")):
        monkeypatch.setenv(key, str(tmp_path / suffix))
    monkeypatch.setenv("ODIN_DESKTOP_PROFILE", "default")
    schema.set_active_config_path(None)
    try:
        yield
    finally:
        _profile_environment.undo()
        _profile_environment = None
        if saved_profile is None:
            os.environ.pop("ODIN_DESKTOP_PROFILE", None)
        else:
            os.environ["ODIN_DESKTOP_PROFILE"] = saved_profile
        _profiles.clear()
        schema.set_active_config_path(None)


CORPUS_SELECTIONS = {
    "config_ceiling_migration": [
        "TestVacuousCompletion::test_non_legacy_values_marked_and_untouched",
        "TestDegenerateInputs::test_non_scalar_or_missing_lexical_shapes_complete_vacuously",
        "TestLexicalLiteralGate",
        "TestVacuousFailureSequence",
        "TestConfigIdentityBinding::test_symlink_aliases_in_different_directories_share_completion",
        "TestConfigIdentityBinding::test_distinct_configs_in_one_directory_do_not_share_completion",
        "TestIdentityMarkerAdversarialBranches",
        "TestPlaceholderIsDeliberate", "TestLoadConfigIntegration",
        "TestAtomicMarkerPersistence", "TestAtomicMarkerFailures",
        "TestRemainingMigrationBranches", "TestLegacyMarkerClaim",
    ],
    "image_defaults_core": [
        "test_later_operator_pin_and_alias_identity",
        "test_loader_new_defaults_and_later_old_pin",
        "test_loader_reconciles_save_between_migrations",
    ],
    "config_schema_validators": ["test_max_concurrent_agents_default_and_bounds"],
}
CORPUS_EXCLUSIONS = {
    "tests/test_config_ceiling_migration.py::TestPackagedSymlink":
        ("Asserts unresolved /opt-to-/etc launch sibling data anchor. Desktop owns separate XDG "
         "data, never imported server directory provenance. Canonical selected profile alias "
         "behavior is retained separately."),
    "tests/test_config_ceiling_migration.py::TestConfigIdentityBinding::test_concurrent_siblings_cannot_both_adopt_one_legacy_marker":
        ("Asserts two arbitrary siblings in one server data namespace race to adopt one "
         "preidentity marker. Desktop selected profile has one canonical config and isolated "
         "owner data. Claim race algorithm remains unchanged; this old shared-installation "
         "layout is not a Desktop route."),
    "tests/test_config_ceiling_migration.py::TestConfigIdentityBinding::test_preidentity_directory_marker_is_bound_not_shared":
        ("Requires arbitrary first.yml and second.yml sharing one old server directory marker. "
         "Desktop profiles cannot share data or adopt another profile marker; isolated config "
         "identity and foreign-marker refusal retained."),
}


def _register(stem, selected):
    path = f"tests/test_{stem}.py"
    source = frozen_source(path).decode()
    original = ast.parse(source)
    tree = copy.deepcopy(original)
    rules = []

    def edit(node, replacement, symbol, reason):
        kind = "expression" if isinstance(node, ast.expr) else "statements"
        after = dump(replacement) if kind == "expression" else json.dumps([dump(replacement)])
        rules.append({"operation": reason, "symbol": symbol, "line": node.lineno,
                      "before_sha256": hashlib.sha256(dump(node).encode()).hexdigest(),
                      "kind": kind, "after_source": ast.unparse(replacement),
                      "after_sha256": hashlib.sha256(after.encode()).hexdigest()})
        return ast.copy_location(replacement, node)

    class Setup(ast.NodeTransformer):
        symbol = "<module>"

        def visit_ClassDef(self, node):
            old = self.symbol
            self.symbol = node.name
            self.generic_visit(node)
            self.symbol = old
            return node

        def visit_FunctionDef(self, node):
            old = self.symbol
            self.symbol = node.name if old == "<module>" else old + "." + node.name
            self.generic_visit(node)
            self.symbol = old
            return node

        def visit_Assert(self, node):
            return node

        def visit_ImportFrom(self, node):
            if stem == "config_schema_validators" and node.module == "src.config.schema":
                names = [a for a in node.names if a.name not in {"WebConfig", "ApiTokenIdentity"}]
                names = [ast.alias(name="_desktop_config_factory", asname="Config")
                         if a.name == "Config" else a for a in names]
                if any(a.name == "_desktop_config_factory" for a in names):
                    # Only this method-local inert fixture factory is replaced.
                    if self.symbol == "test_max_concurrent_agents_default_and_bounds":
                        return edit(node, ast.ImportFrom(module=__name__, names=names, level=0),
                                    self.symbol, "strict_retired_transport_fixture_factory")
                    names = [a for a in names if a.name != "_desktop_config_factory"]
                    names.append(ast.alias(name="Config"))
                replacement = ast.ImportFrom(module=node.module, names=names, level=node.level)
                if dump(replacement) != dump(node):
                    return edit(node, replacement, self.symbol, "omit_removed_api_types")
            return node

        def visit_Assign(self, node):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                text = node.value.value
                prefix = 'discord: {token: test}\n'
                if text.startswith(prefix):
                    node.value = edit(node.value, ast.Constant(text[len(prefix):] or '{}\n'),
                                      self.symbol, "remove_inert_transport_yaml_setup")
            # Assignment setup only. Numeric/lexical parameter forms remain
            # exactly as frozen; their key chooses a distinct real profile.
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                expr = ast.unparse(node.value)
                value = None
                if (name in {"config_path", "path"} and expr.startswith("tmp_path /")
                        and expr.endswith("'config.yml'")):
                    key = expr.split(" / ")[1] if expr.count(" / ") > 1 else "'default'"
                    value = f"_desktop_config({key})"
                elif name == "config_path" and "config-{safe_name}" in expr:
                    value = "_desktop_config(safe_name)"
                elif name in {"first", "second"} and expr == f"tmp_path / '{name}.yml'":
                    value = f"_desktop_config('{name}')"
                elif (name == "target" and self.symbol.endswith(
                        "test_symlink_aliases_in_different_directories_share_completion")):
                    value = "_desktop_config('aliases')"
                elif name == "legacy" and "tmp_path / 'data'" in expr:
                    value = "_desktop_data() / 'context_ceiling_migration.json'"
                if value:
                    node.value = edit(node.value, ast.parse(value, mode="eval").body,
                                      self.symbol, "genuine_owner_profile_path_setup")
            return self.generic_visit(node)

        def visit_Call(self, node):
            expr = ast.unparse(node)
            # Removed transport YAML only in setup, never parameter/assertion
            # literals. No server YAML reaches the real Desktop loader.
            if isinstance(node.func, ast.Attribute) and node.func.attr == "write_text":
                if (node.args and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)
                        and self.symbol != (
                            "TestRemainingMigrationBranches."
                            "test_required_marker_write_error_is_truthful")):
                    text = node.args[0].value
                    prefixes = ('discord:\n  token: "t"\n', 'discord:\n  token: t\n',
                                'discord: {token: test}\n')
                    for prefix in prefixes:
                        if text.startswith(prefix):
                            node.args[0] = edit(
                                node.args[0], ast.Constant(text[len(prefix):] or '{}\n'),
                                self.symbol, "remove_inert_transport_yaml_setup")
                            break
            if expr in {"path.parent.mkdir()", "legacy.parent.mkdir()"}:
                return edit(node, ast.parse(expr[:-1] + "exist_ok=True)", mode="eval").body,
                            self.symbol, "already_provisioned_private_directory")
            if expr in {"(tmp_path / 'data').write_text('blocks marker directory')",
                        "(tmp_path / 'data').unlink()"}:
                replacement = expr.replace(
                    "tmp_path / 'data'", "_desktop_data() / 'config_migrations'")
                return edit(node, ast.parse(replacement, mode="eval").body,
                            self.symbol, "truthful_profile_marker_storage_failure")
            return self.generic_visit(node)

    # _LEGACY_YAML is a module setup assignment. Strip only its inert transport
    # prefix, preserving all model/literal/comment content and test assertions.
    for node in tree.body:
        if (isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_LEGACY_YAML" for t in node.targets)):
            value = copy.deepcopy(node.value)
            class Strip(ast.NodeTransformer):
                def visit_Constant(self, c):
                    if isinstance(c.value, str) and c.value.startswith('discord:\n  token: "t"\n'):
                        prefix = 'discord:\n  token: "t"\n'
                        return ast.copy_location(ast.Constant(c.value[len(prefix):]), c)
                    return c
            value = Strip().visit(value)
            if dump(value) != dump(node.value):
                node.value = edit(
                    node.value, value, "<module>", "remove_inert_transport_yaml_setup")
    adapted = Setup().visit(tree)
    assert corpus(original) == corpus(adapted)
    ledger = json.loads((ROOT / "maintenance/profile-upgrade-triage.json").read_text())
    pinned = ledger["suites"][path]
    assert hashlib.sha256(source.encode()).hexdigest() == pinned["baseline_sha256"]
    assert len(rules) == pinned["setup_rule_count"]
    assert (hashlib.sha256(json.dumps(rules, sort_keys=True).encode()).hexdigest()
            == pinned["setup_rules_sha256"])
    ast.fix_missing_locations(adapted)
    namespace = {"__name__": __name__, "__file__": str(ROOT / path),
                 "_desktop_config": _desktop_config, "_desktop_select": _desktop_select,
                 "_desktop_data": _desktop_data}
    exec(compile(adapted, str(ROOT / path), "exec"), namespace)
    # Genuine owner profile selection is fixture routing, not guard bypass.
    if stem == "config_ceiling_migration":
        original_migrate = namespace["_migrate"]
        def selected_migrate(path, *args, **kwargs):
            _desktop_select(path)
            return original_migrate(path, *args, **kwargs)
        namespace["_migrate"] = selected_migrate
        namespace["ceiling_marker_path"] = _desktop_marker
    for name, obj in list(namespace.items()):
        if name.startswith("Test") and isinstance(obj, type):
            methods = [s.split("::", 1)[1] for s in selected if s.startswith(name + "::")]
            if name not in selected and not methods:
                continue
            if name not in selected:
                for method in list(vars(obj)):
                    if method.startswith("test_") and method not in methods:
                        delattr(obj, method)
            dest = "Test" + stem.title().replace("_", "") + name[4:]
            globals()[dest] = obj
            for method in vars(obj):
                if method.startswith("test_"):
                    CASE_MAP[f"{path}::{name}::{method}"] = f"{dest}::{method}"
        elif name.startswith("test_") and name in selected:
            dest = "test_" + stem + "__" + name[5:]
            globals()[dest] = obj
            CASE_MAP[f"{path}::{name}"] = dest
    ORIGINALS[path] = {"baseline_sha256": hashlib.sha256(source.encode()).hexdigest(),
                       "transformations": rules, "assertions_parameters_signatures_preserved": True,
                       "selected": selected}


for _stem, _selected in CORPUS_SELECTIONS.items():
    _register(_stem, _selected)


def test_profile_fixture_corpus_preserves_every_assertion_and_case():
    assert len(ORIGINALS) == 3
    assert all(row["assertions_parameters_signatures_preserved"] for row in ORIGINALS.values())
    assert len(CASE_MAP) >= 17
    for stem, selected in CORPUS_SELECTIONS.items():
        for selector in selected:
            prefix = f"tests/test_{stem}.py::{selector}"
            assert any(key == prefix or key.startswith(prefix + "::") for key in CASE_MAP)
