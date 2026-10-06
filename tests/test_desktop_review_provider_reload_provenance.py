import ast
import hashlib

from scripts.maintenance.fixture_corpus import corpus, dump
from tests.desktop_adapters import review_provider_reload as adapter


def test_full_assertions_and_whole_selection_preserved():
    assert corpus(adapter.source_tree()) == corpus(adapter.adapted_tree())
    assert len(corpus(adapter.source_tree())["cases"]) == 1
    assert len(corpus(adapter.source_tree())["assertions"]) == 6
    assert adapter.CORPUS_SELECTIONS == {"test_campaign_provider_reload_coverage": None}
    assert adapter.CORPUS_EXCLUSIONS == {}


def test_exact_reversible_hunk_seals():
    assert len(adapter.hunk_records()) == 5
    for record in adapter.hunk_records():
        for side in ("before", "after"):
            node = ast.parse(record[f"{side}_source"]).body[0]
            assert hashlib.sha256(dump(node).encode()).hexdigest() == record[f"{side}_sha256"]
        assert record["reversible"]


async def test_real_durable_patch_and_rollback_evidence(desktop_provider_graph):
    from unittest.mock import AsyncMock

    graph = desktop_provider_graph
    before_text = graph.paths.config_file.read_text()
    before_config, before_client = graph.settings.config, graph.owner.compatible_client
    graph.owner._probe_openai_compatible = AsyncMock(return_value="rejected candidate")
    result = await adapter.save(
        graph, "providers.compat.set", ("openai_compatible.model", "candidate")
    )
    assert result.status == 500 and result.verdict.code == "internal_error"
    assert graph.settings.config is before_config
    assert graph.owner.compatible_client is before_client
    assert graph.paths.config_file.read_text() == before_text
    assert graph.events == [
        [(("openai_compatible", "model"), "candidate")],
        [(("openai_compatible", "model"), before_config.openai_compatible.model)],
    ]


desktop_provider_graph = adapter.desktop_provider_graph
