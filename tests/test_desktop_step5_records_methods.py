"""Real named Records reads over authentic disposable filesystem resources."""
import json
import threading
import tracemalloc
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.audit.logger import AuditLogger
from src.desktop import records
from src.desktop.management import MethodError


def service(tmp_path, *, writer=None):
    return records.RecordsService(SimpleNamespace(data_dir=tmp_path), audit=writer)


async def test_diff_filters_limits_fallback_and_untruncated_payload(tmp_path):
    writer = AuditLogger(str(tmp_path / "audit.jsonl"))
    await writer.log_execution(user_id="u", user_name="Alice", channel_id="c",
                               tool_name="apply_patch", tool_input={}, approved=True,
                               result_summary="done", execution_time_ms=1,
                               diff="星" * 5000 + "\n")
    reader = service(tmp_path, writer=writer)
    result = await reader.handle("audit.diffs", {"tool": "apply_patch", "user": "Alice",
                                               "date": datetime.now(UTC).date().isoformat(),
                                               "limit": "bad"})
    assert result["count"] == 1
    assert result["entries"][0]["diff"] == "星" * 5000 + "\n"
    assert (await reader.handle("audit.diffs", {"tool": "missing"}))["count"] == 0
    assert records._limit({"limit": 1000}, 20, 100) == 100
    assert records._limit({"limit": 0}, 20, 100) == 1


async def test_stats_and_failures_read_rotations_and_close_handles(tmp_path, monkeypatch):
    writer = AuditLogger(str(tmp_path / "audit.jsonl"))
    writer.path.with_name("audit.jsonl.1").write_text(json.dumps({
        "timestamp": datetime.now(UTC).isoformat(), "tool_name": "retained",
        "failure": {"class": "timeout"}, "error": "timeout",
    }) + "\n", encoding="utf-8")
    opened = []
    original = writer.open_read_snapshot
    async def capture():
        snapshot = await original()
        opened.extend(handle for handle, _stat in snapshot)
        return snapshot
    monkeypatch.setattr(writer, "open_read_snapshot", capture)
    reader = service(tmp_path, writer=writer)
    stats = await reader.handle("logs.stats", {})
    assert stats["total"] == 1 and stats["tools"] == ["retained"]
    failures = await reader.handle("audit.failures", {"window": "bad"})
    assert failures["classified"] == 1
    assert failures["coverage"]["generations"] == 1
    assert opened and all(handle.closed for handle in opened)


async def test_failure_aggregate_exception_closes_real_snapshot(tmp_path, monkeypatch):
    from src.observability import aggregates

    writer = AuditLogger(str(tmp_path / "audit.jsonl"))
    writer.path.write_text('{}\n')
    opened = []
    original = writer.open_read_snapshot
    async def capture():
        snapshot = await original()
        opened.extend(handle for handle, _stat in snapshot)
        return snapshot
    def failure(*args, **kwargs):
        raise RuntimeError("aggregate read failed")
    monkeypatch.setattr(writer, "open_read_snapshot", capture)
    monkeypatch.setattr(aggregates, "failure_aggregates", failure)
    with pytest.raises(MethodError, match="unavailable"):
        await service(tmp_path, writer=writer).handle("audit.failures", {})
    assert opened and all(handle.closed for handle in opened)


@pytest.mark.parametrize("method", ["audit.tail", "logs.tail"])
async def test_named_tail_follow_utf8_newline_rotation_and_page_bounds(tmp_path, method):
    path = tmp_path / "audit.jsonl"
    path.write_bytes(b"first\r\n\npartial \xe6")
    reader = service(tmp_path)
    page = await reader.handle(method, {})
    assert page["lines"] == ["first", ""]
    with path.open("ab") as handle:
        handle.write(b"\x98\x9f\n" + b"".join(f"row-{n}\n".encode() for n in range(80)))
    following = await reader.handle(method, {"cursor": page["cursor"]})
    assert following["lines"] == ["partial 星"] + [f"row-{n}" for n in range(49)]
    final = await reader.handle(method, {"cursor": following["cursor"]})
    assert final["lines"] == [f"row-{n}" for n in range(49, 80)]
    other = tmp_path / "replacement"
    other.write_text("new 星\n", encoding="utf-8")
    other.replace(path)
    assert (await reader.handle(method, {"cursor": final["cursor"]}))["lines"] == ["new 星"]


async def test_tail_missing_is_read_only_and_cursors_are_source_bound(tmp_path):
    reader = service(tmp_path)
    page = await reader.handle("audit.tail", {})
    assert page["availability"] == "missing" and page["lines"] == []
    assert not (tmp_path / "audit.jsonl").exists()
    with pytest.raises(MethodError, match="another source"):
        await reader.handle("logs.tail", {"cursor": page["cursor"]})
    with pytest.raises(MethodError, match="Unknown"):
        await reader.handle("audit.tail", {"cursor": "/arbitrary/path"})
    (tmp_path / "audit.jsonl").write_text("created\n")
    assert (await reader.handle("audit.tail", {"cursor": page["cursor"]}))["lines"] == ["created"]


async def test_tail_worker_thread_and_valid_record_is_not_text_capped(tmp_path, monkeypatch):
    (tmp_path / "audit.jsonl").write_text("星" * 5000 + "\n", encoding="utf-8")
    loop_thread = threading.get_ident()
    seen = []
    original = records._read_log_tail
    def measured(path):
        seen.append(threading.get_ident())
        return original(path)
    monkeypatch.setattr(records, "_read_log_tail", measured)
    page = await service(tmp_path).handle("logs.tail", {})
    assert page["lines"] == ["星" * 5000]
    assert seen and all(thread != loop_thread for thread in seen)


async def test_tail_explicit_lines_bound_and_reset_metadata(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text("".join(f"row-{n}\n" for n in range(240)))
    reader = service(tmp_path)
    page = await reader.handle("audit.tail", {"lines": 1000})
    assert len(page["lines"]) == 200 and page["lines"][0] == "row-40"
    assert page["page_limit"] == 200 and page["page_full"] and not page["reset"]
    other = tmp_path / "other"
    other.write_text("rotation\n")
    other.replace(path)
    reset = await reader.handle("audit.tail", {"lines": 200, "cursor": page["cursor"]})
    assert reset["reset"] and reset["lines"] == ["rotation"]
    assert not reset["page_full"]
    assert (await reader.handle("audit.tail", {"lines": "invalid"}))["page_limit"] == 50


async def test_tail_readers_close_after_invalid_utf8(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_bytes(b"\xff\n")
    with pytest.raises(MethodError, match="unavailable"):
        await service(tmp_path).handle("audit.tail", {})
    path.write_bytes(b"valid\n")
    assert (await service(tmp_path).handle("audit.tail", {}))["lines"] == ["valid"]


def test_all_records_methods_are_read_only():
    assert records.METHODS == records.READ_METHODS
    assert {
        "audit.diffs", "audit.failures", "audit.tail", "logs.stats", "logs.tail"
    } <= records.METHODS


def test_frozen_adapters_meet_full_export_qualification_contract():
    from scripts.maintenance.fixture_corpus import ROOT
    from scripts.maintenance.phase2_suites import _full_adapter
    from tests.desktop_adapters.step5_records import SUITES

    for suite, digest in SUITES.items():
        assert _full_adapter(ROOT, "tests/test_desktop_step5_records_corpus.py",
                             f"tests/{suite}.py", digest)


def test_follow_incomplete_large_append_is_memory_bounded(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_bytes(b"initial\n")
    _lines, cursor, identity = records._read_log_tail(path)
    with path.open("ab") as handle:
        for _ in range(128):
            handle.write(b"x" * 65536)
    tracemalloc.start()
    try:
        lines, after, _identity = records._read_log_updates(path, cursor, identity)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert lines == [] and after == cursor
    assert peak < 16 * records._LOG_READ_BLOCK
