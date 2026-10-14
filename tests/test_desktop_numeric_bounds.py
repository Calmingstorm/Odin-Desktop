"""Numeric settings: strict saves, read-only startup compatibility.

Odin 4.14 (#640), carried to Desktop: a Desktop profile has no `discord` section (its config
refuses one), so the fixtures leave it out; the refused-save case runs through the app's own
settings methods in tests/test_desktop_settings.py instead of Odin's web API."""

from __future__ import annotations

from typing import get_args

import pytest
import yaml
from pydantic import ValidationError

from src.config import schema
from src.config.schema import Config, ObservabilityConfig, load_config


def _numeric_fields():
    from pydantic import BaseModel

    result = []
    for name, model in vars(schema).items():
        if not isinstance(model, type) or not issubclass(model, BaseModel):
            continue
        for field_name, field in model.model_fields.items():
            annotation = field.annotation
            args = get_args(annotation)
            if annotation in (int, float) or int in args or float in args:
                kind = float if annotation is float or float in args else int
                result.append(pytest.param(model, field_name, field, kind,
                                           id=f"{name}.{field_name}"))
    return result


NUMERIC_FIELDS = _numeric_fields()


def _model_data(model):
    if model is schema.ToolHost:
        return {"address": "127.0.0.1"}
    if model is schema.OpenAICompatibleModelProfile:
        return {"total_window_tokens": 100_000, "max_output_tokens": 10_000}
    return {}


@pytest.mark.parametrize("model,name,field,kind", NUMERIC_FIELDS)
def test_every_numeric_setting_has_strict_bounded_metadata(model, name, field, kind):
    assert any(getattr(item, "strict", False) for item in field.metadata)
    assert any(getattr(item, "ge", None) is not None for item in field.metadata)
    assert any(getattr(item, "le", None) is not None for item in field.metadata)


@pytest.mark.parametrize("model,name,field,kind", NUMERIC_FIELDS)
def test_every_numeric_setting_rejects_booleans_and_out_of_range(model, name, field, kind):
    lower = next(item.ge for item in field.metadata if getattr(item, "ge", None) is not None)
    upper = next(item.le for item in field.metadata if getattr(item, "le", None) is not None)
    invalid = [True, False, kind(lower - 1), kind(upper + 1), "1"]
    if kind is int:
        invalid.append(float(max(1, lower)))
    else:
        invalid.extend([float("nan"), float("inf"), -float("inf")])
    for value in invalid:
        with pytest.raises(ValidationError):
            model.model_validate({**_model_data(model), name: value})


@pytest.mark.parametrize("model,name,field,kind", NUMERIC_FIELDS)
def test_all_nonsensitive_numeric_settings_keep_legacy_startup_values(
    model, name, field, kind, caplog
):
    # Computer identity fields predate this change and remain fail-closed.
    if model is schema.ComputerUseConfig:
        return
    upper = next(item.le for item in field.metadata if getattr(item, "le", None) is not None)
    value = kind(upper + 1)
    with caplog.at_level("WARNING"):
        config = model.model_validate(
            {**_model_data(model), name: value}, context={"startup": True}
        )
    assert getattr(config, name) == value
    assert name in caplog.text and "Startup compatibility" in caplog.text


@pytest.mark.parametrize("value", [True, False, 2000.0, "2000"])
def test_startup_retains_legacy_integer_coercion_with_warning(value, caplog):
    config = ObservabilityConfig.model_validate(
        {"max_tool_result_chars": value}, context={"startup": True}
    )
    assert type(config.max_tool_result_chars) is int
    assert config.max_tool_result_chars == int(value)
    assert "max_tool_result_chars" in caplog.text


@pytest.mark.parametrize("section,field,values", [
    ("sessions", "context_budget_overrides", {"channel": True}),
    ("sessions", "context_budget_overrides", {"channel": 0}),
    ("sessions", "context_budget_overrides", {"channel": 10**12}),
    ("tools", "tool_timeouts", {"fetch_url": "30"}),
    ("tools", "tool_timeouts", {"fetch_url": True}),
    ("tools", "tool_timeouts", {"fetch_url": 10**12}),
    ("agents", "final_warning_iterations", [True]),
    ("agents", "final_warning_iterations", [1.0]),
    ("agents", "final_warning_iterations", [10**12]),
    ("openai_codex", "context_budget_overrides", {"gpt-6-luna": 60000.0}),
    ("openai_codex", "context_budget_overrides", {"gpt-6-luna": True}),
])
def test_numeric_container_entries_are_strict_and_bounded(section, field, values):
    with pytest.raises(ValidationError):
        Config.model_validate({section: {field: values}})


@pytest.mark.parametrize("value", [True, 300.0, "300", -1, 0, 10**12])
def test_legacy_timeout_alias_cannot_bypass_save_validation(value):
    with pytest.raises(ValidationError):
        schema.OpenAICompatibleConfig(timeout=value)


@pytest.mark.parametrize("value", [True, 90000.0, 90000.5, "90000", -1, 0, 10**12])
def test_legacy_profile_alias_cannot_bypass_strict_save_validation(value):
    with pytest.raises(ValidationError):
        schema.OpenAICompatibleModelProfile(usable_input_tokens=value, max_output_tokens=10000)


def test_legacy_profile_strings_remain_startup_compatible(caplog):
    config = schema.OpenAICompatibleModelProfile.model_validate(
        {"usable_input_tokens": "90000", "max_output_tokens": "10000"},
        context={"startup": True},
    )
    assert config.total_window_tokens == 100000
    assert config.max_output_tokens == 10000
    assert "Startup compatibility" in caplog.text


@pytest.mark.parametrize("yaml_value,expected_usable", [
    ("90000.5", 90000),
    ("90000.0", 90000),
    ('"90000"', 90000),
    ("true", 1),
    ("0", 0),
    ("10000001", 10000001),
])
def test_real_legacy_profile_load_preserves_conversion_without_rewriting(
    tmp_path, monkeypatch, caplog, yaml_value, expected_usable
):
    path = tmp_path / "legacy-profile.yml"
    original = (
        "# Preserve operator formatting as well as values.\r\n"
        "openai_compatible:\r\n  model_profiles:\r\n    fixture:\r\n"
        f"      usable_input_tokens: {yaml_value}\r\n"
        "      max_output_tokens: 10000\r\n"
    ).encode()
    path.write_bytes(original)
    monkeypatch.setattr(schema, "_ACTIVE_CONFIG_PATH", None)
    monkeypatch.setattr(schema, "_LAUNCH_CONFIG_PATH", None)
    with caplog.at_level("WARNING"):
        config = load_config(path)
    profile = config.openai_compatible.model_profiles["fixture"]
    assert profile.total_window_tokens == expected_usable + 10000
    assert profile.usable_input_tokens == expected_usable
    assert profile.max_output_tokens == 10000
    assert path.read_bytes() == original
    assert "Startup compatibility: legacy usable_input_tokens profile" in caplog.text
    # Loading an old spelling is not permission to save it with relaxed typing.
    with pytest.raises(ValidationError):
        Config.model_validate(yaml.safe_load(original))
    assert path.read_bytes() == original


def test_default_roundtrip_is_unchanged_without_numeric_warnings(caplog):
    data = Config().model_dump()
    assert Config.model_validate(data, context={"startup": True}).model_dump() == data
    assert "numeric save constraints" not in caplog.text


def test_real_nested_config_load_retains_outliers(tmp_path, monkeypatch, caplog):
    path = tmp_path / "nested.yml"
    text = (
        "tools:\n  bulkhead:\n    ssh_max_concurrent: 1000000000000\n"
        "  streaming:\n    max_chunk_chars: true\n"
        "sessions:\n  context_budget_overrides:\n    channel: -1\n"
        "mcp:\n  servers:\n    fixture:\n      timeout_seconds: -1\n"
    )
    path.write_text(text)
    monkeypatch.setattr(schema, "_ACTIVE_CONFIG_PATH", None)
    monkeypatch.setattr(schema, "_LAUNCH_CONFIG_PATH", None)
    config = load_config(path)
    assert config.tools.bulkhead.ssh_max_concurrent == 10**12
    assert config.tools.streaming.max_chunk_chars == 1
    assert config.sessions.context_budget_overrides == {"channel": -1}
    assert config.mcp.servers["fixture"].timeout_seconds == -1
    assert path.read_text() == text
    for field in ("ssh_max_concurrent", "max_chunk_chars", "context_budget_overrides",
                  "timeout_seconds"):
        assert field in caplog.text


def test_numeric_startup_does_not_bypass_other_validation():
    with pytest.raises(ValidationError):
        schema.OpenAICodexConfig.model_validate(
            {"context_budget_overrides": {"": -1}}, context={"startup": True}
        )
    with pytest.raises(ValidationError):
        schema.ToolHost.model_validate(
            {"address": "localhost", "host_id": "not-a-uuid", "port": -1},
            context={"startup": True},
        )


@pytest.mark.parametrize("value", [-1, 0, 10**12, True, False, 2000.0, "2000"])
def test_tool_result_save_rejects_invalid_numeric(value):
    with pytest.raises(ValidationError):
        ObservabilityConfig(max_tool_result_chars=value)


def test_existing_out_of_range_config_file_loads_with_warning(tmp_path, caplog, monkeypatch):
    # Real loader and an actual pre-upgrade YAML file, not model_validate alone.
    path = tmp_path / "existing.yml"
    text = "observability:\n  max_tool_result_chars: -1\n"
    path.write_text(text)
    monkeypatch.setattr(schema, "_ACTIVE_CONFIG_PATH", None)
    monkeypatch.setattr(schema, "_LAUNCH_CONFIG_PATH", None)
    with caplog.at_level("WARNING"):
        config = load_config(path)
    assert config.observability.max_tool_result_chars == -1
    assert path.read_text() == text
    assert "max_tool_result_chars" in caplog.text
    assert "startup" in caplog.text.lower()


# Odin 4.14 changed one case in each of tests/test_context_budget.py and
# tests/test_token_budget.py for these bounds. Desktop keeps Odin 4.13's bytes of
# those files (the plan excludes the two superseded cases), so Odin 4.14's versions
# run here, unchanged.
def test_compatible_profile_legacy_shape_and_openrouter_catalogue_fallback():
    from types import SimpleNamespace

    from src.config.schema import OpenAICompatibleModelProfile
    from src.llm.context_budget import (
        compatible_agent_unavailable_reason,
        compatible_model_profile,
        compatible_usable_input_tokens,
    )

    legacy = OpenAICompatibleModelProfile(
        usable_input_tokens=80000,
        max_output_tokens=20_000,
    )
    assert legacy.total_window_tokens == 100_000
    assert legacy.usable_input_tokens == 80_000
    assert compatible_usable_input_tokens(
        SimpleNamespace(usable_input_tokens="70000")
    ) == 70_000
    assert compatible_usable_input_tokens(
        SimpleNamespace(usable_input_tokens="bad")
    ) is None

    derived = OpenAICompatibleModelProfile(
        total_window_tokens=120_000,
        max_output_tokens=20_000,
    )
    cfg = SimpleNamespace(
        preset="openrouter",
        model_profiles={},
        context_utilization=75,
        openrouter=SimpleNamespace(catalogue_profiles={"vendor/model": derived}),
    )
    assert compatible_model_profile("compat:vendor/model", cfg) is derived
    assert compatible_agent_unavailable_reason("vendor/model", cfg) is None
    assert compatible_agent_unavailable_reason("unknown", cfg) == (
        "no context profile configured"
    )


def test_zero_budget():
    # Legacy zero files still load; new saves require a positive budget.
    with pytest.raises(ValueError):
        schema.SessionsConfig(token_budget=0)
    config = schema.SessionsConfig.model_validate({"token_budget": 0}, context={"startup": True})
    assert config.token_budget == 0
