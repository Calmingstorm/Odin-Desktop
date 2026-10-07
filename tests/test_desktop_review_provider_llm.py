"""Independent present-feature checks; NOT an inherited LLM suite restoration."""
import asyncio

import aiohttp
import pytest

from src.desktop.management import MethodError
from src.llm import OllamaClient, OpenAICompatibleClient
from tests.desktop_adapters.review_provider_llm import command, provider_graph, save


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("PR34 LLM tests must not open a network session")
    monkeypatch.setattr(aiohttp, "ClientSession", blocked)


@pytest.mark.asyncio
async def test_real_owner_main_model_persists_and_adopts(tmp_path):
    async with provider_graph(tmp_path) as graph:
        assert graph.permissions.is_owner(graph.authority.owner_id)
        configured = await save(graph, "providers.ollama.set", ("ollama.enabled", True))
        assert configured.status == 200
        assert isinstance(graph.owner.ollama, OllamaClient)
        assert graph.owner.main is None
        response = await command(graph, "models.main.set", {"model": "ollama:llama3"})
        assert response.status == 200
        assert (await response.json())["configured_provider"] == "ollama"
        assert graph.owner.main is graph.owner.ollama
        assert graph.owner.main.model == "llama3"
        assert graph.settings.config.llm_provider.model == "ollama:llama3"
        assert "ollama:llama3" in graph.paths.config_file.read_text()
        assert graph.owner.main._session is None


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["auto", "compat:", "ollama:"])
async def test_invalid_main_model_never_persists_or_publishes(tmp_path, model):
    async with provider_graph(tmp_path) as graph:
        before = graph.paths.config_file.read_bytes()
        response = await command(graph, "models.main.set", {"model": model})
        assert response.status == 400
        assert isinstance(response.verdict, MethodError)
        assert graph.paths.config_file.read_bytes() == before
        assert graph.owner._generation == 0
        assert graph.owner.main is None


@pytest.mark.asyncio
async def test_stale_main_revision_preserves_real_live_graph(tmp_path):
    async with provider_graph(tmp_path) as graph:
        await save(graph, "providers.ollama.set", ("ollama.enabled", True))
        revision = graph.settings.revision
        assert (await command(graph, "models.main.set", {"model": "ollama:adopted"})).status == 200
        client = graph.owner.main
        generation = graph.owner._generation
        before = graph.paths.config_file.read_bytes()
        response = await command(graph, "models.main.set", {
            "model": "ollama:rejected", "expected_revision": revision,
        })
        assert response.status == 409
        assert response.verdict.code == "stale_binding"
        assert graph.owner.main is client
        assert graph.owner._generation == generation
        assert not getattr(client, "_generation_retired", False)
        assert graph.paths.config_file.read_bytes() == before


@pytest.mark.asyncio
async def test_private_provider_validation_precedes_mutation(tmp_path):
    async with provider_graph(tmp_path) as graph:
        before = graph.paths.config_file.read_bytes()
        response = await save(graph, "providers.codex.set",
                              ("openai_codex.reasoning_effort", "not-an-effort"))
        assert response.status == 400
        assert response.verdict.code == "bad_request"
        assert graph.paths.config_file.read_bytes() == before
        assert graph.owner._generation == 0


@pytest.mark.asyncio
async def test_concrete_compatible_probe_failure_restores_disk_and_runtime(tmp_path, monkeypatch):
    probes = []

    async def unhealthy(client):
        probes.append(client)
        return {"healthy": False, "error": "fixture endpoint rejected"}

    monkeypatch.setattr(OpenAICompatibleClient, "health_check", unhealthy)
    async with provider_graph(tmp_path) as graph:
        graph.settings.secrets.set("openai_compatible.api_key", "fixture-only-credential")
        before = graph.paths.config_file.read_bytes()
        config = graph.settings.config.model_dump()
        response = await save(graph, "providers.compat.set",
                              ("openai_compatible.enabled", True))
        assert response.status == 500
        assert response.verdict.code == "internal_error"
        assert probes and isinstance(probes[0], OpenAICompatibleClient)
        assert graph.paths.config_file.read_bytes() == before
        assert graph.settings.config.model_dump() == config
        assert graph.owner.compat is None
        assert graph.owner._generation == 0
        assert "fixture-only-credential" not in str(await response.json())


@pytest.mark.asyncio
async def test_real_settings_cancellation_during_probe_restores_snapshot(tmp_path, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()

    async def suspended_probe(client):
        started.set()
        await release.wait()
        return {"healthy": True}

    monkeypatch.setattr(OpenAICompatibleClient, "health_check", suspended_probe)
    async with provider_graph(tmp_path) as graph:
        graph.settings.secrets.set("openai_compatible.api_key", "fixture-only-credential")
        before = graph.paths.config_file.read_bytes()
        task = asyncio.create_task(save(graph, "providers.compat.set",
                                        ("openai_compatible.enabled", True)))
        try:
            await asyncio.wait_for(started.wait(), 2)
            assert graph.paths.config_file.read_bytes() != before
            assert graph.owner.compat is None
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert graph.paths.config_file.read_bytes() == before
            assert graph.settings.config.openai_compatible.enabled is False
            assert graph.owner.compat is None
            assert graph.owner._generation == 0
        finally:
            release.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_unconfigured_auxiliary_is_honest_refusal(tmp_path):
    async with provider_graph(tmp_path) as graph:
        before = graph.paths.config_file.read_bytes()
        response = await save(graph, "providers.auxiliary.set",
                              ("openai_codex.auxiliary.enabled", True))
        assert response.status == 503
        assert response.verdict.code == "unavailable"
        assert graph.owner.auxiliary is None
        assert graph.paths.config_file.read_bytes() == before
