"""Canonical usage writer and calibration hooks, without transport facades."""
import pytest

from src.llm.context_budget import WorkloadScope
from src.llm.window_observer import WindowObserver
from tests.desktop_adapters.step8_6a_characterization import (
    characterization_owner as characterization_owner,
)
from tests.desktop_adapters.step8_6a_characterization import make_bot


@pytest.mark.asyncio
async def test_real_usage_owner_indexes_a_saved_chat_turn():
    from src.trajectories.saver import TrajectoryTurn

    bot = make_bot()
    rollup = bot.usage_rollup
    assert rollup.available
    assert rollup.db_path.is_file()
    assert bot.tool_catalog.get_usage_rollup() is rollup
    await bot.trajectory_saver.save(TrajectoryTurn(
        message_id="usage-wiring", channel_id="local-conversation", user_id="fixture-owner"))
    await rollup.stop()
    connection = rollup._ro_connect()
    try:
        assert connection.execute("SELECT COUNT(*) FROM turn_facts").fetchone()[0] == 1
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_actual_calibration_release_hooks(tmp_path):
    from types import SimpleNamespace

    from src.config.schema import Config
    from src.desktop.authority import OwnerAuthority
    from src.desktop.commands import JournalStore
    from src.desktop.conversations import ConversationStore
    from src.desktop.delivery import DurableDelivery, PublicationEventJournal
    from src.desktop.paths import ProfilePaths
    from src.desktop.services import build_engine_services
    from src.desktop.transcript import TranscriptStore
    from src.permissions.manager import PermissionManager

    paths = ProfilePaths.from_xdg("calibration-wiring", home=tmp_path, environ={})
    authority = OwnerAuthority(paths)
    permissions = PermissionManager(authority)
    store = JournalStore(paths.data_dir / "transport.sqlite3", paths.profile_id)
    events = PublicationEventJournal(store)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    cfg = Config()
    cfg.openai_codex.enabled = False
    cfg.browser.enabled = False
    cfg.learning.enabled = False
    cfg.context.directory = str(paths.data_dir / "context")
    observer = WindowObserver(paths.data_dir / "window-evidence.json")
    engine = build_engine_services(cfg, paths, permissions,
        delivery=DurableDelivery(store, events, transcript_commit=transcript.commit),
        runtime_context=SimpleNamespace(window_observer=observer))
    try:
        d = engine.deps
        assert d.agent_manager._window_observer is observer
        assert d.housekeeping._window_observer is observer
        assert engine.runner._window_observer is observer
        for kind, owner, identity in (("loop", d.loop_manager, "loop-wiring"),
                                      ("agent", d.agent_manager, "agent-wiring")):
            scope = WorkloadScope(kind, identity)
            observer._density_milli[(kind, identity, "gpt-5.6-sol")] = 609
            owner._release_calibration(identity)
            assert observer.density_for(scope, "gpt-5.6-sol") is None
    finally:
        await engine.close()
        store.close()
        authority.release_runtime()
