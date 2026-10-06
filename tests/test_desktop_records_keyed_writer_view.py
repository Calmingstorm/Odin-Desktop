"""Keyed audit reads of the active writer keep its fence and live durability."""
import asyncio
from types import SimpleNamespace

import pytest

from src.audit.logger import AuditLogger
from src.audit.signer import verify_segment
from src.desktop.records import RecordsService


def composed(tmp_path):
    path = tmp_path / "audit.jsonl"
    writer = AuditLogger(str(path), hmac_key="")
    service = RecordsService(SimpleNamespace(data_dir=tmp_path),
                             get_audit_path=lambda: path, audit_getter=lambda: writer)
    return path, writer, service


async def test_keyed_view_snapshot_waits_for_the_writers_append(tmp_path):
    path, writer, service = composed(tmp_path)
    view = service._bind_audit("profile-key")
    assert view is not writer
    assert view._persist_lock is writer._persist_lock
    async with writer._persist_lock:
        path.write_bytes(b'{"timestamp":')
        pending = asyncio.ensure_future(view._open_verify_snapshot())
        await asyncio.sleep(0.05)
        assert not pending.done(), "a verification snapshot must not cut into an append"
        path.write_bytes(b'{"timestamp":"settled"}\n')
    rows = await asyncio.wait_for(pending, timeout=5)
    try:
        assert rows[0]["size"] == len(b'{"timestamp":"settled"}\n')
        assert verify_segment(rows[0]["handle"], rows[0]["size"], b"profile-key")["reason"] != "invalid_json"
    finally:
        for row in rows:
            if row["handle"] is not None:
                row["handle"].close()


async def test_keyed_view_reports_the_writers_current_durability(tmp_path):
    path, writer, service = composed(tmp_path)
    path.write_text('{"timestamp":"settled"}\n')
    marker = path.with_name(path.name + ".repair-required")
    marker.write_text("successful append temporarily pending")
    view = service._bind_audit("profile-key")
    marker.unlink()
    assert service._bind_audit("profile-key") is view
    assert (await view.verify_integrity())["durability"] != "repair_required"
    writer._quarantine_uncertain_append()
    assert service._bind_audit("profile-key") is view
    assert (await view.verify_integrity())["durability"] == "repair_required"


async def test_matching_key_still_reads_through_the_writer(tmp_path):
    path, writer, service = composed(tmp_path)
    assert service._bind_audit("") is writer
    relocated = tmp_path / "elsewhere.jsonl"
    other = RecordsService(SimpleNamespace(data_dir=tmp_path),
                           get_audit_path=lambda: relocated, audit_getter=lambda: writer)
    reader = other._bind_audit("profile-key")
    assert reader is not writer and reader._persist_lock is not writer._persist_lock


def test_keyed_view_cannot_write(tmp_path):
    path, writer, service = composed(tmp_path)
    view = service._bind_audit("profile-key")
    with pytest.raises(AttributeError):
        view.repair_required = False
