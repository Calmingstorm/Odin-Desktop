"""SkillContext callbacks through the actual engine, requests and artifact store."""
import asyncio
import base64
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.desktop.artifacts import ArtifactStore
from src.desktop.delivery import ArtifactPost, ArtifactPublisher, DurableDelivery, RequestContext
from src.discord.response_guards import scrub_response_secrets
from src.llm.types import LLMResponse, ToolCall

pytest_plugins = ["tests.test_desktop_engine_services"]

SKILL = '''
import asyncio
SKILL_DEFINITION = {"name": "delivery_probe", "description": "Delivery contract probe",
                    "input_schema": {"type": "object", "properties": {}}}
async def execute(inp, context):
    async def child():
        await context.post_message("exact marker\\npassword=fixture-secret")
        await context.post_file(b"opaque\\x00bytes", "probe.bin", "caption marker")
        await context.post_file(b"second", "second.txt")
    await asyncio.create_task(child())
    return "Delivery complete."
'''


def setup_skill(graph):
    requests, engine, provider, transcript, cid = graph
    manager = engine.deps.skill_manager
    assert "created" in manager.create_skill("delivery_probe", SKILL).lower()
    artifacts = ArtifactStore(requests.store,
                              authorize=engine.deps.tool_executor._authorize_output)
    requests.delivery.artifact_converter = ArtifactPublisher(artifacts, requests.events)
    return requests, engine, provider, transcript, cid, artifacts


async def run_skill(graph, *, mode="send", tool="invoke_skill"):
    requests, engine, provider, transcript, cid, artifacts = setup_skill(graph)
    dispatcher = engine.deps.native_tools
    if mode == "stage":
        original = dispatcher.dispatch

        async def stage(*args, **kwargs):
            kwargs["skill_file_delivery"] = "stage"
            return await original(*args, **kwargs)

        dispatcher.dispatch = stage
    arguments = {"name": "delivery_probe", "input": {}} if tool == "invoke_skill" else {}
    provider.responses = [LLMResponse(tool_calls=[ToolCall("skill", tool, arguments)]),
                          LLMResponse(text="Final reply.")]
    receipt = requests.submit({"client_submission_id": "skill", "conversation_id": cid,
                               "text": "Execute the delivery probe"})
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    assert requests.get_request(receipt["request_id"])["state"] == "completed"
    return requests, engine, provider, transcript, cid, artifacts, receipt


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["invoke_skill", "delivery_probe"])
async def test_real_skill_child_posts_exact_scrubbed_durable_message_and_bytes(graph, tool):
    requests, _engine, _provider, transcript, cid, artifacts, receipt = await run_skill(
        graph, tool=tool)
    rows = transcript.list(cid)["items"]
    notice = next(row for row in rows if row["text"].startswith("exact marker"))
    assert notice["text"] == scrub_response_secrets("exact marker\npassword=fixture-secret")
    assert "fixture-secret" not in notice["text"]
    assert notice["request_id"] == receipt["request_id"]
    assert "author" not in notice
    files = [row for row in rows if row.get("artifacts")]
    assert len(files) == 2 and all(row["role"] == "notice" for row in files)
    assert all(row["author"] == "odin" for row in files)
    artifact = files[0]["artifacts"][0]
    assert artifact["mime"] == "application/octet-stream"
    page = artifacts.read(artifact["ref"], 0, 100, owner=requests.authority.owner_id)
    assert base64.b64decode(page["data_b64"]) == b"opaque\x00bytes"
    stored = requests.store.connection.execute(
        "SELECT * FROM desktop_artifacts WHERE ref=?", (artifact["ref"],)).fetchone()
    assert stored["tool"] == "delivery_probe"
    assert stored["request_id"] == receipt["request_id"] and stored["conversation_id"] == cid
    assert json.loads(stored["hosts"]) == []
    durable = requests.store.connection.execute(
        "SELECT payload FROM desktop_delivery_outbox WHERE request_id=?",
        (receipt["request_id"],)).fetchall()
    assert any(notice["id"] in row[0] for row in durable)
    assert all("fixture-secret" not in row[0] for row in durable)


@pytest.mark.asyncio
async def test_real_stage_files_consumed_only_on_matching_final_reply(graph):
    requests, _engine, _provider, transcript, cid, artifacts, receipt = await run_skill(
        graph, mode="stage")
    rows = transcript.list(cid)["items"]
    files = [row for row in rows if row.get("artifacts")]
    assert len(files) == 1 and files[0]["role"] == "assistant"
    assert files[0]["text"] == "Final reply."
    assert [file["name"] for file in files[0]["artifacts"]] == ["probe.bin", "second.txt"]
    for file, expected in zip(files[0]["artifacts"], [b"opaque\x00bytes", b"second"], strict=True):
        page = artifacts.read(file["ref"], 0, 100, owner=requests.authority.owner_id)
        assert base64.b64decode(page["data_b64"]) == expected
    assert requests.store.connection.execute(
        "SELECT COUNT(*) FROM desktop_staged_files").fetchone()[0] == 0
    assert files[0]["request_id"] == receipt["request_id"]
    assert not any(row.get("artifacts") for row in rows if row["role"] == "notice")


@pytest.mark.asyncio
async def test_unbound_foreign_and_settled_skill_callbacks_refused(graph):
    requests, engine, _provider, transcript, cid, _artifacts = setup_skill(graph)
    dispatcher = engine.deps.native_tools
    first = requests.submit({"client_submission_id": "first", "conversation_id": cid,
                             "text": "First request"})
    message = requests.fetch_request(cid, first["request_id"])
    with pytest.raises(PermissionError):
        await dispatcher.skills._skill_message_cb(message)("unbound")
    with pytest.raises(PermissionError):
        await dispatcher.skills._skill_file_cb(SimpleNamespace(), "stage", "delivery_probe")(
            b"wrong", "wrong.txt")
    saved = []
    original = engine.run

    async def inspect(active, **kwargs):
        saved.append(dispatcher.skills._skill_message_cb(active))
        foreign = replace(active, request_id="wrong")
        with pytest.raises(PermissionError):
            await dispatcher.skills._skill_message_cb(foreign)("foreign")
        await asyncio.create_task(dispatcher.skills._skill_message_cb(active)("owned child"))
        return await original(active, **kwargs)

    engine.run = inspect
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    with pytest.raises(PermissionError):
        await saved[0]("late callback")
    texts = [row["text"] for row in transcript.list(cid)["items"]]
    assert "owned child" in texts and "foreign" not in texts and "late callback" not in texts


@pytest.mark.asyncio
async def test_skill_callbacks_refused_during_final_delivery_after_execution_settles(graph):
    requests, engine, provider, transcript, cid, _artifacts = setup_skill(graph)
    captured = []
    attempted = []
    original = engine.run

    async def capture(message, **kwargs):
        skills = engine.deps.native_tools.skills
        captured.extend([skills._skill_message_cb(message),
                         skills._skill_file_cb(message, "send", "delivery_probe"),
                         skills._skill_file_cb(message, "stage", "delivery_probe")])
        return await original(message, **kwargs)

    class Sink:
        async def deliver(self, _delivery_id, frame):
            if (frame["type"] == "message.committed"
                    and frame["payload"]["message"]["role"] == "assistant"):
                for index, callback in enumerate(captured):
                    with pytest.raises(PermissionError):
                        if index == 0:
                            await asyncio.create_task(callback("late notice"))
                        else:
                            await asyncio.create_task(callback(b"late", "late.txt"))
                    attempted.append(index)
            return True

    engine.run = capture
    requests.delivery.sink = Sink()
    provider.responses = [LLMResponse(text="Settled reply.")]
    requests.submit({"client_submission_id": "late-child", "conversation_id": cid,
                     "text": "Finish without late callbacks"})
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    assert attempted == [0, 1, 2]
    assert not any(row["text"] == "late notice" for row in transcript.list(cid)["items"])
    assert requests.store.connection.execute(
        "SELECT COUNT(*) FROM desktop_staged_files").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_stage_failure_is_atomic_survives_reopen_and_never_crosses_request(graph):
    requests, _engine, _provider, transcript, cid, artifacts = setup_skill(graph)
    # Admission is covered above; here exercise the durable domain independently.
    delivery = DurableDelivery(requests.store, requests.events, transcript_commit=transcript.commit,
                               artifact_converter=ArtifactPublisher(artifacts, requests.events))
    ctx = RequestContext(cid, "retained-turn", 1, requests.authority.owner_id)
    file = ArtifactPost(b"retained", "retained.txt", "text/plain", tool="delivery_probe")
    delivery.stage_file(ctx, file)
    other = replace(ctx, request_id="other-turn")
    await delivery.send_reply(other, "Unrelated final.",
                              guarded=delivery.guarded_reply(other, "Unrelated final."))
    assert transcript.list(cid)["items"][-1]["artifacts"] == []
    await delivery.send(ctx, "Interim notice")
    await delivery.send_reply(ctx, "Preserved.", guarded=delivery.guarded_reply(ctx, "Preserved."),
                              consume_staged=False)
    assert requests.store.connection.execute(
        "SELECT COUNT(*) FROM desktop_staged_files").fetchone()[0] == 1
    resumed = replace(ctx, generation=2)
    requests.store.connection.execute("""CREATE TRIGGER harmless_stage_failure
        BEFORE INSERT ON desktop_messages BEGIN SELECT RAISE(ABORT,'fixture failure'); END""")
    with pytest.raises(Exception):
        await delivery.send_reply(resumed, "Resumed.",
                                  guarded=delivery.guarded_reply(resumed, "Resumed."))
    assert requests.store.connection.execute(
        "SELECT COUNT(*) FROM desktop_staged_files").fetchone()[0] == 1
    assert requests.store.connection.execute(
        "SELECT COUNT(*) FROM desktop_artifacts").fetchone()[0] == 0
    requests.store.connection.execute("DROP TRIGGER harmless_stage_failure")
    reopened = DurableDelivery(requests.store, requests.events, transcript_commit=transcript.commit,
                               artifact_converter=ArtifactPublisher(artifacts, requests.events))
    reply = await reopened.send_reply(resumed, "Resumed.",
                                      guarded=reopened.guarded_reply(resumed, "Resumed."))
    assert len(reply["artifacts"]) == 1
    assert requests.store.connection.execute(
        "SELECT COUNT(*) FROM desktop_staged_files").fetchone()[0] == 0
    again = await reopened.send_reply(resumed, "Resumed.",
                                      guarded=reopened.guarded_reply(resumed, "Resumed."))
    assert again == reply
    assert requests.store.connection.execute(
        "SELECT COUNT(*) FROM desktop_artifacts").fetchone()[0] == 1
    with pytest.raises(PermissionError, match="already committed"):
        reopened.stage_file(resumed, file)


@pytest.mark.asyncio
async def test_staged_tool_output_has_presentation_author_not_assistant_role(graph):
    requests, _engine, _provider, transcript, cid, artifacts = setup_skill(graph)
    delivery = DurableDelivery(requests.store, requests.events, transcript_commit=transcript.commit,
                               artifact_converter=ArtifactPublisher(artifacts, requests.events))
    ctx = RequestContext(cid, "staged-output", 1, requests.authority.owner_id)
    delivery.stage_file(
        ctx, ArtifactPost(b"image", "result.png", "image/png", "image", "delivery_probe")
    )
    message = await delivery.finish_staged(ctx)
    assert message["role"] == "notice" and message["author"] == "odin"
    assert message["artifacts"][0]["kind"] == "image"
    assert await delivery.finish_staged(ctx) is None
    assert transcript.list(cid)["items"][-1] == message
    assert delivery.notifications.pending() == []


@pytest.mark.asyncio
async def test_stage_authorization_and_conversation_delete(graph):
    requests, _engine, _provider, _transcript, cid, artifacts = setup_skill(graph)
    ctx = RequestContext(cid, "staging", 1, requests.authority.owner_id)
    delivery = DurableDelivery(requests.store, requests.events,
        transcript_commit=requests.transcript.commit,
        artifact_converter=ArtifactPublisher(artifacts, requests.events))
    artifact = ArtifactPost(b"owned", "owned.txt", "text/plain", tool="delivery_probe")
    artifacts.authorize = lambda *_: False
    with pytest.raises(ValueError, match="not authorized"):
        delivery.stage_file(ctx, artifact)
    assert requests.store.connection.execute(
        "SELECT COUNT(*) FROM desktop_staged_files").fetchone()[0] == 0
    artifacts.authorize = lambda *_: True
    delivery.stage_file(ctx, artifact)
    delivery.delete_conversation(cid)
    assert requests.store.connection.execute(
        "SELECT COUNT(*) FROM desktop_staged_files").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_export_skill_always_stages_through_real_final_reply(graph):
    requests, engine, provider, transcript, cid, artifacts = setup_skill(graph)
    expected, name = engine.deps.skill_manager.export_skill("delivery_probe")
    provider.responses = [LLMResponse(tool_calls=[ToolCall("export", "export_skill", {
        "name": "delivery_probe"})]), LLMResponse(text="Export complete.")]
    receipt = requests.submit({"client_submission_id": "export", "conversation_id": cid,
                               "text": "Export delivery_probe"})
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    assert requests.get_request(receipt["request_id"])["state"] == "completed"
    files = [row for row in transcript.list(cid)["items"] if row.get("artifacts")]
    assert len(files) == 1 and files[0]["role"] == "assistant"
    artifact = files[0]["artifacts"][0]
    assert artifact["name"] == name
    page = artifacts.read(artifact["ref"], 0, 65536, owner=requests.authority.owner_id)
    assert base64.b64decode(page["data_b64"]) == expected
    provenance = requests.store.connection.execute(
        "SELECT tool FROM desktop_artifacts WHERE ref=?", (artifact["ref"],)).fetchone()[0]
    assert provenance == "export_skill"


@pytest.mark.asyncio
async def test_background_channel_only_envelopes_fail_closed_without_work_admission(graph):
    _requests, engine, _provider, _transcript, cid = graph
    for envelope in (SimpleNamespace(conversation_id=cid),
                     SimpleNamespace(conversation_id=cid, execution_id="schedule-run"),
                     SimpleNamespace(conversation_id=cid, agent_id="agent-run")):
        with pytest.raises(PermissionError):
            await engine.deps.native_tools.skills._skill_message_cb(envelope)("background")
        with pytest.raises(PermissionError):
            await engine.deps.native_tools.skills._skill_file_cb(envelope, "send", "probe")(
                b"background", "background.txt")
