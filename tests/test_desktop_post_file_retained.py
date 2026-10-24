"""post_file posts a file a tool returned, as a conversation artifact (Odin 4.24.0, PR #737).

An MCP result's file (a phone photo) is retained in the private output store
and named by an attachment manifest. ``post_file(attachment=<entry cursor>)``
publishes those exact bytes like a host file, under get_tool_output's fences.
These run the real Desktop engine: its executor and output store, the copied
media handler through DesktopMediaTools, durable delivery and the artifact store.
"""
import asyncio
import base64
import hashlib
import itertools
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.config.schema import ToolHost
from src.discord.native_tools.media import _DELIVERY_UNAVAILABLE, MediaTools
from src.llm.types import LLMResponse, ToolCall
from src.tools import retained_files
from src.tools.execution_outcome import is_tool_failure
from src.tools.media_result import BinaryAttachment
from src.tools.output_delivery import render_page
from tests.test_desktop_d17_parity_visibility import graph as d17_parity_graph

d17_graph = d17_parity_graph  # the real engine: executor, output store, delivery, artifacts

# Lifted from Odin 4.24.0 byte for byte; change them only by carrying Odin's bytes.
ODIN_V4_24_0_SHA256 = {
    "retained_files.py": "8c1da66774d50b27c7188a3b1d28ba54fbded3635892f2344499bca70c7f7cba",
    "output_delivery.py": "8d204c5b337dd2c2c678b27447d0e494c34d2a75256819888361ef6e8c1b8b77",
}

PHOTO = b"\xff\xd8\xff\xe0" + bytes(range(256)) * 4  # a JPEG signature, then opaque bytes
_submission = itertools.count()


async def run_tool(graph, name, arguments):
    """One model turn that calls one tool; returns the result text the model saw."""
    engine, requests, provider, transcript, artifacts, cid, cfg = graph
    provider.responses = [
        LLMResponse(tool_calls=[ToolCall("call", name, arguments)], stop_reason="tool_use"),
        LLMResponse(text="Done."),
    ]
    first = len(provider.calls)
    receipt = requests.submit({"client_submission_id": f"post-{next(_submission)}",
                               "conversation_id": cid, "text": "Post the file"})
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    assert requests.get_request(receipt["request_id"])["state"] == "completed"
    [result] = provider.calls[first + 1]["messages"][-1]["content"]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "call"
    return result["content"]


def retain(graph, data=PHOTO, *, media_type="image/jpeg", channel=None):
    """Retain one file as an MCP result would; return (manifest cursor, entry cursor)."""
    engine, requests, provider, transcript, artifacts, cid, cfg = graph
    owner = requests.authority.owner_id
    executor = engine.deps.tool_executor
    reference = executor.retain_attachments(
        [BinaryAttachment(data=data, media_type=media_type, content_index=1, kind="image")],
        tool_name="read_file", user_id=owner, channel_id=channel or cid)
    manifest = reference["retrieval"]["arguments"]["cursor"]
    snapshot, _ = executor._ensure_output_store().read(
        manifest, owner=owner, channel=channel or cid, authorize=lambda tool, hosts: True)
    [entry] = json.loads(snapshot.text)["attachments"]
    return manifest, entry["retrieval"]["arguments"]["cursor"]


def posted(graph):
    engine, requests, provider, transcript, artifacts, cid, cfg = graph
    return [(row["text"], artifact) for row in transcript.list(cid)["items"]
            for artifact in row.get("artifacts") or []]


def artifact_bytes(graph, artifact):
    engine, requests, provider, transcript, artifacts, cid, cfg = graph
    data = b""
    while len(data) < artifact["size"]:
        page = artifacts.read(artifact["ref"], len(data), artifacts.chunk_bytes,
                              owner=requests.authority.owner_id)
        data += base64.b64decode(page["data_b64"])
    return data


def test_lifted_odin_files_are_odins_4_24_0_bytes():
    root = Path(__file__).resolve().parents[1] / "src/tools"
    for name, digest in ODIN_V4_24_0_SHA256.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name


async def test_a_retained_file_is_posted_as_a_conversation_artifact(d17_graph):
    _, entry = retain(d17_graph)
    seen = await run_tool(d17_graph, "post_file",
                          {"attachment": entry, "caption": "The phone photo."})
    name = f"retained-{entry.split(':')[0][:8]}-1.jpg"
    assert seen == f"Posted `{name}` ({len(PHOTO) / 1024:.1f} KB) to conversation."
    [(text, artifact)] = posted(d17_graph)
    assert text == "The phone photo."
    assert (artifact["name"], artifact["mime"], artifact["kind"], artifact["size"]) == (
        name, "image/jpeg", "image", len(PHOTO))
    assert artifact_bytes(d17_graph, artifact) == PHOTO


async def test_posted_bytes_outlive_the_retained_evidence(d17_graph):
    """Posted bytes are transcript content: removing the evidence leaves the posted file."""
    engine, requests, *_ = d17_graph
    _, entry = retain(d17_graph)
    await run_tool(d17_graph, "post_file", {"attachment": entry})
    store = engine.deps.tool_executor._ensure_output_store()
    with sqlite3.connect(store.path) as db:
        db.execute("DELETE FROM output_blobs")
    [(_, artifact)] = posted(d17_graph)
    assert artifact_bytes(d17_graph, artifact) == PHOTO


async def test_a_later_turn_posts_a_file_an_earlier_turn_retained(d17_graph):
    _, entry = retain(d17_graph)
    await run_tool(d17_graph, "post_file", {"attachment": entry})
    seen = await run_tool(d17_graph, "post_file", {"attachment": entry, "caption": "Again."})
    assert seen.startswith("Posted `retained-")
    assert [text for text, _ in posted(d17_graph)] == ["", "Again."]


async def test_an_unrecognized_file_type_is_posted_as_a_plain_file(d17_graph):
    _, entry = retain(d17_graph, b"opaque \x00 bytes", media_type="application/x-unknown")
    seen = await run_tool(d17_graph, "post_file", {"attachment": entry})
    name = f"retained-{entry.split(':')[0][:8]}-1.bin"
    assert seen.startswith(f"Posted `{name}`")
    [(_, artifact)] = posted(d17_graph)
    assert (artifact["mime"], artifact["kind"]) == ("application/octet-stream", "file")


@pytest.mark.parametrize("case", ["manifest", "text", "page offset", "malformed", "both sources",
                                  "another conversation", "tampered bytes"])
async def test_refusals_post_nothing(d17_graph, case):
    engine, requests, provider, transcript, artifacts, cid, cfg = d17_graph
    owner = requests.authority.owner_id
    store = engine.deps.tool_executor._ensure_output_store()
    manifest, entry = retain(d17_graph)
    arguments = {"attachment": entry}
    expected = "Retained file unavailable: "
    if case == "manifest":
        arguments["attachment"] = manifest
        expected += "Not a retained file:"
    elif case == "text":
        text = store.retain("plain text output", owner=owner, channel=cid, tool="read_file")
        arguments["attachment"] = f"{text.result_id}:0"
        expected += "Not a retained file:"
    elif case == "page offset":
        arguments["attachment"] = entry.replace(":0", ":5")
        expected += "Not a whole-file cursor:"
    elif case == "malformed":
        arguments["attachment"] = "nope"
        expected += "Invalid output cursor."
    elif case == "both sources":
        arguments.update(host="localhost", path="/etc/hostname")
        expected = "Give either 'attachment' or 'host' and 'path', not both. Nothing was posted."
    elif case == "another conversation":
        _, arguments["attachment"] = retain(d17_graph, channel="another-conversation")
        expected += "Permission denied"
    else:
        with sqlite3.connect(store.path) as db:
            db.execute("UPDATE output_blobs SET data=? WHERE id=?",
                       (b"\xff\xd8 not the photo", entry.split(":")[0]))
        expected += "Retained file failed its integrity check"
    seen = await run_tool(d17_graph, "post_file", arguments)
    assert seen.startswith("Error (tool reported failure):"), seen
    assert expected in seen, seen
    assert posted(d17_graph) == []


@pytest.mark.parametrize("blank", [None, "", "   "])
async def test_a_blank_attachment_leaves_host_file_posting_as_it_was(d17_graph, blank):
    engine, requests, provider, transcript, artifacts, cid, cfg = d17_graph
    engine.deps.tool_executor.host_registry.publish({"localhost": ToolHost(address="localhost")})
    note = Path(cfg.tools.local_working_dir) / "note.txt"
    note.write_bytes(b"host file bytes\n")
    seen = await run_tool(d17_graph, "post_file", {
        "host": "localhost", "path": str(note), "caption": "From the host.", "attachment": blank})
    assert seen == "Posted `note.txt` (0.0 KB) to conversation."
    [(text, artifact)] = posted(d17_graph)
    assert (text, artifact["name"]) == ("From the host.", "note.txt")
    assert artifact_bytes(d17_graph, artifact) == b"host file bytes\n"


class _Untouchable:
    def __getattr__(self, name):
        raise AssertionError(f"post_file touched tool_executor.{name}")


class _Publishing(MediaTools):
    def _delivery_available(self):
        return True


@pytest.mark.parametrize("arguments, text", [
    ({"attachment": 7}, "'attachment' must be a retained-file cursor string."),
    ({"attachment": ["a:0"]}, "'attachment' must be a retained-file cursor string."),
    ({"attachment": "a:0", "host": "localhost"}, "not both. Nothing was posted."),
    ({"attachment": "a:0", "path": "/tmp/x"}, "not both. Nothing was posted."),
])
async def test_bad_sources_are_refused_before_anything_is_read(arguments, text):
    tools = _Publishing(get_config=lambda: None, browser_manager=None, tool_executor=_Untouchable())
    result = await tools._handle_post_file(None, arguments)
    assert is_tool_failure(result) and text in str(result)


class _Recording(_Publishing):
    def __init__(self, failure=None):
        super().__init__(get_config=lambda: None, browser_manager=None, tool_executor=object())
        self.published, self.failure = [], failure

    async def _publish_attachment(self, message, data, filename, caption=""):
        if self.failure:
            raise self.failure
        self.published.append((filename, len(data), caption))


def _stored(data):
    return SimpleNamespace(data=data, result_id="0123456789abcdef", content_index=2,
                           media_type="image/png")


@pytest.mark.parametrize("read, text", [
    (sqlite3.OperationalError("disk I/O error"),
     "Retained file storage is unavailable. Nothing was posted."),
    (OSError("gone"), "Retained file storage is unavailable. Nothing was posted."),
    (ValueError("undecodable metadata"),
     "Retained file storage is unavailable. Nothing was posted."),
    (_stored(b"\0" * (25 * 1024 * 1024 + 1)),
     "File too large to post (25.0 MB). Conversation attachment limit is 25 MB."),
])
async def test_storage_failures_and_oversized_files_publish_nothing(monkeypatch, read, text):
    def fake_read(executor, cursor):
        if isinstance(read, Exception):
            raise read
        return read

    monkeypatch.setattr(retained_files, "read_retained_file", fake_read)
    tools = _Recording()
    result = await tools._handle_post_file(None, {"attachment": "0123456789abcdef:0"})
    assert is_tool_failure(result) and str(result) == text
    assert tools.published == []


async def test_a_failed_publication_is_reported_not_posted(monkeypatch):
    monkeypatch.setattr(retained_files, "read_retained_file",
                        lambda executor, cursor: _stored(b"\x89PNG\r\n\x1a\nimage"))
    tools = _Recording(failure=RuntimeError("the conversation sink is closed"))
    result = await tools._handle_post_file(None, {"attachment": "0123456789abcdef:0"})
    assert is_tool_failure(result)
    assert str(result) == "Failed to upload to the conversation: the conversation sink is closed"
    published = _Recording()
    monkeypatch.setattr(retained_files, "read_retained_file",
                        lambda executor, cursor: _stored(b"\x89PNG\r\n\x1a\nimage"))
    ok = await published._handle_post_file(
        None, {"attachment": "0123456789abcdef:0", "caption": "c"})
    assert ok == "Posted `retained-01234567-2.png` (0.0 KB) to conversation."
    assert published.published == [("retained-01234567-2.png", 13, "c")]


async def test_unavailable_publication_reads_nothing():
    tools = MediaTools(get_config=lambda: None, browser_manager=None, tool_executor=_Untouchable())
    result = await tools._handle_post_file(None, {"attachment": "a:0"})
    assert (result.ok, result.error, result.output) == (
        False, "conversation_delivery_unavailable", _DELIVERY_UNAVAILABLE)


def test_a_binary_page_names_its_posting_cursor_and_keeps_its_bytes(d17_graph):
    engine, requests, provider, transcript, artifacts, cid, cfg = d17_graph
    owner = requests.authority.owner_id
    _, entry = retain(d17_graph)
    snapshot, offset = engine.deps.tool_executor._ensure_output_store().read(
        entry, owner=owner, channel=cid, authorize=lambda tool, hosts: True)
    page = json.loads(render_page(snapshot, offset=offset, limit=4000, budget=12000))
    assert page["post"] == {"tool": "post_file", "arguments": {"attachment": entry}}
    assert base64.b64decode(page["data_base64"]) == PHOTO[page["start"]:page["end"]]
    # Smaller pages: every page names the whole file's cursor and the bytes still join.
    joined, start = b"", 0
    while start < len(PHOTO):
        page = json.loads(render_page(snapshot, offset=start, limit=400, budget=12000))
        assert page["post"]["arguments"]["attachment"] == entry
        assert page["start"] == start and page["end"] > start
        joined += base64.b64decode(page["data_base64"])
        start = page["end"]
    assert joined == PHOTO


async def test_a_file_is_refused_once_output_retrieval_is_disabled(d17_graph):
    engine, requests, provider, transcript, artifacts, cid, cfg = d17_graph
    _, entry = retain(d17_graph)
    engine.deps.tool_executor.config.disabled_tools = ["get_tool_output"]
    seen = await run_tool(d17_graph, "post_file", {"attachment": entry})
    assert "Retained file unavailable: Permission denied: retrieval of retained files is not " \
        "authorized." in seen
    assert posted(d17_graph) == []


@pytest.mark.parametrize("data, media_type, extension", [
    (b"\x89PNG\r\n\x1a\n...", "application/octet-stream", ".png"),
    (b"\xff\xd8\xff...", "image/png", ".jpg"),
    (b"GIF87a...", "", ".gif"),
    (b"GIF89a...", "", ".gif"),
    (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "", ".webp"),
    (b"RIFF\x00\x00\x00\x00WAVEfmt ", "", ".bin"),
    (b"%PDF-1.7", "application/pdf; charset=binary", ".pdf"),
])
def test_names_follow_the_bytes_signature_then_the_declared_type(data, media_type, extension):
    snapshot = SimpleNamespace(data=data, media_type=media_type, result_id="fedcba9876543210",
                               content_index=3)
    assert retained_files.retained_filename(snapshot) == f"retained-fedcba98-3{extension}"
