"""Case-level dispositions from inspected 6B/native service contracts."""
REVIEWER = "Claude, review of step 8 part 4"

RETIRED_CASES = {
    "test_scheduled_report_pagination_listener": {
        "test_loaded_listener_routes_managed_reaction_to_pagination_service": "Removed Discord startup extension/cog and on_raw_reaction_add emoji routing.",
        "test_listener_ignores_bot_reactions_and_unmanaged_messages": "Removed Discord bot self-reaction filter and raw reaction listener.",
    },
    "test_scheduled_report_wiring": {
        "test_registry_and_pagination_service_are_bot_components": "Original static assertions specifically pin removed Discord BotComponents and Discord wiring source spellings, not retained native report registry behavior.",
    },
    "test_scheduled_report": {
        "TestPaginationState.test_navigation_wraps_and_removes_user_reaction": "Removed Discord message editing and user-reaction removal contract.",
        "TestPaginationState.test_missing_message_removes_persisted_state": "Removed Discord NotFound/fetch_message pagination-message lifecycle.",
        "TestRegistryAndPersistenceFailureEdges.test_reaction_unknown_emoji_or_message_is_ignored": "Removed raw Discord emoji/message routing.",
        "TestRegistryAndPersistenceFailureEdges.test_missing_channel_keeps_state_without_editing": "Removed Discord channel lookup/edit contract.",
        "TestRegistryAndPersistenceFailureEdges.test_discord_edit_error_keeps_state": "Removed Discord Forbidden message-edit failure handling.",
        "TestRegistryAndPersistenceFailureEdges.test_reaction_add_failures_do_not_fail_delivery": "Removed Discord reaction-add failure contract.",
        "TestRegistryAndPersistenceFailureEdges.test_reaction_removal_failure_does_not_fail_redraw": "Removed Discord reaction removal failure contract.",
    },
}

DEFERRED_CASES = {
    "test_native_scheduling": {
        "TestUpdateSchedule.test_strict_update_without_existing_selected_tool_remains_safe": "Real ScheduleService._owned raises ConversationError before scheduler.update for missing IDs; native handler catches ValueError only. Original missing-update assertion requires scheduler.update validation flag. Needs coordinated production fix, not a fabricated service.",
    },
    "test_scheduled_report_wiring": {
        "test_state_path_comes_from_configured_scheduler_persistence_root": "Static Path.read_text assertions hardcode absent src/discord/wiring.py. CoreService reports use shared JournalStore, not scheduler-parent JSON storage; no honest original-source adapter exists without fabricating code text.",
    },
    "test_scheduled_report": {
        "TestPaginatedEmbedV1Contract.test_required_optional_defaults_and_rendering": "Mixed retained normalization and removed embed rendering assertions: actual ReportService.registry.render_page returns native dict, no Embed.to_dict or rendered Links field. Preserve unchanged case pending contract adjudication.",
        "TestPaginatedEmbedV1Contract.test_parse_first_then_scrub_rendered_strings_only": "Actual native renderer stores inert plain text, not Discord markdown/mention escapes. Scrubbing remains retained; combined original exact escaping assertions cannot be satisfied without copied legacy presentation.",
        "TestPaginatedEmbedV1Contract.test_freeform_text_cannot_create_clickable_links": "Actual native renderer returns inert plain text; exact original Discord markdown-escaping assertion differs from native clickable-link adoption. Needs reviewed contract disposition rather than assertion rewrite.",
        "TestPaginationState.test_post_persists_only_normalized_projection_and_reloads": "6B ReportService persists bound versioned pages in JournalStore. Legacy pagination.post explicitly raises NotImplementedError; exact message/channel JSON key and reload/edit assertions cannot map to native immutable bound reports.",
        "TestPaginationState.test_refresh_is_redraw_only_and_does_not_reproject_or_execute": "Retained no-reexecution behavior is in ReportService.page, but original requires unavailable legacy post/reaction/edit plus mutable JSON page state. Native snapshots have no such redraw seam; do not blanket retire retained safety.",
        "TestPaginationState.test_requires_absolute_state_path_and_prunes_older_than_26h": "Legacy store now requires report_id/conversation_id and lacks handles(99, emoji); 6B bound ReportService retains historical receipts without 26h TTL. Persistence lifecycle contract needs adjudication, not a legacy service shim.",
        "TestPaginationState.test_stale_in_memory_state_is_pruned_and_persisted_on_reaction": "Original message-indexed post/reaction TTL state differs from native immutable bound snapshots; legacy post unavailable. Retained stale persistence concern cannot be rewritten silently.",
        "TestRegistryAndPersistenceFailureEdges.test_malformed_persisted_state_fails_closed": "Original JSON pagination construction requires removed get_channel and handles; real 6B ReportService uses JournalStore. Original fail-closed assertion cannot be mapped without fabricated compatibility storage.",
        "TestRegistryAndPersistenceFailureEdges.test_persistence_failure_after_post_is_best_effort": "Native ReportService publication is transactionally durable/fail-closed, while original best-effort JSON write failure returns an already-sent Discord message. Retained delivery failure concern needs reviewed semantic disposition.",
    },
}
