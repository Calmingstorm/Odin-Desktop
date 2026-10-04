"""Frozen shared engine corpus, using audited Desktop-only fixture setup."""

import ast
import copy
import hashlib
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ORIGINALS = {}
CASE_MAP = {}


@pytest.fixture
def desktop_profile_config_dir(tmp_path, monkeypatch):
    from src.desktop.authority import OwnerAuthority
    from src.desktop.paths import ProfilePaths
    paths = ProfilePaths.from_xdg(environ={
        "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
        "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
        "XDG_CACHE_HOME": str(tmp_path / "xdg-cache"),
    })
    OwnerAuthority(paths)
    monkeypatch.setattr("src.runtime_paths.runtime_profile_paths", lambda: paths)
    return paths.config_dir


def _proof(tree, source):
    return (
        [(ast.dump(n, include_attributes=False), ast.get_source_segment(source, n))
         for n in ast.walk(tree) if isinstance(n, ast.Assert)],
        [ast.dump(d, include_attributes=False) for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
         for d in n.decorator_list],
    )


def _load_corpus(stem, selected=None, *, destination=None):
    path = f"tests/test_{stem}.py"
    archive = ROOT / "maintenance/odin-v4.13.0.tar.gz"
    expected_archive = "845d783bd4ee46cd44e63d56532512fd9cef10d08b1432e45047d155c6b348d0"
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected_archive
    with tarfile.open(archive) as frozen:
        member = next(m for m in frozen.getmembers() if m.name.lstrip("./") == path)
        source_bytes = frozen.extractfile(member).read()
    assert (ROOT / path).read_bytes() == source_bytes
    source = source_bytes.decode()
    tree = ast.parse(source, filename=path)
    if selected is not None:
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                methods = {s.split("::", 1)[1] for s in selected if s.startswith(node.name + "::")}
                if methods:
                    node.body = [n for n in node.body if not (
                        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and
                        n.name.startswith("test_") and n.name not in methods
                    )]
    tree.body = [n for n in tree.body if not (
        selected is not None
        and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and (n.name.startswith("test_") or n.name.startswith("Test")) and n.name not in selected
        and not any(s.startswith(n.name + "::") for s in selected)
    )]
    before = _proof(tree, source)
    edits = []

    class Setup(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            self.generic_visit(node)
            profile_suites = {
                "image_defaults_core", "config_ceiling_migration", "campaign_coverage_core_config"
            }
            if stem in profile_suites and node.name.startswith("test_"):
                for arg in node.args.args:
                    if arg.arg == "tmp_path":
                        arg.arg = "desktop_profile_config_dir"
                        node.body.insert(0, ast.Assign(
                            targets=[ast.Name(id="tmp_path", ctx=ast.Store())],
                            value=ast.Name(id="desktop_profile_config_dir", ctx=ast.Load()),
                        ))
                        edits.append((node.lineno, "fresh owner profile config-dir fixture"))
            return node

        def visit_Assert(self, node):
            return node

        def visit_Call(self, node):
            self.generic_visit(node)
            if isinstance(node.func, ast.Name) and node.func.id == "Config":
                for keyword in list(node.keywords):
                    if keyword.arg == "discord":
                        assert isinstance(keyword.value, ast.Dict)
                        assert [k.value for k in keyword.value.keys] == ["token"]
                        assert isinstance(keyword.value.values[0], ast.Constant)
                        node.keywords.remove(keyword)
                        edits.append((node.lineno, "remove Config dummy discord keyword"))
            return node

        def visit_Assign(self, node):
            self.generic_visit(node)
            if stem == "multi_provider_schema_boundaries" and isinstance(node.value, ast.Dict):
                pairs = list(zip(node.value.keys, node.value.values))
                if any(isinstance(k, ast.Constant) and k.value == "discord" for k, _ in pairs):
                    assert len(node.targets) == 1 and node.targets[0].id == "raw"
                    pairs = [(k, v) for k, v in pairs
                             if not (isinstance(k, ast.Constant) and k.value == "discord")]
                    node.value.keys, node.value.values = map(list, zip(*pairs))
                    edits.append((node.lineno, "remove raw setup transport member"))
            return node

        def visit_ImportFrom(self, node):
            if stem == "campaign_coverage_core_config" and node.module == "src.config":
                node.names = [a for a in node.names if a.name != "package_migrations"]
            if stem == "agent_tool_policy_branch_coverage" and node.module == "src.tools.registry":
                for alias in node.names:
                    if alias.name == "get_tool_definitions":
                        alias.name = "get_documentation_tool_definitions"
                        alias.asname = "get_tool_definitions"
                        edits.append((node.lineno, "static documentation catalogue import only"))
            if stem == "config_schema_validators" and node.module == "src.config.schema":
                node.names = [a for a in node.names
                              if a.name not in {"WebConfig", "ApiTokenIdentity"}]
                edits.append((node.lineno, "omit removed API types for neutral selected cases"))
            return node

    adapted = Setup().visit(copy.deepcopy(tree))
    assert _proof(adapted, source) == before, f"assertion/case mutation: {path}"
    ast.fix_missing_locations(adapted)
    namespace = {"__name__": __name__, "__file__": str(ROOT / path)}
    exec(compile(adapted, str(ROOT / path), "exec"), namespace)
    target = globals() if destination is None else destination
    for node in adapted.body:
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            name = "Test" + "".join(p.title() for p in stem.split("_")) + node.name[4:]
            target[name] = namespace[node.name]
            for case in node.body:
                if (isinstance(case, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and case.name.startswith("test_")):
                    CASE_MAP[f"{path}::{node.name}::{case.name}"] = f"{name}::{case.name}"
        elif (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
              and node.name.startswith("test_")):
            name = f"test_{stem}__{node.name[5:]}"
            target[name] = namespace[node.name]
            CASE_MAP[f"{path}::{node.name}"] = name
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
            (isinstance(d, ast.Attribute) and d.attr == "fixture") or
            (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
             and d.func.attr == "fixture")
            for d in node.decorator_list
        ):
            target[node.name] = namespace[node.name]
    ORIGINALS[path] = {"sha256": hashlib.sha256(source_bytes).hexdigest(), "edits": edits,
                       "assert_case_ast_preserved": True, "assert_source_spans_preserved": True}
    return namespace

CORPUS_SELECTIONS = {
    "model_ref": None,
    "multi_provider_schema_boundaries": None,
    "agent_tool_policy_branch_coverage": None,
    "bulkhead": [
        "TestBulkhead", "TestBulkheadRegistry", "TestBulkheadFullError", "TestBulkheadConfig",
        "TestBuildBulkheadRegistry", "TestConfigRoundTrip",
    ],
    "outbound_webhooks": ["TestOutboundWebhookTargetConfig", "TestOutboundWebhooksConfig"],
    "tool_timeouts": ["TestConfigYAMLCompat"],
    "config_schema_validators": [
        "TestSubstituteEnvVars", "TestCodexReasoningEffort", "TestCodexTransportTimeouts",
        "TestAgentsTimeoutConfig", "TestAgentReasoningEffortConfig", "TestAgentModelConfig",
        "test_max_children_per_agent_upper_bound",
        "TestLoadConfig::test_missing_env_var_is_systemexit",
        "TestLoadConfig::test_bad_yaml_is_systemexit",
        "TestLoadConfig::test_non_mapping_is_systemexit",
        "TestLoadConfig::test_validation_failure_is_systemexit",
    ],
    "config_persistence": [
        "TestSubmittedLeaves", "TestPatchConfigPaths", "TestPersistConfigPaths",
        "TestPlaceholderGuard",
        "TestWebhookPlaceholderGuard", "TestCancellationSettlement", "TestTypedPlaceholders",
        "TestAnchorSafety", "TestPersistOutcomeAndMetadata",
        "TestAliasAwareness::test_submitted_alias_resolves_to_the_canonical_field",
        "TestAliasAwareness::test_without_the_schema_an_alias_is_still_dropped",
        "TestAliasAwareness::test_schema_owned_mapping_persists_only_submitted_canonicalized_entries",
        "TestAliasAwareness::test_canonical_key_still_resolves_normally",
        "TestAliasAwareness::test_writer_updates_the_legacy_key_the_file_uses",
        "TestAliasAwareness::test_writer_uses_the_canonical_key_when_the_file_has_it",
        "TestAliasAwareness::test_writer_creates_the_canonical_key_when_neither_exists",
        "TestDualSpellings::test_both_present_keys_are_updated",
    ],
    "version": None,
    "config_ceiling_migration": [
        "TestOneTimeRewrite",
        "TestVacuousCompletion::test_fresh_null_then_hand_written_750k_is_honored",
        "TestVacuousCompletion::test_absent_sections_complete_vacuously", "TestNoResurrection",
        "TestFailureHonesty",
        "TestDegenerateInputs::test_unparseable_original_text_completes_vacuously",
        "TestDegenerateInputs::test_marker_write_failure_after_rewrite_self_heals",
        "TestCompletionRecordProvenance",
        "TestRemainingMigrationBranches::test_required_marker_write_error_is_truthful",
    ],
    "campaign_coverage_core_config": [
        "test_legacy_timeout_bounds_are_persisted_without_losing_other_fields",
        "test_image_upgrade_readonly_marker_uses_runtime_defaults_without_config_write",
        "test_root_config_rejects_nonconcrete_preconstructed_provider",
        "test_personality_model_entries_and_tombstones_keep_leaf_scope",
        "test_generic_nested_mapping_patch_does_not_copy_unsubmitted_siblings",
        "test_mapping_tombstone_cannot_delete_missing_or_scalar_parent",
        "test_unrequested_webhook_row_cannot_be_inserted_as_an_implicit_create",
        "test_host_identity_rejects_control_or_noncanonical_material",
        "test_computer_configuration_rejects_ambiguous_local_authority",
        "test_compatible_legacy_thinking_mode_adapts_without_overriding_explicit_effort",
        "test_mcp_transport_validation_preserves_supported_lanes_only",
        "test_agent_fixed_axis_classifies_opaque_provider_model_without_rewriting",
        "test_unknown_config_warning_recognizes_schema_aliases",
    ],
    "image_defaults_core": [
        "test_independent_byte_preserving_matrix", "test_shared_anchor_refusal",
        "test_generic_roundtrip_and_explicit_intent",
        "test_env_pin_metadata_and_flatten_only_explicit",
        "test_prepared_failure_fences_retry", "test_persistence_settlement",
        "test_invalid_intent_no_mutation", "test_concurrent_loader_snapshot",
        "test_special_string_spellings", "test_block_header_comment_preserved",
        "test_scalar_anchor_name_refused", "test_postimage_value_mismatch_refused_before_commit",
        "test_env_expansion_old_value_is_not_raw_match",
        "test_completion_failure_recovers_postimage",
        "test_corrupt_marker_fails_closed", "test_entire_concurrent_revision_reconciled",
        "test_metadata_inherited_pins", "test_crlf_and_config_permissions",
        "test_unsafe_lock_paths_refused", "test_lock_modes_and_alias_rendezvous",
        "test_foreign_lock_owner_refused", "test_concurrent_save_serializes_migration",
        "test_reconcile_rejects_nonmapping", "test_escaped_continuation_old_literal",
        "test_inconsistent_scalar_token_fails_closed",
        "test_pin_requires_value_and_follow_overrides_value",
    ],
}

for _stem, _selected in CORPUS_SELECTIONS.items():
    _load_corpus(_stem, _selected)


def test_assert_case_preservation_evidence():
    assert all(v["assert_case_ast_preserved"] and v["assert_source_spans_preserved"]
               for v in ORIGINALS.values())
    assert len(CASE_MAP) >= 50


def test_selected_corpus_is_nonempty_and_selector_complete():
    for stem, selectors in CORPUS_SELECTIONS.items():
        path = f"tests/test_{stem}.py"
        originals = [node for node in CASE_MAP if node.startswith(path + "::")]
        assert originals, path
        if selectors is not None:
            for selected in selectors:
                assert any(node == path + "::" + selected or
                           node.startswith(path + "::" + selected + "::") for node in originals), (
                    path, selected
                )
