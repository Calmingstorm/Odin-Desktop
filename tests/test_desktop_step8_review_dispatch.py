"""Reviewed inherited dispatcher executions and authentic identity proofs."""
import asyncio

import pytest

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from src.config.schema import ToolsConfig
from src.tools.executor import _user_id_ctx
from tests.desktop_adapters import step8_review_dispatch as adapter
from tests.desktop_adapters import step8_review_helpers as helpers

LOADED = adapter.load(globals())


@pytest.fixture(autouse=True)
async def authentic_owner(request, tmp_path):
    if request.node.name.startswith("test_adapter_"):
        yield
        return
    async with helpers.owner_fixture(tmp_path):
        yield


def test_adapter_frozen_assertions_unchanged():
    original, adapted = LOADED
    assert corpus(original) == corpus(adapted)
    assert dump(adapter.load({"__name__": "dispatch_audit"})[1]) == dump(adapted)
    assert frozen_source(adapter.SOURCE_PATH)


async def test_adapter_actual_memory_owner_kwarg(tmp_path):
    async with helpers.owner_fixture(tmp_path) as state:
        executor = helpers.desktop_executor(config=ToolsConfig())
        seen = []

        async def handler(_input, *, user_id=None):
            seen.append(user_id)
            return "ok"

        executor._handle_memory_manage = handler
        result = await executor.execute("memory_manage", {"action": "list"},
                                        user_id=state.authority.owner_id)
        assert result.ok is True
        assert seen == [state.authority.owner_id]
        denied = await executor.execute("memory_manage", {"action": "list"}, user_id="u-42")
        assert denied.ok is False and denied.error == "permission_denied"
        assert seen == [state.authority.owner_id]


async def test_adapter_two_profiles_shared_contextvar_not_shared_executor(tmp_path):
    async with adapter.two_profiles(tmp_path, ToolsConfig()) as facade:
        first, second = facade.routes
        assert first.owner_id != second.owner_id
        assert first.executor is not second.executor
        before = _user_id_ctx.get()
        both_started = asyncio.Event()
        observations = []

        async def report_identity(_input):
            uid = _user_id_ctx.get()
            observations.append((uid, asyncio.current_task().get_name(),
                                 first.state.manager.is_owner(uid),
                                 second.state.manager.is_owner(uid)))
            if len(observations) == 2:
                both_started.set()
            await both_started.wait()
            assert _user_id_ctx.get() == uid
            return f"uid={_user_id_ctx.get()}"

        facade.install_handler_fixture("run_command", report_identity)
        facade.install_handler_fixture("run_script", report_identity)
        res_a, res_b = await asyncio.wait_for(asyncio.gather(
            facade.execute("run_command", {"command": "x"}, user_id=first.owner_id),
            facade.execute("run_script", {"script": "y"}, user_id=second.owner_id),
        ), timeout=10)
        assert res_a.ok is True and res_b.ok is True
        assert res_a.output.strip() == f"uid={first.owner_id}"
        assert res_b.output.strip() == f"uid={second.owner_id}"
        assert _user_id_ctx.get() == before
        assert sorted((uid, a, b) for uid, _task, a, b in observations) == sorted([
            (first.owner_id, True, False), (second.owner_id, False, True)])
        assert all(task.startswith("desktop-request:") for _uid, task, _a, _b in observations)
        assert len({task for _uid, task, _a, _b in observations}) == 2
        for foreign in ("alice", "bob"):
            denied = await facade.execute("run_command", {"command": "x"}, user_id=foreign)
            assert denied.ok is False and denied.error == "permission_denied"
        assert len(observations) == 2
        for route in facade.routes:
            rows = route.state.admissions[0].journal.connection.execute(
                "SELECT owner,state FROM desktop_requests").fetchall()
            assert rows
            assert all(row[0] == route.owner_id and row[1] == "completed" for row in rows)


async def test_adapter_shared_executor_rejects_second_profile(tmp_path):
    async with adapter.two_profiles(tmp_path, ToolsConfig()) as facade:
        first, second = facade.routes
        called = []

        async def handler(_input):
            called.append(True)
            return "not admissible"

        first.executor._handle_run_command = handler
        denied = await first.execute("run_command", {"command": "x"}, user_id=second.owner_id)
        assert denied.ok is False and denied.error == "permission_denied"
        assert called == []
