"""The real core releases only the resumed turn's exact calibration scope."""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from src.desktop.core import CoreService
from src.llm.context_budget import chat_workload_scope
from src.llm.window_observer import WindowObserver
from src.turn_state import TurnKey
from tests.test_desktop_core_lifecycle import profile
from tests.test_desktop_request_core import Provider, configured


@pytest.mark.asyncio
async def test_real_core_resume_release_keeps_other_turn_and_agent_calibration(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    observer = WindowObserver(paths.data_dir / "window-evidence.json")
    core = CoreService(
        paths, socket_path, token_file, config_provider=configured,
        runtime_provider=lambda *_: SimpleNamespace(
            compatible_client=Provider(), window_observer=observer))
    read_fd, write_fd = os.pipe()
    try:
        await core.start(read_fd)
        key = TurnKey(source="conversation", channel_id="conversation-fixture",
                      message_id="request-fixture")
        scope = chat_workload_scope(key.source, key.channel_id, key.message_id)
        other = chat_workload_scope(key.source, key.channel_id, "other-request")
        model = "fixture-model"
        observer._density_milli[("chat", scope.workload_id, model)] = 609
        observer._density_milli[("chat", other.workload_id, model)] = 701
        observer._density_milli[("agent", "independent-agent", model)] = 801
        assert core.resume_manager is not None
        core.resume_manager._release_calibration(key)
        assert observer.density_for(scope, model) is None
        assert observer.density_for(other, model) == 701
        assert observer._density_milli[("agent", "independent-agent", model)] == 801
    finally:
        await core.close()
        os.close(read_fd)
        os.close(write_fd)
