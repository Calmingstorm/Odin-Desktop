"""Odin 4.22.0 (PR #729 review fix): a request's saved attachments stay until its turn ends.

Desktop pins the request's attachment workspace for the whole of its execution, a resumed
one included, so a cleanup pass with a short retention (another reply's housekeeping, the
new timer) never removes a file the turn still reads. Queued uploads are SQLite rows, not
workspaces, until their request is processed, and a pin holds nothing across suspension or
a restart: the in-memory pin covers execution only.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from src.discord import turn_resume
from src.discord.attachments import _PINNED_WORKSPACES, AttachmentProcessor, pin_workspaces
from src.llm.errors import LLMCapacityError
from src.llm.recovery import RecoveryPolicy
from src.llm.types import LLMResponse
from tests.test_desktop_attachment_knowledge import upload
from tests.test_desktop_auto_resume import recover_capacity, wait_until
from tests.test_desktop_core_lifecycle import connect, profile, request
from tests.test_desktop_request_core import Provider, configured, service, settled

# Longer than the inline preview, so the file is saved in the request's workspace.
LONG_TEXT = "\n".join(f"line {i}: entry {i * 7}" for i in range(6000)).encode()


def aged(path):
    past = time.time() - 3600
    os.utime(path, (past, past))


def sweep(core):
    """A cleanup pass with no retention: every unpinned workspace is old enough to go."""
    root = Path(core.engine.deps.get_config().attachments.temp_directory)
    for place in root.glob("*/*"):
        aged(place)
    return AttachmentProcessor(temp_dir=str(root), retention_hours=0).cleanup_old_workspaces()


def workspace(core, cid, rid):
    return Path(core.engine.deps.get_config().attachments.temp_directory) / cid / rid


def saved_names(place):
    """Saved names carry a unique prefix: ``<hex>-notes.txt``."""
    return sorted(path.name.split("-", 1)[1] for path in place.iterdir())


def running(core):
    row = core.store.connection.execute(
        "SELECT * FROM desktop_requests WHERE state='running'").fetchone()
    return row["conversation_id"], row["request_id"]


def test_overlapping_pins_hold_a_workspace_until_the_last_ends(tmp_path):
    root = tmp_path / "attachments"
    for rid in ("held", "free"):
        (root / "conversation" / rid).mkdir(parents=True)
        (root / "conversation" / rid / "file.txt").write_text("kept")
        aged(root / "conversation" / rid)
    processor = AttachmentProcessor(temp_dir=str(root), retention_hours=0)
    with pin_workspaces("conversation", ["held"]):
        with pin_workspaces("conversation", ["held"]):
            assert processor.cleanup_old_workspaces() == 1  # only the unpinned one
        assert processor.cleanup_old_workspaces() == 0
        assert (root / "conversation" / "held" / "file.txt").exists()
    assert ("conversation", "held") not in _PINNED_WORKSPACES
    assert processor.cleanup_old_workspaces() == 1
    with pytest.raises(RuntimeError):
        with pin_workspaces("conversation", ["failed"]):
            raise RuntimeError("an error releases the pin")
    assert ("conversation", "failed") not in _PINNED_WORKSPACES


async def submit(core, reader, writer, text="Read the saved file"):
    cid = (await request(reader, writer, "conversations.create", {}))[
        "result"]["conversation"]["id"]
    ref = await upload(reader, writer, cid, "notes.txt", LONG_TEXT)
    sent = await request(reader, writer, "submission.send", {
        "client_submission_id": "pinned", "conversation_id": cid, "text": text,
        "attachments": [{"ref": ref, "add_to_knowledge": False}]})
    assert sent["ok"], sent
    return cid, sent["result"]["request_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["completed", "failed"])
async def test_a_running_requests_files_survive_a_sweep_and_go_after_it(tmp_path, outcome):
    paths, socket_path, token_file = profile(tmp_path)
    provider = Provider()
    core = service(paths, socket_path, token_file, provider)
    seen = []

    async def respond(**_kwargs):
        provider.calls += 1
        place = workspace(core, *running(core))
        removed = sweep(core)
        seen.append((removed, saved_names(place)))
        if outcome == "failed":
            raise RuntimeError("the turn fails after reading")
        return LLMResponse(text="The notes list numbered entries.")

    provider.chat_with_tools = respond
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        reader, writer, _ = await connect(socket_path)
        cid, rid = await submit(core, reader, writer)
        await settled(core)
        assert seen and all(entry == (0, ["notes.txt"]) for entry in seen)
        assert core.requests.get_request(rid)["state"] == outcome
        assert (cid, rid) not in _PINNED_WORKSPACES
        assert sweep(core) == 1 and not workspace(core, cid, rid).exists()
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.asyncio
async def test_a_resumed_requests_files_survive_a_sweep_during_its_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(turn_resume, "_AUTO_POLL_SECONDS", 0.01)
    paths, socket_path, token_file = profile(tmp_path)
    provider = Provider()
    core = service(paths, socket_path, token_file, provider)

    def config(paths):
        cfg = configured(paths)
        cfg.turn_state.auto_resume = True
        cfg.turn_state.resume_ttl_hours = 72.0
        return cfg

    core.config_provider = config
    available = False
    seen = []

    async def respond(**_kwargs):
        provider.calls += 1
        if not available:
            raise LLMCapacityError("Temporary test capacity", provider="compat", model="test")
        place = workspace(core, *running(core))
        seen.append((sweep(core), saved_names(place)))
        return LLMResponse(text="The notes list numbered entries.")

    provider.chat_with_tools = respond
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        core.engine.deps.llm_gateway._recovery_policy_source = lambda: RecoveryPolicy(
            deadline_seconds=0.05, backoff_base=0.001, backoff_cap=0.002,
            retry_after_cap=0.005)
        reader, writer, _ = await connect(socket_path)
        cid, rid = await submit(core, reader, writer)
        await settled(core)
        assert core.requests.get_request(rid)["state"] == "suspended"
        assert (cid, rid) not in _PINNED_WORKSPACES  # nothing is held while suspended
        available = True
        recover_capacity(core)
        await wait_until(lambda: core.requests.get_request(rid)["state"] == "completed")
        await settled(core)
        assert core.requests.get_request(rid)["generation"] == 2
        assert seen and all(entry == (0, ["notes.txt"]) for entry in seen)
        assert (cid, rid) not in _PINNED_WORKSPACES
        assert sweep(core) == 1
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


class QueueProvider(Provider):
    """The first turn waits until released; later turns record their saved files."""

    def __init__(self):
        super().__init__()
        self.release = __import__("asyncio").Event()
        self.seen = []
        self.core = None

    async def chat_with_tools(self, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            self.entered.set()
            await self.release.wait()
            return LLMResponse(text="The first request is done.")
        place = workspace(self.core, *running(self.core))
        self.seen.append((sweep(self.core), saved_names(place)))
        return LLMResponse(text="The notes list numbered entries.")


@pytest.mark.asyncio
async def test_a_queued_upload_survives_sweeps_and_is_pinned_once_it_runs(tmp_path):
    import asyncio

    paths, socket_path, token_file = profile(tmp_path)
    provider = QueueProvider()
    core = service(paths, socket_path, token_file, provider)
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        reader, writer, _ = await connect(socket_path)
        cid = (await request(reader, writer, "conversations.create", {}))[
            "result"]["conversation"]["id"]
        first = await request(reader, writer, "submission.send", {
            "client_submission_id": "first", "conversation_id": cid, "text": "Take a while"})
        assert first["ok"], first
        async with asyncio.timeout(5):
            await provider.entered.wait()
        ref = await upload(reader, writer, cid, "notes.txt", LONG_TEXT)
        queued = await request(reader, writer, "submission.send", {
            "client_submission_id": "queued", "conversation_id": cid, "text": "Read it next",
            "attachments": [{"ref": ref, "add_to_knowledge": False}]})
        assert queued["ok"], queued
        rid = queued["result"]["request_id"]
        assert core.requests.get_request(rid)["state"] == "queued"
        sweep(core)  # its upload is a stored row, not yet a workspace: nothing to remove
        provider.release.set()
        await settled(core)
        assert core.requests.get_request(rid)["state"] == "completed"
        assert provider.seen and all(entry == (0, ["notes.txt"]) for entry in provider.seen)
        assert (cid, rid) not in _PINNED_WORKSPACES and sweep(core) == 1
    finally:
        provider.release.set()
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.asyncio
async def test_a_stopped_requests_pin_is_released(tmp_path):
    import asyncio

    paths, socket_path, token_file = profile(tmp_path)
    provider = Provider(blocked=True)
    core = service(paths, socket_path, token_file, provider)
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        reader, writer, _ = await connect(socket_path)
        cid, rid = await submit(core, reader, writer)
        async with asyncio.timeout(5):
            await provider.entered.wait()
        assert (cid, rid) in _PINNED_WORKSPACES
        generation = core.requests.get_request(rid)["generation"]
        stopped = await request(reader, writer, "control.stop", {
            "control_command_id": "stop-pinned", "conversation_id": cid, "request_id": rid,
            "generation": generation})
        assert stopped.get("result") == {"disposition": "requested"}, stopped
        provider.release.set()
        await settled(core)
        assert (cid, rid) not in _PINNED_WORKSPACES and sweep(core) == 1
    finally:
        provider.release.set()
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)
