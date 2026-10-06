"""Whole frozen learning/recovery suite selection, with case-level retirements."""
import ast

import pytest
import pytest_asyncio

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from tests.desktop_adapters import lane6_health_learning as bridge

CORPUS_SELECTIONS = {
    "test_chat_loop_recovery": None,
    "test_learning_runtime_switch": None,
    "test_learning_transport_switch": None,
}
CORPUS_EXCLUSIONS = {
    "test_chat_loop_recovery": [
        "TestEntryPointCensus.test_full_discord_run_rescues_durably",
        "TestEntryPointCensus.test_nondurable_web_run_still_rescues",
    ],
    "test_learning_runtime_switch": [
        "test_config_api_flip_drives_real_prompt_with_persisted_memory",
    ],
    "test_learning_transport_switch": [
        "test_web_physical_request_refreshes_after_provider_lock_wait",
        "test_legacy_checkpoint_resume_rebuilds_prompt_from_live_components",
    ],
}


@pytest_asyncio.fixture(autouse=True)
async def lane6_health_learning_graph(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    graph = bridge.make_graph(tmp_path)
    token = bridge.GRAPH.set(graph)
    try:
        yield graph
    finally:
        bridge.GRAPH.reset(token)
        await graph.requests.close()
        await graph.engine.close()
        graph.store.close()
        graph.permissions.reset_request_owner(graph.owner_token)
        graph.authority.release_runtime()


bridge.load(globals())


@pytest.mark.parametrize("stem", tuple(bridge.SUITES))
def test_lane6_health_learning_frozen_corpus_exact(stem):
    assert corpus(ast.parse(frozen_source(f"tests/{stem}.py"))) == corpus(bridge.adapted_tree(stem))
