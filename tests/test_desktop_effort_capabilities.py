"""Model settings expose core restrictions without inventing provider support."""
from copy import deepcopy
from types import SimpleNamespace
from typing import get_args

import pytest
from pydantic import ValidationError

from src.config.schema import Config, OpenAICompatibleModelProfile, ReasoningEffort
from src.desktop.openrouter_admin import _project_model_catalogue
from src.web.api import llm_admin
from tests import test_desktop_step5_llm_methods as model_fixtures

service = model_fixtures.service


@pytest.fixture(autouse=True)
def isolated_catalogue(monkeypatch):
    monkeypatch.setattr(llm_admin, "_openrouter_cache", {"models": None})


def catalogue(config):
    return _project_model_catalogue(
        config, llm_admin._model_catalogue(
            SimpleNamespace(config=config), codex_configured=True, ollama_configured=False,
        ),
    )


@pytest.mark.parametrize("model", [
    "gpt-6.1-sol", "gpt-6-astra", "gpt-5.4", "gpt-5.4-mini", "gpt-6-sol",
    "codex-auto-review", "future:opaque", "GPT-6.1-sol", "codex:gpt-6.1-sol",
    "  gpt-6.1-sol  ",
])
def test_codex_presentation_matches_actual_config_pair_validation(model):
    config = Config()
    config.llm_provider.model = model
    config.openai_codex.model = model
    row = next(item for item in catalogue(config)["codex"] if item["ref"] == model)
    accepted = []
    for effort in get_args(ReasoningEffort):
        try:
            Config(llm_provider={"model": model}, openai_codex={"reasoning_effort": effort})
        except ValidationError:
            continue
        accepted.append(effort)
    assert row["efforts"] == accepted
    assert row["effort_capabilities"]["values"] == accepted
    assert row["effort_capabilities"]["source"] == "core_validation"


def test_unknown_codex_keeps_request_enum_without_claiming_known_restrictions():
    row = next(item for item in catalogue(Config(openai_codex={"model": "new-model"}))["codex"]
               if item["ref"] == "new-model")
    assert row["efforts"] == list(get_args(ReasoningEffort))
    assert row["effort_capabilities"]["restrictions_known"] is False
    restricted = next(item for item in catalogue(Config())["codex"] if item["ref"] == "gpt-6.1-sol")
    assert "none" not in restricted["efforts"]
    assert restricted["effort_capabilities"]["restrictions_known"] is True


def test_bare_agent_policy_refs_and_retired_selections_remain_visible():
    config = Config()
    config.agents.model = "gpt-5.4"
    config.agents.auto_model_allowlist = ["future-opaque"]
    config.openai_codex.model = "gpt-5.5"
    rows = {item["ref"]: item for item in catalogue(config)["codex"]}
    assert rows["gpt-5.4"]["efforts"] == ["none", "low", "medium", "high", "xhigh"]
    assert rows["future-opaque"]["effort_capabilities"]["restrictions_known"] is False
    assert rows["gpt-5.5"]["effort_capabilities"] == {
        "values": [], "source": "core_validation", "restrictions_known": True,
    }


@pytest.mark.parametrize("ref", ["kimi:legacy", "codex:gpt-6.1-sol", "future:opaque"])
def test_desktop_projection_does_not_add_colon_policy_refs(ref):
    config = Config()
    config.agents.model = ref
    config.agents.auto_model_allowlist = [
        ref, "bare-agent-name", "compat:vendor/model", "ollama:local",
    ]
    raw = llm_admin._model_catalogue(
        SimpleNamespace(config=config), codex_configured=False, ollama_configured=False,
    )
    projected = _project_model_catalogue(config, raw)
    for rows in (raw, projected):
        codex_refs = {row["ref"] for row in rows["codex"]}
        assert ref not in codex_refs
        assert "bare-agent-name" in codex_refs
        assert "compat:vendor/model" not in codex_refs
        assert "ollama:local" not in codex_refs
        assert "compat:vendor/model" in {row["ref"] for row in rows["compat"]}
        assert "ollama:local" in {row["ref"] for row in rows["ollama"]}
    assert all("effort_capabilities" not in row for group in raw.values() for row in group)


def test_projection_preserves_catalogue_membership_order_and_unrelated_facts():
    config = Config()
    config.llm_provider.model = "main-only-name"
    raw = llm_admin._model_catalogue(
        SimpleNamespace(config=config), codex_configured=False, ollama_configured=False,
    )
    before = deepcopy(raw)
    projected = _project_model_catalogue(config, raw)
    assert raw == before
    assert projected is not raw
    assert list(projected) == list(raw)
    assert "main-only-name" not in {row["ref"] for row in projected["codex"]}
    for provider, rows in raw.items():
        assert [row["ref"] for row in projected[provider]] == [row["ref"] for row in rows]
        for original, enriched in zip(rows, projected[provider], strict=True):
            assert enriched is not original
            assert {key: value for key, value in enriched.items()
                    if key not in {"efforts", "effort_capabilities"}} == {
                        key: value for key, value in original.items() if key != "efforts"
                    }
            assert "effort_capabilities" not in original


def profile(efforts=None):
    return OpenAICompatibleModelProfile(
        total_window_tokens=100_000, max_output_tokens=10_000,
        supports_reasoning=True, supported_efforts=efforts,
    )


def compatible_config():
    return Config(openai_compatible={
        "preset": "openrouter", "base_url": "https://openrouter.ai/api/v1",
        "model": "vendor/model", "model_profiles": {"vendor/model": profile()},
    })


def compatible_row(config):
    return next(item for item in catalogue(config)["compat"] if item["name"] == "vendor/model")


def test_undeclared_compatible_efforts_are_unknown_not_a_codex_fallback():
    row = compatible_row(compatible_config())
    assert row["capability"] == "reasoning"
    assert row["efforts"] == []  # retained compatibility field
    assert row["effort_capabilities"] == {
        "values": None, "source": "unknown", "restrictions_known": False,
    }


def test_resolved_profile_efforts_precede_provider_catalogue():
    config = compatible_config()
    config.openai_compatible.model_profiles["vendor/model"] = profile(["vendor-balanced"])
    llm_admin._openrouter_cache["models"] = [{
        "id": "vendor/model", "variant": "standard", "supports_reasoning": True,
        "supported_efforts": ["provider-fast"],
    }]
    row = compatible_row(config)
    assert row["efforts"] == ["vendor-balanced"]
    assert row["effort_capabilities"] == {
        "values": ["vendor-balanced"], "source": "model_profile", "restrictions_known": True,
    }
    config.openai_compatible.model_profiles["vendor/model"] = profile()
    row = compatible_row(config)
    assert row["effort_capabilities"] == {
        "values": ["provider-fast"], "source": "provider_catalogue", "restrictions_known": True,
    }


def test_compatible_alias_uses_core_resolved_profile_efforts():
    config = Config()
    config.openai_compatible.model = "deepseek-flash"
    config.openai_compatible.reasoning_dialect = "openai_reasoning_effort"
    config.openai_compatible.model_profiles["deepseek-v4-flash"] = profile(["opaque-native"])
    row = next(item for item in catalogue(config)["compat"] if item["name"] == "deepseek-flash")
    assert row["efforts"] == ["opaque-native"]
    assert row["effort_capabilities"]["source"] == "model_profile"


def test_other_endpoint_does_not_inherit_cached_openrouter_efforts():
    config = compatible_config()
    config.openai_compatible.preset = "custom"
    config.openai_compatible.base_url = "http://localhost:8000/v1"
    config.openai_compatible.reasoning_dialect = "openai_reasoning_effort"
    llm_admin._openrouter_cache["models"] = [{
        "id": "vendor/model", "supports_reasoning": True, "supported_efforts": ["provider-fast"],
    }]
    assert compatible_row(config)["effort_capabilities"]["source"] == "unknown"


@pytest.mark.parametrize("dialect,capability", [("none", "none"), ("thinking_type", "thinking")])
def test_wire_dialect_not_profile_decides_if_effort_control_applies(dialect, capability):
    config = compatible_config()
    config.openai_compatible.reasoning_dialect = dialect
    config.openai_compatible.model_profiles["vendor/model"] = profile(["opaque"])
    row = compatible_row(config)
    assert row["capability"] == capability
    assert row["efforts"] == []
    assert row["effort_capabilities"] == {
        "values": [], "source": "not_applicable", "restrictions_known": True,
    }


def test_ollama_has_no_native_effort_choices():
    row = catalogue(Config())["ollama"][0]
    assert row["effort_capabilities"]["source"] == "not_applicable"
    assert row["efforts"] == []


@pytest.mark.asyncio
async def test_existing_models_status_delivers_metadata_without_write(service):
    before = service.settings.paths.config_file.read_bytes()
    config = service.settings.config
    config.openai_compatible.model_profiles["vendor/model"] = profile(["vendor-balanced"])
    config.agents.model = "kimi:legacy"
    config.agents.auto_model_allowlist = ["codex:gpt-6.1-sol", "future:opaque"]
    result = await service.handle("models.status", {})
    row = next(item for item in result["model_catalogue"]["codex"] if item["ref"] == "gpt-6.1-sol")
    assert row["effort_capabilities"]["values"] == ["low", "medium", "high", "xhigh", "max"]
    assert not {"kimi:legacy", "codex:gpt-6.1-sol", "future:opaque"}.intersection(
        item["ref"] for item in result["model_catalogue"]["codex"]
    )
    compatible = next(item for item in result["model_catalogue"]["compat"]
                      if item["name"] == "vendor/model")
    assert compatible["effort_capabilities"] == {
        "values": ["vendor-balanced"], "source": "model_profile", "restrictions_known": True,
    }
    assert service.settings.paths.config_file.read_bytes() == before
