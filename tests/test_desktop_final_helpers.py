"""Final neutral helper proofs and named, effect-free Phase 2 boundaries."""

from __future__ import annotations

import ast
import re
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from src.config.apply_registry import (
    HEALTH_STATES,
    SECTIONS,
    build_field_record,
    build_meta_payload,
    schema_facts,
)
from src.config.schema import Config, ToolsConfig
from src.discord.native_tools.knowledge import KnowledgeTools
from src.error_presentation import format_user_facing_error
from src.knowledge.importer import BulkImporter
from src.knowledge.store import KnowledgeStore
from src.search.errors import validate_search_query
from src.tools.builtin_policy import BuiltinToolPolicy
from src.tools.executor import ToolExecutor
from tests.desktop_adapters.final_helpers import (
    CASE_MAP,
    export_error_exact,
    export_exact,
    verified_error_tree,
    verified_tree,
)
from tests.desktop_adapters.tools_cases import owner_fixture

export_exact(globals())
export_error_exact(globals())


def test_exact_full_tree_assertions_parameters_and_setup_hashes():
    original = ast.parse(frozen_source("tests/test_apply_registry.py"))
    adapted, changes = verified_tree("test_apply_registry")
    assert corpus(original) == corpus(adapted)
    assert len(CASE_MAP) == 6
    assert len(changes) == 5
    assert corpus(ast.parse(frozen_source("tests/test_error_presentation.py"))) == corpus(
        verified_error_tree()
    )


def test_removed_intake_and_webui_claims_have_no_schema_surface():
    from typing import get_args

    from src.config.apply_registry import FIELDS, ApplyMode

    fields = Config.model_fields
    assert "discord" not in fields and "web" not in fields
    assert "discord" not in SECTIONS and "web" not in SECTIONS
    assert not any(path.startswith(("discord.", "web.")) for path in schema_facts())
    modes = set(get_args(ApplyMode))
    assert {"dormant", "activation_required"} <= modes
    assert all(section.apply_mode in modes for section in SECTIONS.values())
    assert all(field.apply_mode is None or field.apply_mode in modes for field in FIELDS.values())
    assert all(
        consumer.apply_mode in modes for field in FIELDS.values() for consumer in field.consumers
    )


def test_actual_schema_retains_restart_truth_without_old_count():
    facts = schema_facts()
    assert facts
    assert "openai_compatible.openrouter.model_pins" in facts
    assert "openai_compatible.openrouter.catalogue_profiles" in facts
    assert "mcp.max_published_tools_per_server" in facts
    assert "mcp.max_published_tools_global" in facts
    for path in (
        "computer.hyprland_discovery_mode",
        "computer.hyprland_managed_activation",
        "computer.hyprland_plugin_manifest",
        "graceful_degradation.degraded_threshold",
        "graceful_degradation.unavailable_threshold",
    ):
        record = build_field_record(path, None)
        assert path in facts
        assert record["apply_mode"] == "restart"
        assert record["restart_reason"]
    for path in (
        "graceful_degradation.enabled",
        "grafana_alerts.enabled",
        "comfyui.enabled",
        "image.backend",
    ):
        assert path not in facts


def test_real_retained_list_record_schema_facts():
    record = build_field_record("outbound_webhooks.targets.0.name", None)
    assert record["type"] == "string"
    assert record["default"] == ""
    assert "outbound_webhooks.targets.secret" in schema_facts()
    records = build_meta_payload(
        {
            "outbound_webhooks": {
                "targets": [
                    {
                        "name": "fixture",
                        "url": "https://example.invalid",
                        "secret": "SYNTHETIC-SECRET",
                    }
                ]
            }
        }
    )["fields"]
    assert len(records) == 3
    assert all(row["structured_container_child"] for row in records)
    assert all(not row["structured_container"] for row in records)
    assert records[2]["desired"] != "SYNTHETIC-SECRET"
    assert records[0]["desired"] == "fixture"


def test_actual_health_states_cover_every_field_not_removed_webui():
    payload = build_meta_payload(
        {"browser": {"viewport_width": 1280}}, persistence_error="harmless storage failure"
    )
    assert tuple(payload["status"]["counts"]) == HEALTH_STATES
    assert sum(payload["status"]["counts"].values()) == len(payload["fields"])
    assert payload["status"]["persistence_error"] == "harmless storage failure"


def test_generic_http_body_is_suppressed_without_transport_dependency():
    import inspect

    import src.error_presentation as module

    assert "import discord" not in inspect.getsource(module)
    assert format_user_facing_error(RuntimeError("<html><body>private upstream body")) == (
        "RuntimeError"
    )
    assert len(format_user_facing_error(RuntimeError("x" * 5000))) <= 200


def test_generic_internal_failure_remains_total(monkeypatch):
    import src.error_presentation as module

    def failed(_text):
        raise ValueError("harmless internal sanitizer failure")

    monkeypatch.setattr(module, "_clean_detail", failed)
    assert format_user_facing_error(RuntimeError("boom")) == "RuntimeError"


@pytest.mark.parametrize(
    "reason,required,forbidden",
    [
        ("Bad\x9b\x7fReason\x00", "BadReason", ("\x9b", "\x7f", "\x00")),
        ("notify @everyone and @here", "everyone", ("@everyone", "@here")),
        ("zero\u200bwidth", "zerowidth", ("\u200b",)),
        ("rejected sk-" + "a" * 24, "[REDACTED]", ("sk-" + "a" * 24,)),
    ],
    ids=["controls", "mentions", "format", "secrets"],
)
def test_generic_reason_preserves_neutral_sanitization(reason, required, forbidden):
    output = format_user_facing_error(RuntimeError(reason))
    assert required in output
    assert all(value not in output for value in forbidden)


def test_html_reason_and_status_do_not_invent_structured_transport_support():
    assert format_user_facing_error(RuntimeError("<html>oops</html>")) == "RuntimeError"
    output = format_user_facing_error(RuntimeError("@everyone 500 Internal Server Error"))
    assert "@everyone" not in output
    assert output.startswith("RuntimeError:")
    assert "Discord API" not in output


def test_real_aiohttp_exception_uses_generic_total_sanitized_contract():
    import aiohttp
    from multidict import CIMultiDict, CIMultiDictProxy
    from yarl import URL

    url = URL("https://example.invalid/")
    request = aiohttp.RequestInfo(url, "GET", CIMultiDictProxy(CIMultiDict()), real_url=url)
    html = aiohttp.ClientResponseError(request, (), status=500, message="<html>private body")
    assert format_user_facing_error(html) == "ClientResponseError"
    malformed_status = aiohttp.ClientResponseError(
        request, (), status="@everyone 500\x00\x9b", message="BadReason"
    )
    output = format_user_facing_error(malformed_status)
    assert output.startswith("ClientResponseError:")
    assert "BadReason" in output
    assert "@everyone" not in output
    assert "\x00" not in output and "\x9b" not in output
    assert len(output) <= 200


@pytest.fixture
def knowledge_dependencies(tmp_path):
    with owner_fixture(tmp_path / "owner") as state:
        root = state.paths.data_dir / "imports"
        root.mkdir()
        store = KnowledgeStore(str(state.paths.data_dir / "knowledge.db"))
        handler = KnowledgeTools(
            sessions=None, get_knowledge_store=lambda: store, embedder=None, audit=None
        )
        try:
            yield state, root, store, handler
        finally:
            store.close()


async def test_neutral_search_invalid_query_and_store_failure(knowledge_dependencies):
    _, _, _, handler = knowledge_dependencies
    store = MagicMock()

    async def validate(query, *_args, **_kwargs):
        validate_search_query(query)
        return []

    store.search_hybrid = AsyncMock(side_effect=validate)
    handler.get_knowledge_store = lambda: store
    assert "Invalid query" in await handler._handle_search_knowledge({"query": "\ud800"})
    store.search_hybrid = AsyncMock(side_effect=RuntimeError("harmless store failure"))
    assert "Search failed" in await handler._handle_search_knowledge({"query": "valid"})
    store.search_hybrid.assert_awaited_once()


async def test_neutral_ingest_zero_is_failure_and_real_content_is_stored(knowledge_dependencies):
    state, _, store, handler = knowledge_dependencies
    assert "Failed to ingest" in await handler._handle_ingest_document(
        {"source": "empty.md", "content": "   "}, state.authority.owner_id
    )
    assert store.get_source_content("empty.md") is None
    assert "Ingested" in await handler._handle_ingest_document(
        {"source": "doc.md", "content": "neutral actual storage content"}, state.authority.owner_id
    )
    assert store.get_source_content("doc.md") == "neutral actual storage content"


@pytest.mark.parametrize("items", [None, "not a list"])
async def test_neutral_bulk_items_validation_has_no_store_effect(knowledge_dependencies, items):
    state, _, store, handler = knowledge_dependencies
    payload = {} if items is None else {"items": items}
    assert (
        "required" in (await handler._handle_bulk_ingest(payload, state.authority.owner_id)).lower()
    )
    assert store.list_sources() == []


async def test_neutral_bulk_real_explicit_root_dependency_and_results(
    knowledge_dependencies,
    monkeypatch,
):
    state, root, store, handler = knowledge_dependencies
    (root / "a.md").write_text("actual content a", encoding="utf-8")
    (root / "b.md").write_text("different actual content b", encoding="utf-8")

    # Exact dependency injection into the neutral helper only. This constructs
    # the real importer with fixture-owned roots; no intake is asserted ready.
    def importer(dependency, embedder):
        assert dependency is store
        return BulkImporter(dependency, embedder, admitted_roots=(root,))

    monkeypatch.setattr("src.knowledge.importer.BulkImporter", importer)
    output = await handler._handle_bulk_ingest(
        {"items": [{"type": "directory", "path": str(root)}]}, state.authority.owner_id
    )
    assert "2 succeeded" in output and "0 failed" in output
    assert "[OK]" in output and "a.md" in output and "b.md" in output
    assert store.get_source_content((root / "a.md").as_uri()) == "actual content a"
    assert store.get_source_content((root / "b.md").as_uri()) == "different actual content b"


async def test_current_batch_result_dictionary_reports_typed_outcome(knowledge_dependencies):
    _, root, store, _ = knowledge_dependencies
    batch = await BulkImporter(store, admitted_roots=(root,)).import_batch(
        [
            {"type": "directory", "path": str(root / "missing")},
        ]
    )
    result = batch.results[0]
    assert {"source", "status", "chunks", "error"} <= result.keys()
    assert set(result) <= {"source", "status", "chunks", "error", "outcome", "note"}
    assert result["status"] == "error" and result["chunks"] == 0
    assert batch.failed == 1 and batch.succeeded == 0


@pytest.mark.parametrize(
    "original_case",
    [
        "missing_items",
        "invalid_items_type",
        "directory_import_via_api",
        "response_structure",
        "unavailable_store",
        "mixed_results_via_api",
    ],
)
async def test_phase2_import_api_no_admitted_dispatch_or_effect(
    knowledge_dependencies,
    original_case,
):
    state, root, store, _ = knowledge_dependencies
    (root / "api_test.md").write_text("must remain unimported", encoding="utf-8")
    executor = ToolExecutor(
        ToolsConfig(), profile_paths=state.paths, permission_manager=state.manager
    )
    policy = BuiltinToolPolicy(Config, lambda: {"bulk_ingest_knowledge": True})
    assert not policy.is_available("bulk_ingest_knowledge")
    payloads = {
        "missing_items": {},
        "invalid_items_type": {"items": "string"},
        "directory_import_via_api": {"items": [{"type": "directory", "path": str(root)}]},
        "response_structure": {"items": [{"type": "url", "url": "ftp://bad"}]},
        "unavailable_store": {},
        "mixed_results_via_api": {
            "items": [{"type": "directory", "path": str(root)}, {"type": "url", "url": "ftp://bad"}]
        },
    }
    result = await executor.execute(
        "bulk_ingest_knowledge", payloads[original_case], user_id=state.authority.owner_id
    )
    assert result.ok is False
    assert result.error == "tool_unavailable"
    assert store.list_sources() == []


def test_current_tool_reference_order_sections_counts_and_renamed_contract():
    from scripts.docs._reference import SOURCE_COMMIT
    from scripts.docs.generate_tool_reference import OUTPUT, generate, tool_sections
    from src.tools.registry import get_documentation_tool_definitions

    definitions = get_documentation_tool_definitions()
    text = generate()
    assert OUTPUT.read_bytes() == text.encode("utf-8")
    assert re.findall(r"^### (.+)$", text, re.M) == [tool["name"] for tool in definitions]
    assert [tool["name"] for _, section in tool_sections() for tool in section] == [
        tool["name"] for tool in definitions
    ]
    assert len({tool["name"] for tool in definitions}) == len(definitions)
    assert f"**{len(definitions)} built-in tools**" in text
    assert f"`{SOURCE_COMMIT}`" in text
    assert len(re.findall(r"^\*\*Core:\*\* Yes$", text, re.M)) == sum(
        bool(tool.get("is_core")) for tool in definitions
    )
    read = next(tool for tool in definitions if tool["name"] == "read_conversation")
    assert "conversation_id" not in read["input_schema"]["properties"]
    assert "### read_channel\n" not in text


def test_server_cli_packaging_is_absent_and_app_owned_lifecycle_is_documented():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert not (root / "scripts/odin-cli.py").exists()
    assert not (root / "packaging/nfpm.yml").exists()
    assert "web" not in Config.model_fields
    text = (root / "docs/design/architecture.md").read_text(encoding="utf-8")
    assert "Exit" in text and "D3" in text
    assert "supervised" in text


def test_triage_exact_original_source_hashes_and_definition_identity():
    import json
    from pathlib import Path

    from scripts.maintenance.fixture_corpus import nodes
    from tests.desktop_adapters.final_helpers import source_hash

    root = Path(__file__).resolve().parents[1]
    data = json.loads((root / "maintenance/final-helpers-triage.json").read_text())
    assert len(data["cases"]) == 31
    assert len({row["original"] for row in data["cases"]}) == 31
    for row in data["cases"]:
        path, *parts = row["original"].split("::")
        symbol = ".".join(parts)
        assert row["source_sha256"] == source_hash(path)
        definitions = [
            node
            for owner, node in nodes(ast.parse(frozen_source(path)))
            if owner == symbol and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert len(definitions) == 1
        assert row["reason"]
        assert row["executable"] or row["replacement_cases"]
        for target in row["executable"] + row["replacement_cases"]:
            assert target.startswith("tests/test_desktop_final_helpers.py::")
            _, *names = target.split("::")
            obj = globals()[names[0].split("[")[0]]
            if len(names) == 2:
                assert hasattr(obj, names[1])
