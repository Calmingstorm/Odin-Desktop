"""Batch D whole-suite frozen exports. Run only behind the sanitized PID runner."""
import asyncio
from types import SimpleNamespace

import pytest

from scripts.maintenance.fixture_corpus import ROOT, corpus
from scripts.maintenance.phase2_suites import _full_adapter
from src.desktop.protocol import encode_frame, read_frame
from src.knowledge.store import KnowledgeStore
from src.tools.workspace import WorkspaceError
from tests.desktop_adapters import step8_runtime_d as adapter
from tests.desktop_adapters.step8_runtime_d import load, runtime_owner


@pytest.fixture(autouse=True)
def _temporary_runtime_d_owner(tmp_path):
    with runtime_owner(tmp_path):
        yield


_frozen = load(globals())


@pytest.mark.parametrize("stem", tuple(_frozen))
def test_runtime_d_exact_inherited_corpus(stem):
    original, adapted, module = _frozen[stem]
    assert corpus(original) == corpus(adapted)
    assert all(hasattr(module, name) for name, _, _ in corpus(original)["cases"])


async def test_runtime_d_command_rechecks_actual_owner_and_records_result(tmp_path):
    store = KnowledgeStore(tmp_path / "control-knowledge.db")
    await store.ingest("control document", "document")
    async with adapter.KnowledgeCommandClient(store) as client:
        response = await client.post("/api/knowledge/document/reingest")
        assert response.status == 200
        assert await response.json() == response.frame["result"]
        row = client.core.store.connection.execute(
            "SELECT state FROM command_receipts WHERE command_id=?",
            (client.last_command_id,)).fetchone()
        assert row["state"] == "final"
        with pytest.raises(PermissionError):
            await client.core.dispatch(SimpleNamespace(owner_context=None), {
                "id": "snapshot-2", "method": "knowledge.reingest",
                "params": {"source": "document"}})
        assert client.core.store.connection.execute(
            "SELECT COUNT(*) FROM command_receipts").fetchone()[0] == 1
        reader, writer = await asyncio.open_unix_connection(client.core.socket_path)
        try:
            writer.write(encode_frame({
                "t": "hello", "protocol": {"major": 0, "minor": 3},
                "client": {"name": "refusal-fixture", "version": "0"},
                "profile_id": client.core.paths.profile_id,
                "token": "f" * 64, "features": [],
            }))
            await writer.drain()
            assert await asyncio.wait_for(read_frame(reader), 5) == {
                "t": "bye", "reason": "unauthorized"}
            assert client.core.store.connection.execute(
                "SELECT COUNT(*) FROM command_receipts").fetchone()[0] == 1
        finally:
            writer.close()
            await writer.wait_closed()
    store.close()


def test_runtime_d_executor_readiness_and_workspace_fail_closed(tmp_path):
    ex = adapter.executor(tmp_path)
    assert ex._builtin_policy.is_available("manage_process")
    assert not ex._builtin_policy.is_available("run_command")
    state = adapter._owner.get()
    assert str(state.paths.data_dir) in ex._protected_roots()
    ex.config.local_working_dir = str(state.paths.data_dir)
    with pytest.raises(WorkspaceError):
        ex._ensure_local_workspace()
    assert not ex._builtin_policy.is_available("manage_process")
    token = state.manager.set_request_owner(None)
    try:
        with pytest.raises(PermissionError):
            adapter.executor(tmp_path)
    finally:
        state.manager.reset_request_owner(token)


def test_runtime_d_projection_rejects_unmapped_domain_codes():
    with pytest.raises(KeyError):
        adapter.CommandResponse({"ok": False, "error": {
            "code": "unsupported", "message": "must not invent a status"}})


def test_runtime_d_provenance_and_setup_drift_rejected(monkeypatch):
    stem = "test_knowledge_snapshot_campaign"
    with monkeypatch.context() as patch:
        patch.setitem(adapter.SUITES, stem, "0" * 64)
        with pytest.raises(ValueError, match="frozen source changed"):
            adapter.transform(stem)
    rules = list(adapter.SETUP_HUNKS[stem])
    line, kind, _, source = rules[0]
    rules[0] = (line, kind, "0" * 64, source)
    monkeypatch.setitem(adapter.SETUP_HUNKS, stem, rules)
    with pytest.raises(ValueError, match="exactly once"):
        adapter.transform(stem)


@pytest.mark.parametrize("stem", tuple(_frozen))
def test_runtime_d_static_whole_suite_association(stem):
    assert _full_adapter(ROOT, "tests/test_desktop_phase2_runtime_d.py",
                         f"tests/{stem}.py", adapter.SUITES[stem])
