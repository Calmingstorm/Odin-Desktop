"""Authoritative complete frozen work projection partition and byte pins."""
import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from src.agents.manager import AgentInfo, AgentManager
from src.desktop.requests import RequestService
from src.desktop.work import WorkService
from src.tools.autonomous_loop import LoopManager
from tests.desktop_adapters import lane6_work_projection_finish as fixture
from tests.desktop_adapters.lane6_work_projection_finish import load

load(globals())


def test_work_projection_complete_frozen_corpus_and_partition():
    original = corpus(ast.parse(frozen_source(fixture.PATH)))
    assert original == corpus(fixture.transformed_tree())
    cases = {symbol for symbol, *_ in original["cases"]}
    partition = fixture.partition()
    assert set(partition["restored"]).isdisjoint(partition["deferred"])
    assert set(partition["restored"]) | set(partition["deferred"]) == cases
    assert partition["retired"] == []
    assert fixture.CORPUS_SELECTIONS == {fixture.STEM: None}
    assert fixture.CORPUS_EXCLUSIONS == {}
    assert len(fixture.CASE_MAP) == len(cases)
    assert {key.split("::", 1)[1].replace("::", ".") for key in fixture.CASE_MAP} == cases


def test_work_projection_whole_adapter_and_source_hash_pins():
    root = Path(__file__).resolve().parents[1]
    report = json.loads((root / "maintenance/lane6-work-projection-report.json").read_text())
    assert hashlib.sha256(frozen_source(fixture.PATH)).hexdigest() == fixture.SUITES[fixture.STEM]
    for path, expected in report["artifact_sha256"].items():
        assert hashlib.sha256((root / path).read_bytes()).hexdigest() == expected
    partition = fixture.partition()
    assert report["case_partition"] == {
        "restored": len(partition["restored"]), "retired": len(partition["retired"]),
        "deferred": len(partition["deferred"]),
    }
    assert report["restored_cases"] == partition["restored"]


@pytest.mark.asyncio
async def test_work_projection_uses_real_admission_and_retained_managers(monkeypatch):
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("projection must not open sockets")

    calls = []
    actual = WorkService.register

    def observed(self, kind, manager_id, message, **kwargs):
        assert isinstance(self.requests, RequestService)
        self.requests.assert_bound_request(message)
        assert isinstance(self.agents, AgentManager)
        assert isinstance(self.loops, LoopManager)
        assert isinstance(self.agents._agents[manager_id], AgentInfo)
        calls.append((kind, manager_id))
        return actual(self, kind, manager_id, message, **kwargs)

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(WorkService, "register", observed)
    agent = AgentInfo(id="a", label="fixture", goal="harmless", channel_id="fixture",
                      requester_id="fixture", requester_name="Owner")
    agent.has_executed, agent.last_model, agent.last_provider = True, "fixture", "ollama"
    bot = SimpleNamespace(agent_manager=SimpleNamespace(_agents={"a": agent}),
                          config=SimpleNamespace())
    routes = []
    fixture.register_agents(routes, bot)
    app = fixture.Application()
    app.add_routes(routes)
    async with fixture.TestClient(fixture.TestServer(app)) as client:
        response = await client.get("/api/agents")
        assert (await response.json())[0]["display_model"] == "fixture"
    assert calls == [("agent", "a")]


def test_work_projection_required_production_contracts_are_built():
    assert callable(WorkService.agent_detail)
    assert callable(WorkService.loop_detail)
    assert callable(WorkService.start_loop)
    assert callable(WorkService.restart_loop)
    assert fixture.RETIRED_CASES == {}
    assert fixture.DEFERRED_CASES == {fixture.STEM: {}}
