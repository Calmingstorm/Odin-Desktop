"""Odin 4.19.1's output-store eviction, where Desktop's frozen corpus can't carry it.

A full store now expires its oldest snapshots early instead of refusing new
ones (Odin PR #669). Three upstream cases pinned the old refusal; they are
deselected in maintenance/qualification-plan.json and their 4.19.1 versions run
here. Odin's two runtime-delivery hold cases also run here, bound to Desktop's
owner authority: Desktop delivers only for a real, available tool and an
authenticated owner, so Odin's fixture tool name can't be delivered.
"""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.tools.apply_patch import PatchError, apply_plan, parse_patch
from src.tools.media_result import BinaryAttachment
from src.tools.output_delivery import deliver
from src.tools.output_retention import OutputStore, RetentionError
from src.tools.result_validator import ToolResult
from src.tools.runtime_delivery import deliver_runtime_result, execution_delivery_scope
from tests.desktop_adapters.tools_cases import ToolExecutor, owner_fixture, owner_id


def store_at(tmp_path, **kwargs):
    return OutputStore(tmp_path / "evidence.sqlite3", **kwargs)


def retain(store, text):
    return store.retain(text, owner="alice", channel="room", tool="example_tool")


def read(store, cursor):
    return store.read(cursor, owner="alice", channel="room", authorize=lambda *_: True)


def attachment(index, data):
    return BinaryAttachment(index, "resource", "application/octet-stream", data)


# --- 4.19.1 versions of the three superseded upstream cases -------------------------------


def test_quota_failure_never_promises_missing_cursor(tmp_path):
    """tests/test_output_delivery_retention.py's case at Odin v4.19.1."""
    store = store_at(tmp_path, per_result_bytes=30000, global_bytes=25000)
    first = retain(store, "a"*16000)
    # 26,000 bytes can never fit in 25,000, so nothing is evicted to try.
    failed = json.loads(deliver("b"*26000, store=store, owner="alice", channel="room"))
    assert failed["retention"] == "failed" and failed["cursor"] is None
    assert read(store, f"{first.result_id}:0")[0] == first
    with pytest.raises(RetentionError, match="Per-result"):
        retain(store, "é"*15001)


def test_concurrent_quota_admission_is_atomic(tmp_path):
    """tests/test_output_delivery_retention.py's case at Odin v4.19.1."""
    store = store_at(tmp_path, per_result_bytes=100, global_bytes=100)
    with ThreadPoolExecutor(max_workers=4) as pool:
        admitted = list(pool.map(lambda _: retain(store, "x"*60), range(4)))
    # Each admission made room by expiring the one before it early: all four
    # were admitted, and the store ends within its quota, never over it.
    assert len({snapshot.result_id for snapshot in admitted}) == 4
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT count(*), SUM(size) FROM outputs").fetchone() == (1, 60)


def test_binary_bundle_quota_is_atomic_shared_and_charges_empty_metadata(tmp_path):
    """tests/test_mcp_media_retention_checkpoint.py's case at Odin v4.19.1."""
    store = store_at(tmp_path, global_bytes=2500)
    store.retain_binary_bundle([attachment(1, b"")], owner="reader", channel="channel",
                               tool="mcp_fixture_blob")
    with sqlite3.connect(store.path) as db:
        manifest_size = db.execute("SELECT size FROM outputs").fetchone()[0]
        blob_charge = db.execute("SELECT size FROM output_blobs").fetchone()[0]
        assert blob_charge == 512
        used = manifest_size + blob_charge
    # Text and opaque blobs share one quota. Fill its remaining space exactly.
    store.retain("x" * (store.global_bytes - used), owner="reader", channel="channel",
                 tool="ordinary_text")
    # A new two-file bundle makes room by expiring whole older cohorts early:
    # the first bundle together with its blob, then the text.
    newest = store.retain_binary_bundle(
        [attachment(2, b""), attachment(3, b"")], owner="reader", channel="channel",
        tool="mcp_fixture_blob")
    with sqlite3.connect(store.path) as db:
        # No orphan blob and no manifest without its blobs.
        assert db.execute("SELECT id FROM outputs").fetchall() == [(newest.result_id,)]
        assert db.execute("SELECT count(*) FROM output_blobs").fetchone()[0] == 2
        assert db.execute(
            "SELECT (SELECT SUM(size) FROM outputs) + (SELECT SUM(size) FROM output_blobs)"
        ).fetchone()[0] <= store.global_bytes
    # Five files' metadata alone exceeds the whole quota: refused atomically,
    # evicting nothing.
    with pytest.raises(RetentionError, match="Global retention quota"):
        store.retain_binary_bundle(
            [attachment(index, b"") for index in range(4, 9)], owner="reader",
            channel="channel", tool="mcp_fixture_blob")
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT count(*) FROM output_blobs").fetchone()[0] == 2
        assert db.execute("SELECT id FROM outputs").fetchall() == [(newest.result_id,)]


# --- Odin's two runtime-delivery hold cases, through Desktop's owner authority -------------


def constrained(tmp_path):
    executor = ToolExecutor()
    executor._output_store = OutputStore(tmp_path / "held.sqlite3", global_bytes=20_000)
    return executor


def delivered_pointer(executor, result):
    with execution_delivery_scope(owner_id(), "conversation"):
        delivered = deliver_runtime_result(executor, result, tool_name="fetch_url",
                                           tool_input={}, user_id=owner_id(),
                                           channel_id="conversation")
    rendered = str(delivered.output)
    return rendered, json.loads(rendered.split("[output retention] ", 1)[1])


def assert_pointer_readable(executor, pointer):
    assert pointer["retention"] == "retained"
    manifest, _ = executor._ensure_output_store().read(
        pointer["retrieval"]["arguments"]["cursor"], owner=owner_id(), channel="conversation",
        authorize=lambda *_: True)
    assert json.loads(manifest.text)["attachments"][0]["total_bytes"] == 6000


def file_result(text):
    return ToolResult(text, ok=True,
                      attachments=(BinaryAttachment(1, "resource", "text/plain", b"b" * 6000),))


def test_delivery_never_evicts_its_own_bundle_for_its_text(tmp_path):
    with owner_fixture(tmp_path / "owner"):
        executor = constrained(tmp_path)
        # The bundle and the text each fit alone, but not together.
        rendered, pointer = delivered_pointer(executor, file_result("x" * 15_000))
        assert_pointer_readable(executor, pointer)
        head = json.loads(rendered.split("\n[output retention] ", 1)[0])
        assert head["retention"] == "failed" and head["cursor"] is None
        assert executor._ensure_output_store()._holds == {}


def test_delivery_holds_its_bundle_against_an_interleaved_writer(tmp_path, monkeypatch):
    with owner_fixture(tmp_path / "owner"):
        executor = constrained(tmp_path)
        store = executor._ensure_output_store()
        original = type(executor).deliver_output

        def interleaved(self, text, **kwargs):
            # Another writer needs nearly the whole quota between the bundle's
            # admission and this result's text: only the held bundle could
            # make room, so that writer is refused and the pointer stays good.
            with pytest.raises(RetentionError, match="Global retention quota exhausted"):
                store.retain("w" * 15_000, owner="other", channel="elsewhere",
                             tool="fetch_url")
            return original(self, text, **kwargs)

        monkeypatch.setattr(type(executor), "deliver_output", interleaved)
        _, pointer = delivered_pointer(executor, file_result("short"))
        assert_pointer_readable(executor, pointer)
        assert store._holds == {}


# --- Odin 4.19.1 branches the carried cases don't reach ------------------------------------


def test_a_snapshot_held_twice_stays_held_until_both_holds_close(tmp_path):
    store = store_at(tmp_path, per_result_bytes=100, global_bytes=100)
    with store.hold() as outer:
        held = store.retain("a"*60, owner="alice", channel="room", tool="example_tool",
                            hold=outer)
        with store.hold() as inner:
            store._hold(inner, held.result_id)
        # One hold closed; the other still keeps the snapshot from eviction.
        with pytest.raises(RetentionError, match="Global retention quota exhausted"):
            retain(store, "b"*60)
    retain(store, "b"*60)
    with pytest.raises(RetentionError, match="expired or unavailable"):
        read(store, f"{held.result_id}:0")


def ambiguity(tmp_path, source, body):
    (tmp_path / "target.txt").write_text(source)
    with pytest.raises(PatchError, match="context is ambiguous") as caught:
        apply_plan(str(tmp_path), parse_patch(f"*** Begin Patch\n{body}\n*** End Patch\n"))
    return str(caught.value)


def test_an_all_blank_context_gets_locations_without_hints(tmp_path):
    message = ambiguity(tmp_path, "a\n\nb\n\nc\n",
                        "*** Update File: target.txt\n@@\n-\n+x")
    assert "the context matches at line 2 and line 4; add more" in message


def test_an_indented_match_with_nothing_less_indented_above_has_no_hint(tmp_path):
    message = ambiguity(tmp_path, "    x = 1\n    x = 1\n",
                        "*** Update File: target.txt\n@@\n-    x = 1\n+    x = 2")
    assert "the context matches at line 1 and line 2; add more" in message
