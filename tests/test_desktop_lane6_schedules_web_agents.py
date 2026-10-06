"""Whole provenance binding and retained display projections through real work."""
import ast

import pytest

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from tests.desktop_adapters import lane6_schedules_web_agents as fixture

from tests.desktop_adapters.lane6_schedules_web_agents import load

load(globals())


def test_lane6_schedules_web_agents_whole_frozen_corpus():
    assert corpus(ast.parse(frozen_source(fixture.PATH))) == corpus(fixture.transformed_tree())
    expected = {symbol for symbol, *_ in corpus(ast.parse(frozen_source(fixture.PATH)))["cases"]
                if fixture.selected(symbol)}
    assert {key.split("::", 1)[1].replace("::", ".") for key in fixture.CASE_MAP} == expected
    cases = {symbol for symbol, *_ in corpus(ast.parse(frozen_source(fixture.PATH)))["cases"]}
    deferred = set(fixture.DEFERRED_CASES["test_web_api_agents_loops"])
    assert not (expected & deferred)
    assert expected | deferred == cases


@pytest.mark.asyncio
async def test_lane6_schedules_web_agents_calls_actual_work_service(monkeypatch):
    import socket
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from src.desktop.work import WorkService

    observed = []
    real = WorkService.list

    def list_records(self, params=None):
        assert self.authority.accepts(self.permissions.authority.authenticate_local(
            peer_uid=self.authority.owner_uid))
        observed.append(params)
        return real(self, params)

    def forbidden(*args, **kwargs):
        raise AssertionError("Display transport must not create sockets")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(WorkService, "list", list_records)
    bot = MagicMock()
    bot.agent_manager._agents = {"a": SimpleNamespace(requester_id="fixture", channel_id="fixture",
        created_at=1.0, status="running", has_executed=True, last_provider="ollama",
        last_model="fixture-model", last_reasoning_effort=None)}
    bot.config = SimpleNamespace(llm_provider=SimpleNamespace(active_provider="ollama"))
    routes = []
    fixture.register_agents(routes, bot)
    app = fixture.Application()
    app.add_routes(routes)
    async with fixture.TestClient(fixture.TestServer(app)) as client:
        response = await client.get("/api/agents")
        assert (await response.json())[0]["display_model"] == "fixture-model"
    assert observed == [{"kind": "agent"}]
