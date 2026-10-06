# Step 8 core-contract behavioral pins

Request: `req04650fd0`. Scope: `docs/design/core-contracts.md` sections 0–8.
This is a selective map of existing **behavioral** tests, not a feature-completeness
certificate or a claim that every named suite was rerun for this request. Node IDs
below omit parameter suffixes; parametrized tests cover their collected cases.
Source/document wording assertions are deliberately not counted as behavior.

## Existing pins, by seam

| Contract | Exact existing behavioral node IDs | Limit of the pin |
|---|---|---|
| §0/§1 required storage vs D17 optional durability; missing compatible credentials | `tests/test_desktop_core_durability.py::test_core_starts_and_real_ipc_request_replies_in_legacy_and_provider_cases`; `tests/test_desktop_core_durability.py::test_opened_ledger_dies_at_runtime_still_refuses_real_request` | Real temporary-profile core/IPC with deterministic provider; not every provider or fault point. |
| §1 duplicate/conflicting submission; atomic admission; same-thread FIFO | `tests/test_desktop_requests.py::test_submission_deduplicates_before_any_execution`; `tests/test_desktop_requests.py::test_rollback_admits_no_work_or_transcript`; `tests/test_desktop_requests.py::test_followups_execute_once_in_admission_order` | Domain admission pins; deletion/restart and cross-thread ownership added below. |
| §1 attachments owned/digest-bound/atomic; cancellation vs adoption | `tests/test_desktop_attachments.py::test_digest_rechecked_before_adoption_and_runner_read`; `tests/test_desktop_attachments.py::test_receipt_event_and_adoption_are_atomic`; `tests/test_desktop_attachments.py::test_expiry_keeps_adopted_refs_and_identity_tombstones`; `tests/test_desktop_attachments.py::test_foreign_conversation_and_profile_refs_are_unavailable` | Core upload/adoption, not native-picker/platform qualification. |
| §1 attachment interpretation is not implicit ingestion | `tests/test_desktop_attachment_knowledge.py::test_real_request_uses_exact_per_attachment_note` | Retained runner with per-attachment interpretation; not all media codecs. |
| §2 transcript separate from model context, durable files | `tests/test_desktop_transcript.py::test_transcript_independent_of_context_and_persists_restart`; `tests/test_desktop_artifacts.py::test_published_bytes_and_reports_survive_real_restart`; `tests/test_desktop_conversation_search.py::test_restart_context_reset_and_compaction_preserve_searchable_transcript` | Persisted core stores; renderer display/download fidelity is separate. |
| §2 cutoff inheritance, no live alias; read watermarks | `tests/test_desktop_conversations.py::test_child_cutoff_immutable_labeled_context_survives_parent_delete`; `tests/test_desktop_conversations.py::test_branch_before_later_reset_uses_context_at_cutoff`; `tests/test_desktop_conversations.py::test_unread_watermark_monotonic_and_foreign_message_refused` | Domain branch/read state, not an OS notification read receipt. |
| §2 authenticated bounded history and retention-aware visible search | `tests/test_desktop_conversation_search.py::test_bound_model_read_search_fts_and_no_foreign_selector`; `tests/test_desktop_conversation_search.py::test_deleted_transcript_disappears_from_search_and_old_cursor`; `tests/test_desktop_conversation_search.py::test_redaction_before_search_snippet_and_around` | Current-conversation model read and profile search; not imported installation data. |
| §3 guarded final publication and atomic failure | `tests/test_desktop_delivery.py::test_unguarded_candidates_never_become_reply_preview`; `tests/test_desktop_engine_services.py::test_retained_promise_guard_does_not_publish_unexecuted_promise`; `tests/test_desktop_delivery.py::test_actual_outbox_write_failure_rolls_back_all_publication` | Publication gate, not universal factual correctness of accepted prose. |
| §3 disconnected delivery, restart/outbox repair, unknown preserved | `tests/test_desktop_request_core.py::test_ipc_dedup_queue_disconnect_guarded_delivery_artifact_and_restart`; `tests/test_desktop_delivery.py::test_disconnect_restart_and_unknown_accept_repair_never_rerun`; `tests/test_desktop_delivery.py::test_tool_event_identity_prevents_unknown_promotion` | Durable inbox and replay avoidance; no exactly-once external-effects claim. |
| §3 snapshot/tail barrier, expiry/reset, transaction watermark | `tests/test_desktop_conversation_core.py::test_snapshot_then_subscription_replays_exact_committed_tail`; `tests/test_desktop_ipc.py::test_subscribe_response_before_replay_then_live_no_gap`; `tests/test_desktop_core_lifecycle.py::test_validation_refusal_expiry_and_retention_reset_on_wire`; `tests/test_desktop_journal_snapshot.py::test_snapshot_watermark_and_domain_state_share_one_committed_boundary` | Core ordering/catch-up; client rendering/revision application and slow-consumer overrun need their own proof. |
| §4 exact Stop/Steer binding and durable uncertainty | `tests/test_desktop_controls.py::test_stale_generation_or_conversation_never_controls_current_owner`; `tests/test_desktop_controls.py::test_integrated_stop_uses_real_runner_ledger_and_committed_cancel`; `tests/test_desktop_controls.py::test_integrated_steer_consumes_real_mailbox_and_no_followup_turn`; `tests/test_desktop_controls.py::test_restart_closes_lost_steering_without_replaying_input_or_confirming_stop` | No stop-as-undo, successor retargeting or queued-as-consumed claim. |
| §4 guarded resume, spent state/current policy/unknown effects | `tests/test_desktop_resume.py::test_resume_increments_wire_generation_and_restores_exact_spent_state`; `tests/test_desktop_resume.py::test_resume_uses_current_disabled_tools_setting`; `tests/test_desktop_resume.py::test_unknown_effects_halt_before_rebuild_and_never_reexecute`; `tests/test_desktop_resume.py::test_integrated_real_suspension_guarded_resume_and_committed_result` | Explicit foreground checkpoint recovery, not automatic background restart. |
| §5 core ownership/parent loss, independent readiness | `tests/test_desktop_core_lifecycle.py::test_duplicate_profile_different_socket_and_failed_start_cleanup`; `tests/test_desktop_core_lifecycle.py::test_subprocess_parent_eof_lock_release_stale_socket_and_restart`; `tests/test_desktop_runtime.py::test_absent_engine_status_is_not_saved_model_readiness`; `tests/test_desktop_engine_services.py::test_request_not_quiesced_refuses_any_engine_owner_teardown` | Isolated core/platform subset; not all native release or full app-main/tray lifecycle. |
| §5 credentials/config/apply/update compatibility/no import | `tests/test_desktop_settings.py::test_generic_save_preserves_source_and_restart_truth`; `tests/test_desktop_settings.py::test_secret_extra_params_cannot_leak_into_binding`; `tests/test_desktop_package_state.py::test_newer_independent_versions_refuse_without_writes`; `tests/test_desktop_package_state.py::test_transport_unknown_receipts_survive_compatible_upgrade`; `tests/test_desktop_profile_upgrade.py::test_fresh_provision_materializes_intent_without_server_import` | Core-side persistence/preflight only; package-status addition is a separate lane. |
| §5 package identity/notice-only status/lifecycle handoff (sibling lane) | `tests/test_desktop_package_status.py::test_package_identity_is_profile_bound_and_incarnation_fenced`; `tests/test_desktop_package_status.py::test_package_reads_are_notice_only_without_receipts_or_cleanup_effects`; `tests/test_desktop_package_status.py::test_shutdown_acceptance_is_not_quiescence_and_event_never_claims_ready`; `tests/test_desktop_package_status.py::test_package_handoff_waits_for_producers_close_and_external_ownership`; `tests/test_desktop_package_status.py::test_unknown_cleanup_survives_successful_close_and_restart` | Names supplied by the package lane and checked against its file; not rerun by this lane. Extends existing status payload, not a new command or update activation. |
| §6 owner not model payload, live catalog/host authority | `tests/test_desktop_capabilities_owner.py::test_model_owner_fields_do_not_admit_dispatch`; `tests/test_desktop_service_catalog.py::test_builtin_readiness_is_rechecked_after_cached_merge`; `tests/test_desktop_service_catalog.py::test_qualified_skill_and_mcp_merge_cannot_shadow_unready_builtin`; `tests/test_desktop_host_parity.py::test_default_only_preference_persists_and_never_grants_or_narrows`; `tests/test_desktop_host_parity.py::test_owner_access_never_overrides_trust_identity_or_enabled_state` | D17 owner/default-host behavior; qualification remains target-specific. |
| §6 computer origin/revocation/quarantine, no fabricated release | `tests/test_desktop_computer_binding.py::test_context_has_no_conversation_turn_or_input_authority`; `tests/test_desktop_computer_binding.py::test_unknown_release_and_legacy_ack_never_claim_clean`; `tests/test_desktop_computer_binding.py::test_exact_generation_owner_host_and_revocation_rechecks` | Binding/retained-controller tests, not receiver/compositor proof or arbitrary-app qualification. |
| §7 authenticated bounded IPC, no unsafe socket takeover | `tests/test_desktop_ipc.py::test_handshake_refusals`; `tests/test_desktop_ipc.py::test_length_limit_before_body`; `tests/test_desktop_ipc.py::test_live_socket_refused_without_handshake`; `tests/test_desktop_ipc.py::test_one_slow_connection_does_not_block_another`; `tests/test_desktop_ipc.py::test_callback_exception_is_scrubbed` | Local core protocol, not renderer privilege isolation or a remote protocol. |
| §8 unavailable service must not promise trigger/loop dispatch | `tests/test_desktop_capabilities_publication.py::test_phase2_schema_readiness_cannot_publish_or_admit_unwired_handlers`; `tests/test_desktop_capabilities_publication.py::test_loop_start_fails_before_tasks_callbacks_or_send` | Honest refusal only. Outbound webhook tests do not qualify inbound ingress. |

## Newly pinned gaps

Only two tests are added in `tests/test_desktop_core_contracts.py`:

- `test_foreground_ownership_is_per_conversation_not_per_profile`: two blocked
  real-runner turns run concurrently in different conversations while a follow-up
  stays queued behind its own conversation's owner; final commits remain scoped.
- `test_deleted_destination_submission_identity_survives_core_restart`: after
  actual execution and revision-bound destination deletion, fresh transport
  command IDs still return the original submission receipt; changed text or a
  replacement conversation conflicts; core restart executes nothing again.

Both use temporary profile storage, actual local IPC/CoreService and the retained
guarded runner, with a harmless deterministic provider. They do not assert the
presence or wording of documentation/source files.

Focused result (2026-10-06):
`.venv/bin/python scripts/run-phase1-tests.py tests/test_desktop_core_contracts.py -q`
passed **2 tests**, restricted PID isolation helper, non-root UID 1003. Initial
runs exposed two fixture mistakes (nonexistent `conversations.get` method and
JSON-text attachment-row representation); those were corrected, not production
behavior weakened. No full qualification, live desktop/service activity or
package deployment was performed by this lane.

An additional focused run of the two new tests, existing real-IPC
dedup/disconnect/restart, snapshot/tail, guarded-publication and actual outbox
failure pins listed above, plus all of `tests/test_desktop_core_durability.py`,
passed **16 tests** through the same isolated launcher. Other mapped node IDs
are existing evidence locations, not newly reported execution results.

## Unsupported/open or separately qualified contracts

- **Known §1.4 privacy gap:** `desktop_submissions.binding` stores canonical
  submission parameters, including original text/attachment selectors. Deletion
  clears the request content but does not turn that binding into a body-free
  digest tombstone. The new identity test intentionally does not certify this
  requirement. Production repair needs separate coordination/authorization.
- **§8 inbound ingress remains unqualified/unwired in the desktop composition.**
  No new listener is implemented here. Native/signed-envelope authentication,
  lifetime replay tombstones, scoped scheduler candidate handoff, transport
  bounds, wake/restart and admission receipts require their own implementation
  and behavioral qualification. Outbound integration CRUD/delivery is distinct.
- **§5 missed-run policy is still proposed in the contract.** The selected pins
  do not establish sleep/wake catch-up, owner acceptance or background-effect
  recovery. Foreground checkpoint resume is not agent/loop/workflow resumption.
- **Native/app acceptance remains separate:** tray/no-tray reopen, authenticated
  second launch, launcher Exit/login startup, packaged app-parent death, actual
  compositor release, native secret onboarding and update switching need the
  relevant isolated app/platform evidence. Core pipe EOF tests are not all of
  that evidence. Windows/macOS local parity is not inferred from Linux tests.
- **Not exhaustively mapped/qualified here:** every attachment quota/extraction
  format, deletion backup/retention policy, filtered-stream scanned watermark,
  slow-consumer overrun/reset behavior, telemetry gaps, all outbox fault points,
  D1 exact approved bytes/drift gates and every retained tool's platform boundary.
  These are coverage limits, not an assertion that all are absent. The design's
  common vocabulary and event-family names also do not prescribe today's wire
  spelling; this map makes no assertion that the implementation matches every
  proposed field. No general exactly-once guarantee is established.
