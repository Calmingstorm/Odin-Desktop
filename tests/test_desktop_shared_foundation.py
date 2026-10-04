"""Broad frozen foundation qualification, no original assertion rewriting."""
import ast

import pytest

from scripts.maintenance.fixture_corpus import corpus, frozen_source, verify_transform
from tests.desktop_adapters.foundation_cases import CORPUS_SELECTIONS, adapted_tree, export_suite
from tests.desktop_adapters.tools_cases import owner_fixture


@pytest.fixture(autouse=True)
def desktop_foundation_owner(tmp_path_factory):
    with owner_fixture(tmp_path_factory.mktemp("foundation-owner")):
        yield


@pytest.fixture(autouse=True)
def static_catalog_provider_for_pure_merge_cases(request, monkeypatch):
    """Pure merge algorithms receive explicit static schemas, not runtime grants.

    Patch only the provider dependency of the real retained catalog and only
    for the four original pure merge cases. Runtime tests keep the fail-closed
    readiness getter. No privileged shim or alternative catalog implementation.
    """
    if "Test_test_builtin_tool_policy_TestCatalogFiltering" in request.node.nodeid:
        from src.discord import tool_catalog
        from src.tools.registry import get_documentation_tool_definitions

        monkeypatch.setattr(tool_catalog, "get_tool_definitions",
                            get_documentation_tool_definitions)


@pytest.mark.parametrize("name", list(CORPUS_SELECTIONS))
def test_frozen_foundation_assertions_parameters_and_setup_hashes(name):
    path = f"tests/{name}.py"
    original = ast.parse(frozen_source(path))
    adapted = adapted_tree(name)
    assert corpus(original) == corpus(adapted)
    assert verify_transform(path, original, adapted)


for _suite in CORPUS_SELECTIONS:
    export_suite(globals(), _suite)


@pytest.mark.parametrize("path", ["outbound_webhooks.targets", "mcp.servers"])
def test_retained_secret_containers_remain_nonpublic(path):
    from src.config.apply_registry import spec_for

    assert spec_for(path).sensitivity == "secret_container"


@pytest.mark.parametrize("identity", [None, "unknown", "owner"])
def test_permission_owner_identity_is_not_ambient_authority(tmp_path, identity):
    from src.desktop.authority import OwnerAuthority
    from src.desktop.paths import ProfilePaths
    from src.permissions.manager import PermissionManager

    paths = ProfilePaths.from_xdg(environ={
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }, home=tmp_path)
    authority = OwnerAuthority(paths)
    try:
        manager = PermissionManager(authority)
        assert not manager.is_owner(identity)
        assert manager.filter_tools(identity, [{"name": "read_file"}]) is None
        assert manager.allowed_tool_names(identity) == set()
    finally:
        authority.release_runtime()


@pytest.mark.parametrize("payload", ["{bad", '{"allowed_hosts":"srv"}',
                                      '{"allowed_hosts":["srv"],"default_host":"x"}',
                                      '["not", "a", "dict"]',
                                      '{"allowed_hosts":[1]}',
                                      '{"allowed_hosts":[],"default_host":1}',
                                      '{"unexpected":true}'])
def test_host_corrupt_store_denies_authenticated_owner(tmp_path, payload):
    from src.permissions.host_access import HostAccessManager
    from src.permissions.persistence import write_private_atomic
    from tests.desktop_adapters.tools_cases import _fixture

    state = _fixture.get()
    path = tmp_path / "host-policy.json"
    write_private_atomic(path, payload)
    manager = HostAccessManager(path, available_hosts=["srv"], permission_manager=state.manager)
    assert manager.get_allowed_hosts(state.authority.owner_id) == []
    assert manager.get_default_host(state.authority.owner_id) == ""
    assert not manager.is_host_allowed(state.authority.owner_id, "srv")


async def test_host_corrupt_store_refuses_owner_mutation_and_preserves_backup(tmp_path):
    from src.json_store import StoreCorruptError
    from src.permissions.host_access import HostAccessManager
    from src.permissions.persistence import write_private_atomic
    from tests.desktop_adapters.tools_cases import _fixture

    state = _fixture.get()
    path = tmp_path / "hosts.json"
    original = '{"allowed_hosts":["alpha"], TRUNC'
    write_private_atomic(path, original)
    manager = HostAccessManager(path, available_hosts=["alpha"], permission_manager=state.manager)
    assert manager.get_allowed_hosts(state.authority.owner_id) == []
    token = manager.set_request_host_scope(["alpha"])
    try:
        assert manager.get_allowed_hosts(state.authority.owner_id) == []
        assert manager.get_default_host(state.authority.owner_id) == ""
    finally:
        manager.reset_request_host_scope(token)
    with pytest.raises(StoreCorruptError):
        await manager.set_policy(state.authority.owner_id, ["alpha"], "alpha")
    assert path.read_text() == original
    assert [backup.read_text() for backup in tmp_path.glob("hosts.json.corrupt-*")] == [original]


async def test_host_policy_owner_revocation_and_narrowing(tmp_path):
    from src.permissions.host_access import HostAccessManager
    from tests.desktop_adapters.tools_cases import _fixture

    state = _fixture.get()
    manager = HostAccessManager(tmp_path / "hosts.json", available_hosts=["alpha", "beta"],
                                permission_manager=state.manager)
    assert await manager.set_policy(state.authority.owner_id, ["alpha", "beta"], "alpha")
    assert manager.get_allowed_hosts(state.authority.owner_id) == ["alpha", "beta"]
    token = manager.set_request_host_scope(["beta"])
    try:
        assert manager.get_allowed_hosts(state.authority.owner_id) == ["beta"]
        assert manager.get_default_host(state.authority.owner_id) == ""
    finally:
        manager.reset_request_host_scope(token)
    assert manager.get_allowed_hosts("unauthenticated") == []
    with pytest.raises(PermissionError):
        await manager.set_policy("unauthenticated", ["alpha"])


@pytest.mark.parametrize("ready", [None, {}, {"run_command": False},
                                  {"run_command": 1}, {"run_command": True}])
def test_builtin_live_readiness_requires_literal_true(ready):
    from src.config.schema import Config
    from src.tools.builtin_policy import BuiltinToolPolicy

    policy = BuiltinToolPolicy(lambda: Config(), lambda: ready)
    assert policy.is_available("run_command") is (ready == {"run_command": True}
                                                 and ready.get("run_command") is True)
    assert not policy.is_available("nonexistent_tool")


async def test_skills_real_owner_delegation_keeps_requester_and_path_fence(tmp_path):
    from unittest.mock import AsyncMock, MagicMock

    from tests.desktop_adapters.foundation_cases import skill_context_fixture
    from tests.desktop_adapters.tools_cases import _fixture

    executor = MagicMock()
    executor.execute = AsyncMock(return_value="tool output")
    context = skill_context_fixture(tool_executor=executor, skill_name="fixture")
    owner = _fixture.get().authority.owner_id
    assert await context.run_on_host("srv", "true") == "tool output"
    executor.execute.assert_awaited_once_with(
        "run_command", {"host": "srv", "command": "true"}, user_id=owner,
    )
    assert "Access denied" in await context.read_file("srv", str(tmp_path / ".env"))
    assert executor.execute.await_count == 1
    assert context.get_hosts() == ["srv"]


def test_skill_allowed_urls_are_instance_scoped():
    from unittest.mock import MagicMock

    from src.tools.skill_context import SkillContext

    first = SkillContext(MagicMock(), "first", allowed_urls=("https://one.invalid/",))
    second = SkillContext(MagicMock(), "second", allowed_urls=("https://two.invalid",))
    assert first._allowed_urls == ("https://one.invalid",)
    assert second._allowed_urls == ("https://two.invalid",)


async def test_skill_knowledge_neutral_delegations_are_not_history_wiring():
    from unittest.mock import AsyncMock, MagicMock

    from src.tools.skill_context import SkillContext

    store = MagicMock()
    store.search_hybrid = AsyncMock(return_value=[{"content": "x"}])
    store.ingest = AsyncMock(return_value=3)
    context = SkillContext(MagicMock(), "fixture", knowledge_store=store, embedder=object())
    assert (await context.search_knowledge("q"))[0]["content"] == "x"
    assert await context.ingest_document("text", "source") == 3
    empty = SkillContext(MagicMock(), "empty")
    assert await empty.search_knowledge("q") == []
    assert await empty.ingest_document("text", "source") == 0


def test_schema_retained_container_ancestry_and_secret_facts():
    from src.config.apply_registry import build_meta_payload, schema_facts

    records = build_meta_payload({"tools": {"hosts": {"prod": {
        "address": "example.invalid", "ssh_user": "deploy", "description": "test",
    }}}})["fields"]
    assert len(records) == 3
    assert all(record["structured_container_child"] for record in records)
    assert "outbound_webhooks.targets.secret" in schema_facts()


def test_retained_list_record_redaction_preserves_public_siblings():
    from src.config.apply_registry import REDACTED, build_meta_payload

    records = build_meta_payload({"outbound_webhooks": {"targets": [{
        "name": "fixture", "url": "https://example.invalid", "secret": "SYNTHETIC-SECRET",
    }]}})["fields"]
    fields = {row["path"]: row for row in records}
    assert fields["outbound_webhooks.targets.0.name"]["desired"] == "fixture"
    assert fields["outbound_webhooks.targets.0.url"]["desired"] == "https://example.invalid"
    assert fields["outbound_webhooks.targets.0.secret"]["desired"] == REDACTED
    assert "SYNTHETIC-SECRET" not in str(records)


def test_retained_workspace_fence_set_and_restart_truth():
    from src.config.apply_registry import spec_for
    from src.config.workspace_paths import WORKSPACE_PROTECTED_CONFIG_PATH_NAMES
    from src.tools.workspace import _DECLARED_STATE_PATHS

    assert WORKSPACE_PROTECTED_CONFIG_PATH_NAMES == {path for path, _ in _DECLARED_STATE_PATHS}
    assert WORKSPACE_PROTECTED_CONFIG_PATH_NAMES
    for path in WORKSPACE_PROTECTED_CONFIG_PATH_NAMES:
        consumers = [consumer for consumer in spec_for(path).consumers
                     if consumer.name == "Local command workspace fence"]
        assert len(consumers) == 1
        assert consumers[0].apply_mode == "restart"


async def test_knowledge_explicit_root_denies_sibling(tmp_path):
    from src.knowledge.importer import BulkImporter
    from src.knowledge.store import KnowledgeStore

    root = tmp_path / "admitted"
    root.mkdir()
    sibling = tmp_path / "not-admitted.md"
    sibling.write_text("not admitted")
    store = KnowledgeStore(str(tmp_path / "knowledge.db"))
    try:
        importer = BulkImporter(store, admitted_roots=(root,))
        result = await importer.import_file(str(sibling))
        assert result.status == "error"
        assert "allowed import roots" in result.error
        assert store.list_sources() == []
    finally:
        store.close()


def test_documentation_generation_is_pure_and_current_catalog_only(monkeypatch):
    import socket

    from scripts.docs.generate_tool_reference import generate
    from src import config
    from src.config import schema
    from src.tools.registry import TOOLS
    from src.tools.skill_manager import SkillManager

    def forbidden(*args, **kwargs):
        raise AssertionError("documentation attempted runtime discovery or network")

    monkeypatch.setattr(config, "_load_env", forbidden)
    monkeypatch.setattr(schema, "load_config", forbidden)
    monkeypatch.setattr(SkillManager, "get_tool_definitions", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "bind", forbidden)
    text = generate()
    assert f"**{len(TOOLS)} built-in tools**" in text
    assert "### read_conversation\n" in text
    assert "### read_channel\n" not in text


async def test_skill_missing_delivery_and_destination_fail_explicitly():
    from unittest.mock import MagicMock

    from src.tools.skill_context import SkillContext

    context = SkillContext(MagicMock(), "fixture")
    for call in (lambda: context.post_message("hello"),
                 lambda: context.post_file(b"x", "x.txt"),
                 lambda: context.search_history("q"),
                 lambda: context.schedule_task("test", "reminder", "untrusted-id"),
                 lambda: context.update_schedule("S1"),
                 lambda: context.delete_schedule("S1")):
        with pytest.raises(RuntimeError, match="unavailable"):
            await call()


def test_builtin_static_catalog_publishes_real_schemas():
    from src.tools.registry import get_documentation_tool_definitions

    schemas = get_documentation_tool_definitions()
    assert schemas
    assert all(isinstance(tool["input_schema"], dict) for tool in schemas)
    run = next(tool for tool in schemas if tool["name"] == "run_command")
    assert "command" in run["input_schema"]["properties"]


def test_catalog_default_runtime_withholds_unready_builtins():
    from src.config.schema import Config
    from src.discord.tool_catalog import ToolCatalog

    class EmptySkills:
        def get_tool_definitions(self):
            return []

    catalog = ToolCatalog(get_config=Config, skill_manager=EmptySkills())
    assert catalog.merged_definitions(cache_result=False) == []


@pytest.mark.parametrize("name", ["run_command", "fetch_url", "computer_act"])
def test_catalog_unready_builtin_names_remain_reserved(name):
    from src.config.schema import Config
    from src.discord.tool_catalog import ToolCatalog

    definition = {"name": name, "description": "shadow", "input_schema": {"type": "object"}}

    class Shadows:
        def get_tool_definitions(self):
            return [definition]

    catalog = ToolCatalog(get_config=Config, skill_manager=Shadows(),
                          get_mcp_definitions=lambda: [definition])
    assert name not in [tool["name"] for tool in catalog.merged_definitions(cache_result=False)]


def test_current_documentation_catalog_order_sections_and_exact_counts():
    import re

    from scripts.docs.generate_tool_reference import OUTPUT, generate, tool_sections
    from src.tools.registry import TOOLS

    text = generate()
    assert OUTPUT.read_bytes() == text.encode("utf-8")
    assert re.findall(r"^### (.+)$", text, re.M) == [tool["name"] for tool in TOOLS]
    assert [tool["name"] for _, section in tool_sections() for tool in section] == [
        tool["name"] for tool in TOOLS
    ]
    assert len({tool["name"] for tool in TOOLS}) == len(TOOLS)
    assert f"**{len(TOOLS)} built-in tools**" in text


async def test_skill_safe_call_limit_and_denial_without_unsafe_literal():
    from unittest.mock import AsyncMock, MagicMock

    from src.tools.skill_context import MAX_SKILL_TOOL_CALLS, SkillContext

    executor = MagicMock()
    executor.execute = AsyncMock(return_value="tool output")
    context = SkillContext(executor, "fixture")
    assert "not allowed" in await context.execute_tool("run_command", {"command": "true"})
    assert await context.execute_tool("web_search", {"q": "fixture"}) == "tool output"
    assert "Access denied" in await context.execute_tool("read_file", {"path": "/tmp/.env"})
    context._tracker.tool_calls = MAX_SKILL_TOOL_CALLS
    assert "limit" in await context.execute_tool("web_search", {})
    assert executor.execute.await_count == 1
