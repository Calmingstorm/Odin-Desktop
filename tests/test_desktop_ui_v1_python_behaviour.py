"""Deterministic validation, owner rollback and PDF first-use regressions.

These exercise real validators, profile transactions and import machinery.
Only credentials/network and deliberately injected disk damage are fixtures.
The default runner collects this Desktop boundary file automatically.
"""
from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from pydantic import ValidationError

from src.config.schema import OpenAICodexConfig
from src.desktop.management import MethodError
from src.runtime import pdf_resources as pdf
from tests import test_desktop_model_settings as model_fixtures
from tests import test_desktop_providers as provider_fixtures
from tests import test_pdf_resources as pdf_fixtures

service = model_fixtures.service
graph = provider_fixtures.graph
wheel_fixture = pdf_fixtures.wheel_fixture


@pytest.mark.parametrize("value", [True, False, 29, 101])
def test_context_utilization_validator_rejects_boolean_and_out_of_bounds(value):
    # Pydantic's ge/le constraint runs before the custom validator. Exercise
    # both contracts so callers of the validator cannot bypass its own bounds.
    with pytest.raises(ValueError, match="integer percent between 30 and 100"):
        OpenAICodexConfig._validate_context_utilization(value)
    with pytest.raises(ValidationError):
        OpenAICodexConfig(context_utilization=value)
    assert OpenAICodexConfig(context_utilization=30).context_utilization == 30
    assert OpenAICodexConfig(context_utilization=100).context_utilization == 100


@pytest.mark.asyncio
async def test_model_management_rejects_non_object_and_unsupported_effort(service):
    before = service.settings.config.model_dump()
    for method, params in [
        ("models.agents.set", []),
        ("models.main.set", {"model": "ollama:fixture", "reasoning_effort": "high"}),
        ("models.main.set", {"model": "codex:gpt-6.1-sol", "reasoning_effort": 3}),
    ]:
        with pytest.raises(MethodError) as error:
            await service.handle(method, params)
        assert error.value.code == "bad_request"
    assert service.settings.writes == []
    assert service.settings.config.model_dump() == before
    assert service.provider.tool_catalog.invalidations == 0


@pytest.mark.asyncio
async def test_main_owner_missing_result_cannot_confirm_adoption(service):
    confirmed = []
    service.settings.confirm_applied = lambda changes: confirmed.append(changes)

    async def no_result(*args, **kwargs):
        return None

    service.provider.switch_provider = no_result
    with pytest.raises(MethodError) as error:
        await service.handle("models.main.set", {"model": "ollama:fixture"})
    assert error.value.code == "unavailable"
    assert confirmed == []
    assert service.settings.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {"data": {}}, "not-json"])
async def test_model_discovery_rejects_malformed_actual_endpoint(service, body):
    async def catalogue(request):
        if body == "not-json":
            return web.Response(text="fixture-private-response", content_type="application/json")
        return web.json_response(body)

    app = web.Application()
    app.router.add_get("/models", catalogue)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        with pytest.raises(MethodError) as error:
            await service.handle("models.discover", {
                "provider": "compat", "base_url": f"http://127.0.0.1:{port}",
            })
        assert error.value.code == "unavailable"
        assert "fixture-private-response" not in str(error.value)
        assert "fixture-credential" not in str(error.value)
        assert service.settings.writes == []
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,params,message", [
    ("unknown", {}, "Unknown provider"),
    ("ollama", {"model_ref": "codex:gpt-6.1-sol"}, "does not match provider"),
    ("ollama", {"model_ref": "ollama:fixture", "reasoning_effort": "high"},
     "does not accept reasoning effort"),
    ("ollama", {"model_ref": "ollama:fixture", "persist": True},
     "Persistence callback required"),
])
async def test_real_provider_rejects_invalid_switch_without_publication(
    graph, monkeypatch, provider, params, message,
):
    # Ollama transport construction is real; qualification must not make any
    # network request for these rejected switches.
    def blocked(*args, **kwargs):
        pytest.fail("Rejected switches must not open network sessions")

    monkeypatch.setattr("aiohttp.ClientSession", blocked)
    settings, _, owner, _ = graph
    try:
        await provider_fixtures.save(settings, "providers.ollama.set", ("ollama.enabled", True))
        identity = owner.capture_serving_identity()
        config = settings.config.model_dump()
        revision = settings.revision
        data = settings.paths.config_file.read_bytes()
        result = await owner.switch_provider(provider, **params)
        assert message in result["error"]
        assert owner.capture_serving_identity() == identity
        assert settings.config.model_dump() == config
        assert settings.revision == revision
        assert settings.paths.config_file.read_bytes() == data
        assert not owner.switching
    finally:
        await owner.close()


@pytest.mark.asyncio
async def test_cancelled_failed_persistence_rolls_back_real_owner(graph, monkeypatch):
    settings, _, owner, _ = graph
    started, release = threading.Event(), threading.Event()

    def blocked(*args, **kwargs):
        pytest.fail("Ollama switch must not connect during qualification")

    monkeypatch.setattr("aiohttp.ClientSession", blocked)
    await provider_fixtures.save(settings, "providers.ollama.set", ("ollama.enabled", True))
    identity = owner.capture_serving_identity()
    revision = settings.revision
    config = settings.config.model_dump()

    def fail_persist():
        started.set()
        assert release.wait(5)
        raise MethodError("storage_unavailable", "fixture write failed")

    task = asyncio.create_task(owner.switch_provider(
        "ollama", persist=fail_persist, model_ref="ollama:unpublished",
    ))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        assert owner.capture_serving_identity() == identity
        assert settings.revision == revision
        assert settings.config.model_dump() == config
        assert not owner.switching
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await owner.close()


def test_failed_real_pdf_import_removes_partial_modules_and_path(tmp_path, monkeypatch):
    directory = tmp_path / "site-packages"
    package = directory / "fitz"
    package.mkdir(parents=True)
    (package / "partial.py").write_text("value = 7\n")
    (package / "__init__.py").write_text(
        "from . import partial\nraise RuntimeError('fixture import failure')\n"
    )
    # The test owns the modules even on failure; no installed optional extra or
    # preceding suite can determine which package Python selects.
    with monkeypatch.context() as scoped:
        scoped.delitem(sys.modules, "fitz", raising=False)
        scoped.delitem(sys.modules, "fitz.partial", raising=False)
        unrelated = SimpleNamespace(__file__=str(tmp_path / "outside.py"))
        scoped.setitem(sys.modules, "fixture_pdf_unrelated", unrelated)
        old_path = sys.path[:]
        with pytest.raises(RuntimeError, match="fixture import failure"):
            pdf._load_install(directory)
        assert sys.path == old_path
        assert "fitz.partial" not in sys.modules
        assert sys.modules["fixture_pdf_unrelated"] is unrelated


def test_pdf_post_validation_import_damage_removes_publication_and_retries(
    wheel_fixture, monkeypatch,
):
    state = wheel_fixture
    validate = pdf._validate_install

    def validate_then_damage(directory):
        validate(directory)
        package = directory / "fitz"
        (package / "partial.py").write_text("value = 7\n")
        with (package / "__init__.py").open("a") as stream:
            stream.write("\nfrom . import partial\nraise RuntimeError('post-validation damage')\n")

    monkeypatch.setattr(pdf, "_validate_install", validate_then_damage)
    with pytest.raises(pdf.PdfUnavailable, match="could not be installed or loaded"):
        pdf._ensure_pdf()
    assert not (state.root / state.digest).exists()
    assert "fitz.partial" not in sys.modules
    assert not list(state.root.glob(".download-*"))
    assert pdf._inflight is None
    monkeypatch.setattr(pdf, "_validate_install", validate)
    module = pdf._ensure_pdf()
    document = module.open(stream=pdf_fixtures.PDF_BYTES, filetype="pdf")
    assert document[0].get_text() == "Pinned first-use PDF text"
    assert state.requests == 2
    assert Path(module.__file__).is_relative_to(state.root / state.digest)
