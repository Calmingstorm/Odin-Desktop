"""Exact frozen schedule API retained cases and real-owner transport contract."""
import ast

import pytest

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from tests.desktop_adapters import lane6_schedules_web as fixture

from tests.desktop_adapters.lane6_schedules_web import load

load(globals())


def test_lane6_schedules_web_whole_frozen_corpus():
    original = ast.parse(frozen_source(fixture.PATH))
    assert corpus(original) == corpus(fixture.transformed_tree())
    assert {key.split("::", 1)[1].replace("::", ".") for key in fixture.CASE_MAP} == fixture.SELECTED
    cases = {symbol for symbol, *_ in corpus(original)["cases"]}
    deferred = set(fixture.DEFERRED_CASES["test_web_api_schedules"])
    assert not (fixture.SELECTED & deferred)
    assert fixture.SELECTED | deferred == cases


@pytest.mark.asyncio
async def test_lane6_schedules_web_calls_real_owner_without_socket(monkeypatch):
    import socket
    from unittest.mock import MagicMock

    from src.desktop.schedules import ScheduleService

    observed = []
    real = ScheduleService.invoke

    async def invoke(self, method, params, *, owner, **kwargs):
        assert self.authority.accepts(owner)
        observed.append(method)
        return await real(self, method, params, owner=owner, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("Frozen transport must not open sockets")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(ScheduleService, "invoke", invoke)
    routes = []
    fixture.register_schedules(routes, MagicMock())
    app = fixture.Application()
    app.add_routes(routes)
    async with fixture.TestClient(fixture.TestServer(app)) as client:
        response = await client.post("/api/schedules/validate-cron", json={"expression": "0 9 * * *"})
        assert (await response.json())["valid"] is True
    assert observed == ["schedules.validate_cron"]
