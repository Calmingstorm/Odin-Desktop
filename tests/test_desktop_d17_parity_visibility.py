"""Catalog repairs use real owners, durable effects and no network transports."""
import asyncio
import base64
import errno
import io
import os
import stat
from pathlib import Path

import pytest
import pytest_asyncio
from PIL import Image

from src.desktop.artifacts import ArtifactStore
from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import ArtifactPublisher, DurableDelivery, PublicationEventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.requests import RequestService
from src.desktop.services import build_engine_services
from src.desktop.transcript import TranscriptStore
from src.discord.native_tools.media import MediaTools
from src.llm.codex_auth import CodexAuth
from src.llm.types import LLMResponse, ToolCall
from src.permissions.manager import PermissionManager
from src.tools.image import ImageResult
from tests.test_desktop_engine_services import Provider


@pytest_asyncio.fixture
async def graph(tmp_path, monkeypatch):
    import aiohttp

    from src.config.schema import Config

    def no_network(*args, **kwargs):
        raise AssertionError("No real network in D17 owner qualification")

    monkeypatch.setattr(aiohttp, "ClientSession", no_network)
    paths = ProfilePaths.from_xdg("d17-parity", home=tmp_path, environ={})
    authority = OwnerAuthority(paths)
    permissions = PermissionManager(authority)
    binding = permissions.set_request_owner(
        authority.authenticate_local(peer_uid=authority.owner_uid))
    store = JournalStore(paths.data_dir / "transport.sqlite3", paths.profile_id)
    events = PublicationEventJournal(store)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    delivery = DurableDelivery(store, events, transcript_commit=transcript.commit)
    cfg = Config()
    cfg.openai_codex.enabled = True
    cfg.openai_codex.credentials_path = str(paths.secrets_dir / "codex_auth.json")
    cfg.image.openai.enabled = True
    cfg.context.directory = str(paths.data_dir / "context")
    cfg.attachments.temp_directory = str(paths.cache_dir / "attachments")
    cfg.llm_provider.model = "compat:test"
    cfg.openai_compatible.enabled = True
    cfg.learning.enabled = False
    # Generated images keep a local copy in the workspace: never the real default one.
    cfg.tools.local_working_dir = str(paths.data_dir.parent / "workspace")
    (paths.data_dir.parent / "workspace").mkdir(mode=0o700)
    auth = CodexAuth(cfg.openai_codex.credentials_path)
    auth._save({"access_token": "d17-inert", "account_id": "d17-local", "expires_at": 4102444800})
    provider = Provider([])
    engine = build_engine_services(cfg, paths, permissions, delivery=delivery,
                                    compatible_client=provider)
    requests = RequestService(store, conversations, transcript, engine=engine,
        permissions=permissions, authority=authority, delivery=delivery)
    engine.bind_requests(requests)
    artifacts = ArtifactStore(store, authorize=engine.deps.tool_executor._authorize_output)
    delivery.artifact_converter = ArtifactPublisher(artifacts, events)
    cid = conversations.create()["conversation"]["id"]
    try:
        yield engine, requests, provider, transcript, artifacts, cid, cfg
    finally:
        await requests.close()
        await engine.close()
        assert not engine.deps.knowledge_store.available
        assert engine.deps.image_backend._session is None
        store.close()
        permissions.reset_request_owner(binding)
        authority.release_runtime()


async def execute(graph, calls):
    engine, requests, provider, transcript, artifacts, cid, cfg = graph
    provider.responses = [LLMResponse(tool_calls=calls, stop_reason="tool_use"),
                          LLMResponse(text="The requested operation is complete.")]
    receipt = requests.submit({"client_submission_id": "proof", "conversation_id": cid,
                               "text": "Execute the requested tools"})
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    assert requests.get_request(receipt["request_id"])["state"] == "completed"


async def test_knowledge_catalog_is_backed_by_durable_profile_store(graph):
    engine, requests, provider, transcript, artifacts, cid, cfg = graph
    assert engine.deps.knowledge_store.available
    await execute(graph, [ToolCall("ingest", "ingest_document", {
        "source": "d17-proof", "content": "The parity owner keeps durable knowledge."})])
    assert "ingest_document" in {tool["name"] for tool in provider.calls[0]["tools"]}
    assert any(row["source"] == "d17-proof" for row in engine.deps.knowledge_store.list_sources())
    cfg.search.enabled = False
    assert "ingest_document" not in {
        tool["name"] for tool in engine.deps.tool_catalog.merged_definitions()}
    result, _ = await engine.deps.native_tools.dispatch("ingest_document", {
        "source": "denied", "content": "must not persist"}, message=object(),
        user_id=requests.authority.owner_id, skill_file_delivery="send")
    assert not result.ok and result.error == "tool_unavailable"
    assert all(row["source"] != "denied" for row in engine.deps.knowledge_store.list_sources())


async def test_image_auth_visibility_has_real_selector_and_durable_publication(graph, monkeypatch):
    engine, requests, provider, transcript, artifacts, cid, cfg = graph
    backend = engine.deps.image_backend
    assert backend.is_configured()
    assert engine.deps.native_tools.owners["media"].image_selector.openai is backend
    image = io.BytesIO()
    Image.new("RGB", (2, 2), "blue").save(image, format="PNG")
    data = image.getvalue()
    seen = []

    async def generate(*, prompt):
        seen.append(prompt)
        return ImageResult(data, "image/png", 2, 2, "openai", "inert-network-fixture")

    monkeypatch.setattr(backend, "generate", generate)
    await execute(graph, [ToolCall("image", "generate_image", {"prompt": "two blue pixels"})])
    assert seen == ["two blue pixels"]
    assert "generate_image" in {tool["name"] for tool in provider.calls[0]["tools"]}
    files = [row for row in transcript.list(cid)["items"] if row.get("artifacts")]
    assert len(files) == 1
    page = artifacts.read(files[0]["artifacts"][0]["ref"], 0, 1024,
                          owner=requests.authority.owner_id)
    assert base64.b64decode(page["data_b64"]) == data
    cfg.image.openai.enabled = False
    assert "generate_image" not in {
        tool["name"] for tool in engine.deps.tool_catalog.merged_definitions()}
    result, _ = await engine.deps.native_tools.dispatch("generate_image", {"prompt": "denied"},
        message=object(), user_id=requests.authority.owner_id, skill_file_delivery="send")
    assert not result.ok and result.error == "tool_unavailable"
    assert seen == ["two blue pixels"]


async def test_generated_image_result_names_no_attachment_url(graph, monkeypatch, tmp_path):
    """Approved D19-031: a durable artifact replaces Odin's Discord attachment URL.

    1.0.2 (D17 parity): the result names the owner-only local copy instead, so the model can
    open its image again the way Odin uses the attachment URL.
    """
    engine, requests, provider, transcript, artifacts, cid, cfg = graph
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    cfg.tools.local_working_dir = str(workspace)
    image = io.BytesIO()
    Image.new("RGB", (2, 2), "green").save(image, format="PNG")

    async def generate(*, prompt):
        return ImageResult(image.getvalue(), "image/png", 2, 2, "openai", "inert-network-fixture")

    monkeypatch.setattr(engine.deps.image_backend, "generate", generate)
    owner = engine.deps.native_tools.owners["media"]
    original = type(owner)._handle_generate_image
    results = []

    async def recorded(self, message, inp):
        result = await original(self, message, inp)
        results.append(result)
        return result

    monkeypatch.setattr(type(owner), "_handle_generate_image", recorded)
    await execute(graph, [ToolCall("image", "generate_image", {"prompt": "two green pixels"})])
    [result] = results
    assert result.ok
    assert result.audit_metadata["delivery_status"] == "posted"
    assert result.audit_metadata["attachment_url_available"] is False
    assert result.output.startswith("Image generated (2x2, ")
    suffix = " and posted. Local file on localhost: "
    assert suffix in result.output
    saved = Path(result.output.split(suffix, 1)[1])
    assert saved.parent == workspace / "generated-images"
    assert saved.read_bytes() == image.getvalue()
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    assert result.audit_metadata["local_copy_available"] is True
    assert "URL" not in result.output and "http" not in result.output
    assert result.output in str(provider.calls[1]["messages"])
    files = [row for row in transcript.list(cid)["items"] if row.get("artifacts")]
    assert len(files) == 1


async def test_browser_screenshot_result_names_a_local_copy(graph, monkeypatch, tmp_path):
    """L7 (1.0.5): a screenshot reached the chat but not the model, so Odin could not read
    his own screenshot. As for generated images (1.0.2), the result names a local copy."""
    from src.tools import browser as browser_tools

    engine, requests, provider, transcript, artifacts, cid, cfg = graph
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    cfg.tools.local_working_dir = str(workspace)
    cfg.browser.enabled = True
    image = io.BytesIO()
    Image.new("RGB", (2, 2), "blue").save(image, format="PNG")

    summary_text = "Screenshot of **Example** (https://example.test/) — HTTP 200, 1 KB"

    async def screenshot(manager, inp):
        assert inp == {"url": "https://example.test/"}
        return summary_text, image.getvalue()

    monkeypatch.setattr(browser_tools, "handle_browser_screenshot", screenshot)
    policy = engine.deps.tool_executor._builtin_policy
    ready = policy._get_readiness
    monkeypatch.setattr(policy, "_get_readiness", lambda: {**ready(), "browser_screenshot": True})
    owner = engine.deps.native_tools.owners["media"]
    monkeypatch.setattr(owner, "browser_manager", object())
    original = type(owner)._handle_browser_screenshot
    results = []

    async def recorded(self, message, inp):
        results.append(await original(self, message, inp))
        return results[-1]

    monkeypatch.setattr(type(owner), "_handle_browser_screenshot", recorded)
    await execute(graph, [ToolCall("shot", "browser_screenshot", {"url": "https://example.test/"})])
    [result] = results
    summary, location = result.split("\n")
    assert summary == summary_text
    assert location.startswith("Local file on localhost: ")
    saved = Path(location.removeprefix("Local file on localhost: "))
    assert saved.parent == workspace / "screenshots"
    assert saved.read_bytes() == image.getvalue()
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    assert summary in str(provider.calls[1]["messages"])
    files = [row for row in transcript.list(cid)["items"] if row.get("artifacts")]
    assert len(files) == 1


async def test_generated_image_without_a_local_copy_is_still_posted(graph, monkeypatch):
    engine, _requests, _provider, transcript, _artifacts, cid, _cfg = graph
    image = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(image, format="PNG")

    async def generate(*, prompt):
        return ImageResult(image.getvalue(), "image/png", 2, 2, "openai", "inert-network-fixture")

    def unwritable(self, data):
        raise OSError("read-only workspace")

    monkeypatch.setattr(engine.deps.image_backend, "generate", generate)
    owner = engine.deps.native_tools.owners["media"]
    monkeypatch.setattr(type(owner), "_retain_generated_image", unwritable)
    original = type(owner)._handle_generate_image
    results = []

    async def recorded(self, message, inp):
        results.append(await original(self, message, inp))
        return results[-1]

    monkeypatch.setattr(type(owner), "_handle_generate_image", recorded)
    await execute(graph, [ToolCall("image", "generate_image", {"prompt": "two red pixels"})])
    [result] = results
    assert result.ok and result.output.endswith(" and posted.")
    assert result.audit_metadata["local_copy_available"] is False
    assert len([row for row in transcript.list(cid)["items"] if row.get("artifacts")]) == 1



async def _generate_once(graph, monkeypatch, color):
    engine = graph[0]
    image = io.BytesIO()
    Image.new("RGB", (2, 2), color).save(image, format="PNG")

    async def generate(*, prompt):
        return ImageResult(image.getvalue(), "image/png", 2, 2, "openai", "inert-network-fixture")

    monkeypatch.setattr(engine.deps.image_backend, "generate", generate)
    owner = engine.deps.native_tools.owners["media"]
    original = type(owner)._handle_generate_image
    results = []

    async def recorded(self, message, inp):
        results.append(await original(self, message, inp))
        return results[-1]

    monkeypatch.setattr(type(owner), "_handle_generate_image", recorded)
    await execute(graph, [ToolCall("image", "generate_image", {"prompt": f"two {color} pixels"})])
    [result] = results
    return result


@pytest.mark.parametrize("folder", ["permissive", "linked"])
async def test_generated_image_copy_needs_a_private_folder_of_its_own(graph, monkeypatch, tmp_path,
                                                                     folder):
    """An existing shared folder, or a link elsewhere, gets no copy; the image is still posted."""
    cfg = graph[-1]
    workspace = Path(cfg.tools.local_working_dir)
    outside = tmp_path / "outside"
    outside.mkdir()
    if folder == "permissive":
        (workspace / "generated-images").mkdir()
        (workspace / "generated-images").chmod(0o755)
        target = workspace / "generated-images"
    else:
        outside.chmod(0o777)
        (workspace / "generated-images").symlink_to(outside, target_is_directory=True)
        target = outside
    result = await _generate_once(graph, monkeypatch, "blue")
    assert result.ok and result.output.endswith(" and posted.")
    assert result.audit_metadata["local_copy_available"] is False
    assert list(target.iterdir()) == []
    if folder == "permissive":
        assert stat.S_IMODE(target.stat().st_mode) == 0o755  # never chmod'ed behind the owner


async def test_generated_image_copy_never_replaces_an_existing_file(graph, monkeypatch):
    engine, cfg = graph[0], graph[-1]
    folder = Path(cfg.tools.local_working_dir) / "generated-images"
    folder.mkdir(mode=0o700)
    owner = engine.deps.native_tools.owners["media"]
    monkeypatch.setattr(type(owner), "_generated_image_name",
                        staticmethod(lambda: "20260101-000000-01234567.png"))
    existing = folder / "20260101-000000-01234567.png"
    existing.write_bytes(b"keep me")
    result = await _generate_once(graph, monkeypatch, "green")
    assert result.ok and result.output.endswith(" and posted.")
    assert existing.read_bytes() == b"keep me"
    assert sorted(path.name for path in folder.iterdir()) == [existing.name]


async def test_generated_image_copy_that_fails_midway_leaves_no_partial_file(graph, monkeypatch):
    """A write that fails part-way, as on a full disk, removes what landed and reports it."""
    engine, cfg = graph[0], graph[-1]
    owner = engine.deps.native_tools.owners["media"]
    folder = Path(cfg.tools.local_working_dir) / "generated-images"
    real_fdopen = os.fdopen

    class FullDisk:
        def __init__(self, fd, mode):
            self.handle = real_fdopen(fd, mode)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.handle.close()

        def write(self, data):
            self.handle.write(data[:16])  # part of the image lands first
            raise OSError(errno.ENOSPC, "inert: no space left on device")

    with monkeypatch.context() as m:
        m.setattr(os, "fdopen", FullDisk)
        with pytest.raises(OSError, match="no space left"):
            owner._retain_generated_image(b"\x89PNG\r\n\x1a\n" + bytes(64))
    assert folder.is_dir() and list(folder.iterdir()) == []


def test_the_shared_media_tool_keeps_no_local_copy_itself():
    """Odin's media tool keeps no copy; only an embedder that overrides the hook (Desktop) does."""
    assert MediaTools._retain_generated_image(object(), b"\x89PNG\r\n\x1a\n") is None



async def test_failed_image_analysis_settles_as_a_failure(graph, monkeypatch):
    """L11 (1.0.5): analyze_image returned its failures as plain text, so they settled as
    success and the chat showed a check mark beside "Unsupported image format" (an SVG)."""
    import json
    from types import SimpleNamespace

    from src.tools import safe_fetch

    engine, requests, provider, transcript, artifacts, cid, cfg = graph

    async def svg(url, **kwargs):
        return SimpleNamespace(status=200, content_type="image/svg+xml", body=b"<svg/>")

    monkeypatch.setattr(safe_fetch, "safe_fetch", svg)
    await execute(graph, [ToolCall("img", "analyze_image", {"url": "https://example.test/a.svg"})])
    settled = [json.loads(row[0])["payload"] for row in requests.store.connection.execute(
        "SELECT payload FROM desktop_delivery_outbox WHERE kind='tool.settled'")]
    assert [(row["invocation_id"], row["outcome"]) for row in settled] == [("img", "failure")]
    assert "Unsupported image format" in str(provider.calls[1]["messages"])


async def test_native_handlers_return_failures_as_failures_and_empty_answers_as_answers(graph):
    from src.tools.execution_outcome import ToolFailure, is_tool_failure

    engine, *_ = graph
    owners = engine.deps.native_tools.owners
    failures = [
        await owners["media"]._handle_post_file(None, {}),
        await owners["media"]._handle_analyze_image(None, {}),
        await owners["media"]._handle_analyze_image(None, {"url": "ftp://example.test/a.png"}),
        await owners["knowledge"]._handle_ingest_document({}, "owner"),
        await owners["knowledge"]._handle_delete_knowledge({"source": "never-added"}),
        await owners["channel_ops"]._handle_read_conversation(None, {"conversation": "other"}),
    ]
    for result in failures:
        assert isinstance(result, ToolFailure) and is_tool_failure(result), result
    assert failures[0] == "Both 'host' and 'path' are required."
    assert failures[4] == "No document found with source 'never-added'."
    # An empty answer is an answer, not a failure.
    found = await owners["knowledge"]._handle_search_knowledge({"query": "nothing stored"})
    assert not is_tool_failure(found)
