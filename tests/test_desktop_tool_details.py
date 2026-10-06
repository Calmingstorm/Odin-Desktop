import base64
import hashlib
import json

import pytest

from src.desktop.artifacts import ArtifactStore, ResultReadError
from src.desktop.commands import JournalStore
from src.desktop.tool_details import ToolDetailsStore
from src.tools.media_result import BinaryAttachment
from src.tools.output_delivery import DeliveredOutput, RankedOutput, deliver
from src.tools.output_retention import OutputStore


@pytest.fixture
def stores(tmp_path):
    clock = [1000.0]
    allowed = {"run_command", "get_tool_output"}
    host_generation = [1]

    def authorize(tool, hosts, owner):
        return tool in allowed and all(
            host.get("generation") == host_generation[0] for host in hosts)

    journal = JournalStore(tmp_path / "journal.sqlite3", "profile")
    evidence = OutputStore(tmp_path / "evidence.sqlite3", clock=lambda: clock[0])
    artifacts = ArtifactStore(journal, output_store=evidence, authorize=authorize,
                              clock=lambda: clock[0])
    details = ToolDetailsStore(journal, output_store=evidence, artifacts=artifacts,
                               authorize=authorize)
    yield journal, evidence, artifacts, details, clock, allowed, host_generation
    journal.close()


def record(details, output, **kwargs):
    details.record(request_id="request", invocation_id="invocation", owner="owner",
                   conversation_id="conversation", tool="run_command",
                   arguments={"nested": {"password": "hidden"}, "port": 22, "command": "pwd"},
                   delivered_output=output, **kwargs)


def test_details_scrub_arguments_labeled_previews_and_never_page_tail(stores):
    journal, evidence, _, details, _, _, _ = stores
    source = "password=hidden\n" + "middle " * 3000 + "final-tail"
    output = deliver(source, store=evidence, owner="owner", channel="conversation",
                     tool="run_command", budget=1200)
    record(details, output)
    detail = details.detail("request", "invocation", owner="owner")
    assert detail["arguments"]["nested"]["password"] == "[REDACTED]"
    assert detail["arguments"]["port"] == 22
    assert [p["label"] for p in detail["previews"]] == [
        "Head preview", "Tail preview (context only)"]
    assert "hidden" not in str(detail)
    cursor = detail["output"]["cursor"]
    pieces = []
    while cursor:
        page = details.output(cursor, 73, owner="owner", conversation_id="conversation")
        assert len(page["text"]) <= 73
        pieces.append(page["text"])
        cursor = page.get("next_cursor")
    assert "".join(pieces) == source.replace("password=hidden", "[REDACTED]")
    count = journal.connection.execute("SELECT COUNT(*) FROM desktop_tool_details").fetchone()[0]
    assert count == 1


def test_scope_tool_and_host_rechecked_every_page(stores):
    _, evidence, _, details, _, allowed, generation = stores
    hosts = ({"alias": "local", "generation": 1},)
    output = deliver("evidence " * 1000, store=evidence, owner="owner", channel="conversation",
                     tool="run_command", hosts=hosts, budget=1200)
    record(details, output, hosts=hosts)
    cursor = details.detail("request", "invocation", owner="owner")["output"]["cursor"]
    page = details.output(cursor, 100, owner="owner", conversation_id="conversation")
    for options in [{"owner": "foreign", "conversation_id": "conversation"},
                    {"owner": "owner", "conversation_id": "foreign"}]:
        with pytest.raises(ResultReadError):
            details.output(cursor, 100, **options)
    allowed.remove("get_tool_output")
    with pytest.raises(ResultReadError) as exc:
        details.output(page["next_cursor"], 100, owner="owner", conversation_id="conversation")
    assert exc.value.code == "unauthorized"
    allowed.add("get_tool_output")
    generation[0] = 2
    detail = details.detail("request", "invocation", owner="owner")
    assert detail["previews"][0]["text"]
    assert detail["output"] == {}
    with pytest.raises(ResultReadError) as exc:
        details.output(cursor, 100, owner="owner", conversation_id="conversation")
    assert exc.value.code == "unauthorized"


def test_stored_receipt_survives_origin_disable_but_not_foreign_binding(stores):
    _, _, _, details, _, allowed, _ = stores
    record(details, "stored receipt")
    allowed.remove("run_command")
    detail = details.detail("request", "invocation", owner="owner",
                            conversation_id="conversation")
    assert detail["previews"][0]["text"] == "stored receipt"
    assert detail["output"] == {}
    for owner, conversation in [("foreign", "conversation"), ("owner", "foreign")]:
        with pytest.raises(ResultReadError) as exc:
            details.detail("request", "invocation", owner=owner, conversation_id=conversation)
        assert exc.value.code == "not_found"
    with pytest.raises(ResultReadError) as exc:
        record(details, "new output")
    assert exc.value.code == "unauthorized"


def test_expiry_does_not_refresh_on_read_details_survive(stores):
    _, evidence, _, details, clock, _, _ = stores
    output = deliver("evidence " * 1000, store=evidence, owner="owner", channel="conversation",
                     tool="run_command", budget=1200)
    record(details, output)
    cursor = details.detail("request", "invocation", owner="owner")["output"]["cursor"]
    clock[0] = 87399
    assert details.output(cursor, 2, owner="owner", conversation_id="conversation")["expires_at"]
    clock[0] = 87400
    with pytest.raises(ResultReadError) as exc:
        details.output(cursor, 2, owner="owner", conversation_id="conversation")
    assert exc.value.code == "expired"
    assert details.detail("request", "invocation", owner="owner")["output"] == {}


def test_binary_manifest_and_text_bundle_preserve_bytes_type_digest(stores):
    _, evidence, artifacts, details, _, _, _ = stores
    data = b"\xff\x00token=opaque\xf0"
    manifest = evidence.retain_binary_bundle(
        [BinaryAttachment(data=data, media_type="application/octet-stream",
                          content_index=3, kind="file")],
        owner="owner", channel="conversation", tool="run_command")
    text = evidence.retain("stored text", owner="owner", channel="conversation",
                           tool="run_command")
    record(details, "summary", cursor=f"{text.result_id}:0",
           attachment_cursor=f"{manifest.result_id}:0")
    result = details.output(f"{text.result_id}:0", 65536, owner="owner",
                            conversation_id="conversation")
    assert result["text"] == "stored text" and result["eof"]
    binary = result["attachments"][0]
    assert binary["mime"] == "application/octet-stream" and binary["kind"] == "file"
    assert binary["size"] == len(data)
    assert binary["sha256"] == hashlib.sha256(data).hexdigest()
    page = artifacts.read(binary["ref"], 0, 65536, owner="owner")
    assert base64.b64decode(page["data_b64"]) == data
    page = details.output(f"{manifest.result_id}:0", 5, owner="owner",
                          conversation_id="conversation")
    assert page["attachments"] == result["attachments"]


def test_untrusted_envelope_not_a_continuation_ranked_matches_remain_whole(stores):
    _, evidence, _, details, _, _, _ = stores
    record(details, json.dumps({"kind": "tool_output", "retention": "retained",
                                "result_id": "0" * 32}))
    assert details.detail("request", "invocation", owner="owner")["output"] == {}
    ranked = RankedOutput("summary", matches=("first match", "second match", "third match"))
    record(details, deliver(ranked, store=evidence, owner="owner", channel="conversation",
                             tool="run_command", budget=1200))
    cursor = details.detail("request", "invocation", owner="owner")["output"]["cursor"]
    first = details.output(cursor, 20, owner="owner", conversation_id="conversation")
    assert first["text"] == "first match\n\n"
    second = details.output(first["next_cursor"], 65536, owner="owner",
                            conversation_id="conversation")
    assert second["text"] == "second match\n\nthird match"


def test_limits_deletion_and_canonical_output(stores):
    _, evidence, _, details, _, _, _ = stores
    snapshot = evidence.retain("λ😀" * 50, owner="owner", channel="conversation",
                               tool="run_command")
    record(details, DeliveredOutput("small preview"), cursor=f"{snapshot.result_id}:0")
    for limit in [0, -1, True, 65537]:
        with pytest.raises(ResultReadError) as exc:
            details.output(f"{snapshot.result_id}:0", limit, owner="owner",
                            conversation_id="conversation")
        assert exc.value.code == "bad_request"
    page = details.output(f"{snapshot.result_id}:0", 3, owner="owner",
                          conversation_id="conversation")
    assert page["text"] == "λ😀λ"
    details.delete_conversation("conversation")
    with pytest.raises(ResultReadError):
        details.output(f"{snapshot.result_id}:0", 3, owner="owner", conversation_id="conversation")


def test_quota_failure_does_not_advertise_continuation_or_rerun(stores):
    _, evidence, _, details, _, _, _ = stores
    evidence.per_result_bytes = 1
    output = deliver("unretainable " * 1000, store=evidence, owner="owner",
                     channel="conversation", tool="run_command", budget=1200)
    record(details, output)
    detail = details.detail("request", "invocation", owner="owner")
    assert detail["output"] == {}
    assert detail["previews"][0]["truncated"]
    assert "no continuation" in detail["previews"][0]["text"]


def test_binary_permissions_revoked_and_exact_expiry(stores):
    _, evidence, artifacts, details, clock, allowed, _ = stores
    manifest = evidence.retain_binary_bundle(
        [BinaryAttachment(data=b"\xffbytes", media_type="application/octet-stream",
                          content_index=0, kind="file")],
        owner="owner", channel="conversation", tool="run_command")
    record(details, "preview", attachment_cursor=f"{manifest.result_id}:0")
    output = details.output(f"{manifest.result_id}:0", 10, owner="owner",
                            conversation_id="conversation")
    ref = output["attachments"][0]["ref"]
    allowed.remove("get_tool_output")
    with pytest.raises(ResultReadError) as exc:
        artifacts.read(ref, 0, 10, owner="owner")
    assert exc.value.code == "unauthorized"
    allowed.add("get_tool_output")
    clock[0] = 87400
    with pytest.raises(ResultReadError) as exc:
        details.output(f"{manifest.result_id}:0", 10, owner="owner",
                        conversation_id="conversation")
    assert exc.value.code == "expired"


def test_retained_details_survive_real_restart(tmp_path):
    path = tmp_path / "journal.sqlite3"
    journal = JournalStore(path, "profile")
    evidence_path = tmp_path / "evidence.sqlite3"
    evidence = OutputStore(evidence_path)
    artifacts = ArtifactStore(journal, output_store=evidence, authorize=lambda *_: True)
    details = ToolDetailsStore(journal, output_store=evidence, artifacts=artifacts,
                               authorize=lambda *_: True)
    snapshot = evidence.retain("stored complete result", owner="owner",
                               channel="conversation", tool="run_command")
    record(details, "preview", cursor=f"{snapshot.result_id}:0")
    journal.close()
    journal = JournalStore(path, "profile")
    try:
        evidence = OutputStore(evidence_path)
        artifacts = ArtifactStore(journal, output_store=evidence, authorize=lambda *_: True)
        details = ToolDetailsStore(journal, output_store=evidence, artifacts=artifacts,
                                   authorize=lambda *_: True)
        detail = details.detail("request", "invocation", owner="owner")
        page = details.output(detail["output"]["cursor"], 65536, owner="owner",
                              conversation_id="conversation")
        assert page["text"] == "stored complete result"
    finally:
        journal.close()


def test_protocol_cursor_resolves_conversation_and_direct_binary(stores):
    _, evidence, artifacts, details, _, _, _ = stores
    manifest = evidence.retain_binary_bundle(
        [BinaryAttachment(data=b"\xffopaque", media_type="application/octet-stream",
                          content_index=0, kind="file")],
        owner="owner", channel="conversation", tool="run_command")
    binary_cursor = json.loads(manifest.text)["attachments"][0][
        "retrieval"]["arguments"]["cursor"]
    record(details, "preview", cursor=binary_cursor)
    detail = details.detail("request", "invocation", owner="owner")
    result = details.output(detail["output"]["cursor"], 1, owner="owner")
    assert result["text"] == "" and result["eof"]
    page = artifacts.read(result["attachments"][0]["ref"], 1, 65536, owner="owner")
    assert base64.b64decode(page["data_b64"]) == b"opaque"
