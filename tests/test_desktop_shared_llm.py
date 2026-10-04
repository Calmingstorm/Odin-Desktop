"""Frozen neutral provider guard, converter, budget and reliability cases."""

import pytest

from tests.desktop_adapters.llm_cases import export_suite
from tests.desktop_adapters.tools_cases import owner_fixture

CORPUS_SELECTIONS = {
    "agent_campaign": ["test_default_codex_catalog_preserves_authored_model_selection_hint"],
    "model_hints": [
        "test_operator_hints_override_seed_and_allowlist_order_is_preserved",
        "test_profile_facts_and_fresh_usage_p50_are_rendered",
        "test_catalogue_and_alias_spellings_share_hints_and_profile_facts",
        "test_hints_are_canonicalized_and_nonempty",
        "test_catalogue_integrity_preserves_authored_and_derived_hint_inventory",
        "test_gpt_6_1_sol_seed_matches_spawn_copy_and_preference_order",
        "test_compat_catalogue_lookup_uses_configured_preset_namespace",
        "test_unverified_compat_capabilities_are_labelled_and_unknown_models_request_hint",
        "test_custom_endpoint_uses_labelled_unique_model_name_fallback",
    ],
    "llm_security": [
        "TestOllamaURLValidation",
        "TestKimiConfig",
        "TestSecretPersistence",
        "TestConfigBackwardCompat",
    ],
    "kimi_client": [
        "TestConvertMessages",
        "TestConvertTools",
        "TestTemperature",
        "TestParseResponse",
        "TestToolEnforcement",
        "TestProperties",
        "TestKimiConfig",
    ],
    "ollama_client": [
        "TestConvertMessages",
        "TestConvertTools",
        "TestParseResponse",
        "TestProperties",
        "TestOllamaConfig",
        "TestLLMProviderConfig",
        "TestConfigParsing",
        "TestHeaders",
        "TestSessionLifecycle",
        "TestRequestWithRetry",
        "TestChatEndpoints",
        "TestHealthCheck",
    ],
    "openai_codex_client": [
        "TestEligibleAccountKeys",
        "TestConvertMessages",
        "TestConvertMessagesWithTools",
        "TestToolsAndEstimation",
        "TestMetadataAndHeaders",
        "TestReadStream",
        "TestReadToolStream",
        "TestAuthAdapters",
        "TestReasoningEffortBody",
        "TestPerCallReasoningOverride",
        "TestPerCallModelOverride",
        "TestResponseProvenance",
        "TestTransportTimeouts",
        "TestKnownBadPairGuard",
    ],
    "multi_provider_schema_coverage": [
        "test_agent_auto_model_entry_validates_native_controls_and_normalizes_models",
        "test_provider_qualified_auxiliary_and_codex_registry_boundaries",
        "test_compatible_profile_efforts_and_openrouter_values_are_normalized",
        "test_config_rejects_native_control_mismatch_for_configured_endpoint",
        "test_config_covers_allowlist_skips_without_endpoint_and_validation_errors",
    ],
    "learning_knowledge_reliability": [
        "test_queryless_injection_respects_budget",
        "test_injection_keeps_at_least_one_entry",
        "test_gated_injection_prioritizes_corrections",
        "test_consolidation_fallback_pins_corrections",
        "test_consolidation_fallback_pins_preferences",
        "test_delete_entry_async_removes_and_persists",
        "test_delete_entry_async_not_resurrected_by_concurrent_reflection",
        "test_update_entry_async_applies",
        "test_working_memory_capped_per_section",
        "test_working_memory_update_existing_key_no_growth",
        "test_delete_source_async_holds_write_lock",
        "test_merge_sources_async_holds_write_lock",
    ],
}


@pytest.fixture(autouse=True)
def desktop_provider_profile(tmp_path, monkeypatch):
    """Fresh XDG paths; genuine local owner for the two memory cap cases."""
    for variable, directory in (
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_CACHE_HOME", "cache"),
    ):
        monkeypatch.setenv(variable, str(tmp_path / directory))
    monkeypatch.setenv("HOME", str(tmp_path))
    with owner_fixture(tmp_path):
        yield


for _suite, _selection in CORPUS_SELECTIONS.items():
    export_suite(globals(), _suite, _selection)
