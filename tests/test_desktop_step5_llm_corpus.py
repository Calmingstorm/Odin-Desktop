"""Entire frozen OpenRouter/admin/affordance suites on named Desktop services."""
import ast

import pytest

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from tests.desktop_adapters import step5_llm_bridge as bridge
from tests.desktop_adapters.step5_llm_cases import (
    CASE_MAP,
    EVIDENCE,
    SUITE_NAMES,
    adapted_tree,
    load,
)

CORPUS_SELECTIONS = {"test_campaign_openrouter_coverage": None,
                     "test_openrouter_admin_boundaries": None,
                     "test_web_api_new_endpoints": None}
CORPUS_EXCLUSIONS = {}


@pytest.fixture(autouse=True)
def temporary_real_profile(tmp_path, monkeypatch):
    token = bridge.ROOT.set(tmp_path)
    for variable, suffix in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"),
                             ("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache")):
        monkeypatch.setenv(variable, str(tmp_path / suffix))
    yield
    bridge.ROOT.reset(token)


load(globals())


@pytest.mark.parametrize("stem", SUITE_NAMES)
def test_whole_frozen_corpus_is_exact(stem):
    path = f"tests/{stem}.py"
    original = ast.parse(frozen_source(path))
    assert corpus(original) == corpus(adapted_tree(stem))
    evidence = EVIDENCE[path]
    assert evidence["whole_suite"] is True
    assert evidence["exact_corpus"] == corpus(original)
    expected = {symbol for symbol, *_ in corpus(original)["cases"]}
    exported = {key.removeprefix(path + "::").replace("::", ".")
                for key in CASE_MAP if key.startswith(path + "::")}
    assert expected == exported


def test_bridge_owns_real_services(tmp_path):
    fixture = bridge._make_bot(tmp_path)
    assert type(fixture.settings) is bridge.SettingsService
    assert type(fixture.llm_gateway) is bridge.ProviderOwner
    assert type(fixture.openrouter) is bridge.OpenRouterAdminService
    assert type(fixture.models) is bridge.ModelSettingsService
    assert fixture.openrouter.settings is fixture.settings
    assert fixture.openrouter.provider is fixture.llm_gateway
