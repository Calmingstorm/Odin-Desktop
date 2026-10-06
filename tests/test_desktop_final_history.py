"""Current contracts and exact neutral proofs for the last historical failures."""

import ast
import hashlib
import json
from unittest.mock import AsyncMock

import pytest

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from src.config.schema import Config, load_config
from src.tools.autonomous_loop import LoopInfo, LoopManager
from tests.desktop_adapters.final_history import (
    CASE_MAP as CASE_MAP,
)
from tests.desktop_adapters.final_history import (
    REPLACEMENT_SUITES,
    ROOT,
    SELECTIONS,
    executable,
    export_suite,
    transformed_tree,
)

for _suite in SELECTIONS:
    export_suite(globals(), _suite)


@pytest.mark.parametrize("suite", [*SELECTIONS, *REPLACEMENT_SUITES])
def test_final_frozen_full_tree_assertions_and_parameters_unchanged(suite):
    original = corpus(ast.parse(frozen_source(f"tests/{suite}.py")))
    assert original == corpus(transformed_tree(suite)[0])


@pytest.mark.parametrize("unknown", ["sesions", "web_ui", "discord", "web"])
def test_unknown_or_stripped_config_drops_before_profile_migrations(tmp_path, monkeypatch, unknown):
    import src.config.migrations as migrations
    import src.config.schema as schema
    from src.desktop.authority import OwnerAuthority
    from src.desktop.paths import ProfilePaths

    paths = ProfilePaths.from_xdg(environ={
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }, home=tmp_path)
    OwnerAuthority(paths)
    text = f"{unknown}: {{}}\nopenai_codex: {{model: gpt-5.5}}\n"
    paths.config_file.write_text(text)
    monkeypatch.setattr(schema, "runtime_profile_paths", lambda: paths)
    monkeypatch.setattr("src.runtime_paths.runtime_profile_paths", lambda: paths)
    reached = []
    for name in ("apply_legacy_ceiling_migration", "apply_image_defaults_migration",
                 "apply_compatible_timeout_migration"):
        monkeypatch.setattr(migrations, name, lambda *a: reached.append(a))
    assert unknown not in load_config(paths.config_file).model_dump()
    assert paths.config_file.read_text() == text
    assert len(reached) == 3
    assert all(unknown not in args[0] for args in reached)


def test_known_desktop_config_sections_load_without_unknown_warning(tmp_path, caplog):
    path = tmp_path / "desktop.yml"
    path.write_text("tools: {}\ncontext: {}\nsessions: {}\n")
    cfg = load_config(path)
    assert isinstance(cfg, Config)
    assert cfg.tools.enabled
    assert "Ignoring unknown config key" not in caplog.text
    assert path.read_text() == "tools: {}\ncontext: {}\nsessions: {}\n"


def test_retired_model_rejected_at_desktop_selection_contract():
    from src.config.schema import OpenAICodexConfig, canonical_codex_model
    from src.llm.errors import LLMRequestError
    from src.llm.openai_codex import _reject_known_bad_pair

    assert "web" not in Config.model_fields
    for construct in (
        lambda: OpenAICodexConfig(model="gpt-5.5"),
        lambda: OpenAICodexConfig(agent_model="gpt-5.5"),
        lambda: canonical_codex_model("gpt-5.5"),
    ):
        with pytest.raises(ValueError, match="is retired"):
            construct()
    with pytest.raises(LLMRequestError, match="is retired"):
        _reject_known_bad_pair("gpt-5.5", "high")


async def test_missing_bundled_pdf_reports_repair_and_never_fetches(monkeypatch):
    """Retain the historical selector, but exercise Decision F's first-use failure."""
    from src.runtime.pdf_resources import PdfUnavailable
    from src.tools import safe_fetch
    from src.tools.handlers.files_docs import FilesDocsTools

    reason = (
        "PDF support download failed. Check your internet connection and try again; "
        "nothing was installed."
    )
    resolver = AsyncMock(side_effect=PdfUnavailable(reason))
    fetch = AsyncMock(side_effect=AssertionError("must not fetch after PDF resolver failure"))
    monkeypatch.setattr(safe_fetch, "safe_fetch", fetch)
    monkeypatch.setattr("src.runtime.pdf_resources.ensure_pdf", resolver)
    result = await FilesDocsTools.__new__(FilesDocsTools)._handle_analyze_pdf(
        {"url": "https://example.com/fixture.pdf"}
    )
    assert isinstance(result, tuple) and result[1] != 0
    assert result == (reason, 1)
    assert "pip install" not in result[0]
    resolver.assert_awaited_once_with()
    fetch.assert_not_awaited()


def test_desktop_constants_keep_deadlines_without_transport_authority():
    from src import constants

    assert constants.BOT_NAME == "Odin"
    assert constants.BOT_TAGLINE == "Odin Desktop"
    assert constants.CONFIRMATION_TIMEOUT == 30
    assert constants.PAGINATION_TIMEOUT == 120
    for removed in ("MAX_MESSAGE_LENGTH", "PAGINATOR_PAGE_SIZE", "ADMIN_PERMISSIONS", "LOG_EVENTS"):
        assert not hasattr(constants, removed)


def test_implicit_environment_is_private_profile_not_launch_directory(tmp_path, monkeypatch):
    from src import runtime_paths
    from src.config.startup_context import resolve_startup_context
    from src.desktop.paths import ProfilePaths

    paths = ProfilePaths.from_xdg(environ={
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }, home=tmp_path)
    launch = tmp_path / "launch"
    launch.mkdir()
    monkeypatch.setattr(runtime_paths, "runtime_profile_paths", lambda: paths)
    monkeypatch.chdir(launch)
    context = resolve_startup_context(tmp_path / "external-config.yml")
    monkeypatch.chdir(tmp_path)
    assert context.environment_path == paths.environment_file
    assert context.environment_path != launch / ".env"
    assert context.environment_path != context.config_path.parent / ".env"
    assert context.environment_source().path == paths.environment_file
    assert not paths.environment_file.exists()


def test_real_loop_admission_refuses_before_task_or_callback(monkeypatch):
    import src.tools.autonomous_loop as loops

    manager = LoopManager()
    callback = AsyncMock(side_effect=AssertionError("no privileged admission"))
    create = AsyncMock(side_effect=AssertionError("no task creation"))
    monkeypatch.setattr(loops.asyncio, "create_task", create)
    result = manager.start_loop(
        goal="negative boundary", channel=object(), requester_id="owner-looking",
        requester_name="fixture", iteration_callback=callback, interval_seconds=10,
    )
    assert result.startswith("Error:") and "Phase 2 durable admission" in result
    assert "No loop was started" in result
    assert manager._loops == {} and manager.active_count == 0
    callback.assert_not_called()
    create.assert_not_called()


def inert_loop():
    return LoopInfo(
        id="inert", goal="g", mode="notify", interval_seconds=1,
        stop_condition=None, max_iterations=1, channel_id="inert",
        requester_id="no-admission", requester_name="fixture",
    )


async def test_long_loop_response_refuses_unwired_delivery_without_truncation_claim():
    sink = AsyncMock()
    response = "```python\n" + "x" * 1980 + "\nrest of code\n```"
    with pytest.raises(RuntimeError, match="conversation delivery unavailable.*Do not replay"):
        await LoopManager()._post_response(inert_loop(), sink, response)
    sink.send.assert_not_awaited()


async def test_short_loop_response_refuses_unwired_delivery_without_success_claim():
    sink = AsyncMock()
    with pytest.raises(RuntimeError, match="conversation delivery unavailable.*Do not replay"):
        await LoopManager()._post_response(
            inert_loop(), sink, "```python\nprint('kept exactly')\n```"
        )
    sink.send.assert_not_awaited()


def test_final_history_durable_exact_mapping_and_setup_seals():
    triage = json.loads((ROOT / "maintenance/final-history-triage.json").read_text())
    rows = triage["cases"]
    assert len(rows) == len({r["original"] for r in rows}) == 20
    for row in rows:
        source = frozen_source(row["original"].split("::")[0])
        assert hashlib.sha256(source).hexdigest() == row["source_sha256"]
        assert row["reason"] and (row["executable"] or row["replacement_cases"])
        assert row["disposition"] in {
            "executable", "removed-surface-replacement", "phase2-admission-wiring"
        }
    expected_hunks = {suite: transformed_tree(suite)[1] for suite in SELECTIONS}
    assert triage["setup_hunks"] == expected_hunks
    assert triage["case_map"] == CASE_MAP
    for suite, symbols in SELECTIONS.items():
        for symbol in symbols:
            selector = executable(suite, symbol)
            assert any(selector in (r["executable"] + r["replacement_cases"]) for r in rows)
