"""PR48 review 1: reversible bindings of the immutable parity suite."""
# ruff: noqa: E501 - exact inherited snippets and reviewed substitutions
from __future__ import annotations

import ast
import asyncio
import hashlib
import tempfile
from contextvars import ContextVar
from pathlib import Path
from types import ModuleType

import pytest

from scripts.maintenance.fixture_corpus import frozen_source, register_module

SOURCE_PATH = "tests/characterization/test_tool_parity.py"
SOURCE_SHA256 = "41aa806975873b2dd35cb0bc8f0c4763350f9a509c2f3c85b63f267be3f0a6c2"
_root = ContextVar("parity_profile_root")

# docs/design/prompt-changes.md C, catalog rows and interface paragraph.
DESKTOP_BINDINGS = '''
REMOVED = {"purge_messages", "set_permission", "add_reaction", "create_poll"}
RENAMED = {"read_channel": "read_conversation"}
DESKTOP_ORDER = [RENAMED.get(n, n) for n in EXPECTED_TOOL_ORDER if n not in REMOVED]
REPINNED_TOOL_HASHES = {
    "post_file": "8ec4e1871e3ce2ec",  # C: post_file row
    "generate_file": "11fc964044da81c5",  # C: generate_file row
    "schedule_task": "6e091d03f0a4a333",  # C: schedule_task.report_format + interface
    "update_schedule": "c247dd47a9843be1",  # C: update_schedule.report_format + interface
    "search_history": "884752bfda013ff5",  # C: search_history row
    "delegate_task": "2fafd699ad19ee4c",  # C: delegate_task row
    "browser_screenshot": "67b9253438eb2e4a",  # C: browser_screenshot row
    "spawn_agent": "61d109c0d711f188",  # C: spawn_agent row
    "generate_image": "52ce55c45ed09b71",  # C: generate_image row
    "get_tool_output": "6455b67d729056d9",  # C: get_tool_output row
    "read_conversation": "8b9fa51606740965",  # C: read_channel rename + interface
}
assert set(REPINNED_TOOL_HASHES) == {
    "post_file", "generate_file", "schedule_task", "update_schedule", "search_history",
    "delegate_task", "browser_screenshot", "spawn_agent", "generate_image",
    "get_tool_output", "read_conversation",
}, "Only the reviewed eleven definitions may be re-pinned"
DESKTOP_TOOL_HASHES = {
    RENAMED.get(n, n): h for n, h in EXPECTED_TOOL_HASHES.items() if n not in REMOVED
}
DESKTOP_TOOL_HASHES.update(REPINNED_TOOL_HASHES)
'''


def _inherited_catalog_helper():
    # Bind this entire setup helper at the frozen hash, not the obsolete token
    # literal which secret-safe tool evidence may redact.
    source = frozen_source(SOURCE_PATH)
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise AssertionError("frozen parity source changed")
    text = source.decode()
    helper, = [n for n in ast.walk(ast.parse(text))
               if isinstance(n, ast.FunctionDef) and n.name == "_catalog_names"]
    return ast.get_source_segment(text, helper)


# Unique literal substitutions compile to AST; reverse proof rejects all drift.
REVIEWED_SUBSTITUTIONS = (
    ("    get_tool_definitions,", "    get_documentation_tool_definitions as get_tool_definitions,"),
    ("def _canonical_hash(tool_def: dict) -> str:", DESKTOP_BINDINGS + "\n\ndef _canonical_hash(tool_def: dict) -> str:"),
    ("assert len(actual) == len(EXPECTED_TOOL_ORDER) == 67", "assert len(actual) == len(DESKTOP_ORDER)"),
    ("missing = set(EXPECTED_TOOL_ORDER) - set(actual)", "missing = set(DESKTOP_ORDER) - set(actual)"),
    ("added = set(actual) - set(EXPECTED_TOOL_ORDER)", "added = set(actual) - set(DESKTOP_ORDER)"),
    ("assert actual == EXPECTED_TOOL_ORDER,", "assert actual == DESKTOP_ORDER,"),
    ("EXPECTED_TOOL_HASHES[t[\"name\"]]", "DESKTOP_TOOL_HASHES[t[\"name\"]]"),
    ("assert set(TOOL_MAP) == set(EXPECTED_TOOL_ORDER)", "assert set(TOOL_MAP) == set(DESKTOP_ORDER)"),
    (_inherited_catalog_helper(),
     '''def _catalog_names(self, **config_kwargs) -> set[str]:
        from tests.desktop_adapters.tool_parity import catalog_names

        return catalog_names(**config_kwargs)'''),
    ("len(names) == len(EXPECTED_TOOL_ORDER) - len(self.GATED)", "len(names) == len(DESKTOP_ORDER) - len(self.GATED)"),
    ("assert get_tool_definitions() is baseline", "assert get_tool_definitions() == baseline"),
    ('''        first = get_tool_definitions()
        assert get_tool_definitions() is first, "cache must return the same object"''',
     '''        first = get_tool_definitions()
        cache = registry._tool_defs_cache
        assert get_tool_definitions() == first, "returned copies must compare equal"
        assert registry._tool_defs_cache is cache, "internal cache retains identity"
        first[0]["input_schema"]["parity_copy_probe"] = True
        assert "parity_copy_probe" not in get_tool_definitions()[0]["input_schema"]'''),
    ("assert [d[\"name\"] for d in defs] == EXPECTED_TOOL_ORDER", "assert [d[\"name\"] for d in defs] == DESKTOP_ORDER"),
    ('''            # input_schema passes through by REFERENCE (same object)…
            assert d["input_schema"] is src["input_schema"]''',
     '''            # Phase 1 e620f97 returns isolated schema copies by value.
            assert d["input_schema"] == src["input_schema"]'''),
)


def adapted_source():
    source = frozen_source(SOURCE_PATH)
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise AssertionError("frozen parity source changed")
    text = source.decode()
    for old, new in REVIEWED_SUBSTITUTIONS:
        if text.count(old) != 1:
            raise AssertionError(f"nonunique reviewed parity binding: {old}")
        text = text.replace(old, new, 1)
    return text


def load_suite(namespace):
    module = ModuleType("desktop_tool_parity")
    module.__file__ = str(Path(__file__).parents[1] / "characterization/test_tool_parity.py")
    exec(compile(adapted_source(), module.__file__, "exec"), module.__dict__)
    register_module(namespace, module)


@pytest.fixture(autouse=True)
def parity_profile(tmp_path, monkeypatch):
    import socket

    import aiohttp

    def no_network(*args, **kwargs):
        raise AssertionError("Parity catalog construction must not open network connections")

    monkeypatch.setattr(aiohttp, "ClientSession", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    binding = _root.set(tmp_path)
    try:
        yield
    finally:
        _root.reset(binding)


def catalog_names(**config_kwargs):
    """Real composed engine, requests and no-network auth in a private profile."""
    from src.config.schema import Config
    from src.desktop.authority import OwnerAuthority
    from src.desktop.commands import JournalStore
    from src.desktop.conversations import ConversationStore
    from src.desktop.delivery import DurableDelivery, PublicationEventJournal
    from src.desktop.paths import ProfilePaths
    from src.desktop.requests import RequestService
    from src.desktop.services import build_engine_services
    from src.desktop.transcript import TranscriptStore
    from src.llm.codex_auth import CodexAuth
    from src.permissions.manager import PermissionManager

    with tempfile.TemporaryDirectory(dir=_root.get()) as scratch:
        paths = ProfilePaths.from_xdg("parity", home=Path(scratch), environ={})
        authority = OwnerAuthority(paths)
        permissions = PermissionManager(authority)
        store = JournalStore(paths.data_dir / "transport.sqlite3", paths.profile_id)
        events = PublicationEventJournal(store)
        conversations = ConversationStore(store, events)
        transcript = TranscriptStore(store, events, conversations)
        delivery = DurableDelivery(store, events, transcript_commit=transcript.commit)
        cfg = Config(**config_kwargs)
        cfg.openai_codex.enabled = config_kwargs.get("openai_codex", {}).get("enabled", False)
        cfg.openai_codex.credentials_path = str(paths.secrets_dir / "codex_auth.json")
        cfg.context.directory = str(paths.data_dir / "context")
        cfg.attachments.temp_directory = str(paths.cache_dir / "attachments")
        if cfg.openai_codex.enabled:
            auth = CodexAuth(cfg.openai_codex.credentials_path)
            auth._save({"access_token": "parity-not-a-real-token", "refresh_token": "parity-inert",
                        "account_id": "parity-isolated", "expires_at": 4102444800})
            assert auth.is_configured()
        engine = None
        requests = None
        try:
            engine = build_engine_services(cfg, paths, permissions, delivery=delivery)
            requests = RequestService(store, conversations, transcript, engine=engine,
                permissions=permissions, authority=authority, delivery=delivery)
            engine.bind_requests(requests)
            return {t["name"] for t in engine.deps.tool_catalog.merged_definitions()}
        finally:
            async def close():
                if requests is not None:
                    await requests.close()
                if engine is not None:
                    await engine.close()

            try:
                asyncio.run(close())
            finally:
                store.close()
                authority.release_runtime()
