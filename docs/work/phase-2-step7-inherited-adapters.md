# Step 7 inherited webhook adapter evidence and disposition

This is **selected-case qualification**, not a claim that every inherited
webhook suite has been restored. Global safety/maintenance accounting remains
the parent change's responsibility. No production code is owned by this adapter.

## Executed artifact and evidence

- Collector: `tests/test_desktop_webhook_adapters.py`.
- Frozen loader/selection: `tests/desktop_adapters/webhook_cases.py`.
- Actual ingress fixture: `tests/desktop_adapters/webhook_ingress.py`.
- Targeted command: `.venv/bin/python scripts/run-phase1-tests.py tests/test_desktop_webhook_adapters.py`.
- Final targeted result: **110 passed in 10.94s**, Python 3.12.3, isolated PID
  namespace through the repository runner. Earlier development checkpoints:
  97 passed (helpers only), 109 passed (inherited ingress cases added),
  110 passed in 13.52s (additional real graph proof). Ruff check for the three
  Python adapter/collector files and `git diff --check` both passed.
- 74 original functions, including every retained decorator/parameter row,
  expand to **104 inherited pytest cases**. Six additional checks prove complete
  source/AST seals, exact projection, and real durable ingress/scheduler wiring.
- `.venv` is a local symlink to `/home/odin/odin-desktop/.venv`. No dependency
  installation, full qualification, git commit/push, or service change was done.

## What the ingress bridge actually does

The single inherited `_make_server` constructor body is projected onto a
temporary desktop profile. It constructs actual `OwnerAuthority`, `JournalStore`,
`EventJournal`, `ConversationStore`, `TranscriptStore`, `SettingsService`,
`Scheduler(desktop_recovery=True)` and `WebhookIngress`. TestServer binds only
an ephemeral loopback port. Its startup adds a real reminder schedule whose
destination is the real conversation and whose per-trigger credential is stored
in the runtime configuration. The original request bytes, signatures, headers,
paths and response assertions are unchanged.

The original numeric channel `999` is a fixture alias for that conversation,
not an enabled Discord route. The original `set_send_message` callback is only
an **observer after durable transcript readback**. It does not implement event
delivery, authentication, parsing, receipts or dispatch. The scheduler callback
is an inert external-effect boundary which first validates the real desktop run
binding. A separate behavior test reads the actual receipt row, transcript ID,
execution history binding and settlement and verifies the observer saw the
stored message. No fabricated success response or mock ingress implementation
is involved. Authority, SQLite and ingress state are explicitly closed.

Pure scheduler tests keep their original `AsyncMock` effect callbacks. This is
inherited test input at the effect boundary, not a replacement scheduler. They
do not by themselves prove owner/keyring/protocol admission.

## Frozen provenance

Every load checks the already pinned archive hash through `frozen_source`, its
retained repository bytes, and these full-source SHA-256 seals:

| Original suite | SHA-256 | Disposition |
|---|---|---|
| `test_github_webhook.py` | `b35ba5e742419b25a2d04d9ffac2fa539db75c0817e9553fe2e2d03015cecf3c` | 19 functions selected; partial |
| `test_webhook_text.py` | `b1a3101c294eb130dd1537de144e150c66c68d6e161727982bea16cc180c8a49` | All 11 functions and parameter rows; pure outbound YAML helper coverage |
| `test_webhook_persistence.py` | `23f7600e92357f68a1cb50bd2b31f0ef8c6c077943872ff0934f6e24dc39d231` | 32 functions selected; partial |
| `test_scheduler.py` | `310626dbaf7d296db224fb211b0d470247c0d38a90e1044f6d60a4bbb5b0c404` | 12 trigger functions selected; partial |

The complete assertion, signature, decorator and parameter AST is compared
**before selection**. Pure helper/scheduler trees are unchanged. The only
GitHub AST setup hunk is `_make_server` line 38, sealed to:

- Before: `6fe5a45a6d022da2d154ef1b988eed09a20b9d6346e723ddf1b3ce5bfb4d6ae5`.
- After: `7bafbbd5328db3b6efcb26cd731a2ba85ba2b33a92708c83c7030ddbee46fd62`.

It returns `desktop_make_server(secret=secret, channel_id=channel_id,
github_channel_id=github_channel_id)`. The obsolete HealthServer/WebhookConfig
imports are omitted at projection, not implemented as compatibility fakes.
An independent test rebuilds the exact one-body delta and compares the whole
AST. `CASE_MAP` exposes every original function's collected adapter name.

## Exact selected original functions

All paths below are under frozen upstream `tests/`. Decorators and parameter
values are retained exactly; no decorator rows are sliced out.

### `test_github_webhook.py` (19)

- `TestGitHubWebhookSignature`: `test_valid_signature_accepted`,
  `test_invalid_signature_rejected`, `test_missing_signature_rejected`,
  `test_no_secret_configured_rejects`.
- `TestGitHubWebhookEvents`: `test_push_event`, `test_push_truncates_commits`,
  `test_pull_request_event`, `test_issues_event`, `test_release_event`,
  `test_workflow_run_event`, `test_unknown_event`, `test_invalid_json`.
- `TestSchedulerGitHubSource`: `test_validate_github_source`,
  `test_validate_invalid_source`, `test_trigger_matches_github`,
  `test_trigger_no_match_wrong_source`, `test_trigger_matches_repo_substring`,
  `test_trigger_no_match_wrong_event`, `test_add_github_trigger_schedule`.

### `test_webhook_text.py` (all 11)

- `test_update_changes_only_value_tokens_and_preserves_every_other_byte`
- `test_append_boundaries_with_null_flow_indentless_and_block_scalar`
- `test_append_to_no_final_newline`
- `test_legacy_url_edit_adds_id_without_rewriting_neighbour`
- `test_atomic_dumper_explicit_sequence_indent_remains_supported`
- `test_delete_flow_sequence_preserves_other_row_bytes`
- `test_flow_delete_uses_separator_token_not_comma_inside_comment`
- `test_add_missing_field_only_within_selected_row`
- `test_replace_null_and_block_scalar_does_not_consume_trailer`
- `test_shared_source_marks_fail_closed_without_writing`
- `test_reparse_mismatch_or_failure_prevents_commit`

### `test_webhook_persistence.py` (32)

- `test_create_section_and_targets_from_empty_document`
- `test_create_missing_targets_precedes_trailing_section_template`
- `test_create_after_scalar_row_keeps_trailing_comments_separate`
- `test_create_missing_targets_preserves_six_line_eof_comment_block`
- `test_update_refuses_missing_requested_target_without_writing`
- `test_delete_legacy_row_does_not_edit_shifted_legacy_row`
- `test_delete_last_row_emits_empty_targets_and_noop_does_not_rewrite`
- `test_delete_preserves_trailing_row_comments`
- `test_invalid_disk_state_fails_clearly`
- `test_missing_config_path_fails`
- `test_legacy_identity_resolves_environment_url_without_writing_it`
- `test_rows_without_mapping_identity_can_remain_while_new_target_is_added`
- `test_unresolvable_environment_url_uses_raw_value_for_legacy_identity`
- `test_changed_field_missing_from_target_is_ignored`
- `test_delete_comment_detachment_variants`
- `test_deleted_last_row_transfers_comment_block_before_section`
- `test_deleting_earlier_row_transfers_trailing_section_comment`
- `test_create_after_template_empty_targets_keeps_trailing_comment_block`
- `test_create_between_rows_and_trailer_preserves_all_comments`
- `test_delete_first_row_keeps_between_and_last_row_trailer`
- `test_delete_last_row_keeps_both_between_and_trailing_blocks`
- `test_delete_last_row_then_create_keeps_trailer_after_new_row`
- `test_delete_last_row_preserves_leading_and_trailing_comments`
- `test_hand_edited_rows_are_not_reintroduced_or_overwritten`
- `test_missing_requested_row_conflicts_without_writing`
- `test_create_conflicts_with_operator_added_same_id`
- `test_placeholder_guard_bad_numeric_and_boolean_spellings`
- `test_atomic_dump_preserves_requested_mode`
- `test_anchor_shared_mapping_is_refused`
- `test_locked_async_wrapper_normalizes_model_dump_and_settles`
- `test_locked_async_wrapper_normalizes_plain_changed_field_iterable`
- `test_locked_async_wrapper_empty_is_noop`

### `test_scheduler.py` (12)

- `TestSchedulerAdd`: `test_add_trigger_schedule`,
  `test_add_invalid_trigger_key_raises`.
- `TestSchedulerFireTriggers`:
  `test_removed_trigger_source_is_rejected_for_new_schedules`,
  `test_removed_alert_filter_is_rejected_for_new_schedules`,
  `test_fire_triggers_matching`, `test_fire_triggers_no_match`,
  `test_fire_triggers_no_callback`.
- `TestSchedulerUpdate`: `test_update_to_trigger`,
  `test_update_invalid_trigger_raises`.
- `TestSchedulerRetry`: `test_fire_triggers_tracks_failure`,
  `test_fire_triggers_resets_on_success`.
- `TestSchedulerPause`: `test_trigger_skips_paused`.

`test_fire_triggers_no_match` passes the literal source `gitlab` to a pure
wrong-source matcher. It does not create a GitLab endpoint, credential, network
request or ingress. No cases from `test_gitlab_webhook.py` are admitted.

## Inspected but not claimed restored

- GitHub `TestGitHubTriggerMatching`'s two callback-notification cases assume
  a mutable global trigger callback, not the actual schedule-specific desktop
  dispatch obligation. They remain deferred, not made green with fake callbacks.
- GitHub's three channel-routing and three channel-config cases require removed
  Discord channel schema/private helpers. Desktop delivers to the schedule's
  actual conversation. No dummy `_get_channel_id` implementation was added.
- Remaining persistence cases are not automatically admitted. Several frozen
  secret fixtures are redacted in ways which contradict exact downstream
  assertions (`test_force_field_overwrites_placeholder` is one example).
  Other cases exercise unrelated image-model/config schema or artificially
  mutated YAML object internals. Their obligations remain visible for later
  disposition; this partial adapter does not erase them or rewrite their data.
- `test_webhook_campaign.py` inspected at source hash
  `170a4b9a1557635c774aee9e7a9baf48f1fe39e7057fbe91e07f32fa0402e7c4`.
  No campaign cases selected. Its CRUD cases target removed
  `/api/outbound-webhooks` management routes, not inbound delivery. Its redirect,
  metadata-address and DNS-rebind cases contain prohibited attack inputs and
  are not restored by broad class/module selection. The three comment/env-leaf
  persistence campaign fixtures at lines 315, 451 and 481 contain literal
  `[REDACTED]` YAML rows, inconsistent with their unchanged placeholder
  assertions; no synthetic repair or fake pass was introduced.
- `test_health_endpoints.py` inspected at source hash
  `51168456a9e6c2f36adc5d4d2a9eb46acedbba3611f8f88e066c511c86adcbda`.
  Health/status/admin management routes are forbidden on the delivery-only
  listener. Those endpoint/config assertions do not describe its API and are
  not redirected to a fabricated compatibility server.
- `test_health_shutdown.py` inspected at source hash
  `3c5f42e7fe6cd54d258513c164c8fb03ab20a878942fc151f99f96429b875dc4`.
  Its `TestStopIsolation.test_runner_gets_bounded_shutdown_timeout` expects a
  disabled HealthServer still to listen; D10 requires disabled ingress off.
  Its close-all/registration/live-shutdown cases require removed WebUI
  WebSocket managers and `/api/ws`. No WebSocket or admin route is restored.
  Actual ingress parent-loss/listener cleanup proof belongs to
  `tests/test_desktop_webhooks.py`, not a renamed obsolete WebSocket test.

## Safety and limits

Only throwaway profiles, SQLite stores, config files and ephemeral loopback
ports are used. Config lock directories are also redirected into each case's
temporary root. No active desktop, LAN exposure, live data, real repository
payload processing, destructive command or security-attack payload was used.

The full text suite and selected persistence functions exercise the real retained
**outbound YAML helper**, not inbound receipt durability. Actual inbound storage
failure, revocation, duplicates, size limits, unknown routes and parent loss are
the ingress suite's responsibility. These adapters add inherited obligations;
they do not replace or weaken that suite or prove deployment readiness.
