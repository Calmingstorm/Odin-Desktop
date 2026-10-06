"""Complete frozen runtime/health core corpora with audited dispositions."""
import pytest

from tests.desktop_adapters.lane6_health_core import load


@pytest.fixture(autouse=True)
async def lane6_health_core_graph(tmp_path):
    from tests.desktop_adapters.lane6_health_learning import GRAPH, make_graph

    graph = make_graph(tmp_path)
    binding = GRAPH.set(graph)
    try:
        yield graph
    finally:
        await graph.requests.close()
        if getattr(graph, "expected_cleanup_error", False):
            with pytest.raises(RuntimeError):
                await graph.engine.close()
            assert graph.engine.cleanup_outcome["state"] == "unknown"
        else:
            await graph.engine.close()
        graph.store.close()
        graph.permissions.reset_request_owner(graph.owner_token)
        graph.authority.release_runtime()
        GRAPH.reset(binding)

load(globals())


def test_lane6_health_core_complete_disposition_partition():
    import ast

    from scripts.maintenance.fixture_corpus import corpus, frozen_source
    from tests.desktop_adapters import lane6_health_core as adapter

    for stem in adapter.SUITES:
        path = f"tests/{stem}.py"
        cases = {f"{path}::" + name.replace(".", "::")
                 for name, _, _ in corpus(ast.parse(frozen_source(path)))["cases"]}
        assert cases == {case for case in adapter.DISPOSITIONS if case.startswith(path + "::")}
        assert cases == {case for case in adapter.CASE_MAP if case.startswith(path + "::")}
        for case in cases:
            disposition = adapter.DISPOSITIONS[case]
            assert disposition["status"] in {"restored", "retired", "deferred", "proposed"}
            assert len(disposition["case_sha256"]) == 64
            assert disposition["reason"]
            target = adapter.CASE_MAP[case].split("::")
            if len(target) == 2:
                exported = target[0] in globals() and hasattr(globals()[target[0]], target[1])
            else:
                exported = target[0] in globals()
            assert exported == (disposition["status"] == "restored")


async def test_lane6_health_engine_optional_shutdown_owners(lane6_health_core_graph):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    graph = lane6_health_core_graph
    usage = SimpleNamespace(stop=AsyncMock())
    quota = SimpleNamespace(close=AsyncMock())
    backend = SimpleNamespace(close=AsyncMock())
    graph.engine.deps.runtime_context.usage_rollup = usage
    graph.engine.deps.runtime_context.codex_quota_check = quota
    graph.engine.deps.native_tools.owners["media"].image_selector = SimpleNamespace(openai=backend)
    await graph.requests.close()
    await graph.engine.close()
    usage.stop.assert_awaited_once()
    quota.close.assert_awaited_once()
    backend.close.assert_awaited_once()
    assert graph.engine.cleanup_outcome == {"state": "released"}


async def test_lane6_health_engine_optional_cleanup_failure_truthful(lane6_health_core_graph):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    graph = lane6_health_core_graph
    graph.engine.deps.runtime_context.usage_rollup = SimpleNamespace(
        stop=AsyncMock(side_effect=RuntimeError("fixture telemetry close failed")))
    await graph.requests.close()
    with pytest.raises(RuntimeError, match="cleanup did not fully complete"):
        await graph.engine.close()
    assert graph.engine.cleanup_outcome["state"] == "unknown"
    # This expected error is sticky on the real engine owner. Fixture teardown
    # must inspect it, not repeat effects or replace the production owner.
    graph.expected_cleanup_error = True
