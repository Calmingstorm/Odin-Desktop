"""Odin 4.25.0 (PR #743) in Desktop: gpt-6.1-terra in every Codex model list.

Odin 4.25.0 adds gpt-6.1-terra between gpt-6.1-sol and gpt-6-sol: a measured usable-input
floor of 921,847 tokens, every effort from none to max, and a default description for
automatic agent selection. Desktop carries the same engine lines. Odin's new cases run here
with their frozen files' own helpers, in Desktop form (Desktop's Config has no Discord
section), next to the Desktop surfaces Odin does not have: the projected catalogue the app's
model pickers read, models.status and models.main.set.

Odin rewrote three frozen cases for the new list; their 4.25.0 versions run here under their
own names, and the frozen ones leave their selections: test_floors_match_probe_evidence
(tests/test_context_budget.py), test_agent_allowlist_entries_returns_legacy_defaults_as_a_list
(tests/test_agent_tool_policy_branch_coverage.py) and
test_catalogue_integrity_preserves_authored_and_derived_hint_inventory (tests/test_model_hints.py).
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import get_args

import pytest

import tests.test_native_agents_tasks as frozen_agents
import tests.test_openai_codex_client as frozen_codex
from src.config.schema import (
    CODEX_MODEL_INPUT_BUDGETS,
    CODEX_REASONING_EFFORTS,
    CODEX_UNKNOWN_MODEL_INPUT_BUDGET,
    Config,
    ReasoningEffort,
    allowed_efforts_for_model,
    effort_incompatibility_error,
    input_budget_floor_for_model,
    model_rejects_effort,
)
from src.desktop.openrouter_admin import _project_model_catalogue
from src.discord.native_tools.agents_tasks import _parse_spawn_overrides, _spawn_pair_error
from src.llm.context_budget import resolve_context_budget
from src.llm.openai_codex import CodexChatClient
from src.tools.agent_tool_policy import agent_allowlist_entries, apply_agent_axis_policy
from src.tools.defs.agents import SPAWN_MODEL_DESCRIPTIONS
from src.tools.model_hints import MODEL_HINT_CATALOGUE, seed_entry
from src.tools.registry import get_documentation_tool_definitions
from src.web.api import llm_admin
from tests import test_desktop_model_settings as model_settings

service = model_settings.service

TERRA = "gpt-6.1-terra"
ORDER = [
    "gpt-6-astra", "gpt-6.1-sol", TERRA, "gpt-6-sol", "gpt-6-luna",
    "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
]
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_catalogue(monkeypatch):
    monkeypatch.setattr(llm_admin, "_openrouter_cache", {"models": None})


def _raw_catalogue(config):
    return llm_admin._model_catalogue(
        SimpleNamespace(config=config), codex_configured=True, ollama_configured=False,
    )


def _rendered_spawn(agents):
    # Desktop's served built-ins: the documentation catalogue under the agent-axis policy
    # (src/desktop/services.py _ReadyCatalog), where Odin's test reads get_tool_definitions.
    config = Config(openai_codex={"enabled": True}, agents=agents)
    definitions = apply_agent_axis_policy(get_documentation_tool_definitions(), config)
    return next(d for d in definitions if d["name"] == "spawn_agent")


def test_every_codex_model_list_shares_one_order_with_terra_between_the_sols():
    config = Config()
    raw = _raw_catalogue(config)
    assert [row["ref"] for row in raw["codex"]] == ORDER
    assert [row["ref"] for row in _project_model_catalogue(config, raw)["codex"]] == ORDER
    assert [model for model, _description in SPAWN_MODEL_DESCRIPTIONS] == ORDER
    empty = SimpleNamespace(agents=SimpleNamespace(auto_model_allowlist=[]))
    assert agent_allowlist_entries(empty) == ORDER


def test_gpt_6_1_terra_accepts_every_effort():
    # Direct probe 2026-10-26: none..max all serve; no exception entry.
    for effort in CODEX_REASONING_EFFORTS:
        assert not model_rejects_effort(TERRA, effort)
        assert effort_incompatibility_error(TERRA, effort) is None
    assert allowed_efforts_for_model(TERRA) == CODEX_REASONING_EFFORTS


def test_terra_none_pairs_load_on_every_axis():
    cfg = Config(agents={"model": TERRA}, llm_provider={"model": TERRA},
                 openai_codex={"model": TERRA, "reasoning_effort": "none",
                               "agent_reasoning_effort": "none"})
    assert cfg.openai_codex.reasoning_effort == "none"
    assert cfg.openai_codex.agent_reasoning_effort == "none"
    assert (cfg.llm_provider.model, cfg.agents.model) == (TERRA, TERRA)


def test_floors_match_probe_evidence():
    # A floor never exceeds its own accepted observation: only sol got
    # the fine-refinement acceptances (921,601); its window-mates proved
    # 917,506 (plan of record R2).
    assert CODEX_MODEL_INPUT_BUDGETS == {
        # astra: probed 2026-09-04 (accepted 917,534 / rejected at 922,000)
        "gpt-6-astra": 917_534,
        # gpt-6.1-sol: Workspace usage echo 2026-09-29 accepted 921,849.
        "gpt-6.1-sol": 921_849,
        # gpt-6.1-terra: Secondary usage echo 2026-10-26 accepted 921,847.
        "gpt-6.1-terra": 921_847,
        # Sol/Luna: accepted usage-echo evidence from 2026-09-22.
        "gpt-6-sol": 921_799,
        "gpt-6-luna": 921_799,
        "gpt-5.6-sol": 921_601,
        "gpt-5.6-terra": 917_506,
        "gpt-5.6-luna": 917_506,
        "gpt-5.4": 917_506,
        "gpt-5.4-mini": 262_146,
    }
    assert CODEX_UNKNOWN_MODEL_INPUT_BUDGET == 272_000


def test_terra_resolves_to_its_probed_floor_not_the_unknown_default():
    assert input_budget_floor_for_model(TERRA) == 921_847
    snap = resolve_context_budget(TERRA)
    assert (snap.canonical_model, snap.base_source) == (TERRA, "floor")
    assert snap.base_budget == snap.effective_budget == 921_847
    assert snap.primary_chars > resolve_context_budget("gpt-7-unknown").primary_chars


def test_rendered_auto_catalogue_offers_terra_with_its_seed_hint():
    spawn = _rendered_spawn({"model": "auto"})
    model = spawn["input_schema"]["properties"]["model"]
    enum = model["enum"]
    assert enum.index(TERRA) == enum.index("gpt-6.1-sol") + 1
    assert enum.index("gpt-6-sol") == enum.index(TERRA) + 1
    hint = seed_entry(TERRA)["property_hint"]
    assert f"{TERRA} = {hint}" in model["description"]
    assert f"{TERRA} ({seed_entry(TERRA)['clause_hint']})" in spawn["description"]


def test_explicit_allowlist_without_terra_does_not_advertise_it():
    allowlist = ["gpt-6.1-sol", "gpt-6-luna"]
    spawn = _rendered_spawn({"model": "auto", "auto_model_allowlist": allowlist})
    model = spawn["input_schema"]["properties"]["model"]
    assert model["enum"] == ["gpt-6.1-sol", "gpt-6-luna"]
    assert TERRA not in model["description"]
    assert TERRA not in spawn["description"]


def test_operator_hint_for_terra_replaces_the_seed_hint():
    spawn = _rendered_spawn({"model": "auto", "model_selection_hints": {
        TERRA: "UNIQUE operator terra hint"}})
    model_desc = spawn["input_schema"]["properties"]["model"]["description"]
    assert "UNIQUE operator terra hint" in model_desc
    assert "UNIQUE operator terra hint" in spawn["description"]
    assert seed_entry(TERRA)["property_hint"] not in model_desc


def test_terra_override_parsed_on_auto_axes():
    selected, effort, _thinking, err = _parse_spawn_overrides(
        {"model": TERRA, "reasoning_effort": "max"}, model_mode="auto", effort_mode="auto",
    )
    assert (selected, effort, err) == (TERRA, "max", None)


def test_terra_pair_boundary_accepts_none_and_max():
    cfg = frozen_agents.TestRecentModelSpawnBoundary._cfg
    client = frozen_agents._FakeEffortClient()
    for effort in ("none", "max"):
        assert _spawn_pair_error(cfg(), client, TERRA, effort) is None
    # Inherited pair: a fixed gpt-6.1-terra under a "none" main effort is fine.
    client.reasoning_effort = "none"
    assert _spawn_pair_error(cfg(agent_model=TERRA), client, None, None) is None


async def test_terra_none_reaches_the_wire_as_a_literal_effort():
    # gpt-6.1-terra serves "none" (probed 2026-10-26): no guard, no omission.
    guard = frozen_codex.TestKnownBadPairGuard
    client = CodexChatClient(auth=frozen_codex._BareAuth(), model=TERRA, reasoning_effort="none")
    calls = guard._arm_transport(client)
    await client.chat(guard._MSGS, "sys")
    await client.chat_with_tools(guard._MSGS, "sys", guard._TOOLS)
    assert [kind for kind, _body in calls] == ["chat", "tools"]
    for _kind, body in calls:
        assert body["model"] == TERRA
        assert body["reasoning"] == {"effort": "none"}


def test_gpt_6_1_terra_seed_matches_spawn_copy_between_the_two_sols():
    models = [name for name, _description in SPAWN_MODEL_DESCRIPTIONS]
    assert models.index(TERRA) == models.index("gpt-6.1-sol") + 1
    assert models.index("gpt-6-sol") == models.index(TERRA) + 1
    description = dict(SPAWN_MODEL_DESCRIPTIONS)[TERRA]
    assert "slightly less capable than gpt-6.1-sol but cheaper" in description
    assert "escalating to gpt-6.1-sol for harder problems" in description
    # It serves effort "none", so it must not inherit 6.1 Sol's warning.
    assert "rejects effort" not in description
    entry = seed_entry(TERRA)
    assert entry["clause_hint"] == description
    assert entry["property_hint"] == description
    assert (entry["as_of"], entry["structural_source"]) == ("2026-10-26", "shipped")


def test_agent_allowlist_entries_returns_legacy_defaults_as_a_list():
    config = SimpleNamespace(agents=SimpleNamespace(auto_model_allowlist=[]))

    entries = agent_allowlist_entries(config)

    assert entries == ORDER
    assert isinstance(entries, list)


def test_catalogue_integrity_preserves_authored_and_derived_hint_inventory():
    """The checked-in catalogue is deliberately a finite, auditable snapshot."""
    assert len(MODEL_HINT_CATALOGUE) == 142
    assert sum("hint" in entry for entry in MODEL_HINT_CATALOGUE.values()) == 134
    assert sum("hint_derived" in entry for entry in MODEL_HINT_CATALOGUE.values()) == 118
    # 16 authored provider hints plus the eight shipped Codex tier entries.
    assert sum("hint_derived" not in entry for entry in MODEL_HINT_CATALOGUE.values()) == 24


def test_seed_generator_dates_new_codex_entries_without_a_previous_seed():
    source = (ROOT / "scripts/generate_model_hints_seed.py").read_text()
    node = next(n for n in ast.parse(source).body
                if isinstance(n, ast.FunctionDef) and n.name == "entry_as_of")
    namespace = {"AS_OF": "2026-09-22", "_previous_models": {}}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "entry_as_of", "exec"), namespace)
    entry_as_of = namespace["entry_as_of"]
    assert entry_as_of("codex/gpt-6.1-terra") == "2026-10-26"
    assert entry_as_of("codex/gpt-6.1-sol") == "2026-09-29"
    assert entry_as_of("codex/gpt-6-sol") == "2026-09-22"
    namespace["_previous_models"] = {"codex/gpt-6.1-terra": {"as_of": "2026-11-01"}}
    assert entry_as_of("codex/gpt-6.1-terra") == "2026-11-01"


def test_app_picker_row_offers_every_effort_and_the_shipped_description():
    config = Config()
    rows = {row["ref"]: row for row in _project_model_catalogue(
        config, _raw_catalogue(config))["codex"]}
    terra, sol = rows[TERRA], rows["gpt-6.1-sol"]
    every = list(get_args(ReasoningEffort))
    assert every == ["none", "low", "medium", "high", "xhigh", "max"]
    assert terra["efforts"] == every
    assert terra["effort_capabilities"] == {
        "values": every, "source": "core_validation",
        # Like gpt-6-sol and gpt-6-luna: no exception entry, nothing restricted.
        "restrictions_known": False,
    }
    assert terra["effort_capabilities"] == rows["gpt-6-sol"]["effort_capabilities"]
    assert "none" not in sol["efforts"]
    assert (terra["builtin_hint"], terra["builtin_hint_source"]) == (
        dict(SPAWN_MODEL_DESCRIPTIONS)[TERRA], "catalogue")


@pytest.mark.parametrize("effort", ["none", "max"])
async def test_main_model_saves_terra_with_none_and_max(service, effort):
    calls = []

    async def switch(provider, persist, *, model_ref, reasoning_effort):
        calls.append((provider, model_ref, reasoning_effort))
        persist()
        return {"provider": provider, "model": model_ref}

    service.provider.switch_provider = switch
    answer = await service.handle("models.main.set", {
        "model": f"codex:{TERRA}", "reasoning_effort": effort, "expected_revision": "r0",
    })
    assert calls == [("codex", f"codex:{TERRA}", effort)]
    assert answer["main_model"] == f"codex:{TERRA}"
    assert service.settings.config.llm_provider.model == f"codex:{TERRA}"
    assert service.settings.config.openai_codex.reasoning_effort == effort
    assert len(service.settings.writes) == 1
