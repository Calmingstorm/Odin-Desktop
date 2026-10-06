"""Whole frozen observability and prefix-measurement suites, socket-free."""

import pytest

from tests.desktop_adapters.step5_observability_http import load

load(globals())


def test_whole_http_corpus_preserves_all_frozen_assertions_and_cases():
    import ast

    from scripts.maintenance.fixture_corpus import corpus, frozen_source
    from tests.desktop_adapters.step5_observability_http import (
        CASE_MAP,
        CORPUS_EXCLUSIONS,
        CORPUS_SELECTIONS,
        SUITES,
        transformed_tree,
    )

    assert CORPUS_EXCLUSIONS == {}
    assert CORPUS_SELECTIONS == {stem: None for stem in SUITES}
    expected = set()
    for stem in SUITES:
        original = ast.parse(frozen_source(f"tests/{stem}.py"))
        assert corpus(original) == corpus(transformed_tree(stem))
        for node in original.body:
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                for method in node.body:
                    if getattr(method, "name", "").startswith("test_"):
                        expected.add(f"tests/{stem}.py::{node.name}::{method.name}")
            elif (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
            ):
                expected.add(f"tests/{stem}.py::{node.name}")
    assert set(CASE_MAP) == expected
    assert len(expected) == 23


@pytest.mark.asyncio
async def test_http_transport_calls_real_named_owner_without_listening_socket(monkeypatch):
    import socket
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from src.desktop.observability import ObservabilityService
    from tests.desktop_adapters import step5_observability_http as fixture

    original = ObservabilityService.handle
    methods = []

    async def tracked(self, method, params):
        methods.append((method, params))
        return await original(self, method, params)

    def forbidden_socket(*args, **kwargs):
        raise AssertionError("HTTP-shaped fixture must not create a socket")

    monkeypatch.setattr(socket, "socket", forbidden_socket)
    monkeypatch.setattr(ObservabilityService, "handle", tracked)
    bot = SimpleNamespace(
        audit=SimpleNamespace(count_by_tool=AsyncMock(return_value={"read_file": 2})),
    )
    routes = fixture.web.RouteTableDef()
    fixture.register_tools_meta(routes, bot)
    app = fixture.web.Application()
    app.router.add_routes(routes)
    async with fixture.TestClient(fixture.TestServer(app)) as client:
        response = await client.get("/api/tools/stats")
        assert response.status == 200
        assert await response.json() == {"read_file": 2}
        assert client.calls == [("observability", "observability.tools", {})]
    assert methods == [("observability.tools", {})]
    bot.audit.count_by_tool.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_http_tools_uses_actual_settings_persistence_and_model_owner(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    import yaml

    from src.config.schema import Config
    from src.desktop.model_settings import ModelSettingsService
    from src.desktop.settings import SettingsService
    from tests.desktop_adapters import step5_observability_http as fixture

    config = Config()
    executor = SimpleNamespace(config=config.tools.model_copy(deep=True))
    bot = SimpleNamespace(
        config=config, tool_executor=executor,
        tool_catalog=SimpleNamespace(backend_hidden_names=lambda: set(), invalidate=Mock()),
    )
    persistence = AsyncMock(return_value=(None, False))
    monkeypatch.setattr(fixture.persistence, "persist_config_paths_locked", persistence)
    routes = fixture.web.RouteTableDef()
    fixture.register_tools_meta(routes, bot)
    app = fixture.web.Application()
    app.router.add_routes(routes)
    async with fixture.TestClient(fixture.TestServer(app)) as client:
        response = await client.put("/api/tools/timeouts", json={"default_timeout": 61})
        assert response.status == 200
        owner = client.owners[id(bot)]
        assert type(owner) is ModelSettingsService
        assert type(owner.settings) is SettingsService
        saved = yaml.safe_load(client.paths.config_file.read_text())
        assert saved["tools"]["command_timeout_seconds"] == 61
        assert bot.config is owner.settings.config
        assert executor.config.command_timeout_seconds == 61
        assert client.calls == [("models", "tools.timeouts.set", {"default_timeout": 61})]
    persistence.assert_awaited_once_with([(("tools", "command_timeout_seconds"), 61)])
