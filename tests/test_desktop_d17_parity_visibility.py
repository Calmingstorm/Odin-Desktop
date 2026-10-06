"""Catalog repairs use real owners, durable effects and no network transports."""
import asyncio
import base64
import io

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
