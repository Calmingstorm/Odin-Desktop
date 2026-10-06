"""Agent/boot settings do not churn serving transports or discard auxiliary."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.desktop_adapters.review_provider_llm import provider_graph, save


@pytest.mark.parametrize(
    "path,value",
    [
        ("openai_codex.agent_reasoning_effort", "low"),
        ("openai_codex.agent_model", "gpt-5.6-luna"),
        ("openai_codex.connection_pool.max_connections", 12),
        ("openai_codex.context_compression.keep_recent_iterations", 4),
    ],
)
async def test_nontransport_settings_preserve_graph_and_invalidate_cache(
    tmp_path, monkeypatch, path, value
):
    async with provider_graph(tmp_path) as graph:
        # Opaque identity sentinels are never asked to execute provider work.
        # Their preservation proves no constructors/qualification were invoked.
        client, auxiliary = object(), object()
        graph.owner.codex_client = client
        graph.owner.auxiliary_llm_client = auxiliary
        graph.owner.tool_catalog = SimpleNamespace(invalidate=Mock())

        def forbidden(*args, **kwargs):
            raise AssertionError("nontransport settings must not construct a provider")

        monkeypatch.setattr(graph.owner, "_build", forbidden)
        result = await save(graph, "providers.codex.set", (path, value))
        assert result.status == 200
        assert graph.owner.codex_client is client
        assert graph.owner.auxiliary_llm_client is auxiliary
        graph.owner.tool_catalog.invalidate.assert_called_once()
        # Sentinels were observation-only, not owned concrete transports to close.
        graph.owner.codex_client = graph.owner.auxiliary_llm_client = None


async def test_transport_change_still_constructs_codex(tmp_path, monkeypatch):
    async with provider_graph(tmp_path) as graph:
        calls = []
        original = graph.owner._build

        def observe(provider, *args, **kwargs):
            calls.append(provider)
            return original(provider, *args, **kwargs)

        monkeypatch.setattr(graph.owner, "_build", observe)
        result = await save(graph, "providers.codex.set", ("openai_codex.enabled", False))
        assert result.status == 200
        assert calls == ["codex"]
