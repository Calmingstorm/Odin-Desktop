"""Checkbox ingestion intent through real upload, request, runner and delivery."""
from __future__ import annotations

import base64
import hashlib
import os
from copy import deepcopy

import pytest

from tests.test_desktop_core_lifecycle import connect, profile, request
from tests.test_desktop_request_core import Provider, service, settled

INGEST_NOTE = " User requested knowledge ingestion; use ingest_document if appropriate."


class RecordingProvider(Provider):
    def __init__(self):
        super().__init__()
        self.inputs = []

    async def chat_with_tools(self, **kwargs):
        self.inputs.append(deepcopy(kwargs["messages"]))
        return await super().chat_with_tools(**kwargs)


async def upload(reader, writer, cid, name, data, mime="text/plain"):
    begun = await request(reader, writer, "attachments.begin", {
        "client_attachment_id": name, "conversation_id": cid,
        "name": name, "mime": mime, "size": len(data)})
    assert begun["ok"]
    upload_id = begun["result"]["upload_id"]
    chunk = await request(reader, writer, "attachments.chunk", {
        "upload_id": upload_id, "offset": 0,
        "data_b64": base64.b64encode(data).decode("ascii")})
    assert chunk["ok"]
    committed = await request(reader, writer, "attachments.commit", {
        "upload_id": upload_id, "sha256": hashlib.sha256(data).hexdigest()})
    assert committed["ok"]
    return committed["result"]["attachment"]["ref"]


def model_text(provider):
    assert len(provider.inputs) == 1
    return "\n".join(
        message["content"] for message in provider.inputs[0]
        if message["role"] == "user" and isinstance(message["content"], str))


@pytest.mark.asyncio
@pytest.mark.parametrize(("text", "checked", "expected_notes"), [
    ("Review these files", (False, True, False), (False, True, False)),
    ("Review these files", (False, False, False), (False, False, False)),
    ("Remember this for later", (False, False, False), (True, True, True)),
    ("", (True, False, True), (True, False, True)),
])
async def test_real_request_uses_exact_per_attachment_note(
        tmp_path, text, checked, expected_notes):
    paths, socket_path, token_file = profile(tmp_path)
    provider = RecordingProvider()
    core = service(paths, socket_path, token_file, provider)
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        assert not hasattr(core.engine, "ingest_attachment")
        reader, writer, _ = await connect(socket_path)
        created = await request(reader, writer, "conversations.create", {})
        cid = created["result"]["conversation"]["id"]
        attachments = []
        expected_blocks = []
        for index, (add, note) in enumerate(zip(checked, expected_notes, strict=True)):
            name, body = f"file-{index}.txt", f"Source {index}"
            ref = await upload(reader, writer, cid, name, body.encode())
            attachments.append({"ref": ref, "add_to_knowledge": add})
            expected_blocks.append(
                f"**Attached file: {name}**\n```\n{body}\n```\n"
                f"[File read for current task.{INGEST_NOTE if note else ''}]")
        submitted = await request(reader, writer, "submission.send", {
            "client_submission_id": "intent", "conversation_id": cid,
            "text": text, "attachments": attachments})
        assert submitted["ok"]
        await settled(core)
        actual = model_text(provider)
        assert "\n\n".join(expected_blocks) in actual
        assert actual.count(INGEST_NOTE) == sum(expected_notes)
        row = core.store.connection.execute(
            "SELECT state FROM desktop_requests WHERE request_id=?",
            (submitted["result"]["request_id"],)).fetchone()
        assert row["state"] == "completed"
        snapshot = await request(reader, writer, "conversation.snapshot", {"conversation_id": cid})
        replies = [item["text"] for item in snapshot["result"]["messages"]["items"]
                   if item["role"] == "assistant"]
        assert replies == ["Guarded answer 1."]
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.asyncio
async def test_per_attachment_processing_preserves_retained_source_order(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    provider = RecordingProvider()
    core = service(paths, socket_path, token_file, provider)
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        core.config.attachments.inline_text_max_bytes = 1
        reader, writer, _ = await connect(socket_path)
        created = await request(reader, writer, "conversations.create", {})
        cid = created["result"]["conversation"]["id"]
        attachments = []
        for name, body, add in (("first.txt", b"First source", True),
                                ("second.txt", b"Second source", False)):
            ref = await upload(reader, writer, cid, name, body)
            attachments.append({"ref": ref, "add_to_knowledge": add})
        submitted = await request(reader, writer, "submission.send", {
            "client_submission_id": "retention", "conversation_id": cid,
            "text": "Review these files", "attachments": attachments})
        assert submitted["ok"]
        await settled(core)
        actual = model_text(provider)
        first, second = actual.split("**Attached file: second.txt**", 1)
        assert "**Attached file: first.txt**" in first
        assert first.count(INGEST_NOTE) == 1
        assert INGEST_NOTE not in second
        assert '"attachment_count":2' in actual
        store = core.engine.deps.tool_executor._ensure_output_store()
        with store._db() as db:
            blobs = db.execute(
                "SELECT content_index,kind,data FROM output_blobs "
                "ORDER BY content_index").fetchall()
        assert [(row[0], row[1], row[2]) for row in blobs] == [
            (0, "Original text file: first.txt", b"First source"),
            (1, "Original text file: second.txt", b"Second source"),
        ]
        state = core.store.connection.execute(
            "SELECT state FROM desktop_requests WHERE request_id=?",
            (submitted["result"]["request_id"],)).fetchone()[0]
        assert state == "completed"
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)
