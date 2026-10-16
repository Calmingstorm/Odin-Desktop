"""Odin 4.17 carry-over: spawned agents and loops see analyze_image results as images.

Desktop's real core: the native analyze_image handler, runtime delivery, the
agent manager's tool cycle and every store, with a scripted model at the
provider boundary (the same transcript view Odin's own tests capture).
"""
from __future__ import annotations

import asyncio
import base64
import copy
import struct
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.audit.tool_context import _pending_observers
from src.config.schema import OpenAICompatibleModelProfile, ToolHost
from src.llm.kimi import KimiClient
from src.llm.ollama import OllamaClient
from src.llm.openai_codex import CodexChatClient
from src.llm.openai_compatible import OpenAICompatibleClient
from src.llm.types import LLMResponse, ToolCall
from src.tools.result_validator import ToolResult
from tests.test_desktop_background_core import cleanup, session
from tests.test_desktop_core_lifecycle import request
from tests.test_desktop_request_core import Provider, settled
from tests.test_mcp_media_surfaces_checkpoint import assert_grouping

PROMPT = "Which shape is inside the other?"
AGENT = "VISION-AGENT"
LOOP = "VISION-LOOP"


def _wire(provider: str, messages: list[dict]) -> tuple[list[str], list[str]]:
    """(tool result texts, native image payloads) as each provider serializes them.

    Odin 4.17's helper (its tests/test_agent_image_safety.py), kept here because
    Desktop's inherited copy of that file stays frozen at Odin 4.13.
    """
    if provider == "codex":
        wire = CodexChatClient._convert_messages_with_tools(None, messages)
        outputs = [x["output"] for x in wire if x.get("type") == "function_call_output"]
        images = [part["image_url"].rsplit(",", 1)[1] for x in wire
                  if isinstance(x.get("content"), list) for part in x["content"]
                  if part.get("type") == "input_image"]
        return outputs, images
    if provider == "ollama":
        wire = OllamaClient._convert_messages(None, messages, "")
        outputs = [m["content"] for m in wire if m.get("role") == "tool"]
        return outputs, [data for m in wire for data in m.get("images", [])]
    client = KimiClient if provider == "kimi" else OpenAICompatibleClient
    wire = client._convert_messages(None, messages, "")
    outputs = [m["content"] for m in wire if m.get("role") == "tool"]
    images = [part["image_url"]["url"].rsplit(",", 1)[1] for m in wire
              if isinstance(m.get("content"), list) for part in m["content"]
              if part.get("type") == "image_url"]
    return outputs, images


def png(rgb: tuple[int, int, int], size: int = 4) -> bytes:
    """A small valid RGB PNG of one colour."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    rows = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def fixture(tmp_path, name: str, rgb: tuple[int, int, int]) -> tuple[str, str]:
    path = tmp_path / name
    path.write_bytes(png(rgb))
    return str(path), base64.b64encode(path.read_bytes()).decode()


def analyze(path: str) -> tuple[str, dict]:
    return ("analyze_image", {"host": "localhost", "path": path, "prompt": PROMPT})


def _first_text(messages: list[dict]) -> str:
    content = messages[0].get("content") if messages else ""
    return content if isinstance(content, str) else str(content)


def _tool_results(messages: list[dict]) -> list[dict]:
    return [b for m in messages if isinstance(m.get("content"), list)
            for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result"]


class VisionProvider(Provider):
    """Main chat starts one piece of work; that work calls its tools once, then answers."""

    def __init__(self, start: tuple[str, dict], marker: str, work_calls: list[tuple[str, dict]]):
        super().__init__()
        self.start, self.marker, self.work_calls = start, marker, work_calls
        self.work_requests: list[list[dict]] = []

    async def chat_with_tools(self, **kwargs):
        self.calls += 1
        messages = kwargs.get("messages", [])
        if self.marker in _first_text(messages):
            self.work_requests.append(copy.deepcopy(messages))
            if not _tool_results(messages):
                return LLMResponse(tool_calls=[
                    ToolCall(f"call-{index}", name, values)
                    for index, (name, values) in enumerate(self.work_calls, 1)
                ], stop_reason="tool_use")
            return LLMResponse(text="work done")
        if not _tool_results(messages):
            return LLMResponse(tool_calls=[ToolCall("start", *self.start)],
                               stop_reason="tool_use")
        return LLMResponse(text="Started.")


def _local_host(core) -> None:
    """The owner's localhost lease, as a fresh profile has it."""
    core.config.tools.hosts["localhost"] = ToolHost(address="localhost")
    core.engine.deps.host_registry.publish(core.config.tools.hosts)
    Path(core.config.tools.local_working_dir).mkdir(parents=True, mode=0o700)


async def _agent_session(tmp_path, work_calls):
    provider = VisionProvider(("spawn_agent", {"label": "vision", "goal": f"{AGENT} inspect"}),
                              AGENT, work_calls)
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, provider)
    _local_host(core)
    core.config.agents.model = "compat:test"
    core.config.openai_compatible.model_profiles["test"] = OpenAICompatibleModelProfile(
        total_window_tokens=200000, max_output_tokens=10000, supports_thinking_mode=True)
    return provider, core, reader, writer, cid, rfd, wfd


async def _run_agent(core, reader, writer, cid):
    accepted = await request(reader, writer, "submission.send", {
        "client_submission_id": "vision", "conversation_id": cid, "text": "Spawn vision work"})
    assert accepted["ok"]
    await settled(core)
    agents = list(core.engine.deps.agent_manager._agents.values())
    assert len(agents) == 1
    await asyncio.wait_for(agents[0]._task, 5)
    work = (await request(reader, writer, "work.list", {"kind": "agent"}))["result"]["items"]
    assert len(work) == 1 and work[0]["state"] == "completed", work
    return agents[0]


async def _closed_stores(tmp_path, core, writer, rfd, wfd) -> bytes:
    """Every byte the profile kept, read after the core closed its stores."""
    if _pending_observers:
        await asyncio.gather(*list(_pending_observers), return_exceptions=True)
    await cleanup(core, writer, rfd, wfd)
    return b"\n".join(_kept(tmp_path).values())


def _kept(tmp_path) -> dict:
    """{path: bytes} for every non-fixture file the profile kept."""
    return {p: p.read_bytes() for p in sorted(tmp_path.rglob("*"))
            if p.is_file() and p.suffix != ".png"}


@pytest.mark.asyncio
async def test_spawned_agent_sees_analyze_image_as_a_native_image(tmp_path):
    path, pixels = fixture(tmp_path, "fixture.png", (200, 30, 30))
    provider, core, reader, writer, cid, rfd, wfd = await _agent_session(tmp_path, [analyze(path)])
    try:
        agent = await _run_agent(core, reader, writer, cid)
        assert agent.iteration_count >= 2
        assert len(provider.work_requests) == 2
        continuation = provider.work_requests[1]
        assert_grouping(continuation, {"call-1": [pixels]})
        (record,) = _tool_results(continuation)
        assert record["status"] == "succeeded"
        assert record["content"] == f"[Image loaded. Analyze it with this instruction: {PROMPT}]"
        for wire in ("codex", "compatible", "ollama"):
            outputs, images = _wire(wire, continuation)
            assert images == [pixels]
            assert all(pixels not in output for output in outputs)
    finally:
        stored = await _closed_stores(tmp_path, core, writer, rfd, wfd)
    assert pixels.encode() not in stored
    # The scan above covers stores that really hold this call: the agent's
    # trajectory and the audit log both name it.
    kept = _kept(tmp_path)
    assert any(b"analyze_image" in data for path, data in kept.items()
               if "agent_trajectories" in path.parts)
    assert any(b"analyze_image" in data for path, data in kept.items()
               if path.name == "audit.jsonl")


@pytest.mark.asyncio
async def test_several_image_calls_keep_order_labels_and_pairing(tmp_path, monkeypatch):
    first, first_pixels = fixture(tmp_path, "first.png", (10, 200, 10))
    panels = [fixture(tmp_path, name, rgb)[1]
              for name, rgb in (("left.png", (10, 10, 200)), ("right.png", (200, 200, 10)))]
    missing = str(tmp_path / "missing.png")
    everything = [first_pixels, *panels]
    provider, core, reader, writer, cid, rfd, wfd = await _agent_session(tmp_path, [
        analyze(first), ("analyze_image", {"url": "https://example.test/panels.png"}),
        analyze(missing)])
    media = core.engine.deps.native_tools.owners["media"]
    real = media._handle_analyze_image

    async def panels_or_real(message, inp):
        if inp.get("url") == "https://example.test/panels.png":
            # Odin's plural shape: one call, two images and its own text.
            return {"__image_blocks__": [_block(data) for data in panels],
                    "__text__": "two panels"}
        return await real(message, inp)

    monkeypatch.setattr(media, "_handle_analyze_image", panels_or_real)
    try:
        await _run_agent(core, reader, writer, cid)
        continuation = provider.work_requests[1]
        assert_grouping(continuation, {"call-1": [first_pixels], "call-2": panels})
        records = _tool_results(continuation)
        assert [r["tool_use_id"] for r in records] == ["call-1", "call-2", "call-3"]
        assert [r["status"] for r in records] == ["succeeded", "succeeded", "failed"]
        assert records[1]["content"] == "two panels"
        assert "No such file or directory" in records[2]["content"]
        assert not any(data in str(records) for data in everything)
        for wire in ("codex", "compatible", "kimi", "ollama"):
            outputs, images = _wire(wire, continuation)
            assert images == everything
            assert not any(data in output for output in outputs for data in everything)
    finally:
        stored = await _closed_stores(tmp_path, core, writer, rfd, wfd)
    assert not any(data.encode() in stored for data in everything)


@pytest.mark.asyncio
async def test_malformed_marker_is_a_failed_result_without_its_payload(tmp_path, monkeypatch):
    provider, core, reader, writer, cid, rfd, wfd = await _agent_session(
        tmp_path, [("analyze_image", {"url": "https://example.test/a.png"})])

    async def malformed(_message, _inp):
        return {"__image_blocks__": "MALFORMED_PIXELS" * 50}

    monkeypatch.setattr(core.engine.deps.native_tools.owners["media"],
                        "_handle_analyze_image", malformed)
    try:
        await _run_agent(core, reader, writer, cid)
        (record,) = _tool_results(provider.work_requests[1])
        assert record["status"] == "failed"
        assert ("Error: malformed image result; the image could not be delivered."
                in record["content"])
        assert "MALFORMED_PIXELS" not in str(provider.work_requests[1])
    finally:
        stored = await _closed_stores(tmp_path, core, writer, rfd, wfd)
    assert b"analyze_image" in stored
    assert b"MALFORMED_PIXELS" not in stored


@pytest.mark.asyncio
async def test_autonomous_loop_still_sees_analyze_image_as_a_native_image(tmp_path):
    path, pixels = fixture(tmp_path, "loop.png", (120, 120, 0))
    provider = VisionProvider(("start_loop", {
        "goal": f"{LOOP} inspect", "mode": "silent", "max_iterations": 1,
        "interval_seconds": 10}), LOOP, [analyze(path)])
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, provider)
    _local_host(core)
    try:
        accepted = await request(reader, writer, "submission.send", {
            "client_submission_id": "loop", "conversation_id": cid, "text": "Start vision loop"})
        assert accepted["ok"]
        await settled(core)
        loops = list(core.engine.deps.loop_manager._loops.values())
        assert len(loops) == 1
        await asyncio.wait_for(loops[0]._task, 5)
        assert len(provider.work_requests) == 2, provider.work_requests
        assert_grouping(provider.work_requests[1], {"call-1": [pixels]})
    finally:
        stored = await _closed_stores(tmp_path, core, writer, rfd, wfd)
    assert pixels.encode() not in stored


@pytest.mark.asyncio
async def test_scheduled_image_step_posts_an_omission_note_not_pixels(tmp_path):
    path, pixels = fixture(tmp_path, "scheduled.png", (40, 160, 160))
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, Provider())
    _local_host(core)
    try:
        saved = await request(reader, writer, "schedules.save", {
            "description": "Image workflow", "action": "workflow", "channel_id": cid,
            "run_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "steps": [{"tool_name": "analyze_image",
                       "tool_input": {"host": "localhost", "path": path, "prompt": PROMPT}}]})
        assert saved["ok"], saved
        listing = await request(reader, writer, "work.list", {"kind": "schedule"})
        items = listing["result"]["items"]
        ran = await request(reader, writer, "work.control", {
            "control_command_id": "run-image-workflow", "kind": "schedule", "id": items[0]["id"],
            "action": "run_now"})
        assert ran["ok"], ran
        texts = [m["text"] for m in core.transcript.list(cid)["items"]]
        assert any("[1 image(s) omitted from text output.]" in text for text in texts), texts
        assert not any(pixels in text for text in texts)
        history = await request(reader, writer, "schedules.history", {"id": saved["result"]["id"]})
        assert history["ok"] and history["result"][-1]["status"] == "success", history
    finally:
        stored = await _closed_stores(tmp_path, core, writer, rfd, wfd)
    assert pixels.encode() not in stored


def _block(data: str) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}


@pytest.mark.parametrize("marker", [
    {"__image_block__": "not a block"},
    {"__image_block__": {"type": "text", "text": "not an image"}},
    {"__image_blocks__": []},
    {"__image_block__": _block("SHAPE_PIXELS"), "__prompt__": {"not": "text"}},
    {"__image_blocks__": [_block("SHAPE_PIXELS")], "__text__": 7},
])
def test_every_undeliverable_marker_shape_is_refused_without_echo(marker):
    from src.tools.media_result import MediaRejection, classify_native_media, media_safe_text

    rejection = classify_native_media(marker)
    assert isinstance(rejection, MediaRejection)
    assert rejection.message() == (
        "Error: malformed image result; the image could not be delivered.")
    assert media_safe_text(marker) == rejection.message()


@pytest.mark.asyncio
async def test_agent_callback_refuses_a_malformed_marker_that_skipped_delivery(
        tmp_path, monkeypatch):
    provider, core, reader, writer, cid, rfd, wfd = await _agent_session(
        tmp_path, [("analyze_image", {"url": "https://example.test/raw.png"})])
    loop = core.engine.deps.native_tools.owners["agents"]._tool_loop
    original = loop.dispatch_loop_tool

    async def raw_dispatch(tool_name, tool_input, *args, **kwargs):
        if tool_name == "analyze_image":
            # A raw result that never passed runtime delivery: the agent
            # callback's own backstop must still refuse it.
            return {"__image_blocks__": "RAW_MALFORMED" * 20}
        return await original(tool_name, tool_input, *args, **kwargs)

    monkeypatch.setattr(loop, "dispatch_loop_tool", raw_dispatch)
    try:
        await _run_agent(core, reader, writer, cid)
        (record,) = _tool_results(provider.work_requests[1])
        assert record["status"] == "failed"
        assert "malformed image result" in record["content"]
        assert "RAW_MALFORMED" not in str(provider.work_requests[1])
    finally:
        stored = await _closed_stores(tmp_path, core, writer, rfd, wfd)
    assert b"RAW_MALFORMED" not in stored


@pytest.mark.asyncio
async def test_scheduled_typed_image_result_keeps_its_text_and_notes_the_images(
        tmp_path, monkeypatch):
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, Provider())

    async def typed(message, tool, values):
        core.requests.assert_request(message)
        return ToolResult(output="two panels", image_blocks=[
            _block("TYPED_PIXELS_A"), _block("TYPED_PIXELS_B")], tool_name=tool)

    monkeypatch.setattr(core._scheduled_handlers, "_dispatch_tool", typed)
    try:
        saved = await request(reader, writer, "schedules.save", {
            "description": "Typed image workflow", "action": "workflow", "channel_id": cid,
            "run_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "steps": [{"tool_name": "mcp_panels_capture", "tool_input": {}}]})
        assert saved["ok"], saved
        listing = await request(reader, writer, "work.list", {"kind": "schedule"})
        ran = await request(reader, writer, "work.control", {
            "control_command_id": "run-typed-workflow", "kind": "schedule",
            "id": listing["result"]["items"][0]["id"], "action": "run_now"})
        assert ran["ok"], ran
        texts = [m["text"] for m in core.transcript.list(cid)["items"]]
        assert any("two panels" in text and "[2 image(s) omitted from text output.]" in text
                   for text in texts), texts
        history = await request(reader, writer, "schedules.history", {"id": saved["result"]["id"]})
        assert history["ok"] and history["result"][-1]["status"] == "success", history
    finally:
        stored = await _closed_stores(tmp_path, core, writer, rfd, wfd)
    assert b"TYPED_PIXELS" not in stored
