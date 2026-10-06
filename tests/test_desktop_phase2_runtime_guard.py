"""Full frozen subsystem guard export and production-composition regressions."""
import ast
import copy

import pytest

from scripts.maintenance.fixture_corpus import corpus, dump
from src.health.subsystem_guard import SubsystemGuard, SubsystemState
from tests.desktop_adapters.step8_runtime_guard import (
    SYMBOL,
    _target,
    adapt,
    inherited_setup,
    load,
    temporary_guard_graph,
    verify,
)


@pytest.fixture(autouse=True)
def _network_boundary(monkeypatch):
    import aiohttp

    def refuse(*args, **kwargs):
        raise AssertionError("guard tests must not open real network sessions")

    monkeypatch.setattr(aiohttp, "ClientSession", refuse)


@pytest.fixture(autouse=True)
def _inherited_profile(request, tmp_path):
    if request.node.originalname == SYMBOL.split(".")[1]:
        with inherited_setup(tmp_path, request.node.callspec.params["legacy_enabled"]):
            yield
    else:
        yield


_original, _adapted = load(globals())


def test_full_guard_corpus_and_reverse_ast():
    assert corpus(_original) == corpus(_adapted)
    assert dump(verify(_original, _adapted)) == dump(_original)
    exported = {node.name for node in _original.body if isinstance(node, ast.ClassDef)}
    assert exported == {name for name in globals() if name.startswith("Test")}


def test_setup_pin_rejects_threshold_drift():
    changed = copy.deepcopy(_original)
    setup = _target(changed)
    for node in ast.walk(setup.body[3]):
        if isinstance(node, ast.Constant) and node.value == 7:
            node.value = 8
    with pytest.raises(ValueError, match="setup AST pin"):
        adapt(changed)


def test_reverse_verifier_rejects_unapproved_nonassert_change():
    changed = copy.deepcopy(_adapted)
    changed.body.insert(0, ast.parse("unexpected_setup = 1").body[0])
    with pytest.raises(ValueError, match="reverse AST"):
        verify(_original, changed)


def test_corpus_rejects_assertion_drift():
    changed = copy.deepcopy(_adapted)
    assertion = next(node for node in ast.walk(changed) if isinstance(node, ast.Assert))
    assertion.test = ast.Constant(True)
    with pytest.raises(ValueError, match="corpus changed"):
        verify(_original, changed)


@pytest.mark.parametrize("legacy_enabled", [False, True])
def test_production_constructor_once_and_shared_identity(tmp_path, monkeypatch, legacy_enabled):
    calls = []
    constructor = SubsystemGuard.__init__

    def observe(self, *args, **kwargs):
        calls.append((self, args, kwargs))
        constructor(self, *args, **kwargs)

    monkeypatch.setattr(SubsystemGuard, "__init__", observe)
    with temporary_guard_graph(tmp_path, legacy_enabled) as (core, _):
        manager = core.management
        guard = manager.subsystem_guard
        assert type(guard) is SubsystemGuard
        assert len(calls) == 1
        assert calls == [(guard, (), {"degraded_threshold": 7, "unavailable_threshold": 19})]
        assert guard is manager.executor.subsystem_guard
        assert guard is manager.providers.subsystem_guard
        assert guard is manager.runtime.subsystem_guard
        assert manager.runtime.llm_gateway is manager.providers
        assert guard.registered == ["llm_codex", "llm_ollama", "llm_compat", "codex",
                                    "ssh", "knowledge", "browser"]
        assert not hasattr(manager.settings.config.graceful_degradation, "enabled")
        assert manager.settings.config.openai_codex.enabled is False
        assert guard.get_state("llm_codex") is SubsystemState.AVAILABLE


def test_real_composed_guard_default_thresholds(tmp_path):
    with temporary_guard_graph(tmp_path, False, degraded=None, unavailable=None) as (core, _):
        guard = core.management.subsystem_guard
        for _ in range(2):
            guard.record_failure("knowledge", "temporary failure")
        assert guard.get_state("knowledge") is SubsystemState.AVAILABLE
        guard.record_failure("knowledge", "temporary failure")
        assert guard.get_state("knowledge") is SubsystemState.DEGRADED
        for _ in range(7):
            guard.record_failure("knowledge", "temporary failure")
        assert guard.get_state("knowledge") is SubsystemState.UNAVAILABLE


@pytest.mark.parametrize("provider,client_attr", [
    ("codex", "codex_client"), ("ollama", "ollama_client"), ("compat", "compatible_client"),
])
def test_actual_gateway_thresholds_block_and_recover_runtime(tmp_path, provider, client_attr):
    from src.discord.llm_gateway import LLMServingIdentity

    class FailingTransport:
        calls = 0
        fail = True

        async def chat_with_tools(self, **kwargs):
            self.calls += 1
            if self.fail:
                raise RuntimeError("temporary transport failure")
            return "temporary transport response"

    with temporary_guard_graph(tmp_path, False) as (core, runner):
        manager = core.management
        guard = manager.subsystem_guard
        transport = FailingTransport()
        serving = LLMServingIdentity(provider=provider, model="fixture", client=transport,
                                     reasoning_effort=None)
        guard_key = f"llm_{provider}"

        def attempt():
            return runner.run(manager.providers.call_with_tools(
                messages=[], system="fixture", tools=[], serving_identity=serving))

        for index in range(1, 20):
            with pytest.raises(RuntimeError, match="temporary transport failure"):
                attempt()
            expected = (SubsystemState.AVAILABLE if index < 7 else
                        SubsystemState.DEGRADED if index < 19 else SubsystemState.UNAVAILABLE)
            assert guard.get_state(guard_key) is expected
            setattr(manager.providers, client_attr, transport)
            status = {row["name"]: row["health"] for row in manager.runtime.status()["providers"]}
            if index >= 7:
                assert status[provider] == ("degraded" if index < 19 else "unavailable")
            setattr(manager.providers, client_attr, None)
        with pytest.raises(RuntimeError, match="LLM subsystem unavailable"):
            attempt()
        assert transport.calls == 19
        assert manager.providers.inflight_requests == 0
        assert guard.stats.total_blocked == 1
        independent_key = "llm_ollama" if provider != "ollama" else "llm_codex"
        assert guard.get_state(independent_key) is SubsystemState.AVAILABLE
        # Runtime consumes the shared gateway guard for present client health.
        setattr(manager.providers, client_attr, transport)
        status = {row["name"]: row["health"] for row in manager.runtime.status()["providers"]}
        assert status[provider] == "unavailable"
        setattr(manager.providers, client_attr, None)
        guard.record_success(guard_key)
        assert guard.get_state(guard_key) is SubsystemState.AVAILABLE
        for _ in range(7):
            guard.record_failure(guard_key, "temporary failure")
        assert guard.get_state(guard_key) is SubsystemState.DEGRADED
        transport.fail = False
        assert attempt() == "temporary transport response"
        assert transport.calls == 20
        assert guard.get_state(guard_key) is SubsystemState.AVAILABLE
        assert guard.get_subsystem(guard_key).consecutive_failures == 0
