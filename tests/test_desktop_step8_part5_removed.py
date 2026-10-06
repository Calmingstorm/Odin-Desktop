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
                    "systemd-docker-postinstall", "raw-source-web-build",
                    "operator-document-wording"}
                assert not case["selectors"]
            elif case["disposition"] in {"proposed", "deferred"}:
                assert case["owner"] and case["blocker"]
                assert not case["selectors"]
            else:
                assert case["mode"] == "desktop-counterpart"
                assert case["counterpart"] and case["selectors"]
    assert totals == {"restored": 1, "retired": 32, "deferred": 4, "proposed": 0}


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


def test_static_tool_inventory_preserves_registry_identity_and_core_schemas():
    from src.tools.registry import TOOL_MAP, TOOLS, get_documentation_tool_definitions

    definitions = get_documentation_tool_definitions()
    names = [tool["name"] for tool in TOOLS]
    assert names and len(set(names)) == len(names)
    assert list(TOOL_MAP) == names == [tool["name"] for tool in definitions]
    core_names = {tool["name"] for tool in TOOLS if tool.get("is_core")}
    assert core_names
    assert {tool["name"] for tool in definitions if tool.get("is_core")} == core_names
    for original, published in zip(TOOLS, definitions, strict=True):
        assert TOOL_MAP[original["name"]] is original
        assert published["input_schema"] == original["input_schema"]
        assert published["input_schema"] is not original["input_schema"]
    definitions[0]["input_schema"]["properties"]["fixture_only"] = {"type": "string"}
    assert "fixture_only" not in TOOLS[0]["input_schema"]["properties"]
    fresh_schema = get_documentation_tool_definitions()[0]["input_schema"]
    assert "fixture_only" not in fresh_schema["properties"]


def test_codex_effort_defaults_and_input_budget_are_schema_behavior():
    from pydantic import ValidationError

    from src.config.model_defaults import COMPAT_MAIN_MODEL
    from src.config.schema import (
        CODEX_MODEL_UNSUPPORTED_EFFORTS,
        CODEX_REASONING_EFFORTS,
        Config,
        OpenAICodexConfig,
        allowed_efforts_for_model,
        input_budget_floor_for_model,
    )

    defaults = OpenAICodexConfig()
    assert defaults.model == COMPAT_MAIN_MODEL
    assert defaults.reasoning_effort == "xhigh"
    assert CODEX_MODEL_UNSUPPORTED_EFFORTS["gpt-6.1-sol"] == {"none"}
    assert input_budget_floor_for_model(" gpt-6.1-sol ") == 921_849
    assert allowed_efforts_for_model("gpt-6.1-sol") == CODEX_REASONING_EFFORTS - {"none"}
    for effort in ("low", "medium", "high", "xhigh", "max"):
        config = Config(openai_codex={"model": "gpt-6.1-sol", "reasoning_effort": effort})
        assert config.openai_codex.reasoning_effort == effort
        assert config.llm_provider.model == "gpt-6.1-sol"
    with pytest.raises(ValidationError, match="gpt-6.1-sol"):
        Config(openai_codex={"model": "gpt-6.1-sol", "reasoning_effort": "none"})


@pytest.mark.asyncio
async def test_managed_hyprland_first_use_ipc_timeout_is_bounded_and_closes_peer(
    tmp_path, monkeypatch
):
    import socket
    import time

    from src.computer.runtime import hyprland_plugin as plugin
    from tests.test_hyprland_plugin_campaign import approval, identity

    approved, _ = approval(tmp_path)
    adapter = plugin.HyprlandPluginIPC(identity=identity(approved), ipc_path="fixture-only")
    client, peer = socket.socketpair()
    client.setblocking(False)
    deadlines = []

    async def connect(_path, pid, uid, deadline):
        assert (pid, uid) == (adapter.identity.process.pid, adapter.identity.process.uid)
        deadlines.append(deadline)
        return client

    async def revalidate(_identity, deadline):
        deadlines.append(deadline)

    monkeypatch.setattr(plugin, "connect_peer", connect)
    monkeypatch.setattr(plugin, "revalidate", revalidate)
    started = time.monotonic()
    try:
        # Peer deliberately never replies or EOFs. This is an isolated socket,
        # not a compositor, and exercises the real shared half-second deadline.
        with pytest.raises(plugin.HyprlandPluginError, match="ipc_unavailable"):
            await asyncio.wait_for(adapter._request(b"j/plugin list"), timeout=2)
        assert deadlines and len(set(deadlines)) == 1
        assert 0 < deadlines[0] - started <= 0.51
        assert client.fileno() == -1
        assert peer.recv(4096) == b"j/plugin list"
        assert peer.recv(4096) == b""
    finally:
        client.close()
        peer.close()


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


@pytest.mark.asyncio
async def test_tool_batch_budget_and_retained_cycle_count_supplemental(graph, monkeypatch):
    from types import SimpleNamespace

    from src.discord.tool_loop import Phase2WiringRequired
    from src.llm.types import LLMResponse, ToolCall
    from src.tools.autonomous_loop import LoopInfo

    requests, engine, provider, transcript, cid = graph
    config = engine.deps.get_config()
    config.tools.max_tool_iterations_chat = 2
    config.tools.max_tool_iterations_loop = 1
    executed = []
    batches = []
    execute_batch = engine.runner._execute_tool_calls

    async def observe_batch(st, tool_calls):
        results = await execute_batch(st, tool_calls)
        batches.append((list(tool_calls), list(results)))
        return results

    monkeypatch.setattr(engine.runner, "_execute_tool_calls", observe_batch)

    async def harmless_tool(inp):
        executed.append(inp["expression"])
        return f"result:{inp['expression']}"

    scheduling = engine.deps.native_tools.owners["scheduling"]
    monkeypatch.setattr(scheduling, "_handle_parse_time", harmless_tool)
    calls = [ToolCall(f"budget-{i}", "parse_time", {"expression": f"fixture-{i}"})
             for i in range(6)]
    provider.responses = [
        LLMResponse(tool_calls=calls[:3], stop_reason="tool_use"),
        LLMResponse(tool_calls=calls[3:], stop_reason="tool_use"),
        LLMResponse(text="This third generation must not run."),
    ]
    receipt = requests.submit({"client_submission_id": "batch-budget",
        "conversation_id": cid, "text": "Run the six harmless fixture conversions"})
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    assert requests.get_request(receipt["request_id"])["state"] == "failed"
    assert len(provider.calls) == 2
    assert len(provider.responses) == 1
    assert sorted(executed) == [f"fixture-{i}" for i in range(6)]
    assert [[call.id for call in batch_calls] for batch_calls, _ in batches] == [
        [call.id for call in calls[:3]], [call.id for call in calls[3:]]]
    assert [(block["tool_use_id"], block["content"])
            for _, batch_results in batches for block in batch_results] == [
        (call.id, f"result:{call.input['expression']}") for call in calls]
    assert "cap (2) after 6 tool calls" in transcript.read_conversation(cid)[-1]["text"]

    # Retained scheduler kernel only: synthetic task metadata is not durable
    # admission or autonomous conversation delivery. Do not bypass either gate.
    channel = SimpleNamespace(send=AsyncMock())
    manager = engine.deps.loop_manager
    row = LoopInfo(id="synthetic-budget", goal="fixture", mode="silent",
        interval_seconds=0, stop_condition=None, max_iterations=3,
        channel_id=cid, requester_id="fixture", requester_name="fixture")
    cycles = []

    async def cycle(_prompt, supplied_channel, previous, cancel):
        assert supplied_channel is channel and cancel is row._cancel_event
        assert previous == (None if not cycles else "\n---\n".join(
            f"Iteration {i}: cycle-{i}" for i in cycles))
        cycles.append(row.iteration_count)
        return f"cycle-{row.iteration_count}"

    await manager._run_loop(row, channel, cycle)
    assert cycles == [1, 2, 3]
    assert row.iteration_count == row.max_iterations == 3
    assert row.status == "completed" and not row._cancel_event.is_set()
    channel.send.assert_awaited_once_with(
        "Loop `synthetic-budget` completed after 3 iterations.")
    assert len(provider.calls) == 2 and len(executed) == 6
    # The per-autonomous-cycle LLM cap itself remains unavailable at the
    # composed entrypoint; these assertions do not claim live loop readiness.
    with pytest.raises(Phase2WiringRequired):
        await engine.runner.run_autonomous("fixture", channel, None, "fixture")
    assert manager.start_loop("fixture", channel, "fixture", "fixture", cycle,
        max_iterations=3).startswith("Error: Autonomous loops unavailable:")
    assert manager._loops == {}
