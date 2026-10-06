"""Exact, safe inherited webhook cases. No inherited assertions are rewritten.

Outbound YAML helper coverage is deliberately separate from inbound ingress
qualification. A suite with a partial selection is never a full restoration.
"""
from __future__ import annotations

import ast
import copy
import hashlib
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source

SOURCE_SHA256 = {
    "test_github_webhook": "b35ba5e742419b25a2d04d9ffac2fa539db75c0817e9553fe2e2d03015cecf3c",
    "test_webhook_text": "b1a3101c294eb130dd1537de144e150c66c68d6e161727982bea16cc180c8a49",
    "test_webhook_persistence": "23f7600e92357f68a1cb50bd2b31f0ef8c6c077943872ff0934f6e24dc39d231",
    "test_scheduler": "310626dbaf7d296db224fb211b0d470247c0d38a90e1044f6d60a4bbb5b0c404",
}

# Explicit original node IDs, not broad class admission. None is used only
# where EVERY original test and parameter row is safe and retained unchanged.
SELECTIONS = {
    "test_webhook_text": None,
    "test_webhook_persistence": [
        "test_create_section_and_targets_from_empty_document",
        "test_create_missing_targets_precedes_trailing_section_template",
        "test_create_after_scalar_row_keeps_trailing_comments_separate",
        "test_create_missing_targets_preserves_six_line_eof_comment_block",
        "test_update_refuses_missing_requested_target_without_writing",
        "test_delete_legacy_row_does_not_edit_shifted_legacy_row",
        "test_delete_last_row_emits_empty_targets_and_noop_does_not_rewrite",
        "test_delete_preserves_trailing_row_comments",
        "test_invalid_disk_state_fails_clearly",
        "test_missing_config_path_fails",
        "test_legacy_identity_resolves_environment_url_without_writing_it",
        "test_rows_without_mapping_identity_can_remain_while_new_target_is_added",
        "test_unresolvable_environment_url_uses_raw_value_for_legacy_identity",
        "test_changed_field_missing_from_target_is_ignored",
        "test_delete_comment_detachment_variants",
        "test_deleted_last_row_transfers_comment_block_before_section",
        "test_deleting_earlier_row_transfers_trailing_section_comment",
        "test_create_after_template_empty_targets_keeps_trailing_comment_block",
        "test_create_between_rows_and_trailer_preserves_all_comments",
        "test_delete_first_row_keeps_between_and_last_row_trailer",
        "test_delete_last_row_keeps_both_between_and_trailing_blocks",
        "test_delete_last_row_then_create_keeps_trailer_after_new_row",
        "test_delete_last_row_preserves_leading_and_trailing_comments",
        "test_hand_edited_rows_are_not_reintroduced_or_overwritten",
        "test_missing_requested_row_conflicts_without_writing",
        "test_create_conflicts_with_operator_added_same_id",
        "test_placeholder_guard_bad_numeric_and_boolean_spellings",
        "test_atomic_dump_preserves_requested_mode",
        "test_anchor_shared_mapping_is_refused",
        "test_locked_async_wrapper_normalizes_model_dump_and_settles",
        "test_locked_async_wrapper_normalizes_plain_changed_field_iterable",
        "test_locked_async_wrapper_empty_is_noop",
    ],
    "test_scheduler": [
        "TestSchedulerAdd::test_add_trigger_schedule",
        "TestSchedulerAdd::test_add_invalid_trigger_key_raises",
        "TestSchedulerFireTriggers::test_removed_trigger_source_is_rejected_for_new_schedules",
        "TestSchedulerFireTriggers::test_removed_alert_filter_is_rejected_for_new_schedules",
        "TestSchedulerFireTriggers::test_fire_triggers_matching",
        # Pure wrong-source matching, not GitLab ingress or an exposure.
        "TestSchedulerFireTriggers::test_fire_triggers_no_match",
        "TestSchedulerFireTriggers::test_fire_triggers_no_callback",
        "TestSchedulerUpdate::test_update_to_trigger",
        "TestSchedulerUpdate::test_update_invalid_trigger_raises",
        "TestSchedulerRetry::test_fire_triggers_tracks_failure",
        "TestSchedulerRetry::test_fire_triggers_resets_on_success",
        "TestSchedulerPause::test_trigger_skips_paused",
    ],
    "test_github_webhook": [
        "TestGitHubWebhookSignature::test_valid_signature_accepted",
        "TestGitHubWebhookSignature::test_invalid_signature_rejected",
        "TestGitHubWebhookSignature::test_missing_signature_rejected",
        "TestGitHubWebhookSignature::test_no_secret_configured_rejects",
        "TestGitHubWebhookEvents::test_push_event",
        "TestGitHubWebhookEvents::test_push_truncates_commits",
        "TestGitHubWebhookEvents::test_pull_request_event",
        "TestGitHubWebhookEvents::test_issues_event",
        "TestGitHubWebhookEvents::test_release_event",
        "TestGitHubWebhookEvents::test_workflow_run_event",
        "TestGitHubWebhookEvents::test_unknown_event",
        "TestGitHubWebhookEvents::test_invalid_json",
        "TestSchedulerGitHubSource::test_validate_github_source",
        "TestSchedulerGitHubSource::test_validate_invalid_source",
        "TestSchedulerGitHubSource::test_trigger_matches_github",
        "TestSchedulerGitHubSource::test_trigger_no_match_wrong_source",
        "TestSchedulerGitHubSource::test_trigger_matches_repo_substring",
        "TestSchedulerGitHubSource::test_trigger_no_match_wrong_event",
        "TestSchedulerGitHubSource::test_add_github_trigger_schedule",
    ],
}
EVIDENCE = {}
CASE_MAP = {}


def verified_tree(stem):
    """Seal complete source and assertion/parameter corpus before projection."""
    path = f"tests/{stem}.py"
    source = frozen_source(path)
    source_hash = hashlib.sha256(source).hexdigest()
    if source_hash != SOURCE_SHA256[stem]:
        raise ValueError(f"Webhook source seal changed: {path}")
    original = ast.parse(source, filename=path)
    adapted = copy.deepcopy(original)
    edits = []
    if stem == "test_github_webhook":
        factory = next(node for node in adapted.body if isinstance(node, ast.FunctionDef)
                       and node.name == "_make_server")
        before = dump(factory)
        factory.body = ast.parse(
            "return desktop_make_server(secret=secret, channel_id=channel_id, "
            "github_channel_id=github_channel_id)").body
        edits.append({"symbol": "_make_server", "line": factory.lineno,
                      "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
                      "after_sha256": hashlib.sha256(dump(factory).encode()).hexdigest(),
                      "operation": "private_profile_real_ingress_constructor"})
        if (edits[0]["before_sha256"], edits[0]["after_sha256"]) != (
                "6fe5a45a6d022da2d154ef1b988eed09a20b9d6346e723ddf1b3ce5bfb4d6ae5",
                "7bafbbd5328db3b6efcb26cd731a2ba85ba2b33a92708c83c7030ddbee46fd62"):
            raise ValueError("Exact ingress constructor setup hunk changed")
        # Removed import surfaces are projected below, never emulated. All
        # original tests, data, decorators and asserts are verified BEFORE it.
    elif dump(original) != dump(adapted):
        raise ValueError("Pure webhook helper AST changed")
    if corpus(original) != corpus(adapted):
        raise ValueError("Webhook full corpus changed before projection")
    EVIDENCE[path] = {
        "source_sha256": source_hash,
        "full_ast_sha256": hashlib.sha256(dump(original).encode()).hexdigest(),
        "full_corpus_sha256": hashlib.sha256(repr(corpus(original)).encode()).hexdigest(),
        "full_assert_parameter_ast_preserved_before_projection": True,
        "setup_edits": edits,
    }
    return adapted


def export_cases(namespace, stem):
    tree = verified_tree(stem)
    selected = SELECTIONS[stem]
    declared = set()
    projected = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            methods = [child for child in node.body if isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test_")]
            chosen = {child.name for child in methods if selected is None or
                      f"{node.name}::{child.name}" in selected}
            if not chosen:
                continue
            declared.update(f"{node.name}::{method}" for method in chosen)
            node.body = [child for child in node.body if not (
                isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name.startswith("test_") and child.name not in chosen)]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                if selected is not None and node.name not in selected:
                    continue
                declared.add(node.name)
        # GitHub's removed HealthServer/config imports are not executed. The
        # sole constructor hunk above returns actual desktop ingress/stores.
        if stem == "test_github_webhook":
            if isinstance(node, ast.ImportFrom) and node.module in {
                    "src.config.schema", "src.health.server"}:
                continue
        projected.append(node)
    if selected is not None and declared != set(selected):
        raise ValueError(f"Unresolved original webhook selection: {stem}")
    tree.body = projected
    module = ModuleType(f"desktop_webhook_{stem}")
    module.__file__ = f"tests/{stem}.py"
    if stem == "test_github_webhook":
        from tests.desktop_adapters.webhook_ingress import make_server
        module.desktop_make_server = make_server
    exec(compile(ast.fix_missing_locations(tree), module.__file__, "exec"), module.__dict__)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            exported = f"TestWebhook_{stem}_{node.name}"
            owner = getattr(module, node.name)
            owner.__module__ = namespace["__name__"]
            owner.__name__ = owner.__qualname__ = exported
            namespace[exported] = owner
            for child in node.body:
                if getattr(child, "name", "").startswith("test_"):
                    CASE_MAP[f"tests/{stem}.py::{node.name}::{child.name}"] = (
                        f"{exported}::{child.name}")
        elif (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
              and node.name.startswith("test_")):
            exported = f"test_webhook_{stem}_{node.name[5:]}"
            namespace[exported] = getattr(module, node.name)
            CASE_MAP[f"tests/{stem}.py::{node.name}"] = exported
