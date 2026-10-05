import base64
import hashlib
import json

import pytest

from src.desktop.artifacts import ArtifactStore, ResultReadError
from src.desktop.commands import JournalStorageError, JournalStore
from src.tools.media_result import BinaryAttachment
from src.tools.output_retention import OutputStore


@pytest.fixture
def stores(tmp_path):
    clock = [1000.0]
    enabled = [True]
    checks = []

    def authorize(tool, hosts, owner):
        checks.append((tool, hosts, owner))
        return enabled[0]

    journal = JournalStore(tmp_path / "journal.sqlite3", "profile")
    evidence = OutputStore(tmp_path / "evidence.sqlite3", clock=lambda: clock[0])
    artifacts = ArtifactStore(journal, output_store=evidence, authorize=authorize,
                              chunk_bytes=4, clock=lambda: clock[0])
    yield journal, evidence, artifacts, clock, enabled, checks
    journal.close()


def publish(artifacts, data=b"\xff\x00\xf0token=unchanged"):
    return artifacts.publish(data, owner="owner", conversation_id="conversation",
                             request_id="request", name="result.bin",
                             mime="application/octet-stream",
                             tool="generate_file")


def test_binary_bytes_offsets_and_bounds(stores):
    journal, _, artifacts, _, _, _ = stores
    data = b"\xff\x00\xf0token=unchanged"
    artifact = publish(artifacts, data)
    pieces = []
    for offset in range(0, len(data), 4):
        page = artifacts.read(artifact["ref"], offset, 4, owner="owner")
        pieces.append(base64.b64decode(page["data_b64"]))
        assert page["eof"] == (offset + 4 >= len(data))
    assert b"".join(pieces) == data
    digest = journal.connection.execute("SELECT sha256 FROM desktop_artifacts").fetchone()[0]
    assert digest == hashlib.sha256(data).hexdigest()
    for offset, length in [(-1, 4), (True, 4), (0, 5), (100, 1), (0, False)]:
        with pytest.raises(ResultReadError) as exc:
            artifacts.read(artifact["ref"], offset, length, owner="owner")
        assert exc.value.code == "bad_request"
    assert artifacts.read(artifact["ref"], len(data), 4, owner="owner")["eof"]


def test_posted_file_keeps_owner_and_conversation_binding_not_live_scope(stores):
    _, _, artifacts, _, enabled, checks = stores
    artifact = publish(artifacts)
    for owner, conversation in [("another", None), ("owner", "another")]:
        with pytest.raises(ResultReadError) as exc:
            artifacts.read(artifact["ref"], 0, 4, owner=owner, conversation_id=conversation)
        assert exc.value.code == "not_found"
    artifacts.read(artifact["ref"], 0, 4, owner="owner")
    enabled[0] = False
    page = artifacts.read(artifact["ref"], 4, 4, owner="owner")
    assert base64.b64decode(page["data_b64"]) == b"oken"
    # Publication is authorized once; reading delivered bytes does not recheck.
    assert len(checks) == 1
    with pytest.raises(ResultReadError) as exc:
        publish(artifacts)
    assert exc.value.code == "unauthorized"


def test_artifact_lifetime_not_evidence_ttl_or_quota(stores):
    _, evidence, artifacts, clock, _, _ = stores
    evidence.global_bytes = 1
    artifact = publish(artifacts)
    clock[0] += 86401
    page = artifacts.read(artifact["ref"], 0, 4, owner="owner")
    assert base64.b64decode(page["data_b64"]) == b"\xff\x00\xf0t"
    artifacts.delete_conversation("conversation")
    with pytest.raises(ResultReadError) as exc:
        artifacts.read(artifact["ref"], 0, 4, owner="owner")
    assert exc.value.code == "not_found"


def test_retained_binary_not_copied_or_refreshed(stores):
    journal, evidence, artifacts, clock, _, _ = stores
    manifest = evidence.retain_binary_bundle(
        [BinaryAttachment(data=b"\xff\x00abc", media_type="application/octet-stream",
                          content_index=0, kind="file")],
        owner="owner", channel="conversation", tool="browser_screenshot")
    cursor = json.loads(manifest.text)["attachments"][0]["retrieval"]["arguments"]["cursor"]
    blob, _ = evidence.read(cursor, owner="owner", channel="conversation",
                            authorize=lambda *_: True)
    binding = dict(owner="owner", conversation_id="conversation", request_id="request")
    ref = artifacts.register_retained(blob, **binding)
    assert artifacts.register_retained(blob, **binding) == ref
    row = journal.connection.execute("SELECT data,expires_at FROM desktop_artifacts").fetchone()
    assert row[0] is None and row[1] == 87400
    page = artifacts.read(ref["ref"], 1, 4, owner="owner")
    assert base64.b64decode(page["data_b64"]) == b"\x00abc"
    clock[0] = 87400
    with pytest.raises(ResultReadError) as exc:
        artifacts.read(ref["ref"], 0, 4, owner="owner")
    assert exc.value.code == "not_found"


def test_same_transaction_rollback_and_stored_report(stores):
    journal, _, artifacts, _, enabled, _ = stores
    with pytest.raises(RuntimeError):
        with journal.transaction():
            publish(artifacts)
            raise RuntimeError("harmless rollback")
    assert journal.connection.execute("SELECT COUNT(*) FROM desktop_artifacts").fetchone()[0] == 0
    report = artifacts.publish_report(["password=hidden", "second page"], owner="owner",
                                     conversation_id="conversation", request_id="request",
                                     tool="check")
    assert "hidden" not in artifacts.page(report["report_id"], 1, owner="owner")["text"]
    assert artifacts.page(report["report_id"], 2, owner="owner") == {
        "page": 2, "pages": 2, "text": "second page"}
    enabled[0] = False
    with pytest.raises(ResultReadError) as exc:
        artifacts.page(report["report_id"], 1, owner="owner")
    assert exc.value.code == "unauthorized"


def test_nested_failed_read_marks_parent_rollback_only(stores):
    journal, _, artifacts, _, _, _ = stores
    with pytest.raises(JournalStorageError):
        with journal.transaction():
            publish(artifacts)
            try:
                artifacts.read("missing", 0, 1, owner="owner")
            except ResultReadError:
                pass
    assert journal.connection.execute("SELECT COUNT(*) FROM desktop_artifacts").fetchone()[0] == 0


def test_published_bytes_and_reports_survive_real_restart(tmp_path):
    path = tmp_path / "journal.sqlite3"
    journal = JournalStore(path, "profile")
    artifacts = ArtifactStore(journal, authorize=lambda *_: True)
    artifact = publish(artifacts, b"original\xff\x00")
    report = artifacts.publish_report(["saved report"], owner="owner",
                                     conversation_id="conversation", request_id="request",
                                     tool="check")
    journal.close()
    # Requires the parent's shared JournalStore schema integration. No mock or
    # permissive alternate connection pretends the actual reopen gate passed.
    journal = JournalStore(path, "profile")
    try:
        artifacts = ArtifactStore(journal, authorize=lambda *_: True)
        page = artifacts.read(artifact["ref"], 0, 65536, owner="owner")
        assert base64.b64decode(page["data_b64"]) == b"original\xff\x00"
        assert artifacts.page(report["report_id"], 1, owner="owner")["text"] == "saved report"
    finally:
        journal.close()
