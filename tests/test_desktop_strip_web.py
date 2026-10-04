"""Phase 1 neutral helpers and fail-closed surface gates, without live services."""
import ast
import asyncio
import importlib
import inspect
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.health import checker, startup
from src.web import api_common
from src.web.api import Phase2Unavailable

ROOT = Path(__file__).resolve().parents[1]


def test_no_server_routes_or_removed_transport_inventory():
    for directory in (ROOT / "src/web", ROOT / "src/health"):
        for path in directory.rglob("*.py"):
            source = path.read_text()
            ast.parse(source)
            checked = source.replace("from ...discord.native_tools.agents_tasks import _entry_native_reasoning", "")
            for forbidden in ("discord", "api_token", "RouteTableDef", "@routes.",
                              "config.web", "OdinBot", "web.Application"):
                assert forbidden not in checked, (path, forbidden)
    assert not (ROOT / "src/web/api/discord_connection.py").exists()
    assert not (ROOT / "src/web/api/discord_identity.py").exists()


@pytest.mark.parametrize("module", [
    "agents_loops", "codex_admin", "computer", "config_admin", "hosts",
    "integrations", "knowledge_mem", "llm_admin", "observability", "schedules_api",
    "self_update", "sessions_chat", "skills_api", "turn_state",
])
def test_registrars_fail_closed_without_mutating_arguments(module):
    imported = importlib.import_module(f"src.web.api.{module}")
    found = False
    for name, function in vars(imported).items():
        if name.startswith("register_"):
            found = True
            with pytest.raises(Phase2Unavailable, match="Phase 2"):
                function()
    assert found


def test_neutral_health_namespace_and_unchanged_guard():
    import src.health as health

    assert not hasattr(health, "HealthServer")
    baseline = subprocess.check_output(
        ["git", "show", "refs/baselines/odin-v4.13.0:src/health/subsystem_guard.py"], cwd=ROOT,
    )
    assert (ROOT / "src/health/subsystem_guard.py").read_bytes() == baseline


@pytest.mark.parametrize("file,names", [
    ("src/web/api_common.py", ["_validate_string", "_safe_filename", "_sanitize_error", "_safe_int_param",
                               "_contains_blocked_fields", "contains_redaction_mask", "_deep_merge",
                               "_mask_subtree", "_redact_config", "_write_config"]),
    ("src/web/api/hosts.py", ["_tool_host_dump", "_leaf_changes", "_drain_host_mutation"]),
    ("src/web/api/integrations.py", ["_drain_mcp_management"]),
    ("src/web/api/llm_admin.py", ["_openrouter_models", "_openrouter_endpoint_rows", "_validate_ollama_url",
                                 "_parse_int", "_compatible_client", "_reload_openai_compatible",
                                 "_auxiliary_status", "_model_catalogue", "_boot_codex_group_status",
                                 "_set_fields", "_provider_changes", "_parse_codex_advanced", "_apply_ops"]),
    ("src/web/api/computer.py", ["_expiry", "_opaque"]),
    ("src/web/api/config_admin.py", ["_image_intent_revision", "_config_has_explicit_path"]),
    ("src/web/api/turn_state.py", ["_observed_at", "_envelope"]),
])
def test_pure_helper_algorithms_match_exact_copy(file, names):
    baseline = subprocess.check_output(["git", "show", f"f6170072:{file}"], cwd=ROOT).decode()
    current = (ROOT / file).read_text()

    def algorithms(source):
        tree = ast.parse(source)
        result = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Only algorithm bodies, not neutral transport annotations or prose.
                if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
                    node.body.pop(0)
                result[node.name] = ast.dump(ast.Module(body=node.body, type_ignores=[]))
        return result

    before, after = algorithms(baseline), algorithms(current)
    for name in names:
        assert before[name] == after[name], (file, name)


def test_delivery_readiness_is_observed_not_assumed():
    absent = checker.check_delivery(SimpleNamespace())
    assert not absent.healthy and absent.status == "unavailable"
    assert not checker.check_delivery(SimpleNamespace(delivery_readiness="yes")).healthy
    assert checker.check_delivery(SimpleNamespace(delivery_readiness=True)).healthy
    assert checker.check_delivery(SimpleNamespace(delivery_readiness=False)).status == "down"


def test_platform_metrics_are_explicitly_unavailable(monkeypatch):
    monkeypatch.setattr(checker, "resource", None)
    result = checker.check_open_files(None)
    assert result.status == "unavailable" and not result.healthy


def test_unavailable_health_is_not_overall_healthy(monkeypatch):
    monkeypatch.setattr(checker, "_ALL_CHECKERS", [checker.check_delivery])
    result = checker.check_all(SimpleNamespace())
    assert result["overall"] == "degraded" and result["unavailable_count"] == 1


def test_startup_removes_transport_and_inventory_requirements():
    assert startup.check_config_sections(SimpleNamespace()).passed
    assert all("discord" not in name for name, *_ in startup._CONFIG_CHECKS)
    assert "credential_inventory" not in inspect.signature(startup.run_startup_diagnostics).parameters


def test_data_readiness_uses_only_private_xdg_profile(tmp_path, monkeypatch):
    from src.desktop.paths import ProfilePaths

    paths = ProfilePaths.from_xdg(home=tmp_path, environ={})
    monkeypatch.setattr("src.runtime_paths.runtime_profile_paths", lambda: paths)
    monkeypatch.chdir(tmp_path)
    result = startup.check_data_directories()
    assert result.passed
    assert (paths.data_dir / "sessions").is_dir()
    assert (paths.data_dir / "sessions").stat().st_mode & 0o777 == 0o700
    assert not (tmp_path / "data").exists()


def test_data_readiness_refuses_existing_nonprivate_state(tmp_path, monkeypatch):
    from src.desktop.paths import ProfilePaths

    paths = ProfilePaths.from_xdg(home=tmp_path, environ={})
    paths.data_dir.mkdir(parents=True)
    paths.data_dir.chmod(0o755)
    monkeypatch.setattr("src.runtime_paths.runtime_profile_paths", lambda: paths)
    result = startup.check_data_directories()
    assert not result.passed
    assert paths.data_dir.stat().st_mode & 0o777 == 0o755


def test_neutral_security_helpers_keep_recursive_mask_and_bounds():
    assert api_common._contains_blocked_fields({"items": [{"password": "value"}]}, frozenset({"password"}))
    assert api_common.contains_redaction_mask({"items": ["••••••••"]})
    redacted = api_common._redact_config({"headers": {"ordinary": "value"}, "password": "value"})
    assert redacted["headers"]["ordinary"] == "••••••••"
    assert redacted["password"] == "••••••••"
    assert api_common._safe_filename("../../unsafe/name") == ".._.._unsafe_name"
    assert api_common._validate_string("ab", "field", 1)
    assert api_common._safe_int_param(SimpleNamespace(query={"n": "1000"}), "n", 10, hi=100) == 100
    assert api_common._safe_int_param(SimpleNamespace(query={"n": "bad"}), "n", 10) == 10
    assert api_common._scoped_conversation("owner", "current") == "owner:owner:conversation:current"
    with pytest.raises(ValueError):
        api_common._scoped_conversation("owner", "../foreign")
    with pytest.raises(Phase2Unavailable):
        api_common.owner_gate(None)


def test_constant_time_comparison_and_no_default_operator_authority():
    from src.web.authentication import credential_equals
    from src.web.computer_binding import operator_context_authorized

    assert credential_equals("résumé", "résumé")
    assert not credential_equals("résumé", "resume")
    assert not operator_context_authorized(SimpleNamespace())


def test_truthful_ingestion_outcomes_are_preserved():
    from src.web.api.knowledge_mem import _ingest_result_response

    class Outcome(int):
        status = "duplicate"
        duplicate_of = "existing"

    body, status = _ingest_result_response("new", Outcome(0), failure_message="failed", created_status=201)
    assert status == 200 and body["duplicate_of"] == "existing"
    assert "not ingested" in body["status"]
    assert _ingest_result_response("new", 0, failure_message="failed", created_status=201) == ({"error": "failed"}, 500)


def test_provider_ssrf_schema_and_adoption_facts():
    from src.config.schema import OpenAICodexConfig
    from src.web.api.llm_admin import _apply_ops, _boot_codex_group_status, _parse_codex_advanced, _validate_ollama_url

    assert _validate_ollama_url("http://127.0.0.1:11434")
    for url in ("http://8.8.8.8", "http://169.254.169.254", "file:///tmp/local"):
        with pytest.raises(ValueError):
            _validate_ollama_url(url)
    cfg = OpenAICodexConfig()
    assert _parse_codex_advanced({"request_timeout_seconds": True}, cfg).status == 400
    assert _parse_codex_advanced({"retry": []}, cfg).status == 400
    assert _boot_codex_group_status(SimpleNamespace(), "retry", {"max_retries": 1}) == (None, None)
    old = cfg.retry
    new = old.model_copy(update={"max_retries": 2})
    inverse = _apply_ops(cfg, [("retry", new)])
    assert cfg.retry is new
    _apply_ops(cfg, inverse)
    assert cfg.retry is old


@pytest.mark.asyncio
@pytest.mark.parametrize("module,function", [("hosts", "_drain_host_mutation"), ("integrations", "_drain_mcp_management")])
async def test_publication_drains_committed_work_before_cancellation(module, function):
    drain = getattr(importlib.import_module(f"src.web.api.{module}"), function)
    started, finish, settled = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def operation():
        started.set()
        await finish.wait()
        settled.set()

    task = asyncio.create_task(drain(operation(), commit_started=started))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not settled.is_set() and not task.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert settled.is_set()
