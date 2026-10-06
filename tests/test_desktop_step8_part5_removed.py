"""Concrete retained semantics from the removed web updater's mixed suites.

These are desktop-counterpart tests, not frozen copies of the HTTP assertions.
No updater, signal, display, network listener or real credential is involved.
"""
import ast
import asyncio
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
import yaml

from src.config.image_defaults import IMAGE_MODEL_DEFAULTS
from src.config.schema import load_config
from src.desktop.authority import OwnerAuthority
from src.desktop.paths import ProfilePaths
from src.desktop.provisioning import ensure_profile
from src.desktop.secrets import ProfileSecretStore
from src.desktop.settings import SettingsService
from tests.test_desktop_engine_services import graph as graph


class EmptyKeyring:
    def get_password(self, *_):
        return None


def test_removed_case_map_covers_every_inherited_definition_and_hash():
    root = Path(__file__).resolve().parents[1]
    plan = json.loads((root / "maintenance/phase2-step8-part5-removed-cases.json").read_text())
    assert plan["schema_version"] == 1
    assert len(plan["suites"]) == 4
    totals = {name: 0 for name in ("restored", "retired", "deferred", "proposed")}
    for suite in plan["suites"]:
        original = (root / suite["path"]).read_bytes()
        assert hashlib.sha256(original).hexdigest() == suite["inherited_sha256"]
        tree = ast.parse(original)
        definitions = {}
        for node in tree.body:
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name.startswith("test_")):
                definitions[node.name] = node.lineno
            if isinstance(node, ast.ClassDef):
                for case in node.body:
                    if (isinstance(case, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and case.name.startswith("test_")):
                        definitions[f"{node.name}.{case.name}"] = case.lineno
        cases = suite["cases"]
        assert len({case["case"] for case in cases}) == len(cases)
        assert {case["case"]: case["line"] for case in cases} == definitions
        for case in cases:
            totals[case["disposition"]] += 1
            assert case["reason"]
            if case["disposition"] == "retired":
                assert case["citation"] == "Claude, review of step 8 part 5"
                assert case["category"] in {
                    "web-ui-only", "self-update-apply-rollback",
                    "systemd-docker-postinstall", "raw-source-web-build"}
                assert not case["selectors"]
            elif case["disposition"] in {"proposed", "deferred"}:
                assert case["owner"] and case["blocker"]
                assert not case["selectors"]
            else:
                assert case["mode"] == "desktop-counterpart"
                assert case["counterpart"] and case["selectors"]
    assert totals == {"restored": 1, "retired": 24, "deferred": 4, "proposed": 8}


def test_onboarding_image_follow_defaults_persist_without_pinning(tmp_path, monkeypatch):
    restart = Mock(side_effect=AssertionError("onboarding must not request updater re-exec"))
    monkeypatch.setattr("src.restart.request_restart", restart)
    paths = ProfilePaths.from_xdg("image-onboarding", home=tmp_path, environ={})
    authority = OwnerAuthority(paths)
    try:
        config = ensure_profile(paths, authority=authority)
        settings = SettingsService(
            paths, ProfileSecretStore(paths, backend=EmptyKeyring()), config=config)
        settings.save_changes([(("browser", "enabled"), True)])
        before = paths.config_file.read_bytes()
        native = yaml.safe_load(before).get("image", {}).get("openai", {})
        assert "image_model" not in native and "outer_model" not in native
        cfg = load_config(paths.config_file)
        assert (cfg.image.openai.image_model, cfg.image.openai.outer_model) == (
            IMAGE_MODEL_DEFAULTS["image_model"], IMAGE_MODEL_DEFAULTS["outer_model"])
        assert cfg.browser.enabled
        assert not hasattr(cfg, "comfyui")
        assert paths.config_file.read_bytes() == before
        load_config(paths.config_file)
        assert paths.config_file.read_bytes() == before
        metadata = settings.schema()["image_models"]
        assert metadata["image_model"]["status"] == "follow"
        assert metadata["outer_model"]["status"] == "follow"
        restart.assert_not_called()
    finally:
        authority.release_runtime()


@pytest.mark.asyncio
async def test_stop_all_retained_owner_semantics_supplemental(graph):
    _requests, engine, _provider, _transcript, _cid = graph
    manager = engine.deps.loop_manager
    agents = engine.deps.native_tools.owners["agents"]
    assert agents._loop_manager is manager
    stop = AsyncMock(return_value="stopped 3 loops")
    original = manager.stop_loop
    manager.stop_loop = stop
    try:
        # This owner is real and composed, but readiness currently hides the
        # tool and there is no management stop-all IPC. This is supplemental
        # owner evidence, not restoration of the unavailable app surface.
        result = await agents._handle_stop_loop({"loop_id": "all"})
        assert result == "stopped 3 loops"
        stop.assert_called_once_with("all")
        # The retained handler emits a nonblocking lifecycle notification.
        await asyncio.sleep(0)
    finally:
        manager.stop_loop = original


@pytest.mark.asyncio
async def test_stop_all_retained_owner_waits_for_synthetic_task_settlement(graph):
    from src.tools.autonomous_loop import LoopInfo

    _requests, engine, _provider, _transcript, _cid = graph
    manager = engine.deps.loop_manager
    entered = [asyncio.Event(), asyncio.Event()]
    settled = []

    async def task(index):
        entered[index].set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            settled.append(index)

    # Synthetic task records exercise the retained cancellation primitive only.
    # They do not bypass disabled start_loop or claim durable loop admission.
    rows = []
    for index in range(2):
        row = LoopInfo(id=f"synthetic-{index}", goal="fixture", mode="silent",
            interval_seconds=10, stop_condition=None, max_iterations=1,
            channel_id="fixture", requester_id="fixture", requester_name="fixture")
        row._task = asyncio.create_task(task(index))
        manager._loops[row.id] = row
        rows.append(row)
    try:
        await asyncio.gather(*(event.wait() for event in entered))
        result = await manager.stop_loop("all")
        assert result == "Stopped 2 loop(s): synthetic-0, synthetic-1"
        assert set(settled) == {0, 1}
        assert all(row._task.done() and row._cancel_event.is_set() for row in rows)
    finally:
        for row in rows:
            row._task.cancel()
        await asyncio.gather(*(row._task for row in rows), return_exceptions=True)
        for row in rows:
            manager._loops.pop(row.id, None)
