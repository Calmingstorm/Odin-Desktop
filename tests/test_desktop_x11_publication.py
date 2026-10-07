"""Publication and admitted native action, exclusively on a private Xvfb."""

import asyncio
import json
import os
import shutil
import subprocess
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.config.schema import Config
from src.desktop.computer_binding import ComputerBindingService, bind_foreground
from src.desktop.services import _ReadyCatalog, _ReadyPolicy
from src.llm.openai_codex import CodexChatClient
from tests.test_desktop_computer_binding import call, execute
from tests.test_desktop_computer_binding import graph as binding_graph

graph = binding_graph


def service_for(g, tmp_path, enabled=True):
    config = Config()
    config.computer.enabled = enabled
    config.computer.storage_dir = str(tmp_path / "native-store")
    service = ComputerBindingService(
        SimpleNamespace(authority=g.authority, permissions=g.permissions),
        SimpleNamespace(config=config))
    return service, config


def catalog_for(service, config):
    policy = _ReadyPolicy(lambda: config, lambda: {name: service.published_available
        for name in ("computer_session", "computer_observe", "computer_act")})
    return _ReadyCatalog(policy=policy,
        get_config=lambda: config,
        skill_manager=SimpleNamespace(get_tool_definitions=lambda: []),
        computer_available=lambda: service.published_available)


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,session,display,failed,reason", [
    (True, "x11", ":32100", False, "available_on_x11"),
    (False, "x11", ":32100", False, "computer_disabled"),
    (True, "wayland", ":32100", False, "wayland_computer_use_requires_1_1"),
    (True, "x11", "remote:0", False, "local_x11_display_required"),
    (True, "x11", ":32100", True, "x11_backend_unavailable"),
    (True, "x11", ":32100", "backend", "x11_backend_unavailable"),
])
async def test_publication_reasons(graph, tmp_path, monkeypatch,
                                   enabled, session, display, failed, reason):
    monkeypatch.setenv("XDG_SESSION_TYPE", session)
    monkeypatch.setenv("DISPLAY", display)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    child = SimpleNamespace(returncode=1 if failed is True else 0,
        communicate=AsyncMock(return_value=(b'["screen"]', b"")), wait=AsyncMock())
    spawn = AsyncMock(return_value=child)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    backend = SimpleNamespace(start=AsyncMock(return_value={"ok": True}),
        detach=AsyncMock(return_value={"stopped": True, "released": True,
                                      "no_inflight_input": True}))
    if failed == "backend":
        backend.start.side_effect = RuntimeError("native startup failed")
    def factory(**_kwargs):
        return backend
    monkeypatch.setattr("src.computer.runtime.x11_attached.X11AttachedBackend", factory)
    service, config = service_for(graph, tmp_path, enabled)
    await service.start()
    facade = bind_foreground(service, graph.requests)
    try:
        ready = reason == "available_on_x11"
        assert service.readiness()["reason"] == reason
        assert service.published_available is facade.published_available is ready
        assert service.readiness()["input_supported"] is ready
        names = {row["name"] for row in catalog_for(service, config).merged_definitions()}
        assert ({"computer_session", "computer_observe", "computer_act"} <= names) is ready
        assert spawn.await_count == int(enabled and session == "x11" and display == ":32100")
        if ready:
            assert facade.settings.environment == "existing_session"
            assert facade.settings.display == display
            # Runtime-only discovery must not be saved as user configuration.
            assert config.computer.display == "" and config.computer.monitor_names == []
            # Activation uses the transaction's target before config persistence.
            config.computer.enabled = False
            activation = service.prepare_settings(config.model_copy(deep=True),
                                                   [("computer.enabled", False)])
            await activation.apply()
            assert not facade.enabled and not facade.published_available
            desired = config.model_copy(deep=True)
            desired.computer.enabled = True
            activation = service.prepare_settings(desired, [("computer.enabled", True)])
            await activation.apply()
            config.computer.enabled = True
            assert facade.enabled and facade.published_available
            await service.controller.set_enabled(False)
            assert not facade.published_available and not service.published_available
    finally:
        await service.close()
    assert service.readiness()["reason"] == "computer_closed"


@pytest.fixture
def private_x11(tmp_path, monkeypatch):
    assert os.environ.get("DISPLAY") != ":0"
    assert os.getpid() != 1 and os.readlink("/proc/self/ns/pid") == os.readlink("/proc/1/ns/pid")
    # The approved launcher removes host display sockets and creates private /tmp.
    assert not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")
    assert not __import__("pathlib").Path("/tmp/.X11-unix/X0").exists()
    assert all(shutil.which(tool) for tool in ("Xvfb", "xauth"))
    from Xlib import X, display

    name = f":{32000 + os.getpid() % 20000}"
    authority = str(tmp_path / "authority")
    subprocess.run(["xauth", "-f", authority, "add", name, ".", os.urandom(16).hex()],
                   check=True, timeout=3, capture_output=True)
    monkeypatch.setenv("DISPLAY", name)
    monkeypatch.setenv("XAUTHORITY", authority)
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    server = subprocess.Popen(["Xvfb", name, "-screen", "0", "800x600x24",
        "-auth", authority, "-nolisten", "tcp", "-noreset", "-extension", "GLX"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    receiver = None
    try:
        deadline = time.monotonic() + 5
        while receiver is None:
            try:
                receiver = display.Display(name)
            except Exception:
                assert server.poll() is None and time.monotonic() < deadline
                time.sleep(0.03)
        root = receiver.screen().root
        window = root.create_window(20, 20, 600, 400, 0, receiver.screen().root_depth,
            X.InputOutput, X.CopyFromParent, background_pixel=0xFFFFFF,
            event_mask=X.ButtonPressMask | X.ButtonReleaseMask)
        window.set_wm_name("Odin Desktop harmless receiver")
        window.set_wm_class("desktop-receiver", "DesktopReceiver")
        window.change_property(receiver.intern_atom("_NET_WM_PID"),
            receiver.intern_atom("CARDINAL"), 32, [os.getpid()])
        window.map()
        window.set_input_focus(X.RevertToParent, X.CurrentTime)
        receiver.sync()
        yield receiver
    finally:
        if receiver is not None:
            receiver.close()
        server.terminate()
        server.wait(timeout=5)


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_model_catalog_and_admitted_receiver_action(graph, tmp_path, private_x11, enabled):
    from Xlib import X

    service, config = service_for(graph, tmp_path, enabled)
    await service.start()
    facade = bind_foreground(service, graph.requests)
    graph.engine.computer = facade
    catalog = catalog_for(service, config)
    names = {row["name"] for row in catalog.merged_definitions()}
    try:
        assert service.published_available is enabled, service.readiness()
        if not enabled:
            assert not {"computer_session", "computer_observe", "computer_act"} & names
            return
        assert {"computer_session", "computer_observe", "computer_act"} <= names
        adapter = CodexChatClient(auth=object(), model="synthetic-transport")

        async def hook(_message, st):
            st._computer_serving = SimpleNamespace(provider="codex", client=adapter,
                                                  model=adapter.model)
            with facade.foreground(st, call(operation="start")):
                result = await facade._handle_computer_session({"operation": "start"})
                assert result.ok, result
                grant = json.loads(result.output)
            block = call("computer_observe")
            with facade.foreground(st, block):
                image = await facade._handle_computer_observe({"session_id": grant["session_id"],
                                                              "generation": grant["generation"]})
                assert isinstance(image, dict), image
                await facade.validate_delivery(st, block, image)
            live = facade.controller._live[grant["session_id"]]
            observation = next(reversed(live.observations.values()))
            payload = {"session_id": grant["session_id"], "generation": grant["generation"],
                "consent_generation": observation.scope.consent_generation,
                "source_id": observation.source.source_id,
                "source_revision": observation.source.source_revision,
                "observation_id": observation.observation_id, "action_id": "receiver-click",
                "operation": "click", "x": 80, "y": 80,
                "expect": {"type": "pointer_at", "x": 80, "y": 80}}
            with facade.foreground(st, call("computer_act")):
                action = await facade._handle_computer_act(payload)
                receipt = (action.get("__computer_action_receipt__") if isinstance(action, dict)
                           else json.loads(action.output))
                assert receipt["status"] == "verified", receipt
            private_x11.sync()
            events = []
            while private_x11.pending_events():
                events.append(private_x11.next_event().type)
            assert events.count(X.ButtonPress) == events.count(X.ButtonRelease) == 1

        await execute(graph, hook)
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_real_core_catalog_live_activation(tmp_path, private_x11):
    from src.desktop.core import CoreService, profile_config
    from src.llm.types import LLMResponse
    from src.permissions.manager import PermissionManager
    from tests.test_desktop_core_lifecycle import connect, profile, request
    from tests.test_desktop_engine_services import Provider
    from tests.test_desktop_management_core import TemporaryKeyring

    paths, socket_path, token_file = profile(tmp_path)
    config = profile_config(paths)
    config.openai_codex.enabled = False
    config.llm_provider.model = "compat:test"
    config.openai_compatible.enabled = True
    config.learning.enabled = False
    config.browser.enabled = False
    provider = Provider([LLMResponse(text="Private receiver inspected.") for _ in range(2)])
    read_fd, write_fd = os.pipe()
    core = CoreService(paths, socket_path, token_file, secret_backend=TemporaryKeyring(),
        config_provider=lambda _: config,
        runtime_provider=lambda *_: SimpleNamespace(compatible_client=provider))
    writer = None
    try:
        await core.start(read_fd)
        reader, writer, _welcome = await connect(socket_path)
        catalog = core.engine.deps.tool_catalog
        computer_names = {"computer_session", "computer_observe", "computer_act"}

        async def model_turn(label):
            cid = core.conversations.create()["conversation"]["id"]
            owner = core.authority.authenticate_local(peer_uid=core.authority.owner_uid)
            token = PermissionManager.set_request_owner(owner)
            try:
                submitted = core.requests.submit({"client_submission_id": label,
                    "conversation_id": cid, "text": "Inspect the private harmless receiver"})
            finally:
                PermissionManager.reset_request_owner(token)
            await core.requests.after_commit()
            await asyncio.gather(*core.requests._tasks)
            assert core.requests.get_request(submitted["request_id"])["state"] == "completed"
            return {tool["name"] for tool in provider.calls[-1]["tools"]}

        assert not computer_names & {row["name"] for row in catalog.merged_definitions()}
        assert not computer_names & await model_turn("disabled")
        schema = (await request(reader, writer, "settings.schema"))["result"]
        assert [field["path"] for field in schema["fields"]
                if field["path"].startswith("computer.")] == ["computer.enabled"]
        changed = await request(reader, writer, "computer.activation.set", {
            "expected_revision": schema["revision"],
            "changes": [{"path": "computer.enabled", "value": True}]})
        assert changed["ok"], changed
        status = (await request(reader, writer, "computer.status"))["result"]
        assert status["readiness"]["foreground_available"], status
        assert core.computer_foreground.published_available
        assert computer_names <= {row["name"] for row in catalog.merged_definitions()}
        assert computer_names <= await model_turn("enabled")
        runtime = (await request(reader, writer, "status.get"))["result"]
        assert runtime["computer"] == {"published_available": True, "reason": "available_on_x11"}
        schema = (await request(reader, writer, "settings.schema"))["result"]
        changed = await request(reader, writer, "computer.activation.set", {
            "expected_revision": schema["revision"],
            "changes": [{"path": "computer.enabled", "value": False}]})
        assert changed["ok"], changed
        assert not computer_names & {row["name"] for row in catalog.merged_definitions()}
        assert not core.computer_foreground.enabled
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)
