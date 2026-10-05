"""Retired distribution surfaces and real negative admission, without native input.

Frozen tests are parsed for provenance only. No retired shell, server, installer,
tag fixture, or native lifecycle is executed. A private wheel is built offline
from a temporary copy, not by importing the upstream distribution.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import shutil
import subprocess
import sys
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import yaml
from packaging.specifiers import SpecifierSet

from scripts.maintenance.fixture_corpus import digest, frozen_source, nodes

ROOT = Path(__file__).resolve().parents[1]
TRIAGE = ROOT / "maintenance/final-distribution-triage.json"


@pytest.fixture(scope="module")
def private_wheel(tmp_path_factory):
    staging = tmp_path_factory.mktemp("private-wheel")
    shutil.copytree(ROOT / "src", staging / "src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "pyproject.toml", staging / "pyproject.toml")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
         "--no-index", "--disable-pip-version-check", "--wheel-dir", str(staging / "dist"),
         str(staging)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheels = list((staging / "dist").glob("*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as wheel:
        yield wheel


def test_private_wheel_metadata_and_no_legacy_entry_scripts(private_wheel):
    names = private_wheel.namelist()
    metadata_paths = [name for name in names if name.endswith(".dist-info/METADATA")]
    assert len(metadata_paths) == 1
    metadata = BytesParser().parsebytes(private_wheel.read(metadata_paths[0]))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert metadata["Name"] == project["name"] == "odin-desktop-engine"
    assert metadata["Version"] == project["version"]
    assert SpecifierSet(metadata["Requires-Python"]) == SpecifierSet(">=3.12,<3.13")
    assert not any(name.endswith("/entry_points.txt") for name in names)
    assert not any(".data/scripts/" in name for name in names)
    assert not project.get("scripts")
    assert not any(name.startswith(("packaging/", "scripts/", "ui/")) for name in names)
    packaging_members = [name for name in names if name.startswith("src/packaging/")]
    assert packaging_members == ["src/packaging/__init__.py"]
    namespace = ast.parse(private_wheel.read(packaging_members[0]).decode())
    assert len(namespace.body) == 1
    assert isinstance(namespace.body[0], ast.Expr)
    assert isinstance(namespace.body[0].value, ast.Constant)
    assert isinstance(namespace.body[0].value.value, str)


@pytest.mark.parametrize("path", [
    "packaging/nfpm.yml", "src/packaging/migrations.py", "src/packaging/validate.py",
    "scripts/odin-cli.py", "scripts/odin-server", "scripts/monitor.sh",
    ".github/workflows/release.yml",
])
def test_retired_distribution_path_is_absent(path, private_wheel):
    assert not (ROOT / path).exists(), path
    assert path not in private_wheel.namelist()


@pytest.mark.parametrize("entry", ["cli", "root", "api", "api_setup", "components", "services"])
def test_real_unwired_entry_rejects_before_effect(entry, monkeypatch):
    from src import __main__, cli
    from src.discord import wiring
    from src.web import api

    network = Mock(side_effect=AssertionError("unwired boundary attempted network"))
    spawn = Mock(side_effect=AssertionError("unwired boundary attempted process"))
    monkeypatch.setattr("urllib.request.urlopen", network)
    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setattr(sys, "argv", ["desktop", "--config", "fixture.yml"])
    entries = {
        "cli": cli.main, "root": __main__.main, "api": api.create_api_routes,
        "api_setup": api.setup_api, "components": wiring.build_components,
        "services": wiring.build_services,
    }
    with pytest.raises(RuntimeError, match="Phase 2"):
        entries[entry]()
    network.assert_not_called()
    spawn.assert_not_called()


def test_removed_rest_handlers_not_reintroduced_or_shipped(private_wheel):
    from src.web.api import observability

    removed = {"register_tools_meta", "get_bulkheads", "register_bulkheads"}
    assert all(not hasattr(observability, name) for name in removed)
    for path in (ROOT / "src/web").rglob("*.py"):
        tree = ast.parse(path.read_text())
        definitions = {node.name for node in ast.walk(tree)
                       if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert not definitions.intersection(removed), path
    source = private_wheel.read("src/web/api/observability.py").decode()
    assert source == (ROOT / "src/web/api/observability.py").read_text()
    with pytest.raises(RuntimeError, match="Phase 2"):
        observability.register_observability()


@pytest.fixture
def authenticated_executor(tmp_path):
    from src.config.schema import ToolsConfig
    from src.desktop.authority import OwnerAuthority
    from src.desktop.paths import ProfilePaths
    from src.permissions.manager import PermissionManager
    from src.tools.executor import ToolExecutor

    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path)
    authority = OwnerAuthority(paths)
    manager = PermissionManager(authority)
    token = manager.set_request_owner(authority.authenticate_local(peer_uid=os.geteuid()))
    executor = ToolExecutor(ToolsConfig(), permission_manager=manager, profile_paths=paths)
    try:
        yield executor, authority.owner_id
    finally:
        manager.reset_request_owner(token)
        authority.release_runtime()


@pytest.mark.parametrize("name", ["ingest_document", "search_knowledge", "list_knowledge",
                                  "bulk_ingest_knowledge", "invoke_skill"])
async def test_real_background_disabled_gate_precedes_store_skill_effect(
    name, authenticated_executor,
):
    from src.discord.background_task import _execute_tool_captured
    from src.tools.builtin_policy import BuiltinToolPolicy

    executor, owner_id = authenticated_executor
    config = SimpleNamespace(tools=SimpleNamespace(disabled_tools=[name]))
    executor.set_builtin_policy(BuiltinToolPolicy(lambda: config, lambda: {name: True}))
    store = Mock()
    embedder = Mock()
    skills = Mock()
    result = await _execute_tool_captured(
        name, {"source": "fixture", "content": "inert", "query": "fixture",
               "items": [{"type": "url", "url": "https://fixture.invalid"}],
               "name": "fixture"},
        executor, skills, store, embedder, "Owner", requester_id=owner_id,
    )
    assert result.ok is False
    assert result.error == "tool_disabled"
    assert result.tool_name == name
    assert "was not executed" in result.output
    assert store.mock_calls == skills.mock_calls == embedder.mock_calls == []


@pytest.mark.parametrize("name", ["computer_session", "computer_observe", "computer_act"])
async def test_real_computer_owner_disabled_then_unwired_grant_denies(name):
    from src.computer.integration import ComputerIntegration
    from src.discord.native_tools.registry import NativeToolDispatcher
    from src.tools.builtin_policy import BuiltinToolPolicy
    from src.tools.registry import get_tool_definitions

    bot = SimpleNamespace(config=SimpleNamespace(computer=SimpleNamespace(enabled=True)))
    controller = SimpleNamespace(session=AsyncMock(), observe=AsyncMock(), act=AsyncMock())
    computer = ComputerIntegration(bot, controller=controller)
    config = SimpleNamespace(tools=SimpleNamespace(disabled_tools=[name]))
    policy = BuiltinToolPolicy(lambda: config, lambda: {name: True})
    dispatcher = NativeToolDispatcher(
        owners={"computer": computer}, skill_manager=None, tool_catalog=None,
        prompt_builder=None, channel_state=None, builtin_policy=policy,
    )
    message = SimpleNamespace(conversation_id="fixture")
    result, effects = await dispatcher.dispatch(
        name, {}, message=message, user_id="claimed-owner", skill_file_delivery="stage",
    )
    assert result.error == "tool_disabled" and not result.ok
    assert not effects.rebuild_system_prompt
    config.tools.disabled_tools = []
    assert not policy.is_available(name)
    assert get_tool_definitions(readiness={name: True}) == []
    result, _ = await dispatcher.dispatch(
        name, {}, message=message, user_id="claimed-owner", skill_file_delivery="stage",
    )
    assert result.error == "permission_denied" and not result.ok
    for callback in (controller.session, controller.observe, controller.act):
        callback.assert_not_called()


async def test_real_native_scheduler_disabled_precedes_actual_owner_handler():
    from src.discord.native_tools.registry import NativeToolDispatcher
    from src.discord.native_tools.scheduling import SchedulingTools
    from src.tools.builtin_policy import BuiltinToolPolicy

    scheduler = Mock()
    scheduling = SchedulingTools(scheduler=scheduler)
    config = SimpleNamespace(tools=SimpleNamespace(disabled_tools=["list_schedules"]))
    dispatcher = NativeToolDispatcher(
        owners={"scheduling": scheduling}, skill_manager=None, tool_catalog=None,
        prompt_builder=None, channel_state=None,
        builtin_policy=BuiltinToolPolicy(lambda: config),
    )
    dispatcher.register("list_schedules", "scheduling", "_handle_list_schedules", "msg_input")
    result, effects = await dispatcher.dispatch(
        "list_schedules", {}, message=object(), user_id="claimed-owner",
        skill_file_delivery="stage",
    )
    assert not result.ok and result.error == "tool_disabled"
    assert not effects.rebuild_system_prompt
    assert scheduler.mock_calls == []


@pytest.mark.parametrize("name", ["run_command", "fetch_url"])
async def test_real_executor_readiness_denies_authenticated_owner_before_handler(
    name, authenticated_executor,
):
    from src.tools.builtin_policy import BuiltinToolPolicy

    executor, owner_id = authenticated_executor
    config = SimpleNamespace(tools=SimpleNamespace(disabled_tools=[]))
    callback = AsyncMock(side_effect=AssertionError("unready handler entered"))
    executor.__dict__["_handle_" + name] = callback
    executor.set_builtin_policy(BuiltinToolPolicy(lambda: config, lambda: {}))
    result = await executor.execute(name, {}, user_id=owner_id)
    assert not result.ok and result.error == "tool_unavailable"
    callback.assert_not_called()


def test_fresh_profile_does_not_import_or_repair_legacy_config(tmp_path):
    from src.desktop.authority import OwnerAuthority
    from src.desktop.paths import ProfilePaths

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    original = {"config.yml": b"[]\n", "key": b"inert key fixture", "state.json": b"invalid"}
    for name, data in original.items():
        (legacy / name).write_bytes(data)
    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path / "fresh")
    authority = OwnerAuthority(paths)
    try:
        assert not paths.config_file.exists()
        assert sorted(path.name for path in paths.config_dir.iterdir()) == [
            ".identity.lock", "profile.json",
        ]
        assert all((legacy / name).read_bytes() == data for name, data in original.items())
        assert not any(paths.secrets_dir.iterdir())
    finally:
        authority.release_runtime()


def test_profile_logging_is_owned_local_and_not_server_journal(monkeypatch, tmp_path):
    from src.desktop.paths import ProfilePaths
    from src.odin_log.logger import setup_logging

    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / ".local/share"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / ".cache"))
    monkeypatch.delenv("ODIN_DESKTOP_PROFILE", raising=False)
    monkeypatch.setenv("ODIN_LOG_FILE", str(tmp_path / "obsolete-server.log"))
    root = logging.getLogger("odin")
    previous = list(root.handlers)
    root.handlers.clear()
    try:
        setup_logging()
        files = [handler for handler in root.handlers if hasattr(handler, "baseFilename")]
        assert len(files) == 1
        assert Path(files[0].baseFilename) == paths.data_dir / "logs/odin.log"
        assert files[0].maxBytes * (files[0].backupCount + 1) == 50 * 1024 * 1024
        assert not (tmp_path / "obsolete-server.log").exists()
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
            handler.close()
        root.handlers.extend(previous)


def test_current_workflow_has_no_expression_interpolation_into_shell():
    workflows = sorted((ROOT / ".github/workflows").glob("*.yml"))
    assert workflows
    offenders = []
    for path in workflows:
        workflow = yaml.safe_load(path.read_text())
        for job in workflow.get("jobs", {}).values():
            for step in job.get("steps", []):
                if "${{" in str(step.get("run", "")):
                    offenders.append((path.name, step.get("name")))
    assert offenders == []


def test_no_current_release_tag_consumer_or_autonomous_engine_script():
    assert not (ROOT / ".github/workflows/release.yml").exists()
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        workflow = yaml.safe_load(path.read_text())
        assert "build-deb" not in workflow.get("jobs", {})
        events = workflow.get("on", workflow.get(True, {}))
        assert not any("tags" in settings for settings in events.values()
                       if isinstance(settings, dict))
        assert "GITHUB_REF_NAME" not in path.read_text()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert not project.get("scripts")
    tree = ast.parse((ROOT / "src/cli.py").read_text())
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef))
    assert main.name == "main"
    assert isinstance(main.body[-1], ast.Raise)
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree))


def test_exact_triage_rows_are_frozen_symbols_and_real_local_test_selectors():
    document = json.loads(TRIAGE.read_text())
    cases = document["cases"]
    assert cases
    assert len({case["original"] for case in cases}) == len(cases)
    local = {symbol for symbol, node in nodes(ast.parse(Path(__file__).read_text()))
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name.startswith("test_")}
    frozen = {}
    for case in cases:
        path, *symbols = case["original"].split("::")
        if path not in frozen:
            source = frozen_source(path)
            frozen[path] = (digest(source), {symbol for symbol, node in nodes(ast.parse(source))
                                           if isinstance(node, (ast.FunctionDef,
                                                                ast.AsyncFunctionDef))})
        sha, original_symbols = frozen[path]
        assert case["source_sha256"] == sha
        assert ".".join(symbols) in original_symbols
        assert case["reason"]
        assert case["disposition"] in {
            "executable", "removed-surface-replacement", "phase2-admission-wiring",
            "native-prohibited-scope",
        }
        for selector in case["replacement_cases"] + case["executable"]:
            file, function = selector.split("::")
            assert file == "tests/test_desktop_final_distribution.py"
            assert function.split("[", 1)[0] in local
