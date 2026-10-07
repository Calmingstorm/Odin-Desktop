"""A failed index-list read still scans archives without claiming them indexed."""
from unittest.mock import AsyncMock, Mock

import pytest

from src.search.vectorstore import SessionVectorStore
from src.tools.output_retention import OutputStore, RetentionError


@pytest.mark.asyncio
async def test_backfill_index_read_failure_keeps_repair_path(tmp_path):
    store = SessionVectorStore.__new__(SessionVectorStore)
    store._conn = object()
    store._fts = None
    store._get_indexed_ids_sync = Mock(side_effect=RuntimeError("fixture read failure"))
    store.index_session = AsyncMock(side_effect=[True, False])
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    first.write_text("{}")
    second.write_text("{}")
    embedder = object()
    assert await store.backfill(tmp_path, embedder) == 1
    assert store.index_session.await_args_list[0].args == (first, embedder)
    assert store.index_session.await_args_list[1].args == (second, embedder)
    store._get_indexed_ids_sync.assert_called_once_with()


def test_retention_transaction_rechecks_quota_after_preflight(tmp_path, monkeypatch):
    store = OutputStore(tmp_path / "outputs.sqlite3", global_bytes=10)
    measurements = iter([0, 10])
    monkeypatch.setattr(store, "_used", lambda _db, _now: next(measurements))
    with pytest.raises(RetentionError, match="Global retention quota exhausted"):
        store.retain("fixture", owner="owner", channel="channel", tool="fixture")
    with store._db() as db:
        assert db.execute("SELECT COUNT(*) FROM outputs").fetchone()[0] == 0
