"""Odin 4.22.0 (PR #729) in Desktop: Odin's new cases of frozen engine suites, verbatim.

Desktop keeps Odin's v4.13.0 test files byte for byte (several run through restored-corpus
adapters); Odin 4.22.0's new cases for them run here with those files' own helpers:

- stop and steer ownership through a session reset (#707), and the cleanup case Odin
  rewrote for it (the frozen one still passes and still runs);
- near-duplicate overlap counts the new document's chunks (#710);
- archive search takes the newest archives first (#713);
- a rejected create_skill keeps the file it replaced (#674);
- a pinned attachment workspace outlives cleanup (PR #729 review).

Odin's housekeeping timer case builds its 4.19.2 pass-summary fixtures, which Desktop's
housekeeping does not carry; tests/test_desktop_engine_producers.py runs the same timer.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

import tests.test_skill_manager_coverage as _skills_suite
from src.discord.attachments import AttachmentProcessor, pin_workspaces
from src.discord.channel_state import ChannelStateRegistry
from src.knowledge.store import INGEST_STORED
from src.tools.skill_manager import SkillManager
from tests.test_knowledge_ingest_outcomes import _close, _store  # noqa: F401
from tests.test_session_search import _archive_session, _manager  # noqa: F401
from tests.test_skill_manager_coverage import _skill_code  # noqa: F401


async def test_cleanup_keeps_a_running_turns_ownership_after_its_session_reset():
    """#707: a session reset (DELETE/clear/purge/prune) does not end the turn.

    Housekeeping drops channels with no session, but a turn still running
    there keeps its request, so /stop and steering still reach it.
    """
    reg = ChannelStateRegistry()
    registered = asyncio.Event()
    release = asyncio.Event()

    async def running_turn():
        reg.set_active_request("chan", "req")
        registered.set()
        await release.wait()
        reg.clear_active_request("chan", "req")

    task = asyncio.create_task(running_turn())
    await registered.wait()
    reg.cleanup(active_channels=set())  # the channel's session was reset
    assert reg.active_requests == {"chan": "req"}
    target = reg.request_stop("chan")
    assert target is not None and target[0] == "req"
    assert reg.cancel_events["chan"].is_set()
    release.set()
    await task
    assert "chan" not in reg.active_requests and reg._active_request_tasks == {}


async def test_cleanup_releases_stale_active_and_orphan_waiters():
    state = ChannelStateRegistry()

    async def turn_that_ended_without_clearing():
        state.set_active_request("active", "req")

    # A stale registration: its turn is gone but never cleared its ownership.
    await asyncio.create_task(turn_that_ended_without_clearing())
    request_id, active_waiter = state.request_stop("active")
    assert request_id == "req"
    state.cancel_events["active"].clear()
    state.stop_results["orphan"] = asyncio.get_running_loop().create_future()
    orphan_waiter = state.stop_results["orphan"]

    state.cleanup(active_channels=set())

    assert "active" not in state.active_requests
    assert active_waiter.done()
    assert orphan_waiter.done()
    assert "orphan" not in state.stop_results


manager = _skills_suite.manager  # the suite's fixture (some cases also name a local)

class TestStoreOutcomes:
    async def test_one_chunk_shared_with_a_source_that_repeats_it_is_stored(self, tmp_path):
        # The source repeats a boilerplate chunk; the new document shares only
        # that one chunk. Stored rows used to count once per copy (90%).
        from src.knowledge.store import CHUNK_SIZE

        def para(text: str) -> str:
            return (text + " ") * ((CHUNK_SIZE - 50) // (len(text) + 1))

        store = _store(tmp_path)
        try:
            source = "\n\n".join([para("boilerplate")] * 9 + [para("alpha")])
            assert int(await store.ingest(source, "a.md")) > 0
            other = "\n\n".join([para("boilerplate")] + [para(f"bravo{i}") for i in range(9)])
            outcome = await store.ingest(other, "b.md")
            assert outcome.status == INGEST_STORED and int(outcome) > 0
        finally:
            _close(store)


class TestSearchArchivesFiltered:
    def test_archives_are_searched_newest_first_across_channels(self, tmp_path):
        # Names are {channel}_{time}: name order ranks identity-keyed and
        # larger channel ids first, whatever their age.
        mgr = _manager(tmp_path)
        now = time.time()
        _archive_session(str(tmp_path), "111111111111111111", [
            {"role": "user", "content": "deploy notes NEW", "timestamp": now - 60},
        ], last_active=now - 60)
        _archive_session(str(tmp_path), "999999999999999999", [
            {"role": "user", "content": "deploy notes OLD", "timestamp": now - 30 * 86400},
        ], last_active=now - 30 * 86400)
        _archive_session(str(tmp_path), "claude-api-2", [
            {"role": "user", "content": "deploy notes OLDER", "timestamp": now - 60 * 86400},
        ], last_active=now - 60 * 86400)
        results = mgr._search_archives("deploy notes", 3)
        assert [r["content"] for r in results] == [
            "deploy notes NEW", "deploy notes OLD", "deploy notes OLDER",
        ]
        assert mgr._search_archives("deploy notes", 1)[0]["content"] == "deploy notes NEW"


class TestSkillManagerLifecycle:
    @pytest.mark.parametrize("candidate", ["def (:::", _skill_code("othername")])
    def test_create_over_failed_file_keeps_original_when_candidate_rejected(
        self, tmp_path, candidate
    ):
        # A same-name file that failed to load is not a loaded skill. Deleting
        # it is WebUI-only, so a rejected create must put its bytes back.
        skills = tmp_path / "skills"
        skills.mkdir()
        original = b"SKILL_DEFINITION = {'name': 'broken'\n# user's half-finished work\n"
        (skills / "broken.py").write_bytes(original)
        manager = SkillManager(str(skills), tool_executor=MagicMock())
        recorded = manager.definition_errors["broken.py"]
        out = manager.create_skill("broken", candidate)
        assert "kept unchanged" in out
        assert (skills / "broken.py").read_bytes() == original
        assert manager.definition_errors["broken.py"] == recorded
        assert not manager.has_skill("broken") and not manager.has_skill("othername")

    def test_create_over_failed_file_replaces_it_when_candidate_loads(self, tmp_path):
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "broken.py").write_text("def (:::")
        manager = SkillManager(str(skills), tool_executor=MagicMock())
        assert "created and loaded" in manager.create_skill("broken", _skill_code("broken"))
        assert manager.has_skill("broken") and "broken.py" not in manager.definition_errors

    def test_create_never_overwrites_a_loaded_skill_alias_file(self, tmp_path):
        # custom.py holds the working skill "demo"; creating "custom" must not
        # replace demo's source.
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "custom.py").write_text(_skill_code("demo"))
        manager = SkillManager(str(skills), tool_executor=MagicMock())
        assert manager.has_skill("demo")
        out = manager.create_skill("custom", _skill_code("custom"))
        assert "holds another loaded skill" in out
        assert (skills / "custom.py").read_text() == _skill_code("demo")
        assert not manager.has_skill("custom")

    def test_create_fresh_rejected_candidate_still_removes_its_file(self, manager):
        manager.create_skill("fresh", "def (:::")
        assert not (manager.skills_dir / "fresh.py").exists()


class TestWorkspaceCleanup:
    def test_a_pinned_workspace_outlives_cleanup_until_every_pin_ends(self, tmp_path):
        import os

        proc = AttachmentProcessor(temp_dir=str(tmp_path), retention_hours=0)
        pinned, other = tmp_path / "ch1" / "msg1", tmp_path / "ch1" / "msg2"
        for ws in (pinned, other):
            ws.mkdir(parents=True)
            (ws / "file.txt").write_text("saved")
            os.utime(ws, (0, 0))
        with pin_workspaces("ch1", ["msg1"]):
            with pin_workspaces("ch1", ["msg1"]):
                assert proc.cleanup_old_workspaces() == 1
            assert proc.cleanup_old_workspaces() == 0  # still held by the outer pin
            assert pinned.exists() and not other.exists()
        assert proc.cleanup_old_workspaces() == 1
        assert not pinned.exists()
