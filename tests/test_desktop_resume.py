"""Exact request resume uses the real validation/codec/lease path, not a new runner."""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

import src.discord.turn_resume as resume_module
from src.discord.response_guards import StuckLoopTracker
from src.discord.tool_loop import CHAT_POLICY, _ChatTurn
from src.discord.turn_resume import (
    ConversationAccessDeniedError,
    ConversationFetchUnavailableError,
    ConversationMessageNotFoundError,
    TurnResumeManager,
)
from src.trajectories.saver import TrajectoryTurn
from src.turn_state.codec import compute_content_digest, snapshot_chat_turn
from src.turn_state.store import OpState, TurnKey, TurnStateStore, TurnStatus
from tests.test_desktop_controls import ControlHarness
from tests.test_desktop_engine_services import graph as engine_graph

integrated_graph = engine_graph


class ResumeHarness(ControlHarness):
    def __init__(self, tmp_path, monkeypatch):
        super().__init__(tmp_path)
        self.ledger = TurnStateStore(tmp_path / "ledger" / "turns.sqlite3")
        self.key = TurnKey("conversation", "c", "r")
        self.original = SimpleNamespace(
            id="r", channel=SimpleNamespace(id="c"),
            author=SimpleNamespace(id="owner"), content="original task")
        lease, disposition = self.ledger.admit_turn_sync(
            self.key, guild_id=None, user_id="owner",
            content_digest=compute_content_digest(self.original.content), code_version="test",
            prompt_policy_hash=None, tool_catalog_hash=None, session_snapshot={})
        assert disposition == "admitted"
        trajectory = TrajectoryTurn(
            message_id="r", channel_id="c", user_id="owner", user_name="Owner",
            timestamp="2026-10-05T18:00:00Z", source="conversation",
            user_content="original task", system_prompt="preserved prompt", history=[])
        self.turn = _ChatTurn(
            message=self.original, policy=CHAT_POLICY, trace=None, system_prompt="preserved prompt",
            tools=None, messages=[{"role": "user", "content": "original task"}],
            user_id="owner", chat_cap=16, stuck_tracker=StuckLoopTracker(),
            _trajectory=trajectory, _result_store_cap=4000, _cancel=asyncio.Event(),
            _ch_id="c", _req_id="r", iteration=5, continuation_count=2,
            max_continuations=3, fabrication_retried=True, promise_retried=True,
            unavail_retried=True, hedging_retried=True, code_hedging_retried=True,
            premature_failure_retried=True, _validation_retries=1, _max_validation_retries=2,
            _rescue_passes=2, _char_latch=9000, tools_used_in_loop=["parse_time"],
            _gen_identity={"provider": "ollama", "model": "test-model", "effort": None,
                           "upstream_provider": None, "ladder": [12000, 9000],
                           "budget": {"primary_chars": 12000}, "attempts": [
                               {"attempt": 1, "account_key": None, "server_input_tokens": None},
                               {"attempt": 2, "account_key": None, "server_input_tokens": None}]})
        payload = snapshot_chat_turn(self.turn, store_blob=self.ledger.store_blob_sync,
                                     generation_seq=7,
                                     extra={"recovery_deadline_utc": time.time() - 5})
        self.ledger.suspend_sync(lease, payload)
        self.requests.add(state="suspended", ledger_generation=lease.generation)
        self.catalog = [{"name": "current_observation_tool"}]
        self.config = SimpleNamespace(tools=SimpleNamespace(enabled=True))
        self.fetch_error = None
        self.filter_calls = []
        self.released = []

        async def fetch(cid, rid):
            assert (cid, rid) == ("c", "r")
            if self.fetch_error:
                raise self.fetch_error
            return self.original

        def filter_tools(owner, tools):
            self.filter_calls.append((owner, tools))
            return tools if self.authorized else None

        # The fixture constructs the *unchanged* resume manager without the
        # production Phase-1 disabled construction gate. Only that deployment
        # gate is stubbed; reconstruction, current policy, codec and lease all
        # run their actual implementations. Integration wiring is parent-owned.
        monkeypatch.setattr(resume_module, "_require_phase2_wiring", lambda: None)
        manager = TurnResumeManager.__new__(TurnResumeManager)
        manager._store = self.ledger
        manager._tool_loop = SimpleNamespace(
            _stuck_loop_tracker_cls=StuckLoopTracker,
            _prompt_builder=SimpleNamespace(has_learned_provenance=lambda _: True))
        manager._channel_state = self.channels
        manager._permissions = SimpleNamespace(filter_tools=filter_tools)
        manager._tool_catalog = SimpleNamespace(merged_definitions=lambda: self.catalog)
        manager._get_config = lambda: self.config
        manager._fetch_message = fetch
        manager._release_workload = self.released.append
        manager._waiters = {}
        self.controls.resume_manager = manager

    async def close(self):
        for _row, turn in self.requests.resumed:
            turn.durability._stop_heartbeats()
        self.ledger.close()
        self.store.close()


@pytest.fixture
async def h(tmp_path, monkeypatch):
    harness = ResumeHarness(tmp_path, monkeypatch)
    yield harness
    await harness.close()


async def test_resume_increments_wire_generation_and_restores_exact_spent_state(h):
    answer = await h.controls.dispatch("control.resume", h.params())
    assert answer == {"ok": True, "result": {"disposition": "admitted"}}
    row, rebuilt = h.requests.resumed[0]
    assert row["request_id"] == "r" and row["generation"] == 2 and row["state"] == "running"
    assert rebuilt._req_id == "r" and rebuilt.message is h.original
    assert rebuilt.iteration == 5 and rebuilt.continuation_count == 2
    assert rebuilt._validation_retries == 1 and rebuilt._max_validation_retries == 2
    assert rebuilt._rescue_passes == 2 and rebuilt._char_latch == 9000
    assert all(getattr(rebuilt, key) for key in (
        "fabrication_retried", "promise_retried", "unavail_retried", "hedging_retried",
        "code_hedging_retried", "premature_failure_retried"))
    assert rebuilt.tools_used_in_loop == ["parse_time"]
    assert rebuilt.durability.generation_seq == 7
    assert rebuilt.durability.pop_resume_budget() == 0.0
    assert rebuilt.durability.pop_resume_budget() is None
    assert rebuilt.tools == h.catalog
    assert h.filter_calls == [("owner", h.catalog)]
    assert h.ledger.turn_status_sync(h.key) == TurnStatus.ACTIVE
    assert (await h.controls.dispatch("control.resume", h.params())) == answer
    assert len(h.requests.resumed) == 1
    assert [event["payload"]["generation"] for event in h.events.between(0)] == [2]


@pytest.mark.parametrize("status,releases", [
    (None, True), (TurnStatus.TERMINAL_REJECTED, True),
    (TurnStatus.TERMINAL_COMPLETED, True), (TurnStatus.ACTIVE, False),
    (TurnStatus.SUSPENDED, False),
])
async def test_empty_resume_load_releases_only_terminal_or_absent_lineage(
    h, monkeypatch, status, releases,
):
    monkeypatch.setattr(h.ledger, "load_resumable_sync", lambda _key: None)
    monkeypatch.setattr(h.ledger, "turn_status_sync", lambda _key: status)
    answer = await h.controls.dispatch("control.resume", h.params())
    assert answer["result"] == {
        "disposition": "rejected", "reason": "checkpoint_unavailable"}
    assert h.released == ([h.key] if releases else [])
    assert h.requests.resumed == []


async def test_resume_binds_requested_row_not_latest_other_suspension(h):
    h.requests.add("newer", state="suspended", ledger_generation="other")
    answer = await h.controls.dispatch("control.resume", h.params())
    assert answer["result"] == {"disposition": "admitted"}
    assert h.requests.resumed[0][0]["request_id"] == "r"
    assert h.requests.get_request("newer")["state"] == "suspended"


@pytest.mark.parametrize("other_state", ["queued", "running", "stop_requested"])
async def test_resume_rejects_other_work_in_same_conversation(h, other_state):
    h.requests.add("other", state=other_state)
    answer = await h.controls.dispatch("control.resume", h.params())
    assert answer["result"] == {"disposition": "rejected", "reason": "busy"}
    assert h.ledger.turn_status_sync(h.key) == TurnStatus.SUSPENDED
    assert not h.requests.resumed


@pytest.mark.parametrize("state", ["completed", "failed", "cancelled"])
async def test_resume_terminal_request_never_becomes_a_fresh_submission(h, state):
    h.store.connection.execute("UPDATE desktop_requests SET state=?", (state,))
    answer = await h.controls.dispatch("control.resume", h.params())
    assert answer["result"] == {"disposition": "rejected", "reason": "not_resumable"}
    assert not h.requests.resumed


async def test_resume_stale_generation_rejects_exact_binding(h):
    answer = await h.controls.dispatch("control.resume", h.params(generation=2))
    assert answer["result"] == {"disposition": "rejected", "reason": "stale_binding"}
    assert not h.requests.resumed


@pytest.mark.parametrize("error", [
    ConversationFetchUnavailableError(), ConversationAccessDeniedError()])
async def test_fetch_failure_preserves_checkpoint_without_fresh_execution(h, error):
    h.fetch_error = error
    answer = await h.controls.dispatch("control.resume", h.params())
    assert answer["result"]["disposition"] == "rejected"
    assert h.ledger.turn_status_sync(h.key) == TurnStatus.SUSPENDED
    assert not h.requests.resumed


@pytest.mark.parametrize("change", ["deleted", "edited", "author"])
async def test_original_message_validation_is_existing_manager_terminal_rejection(h, change):
    if change == "deleted":
        h.fetch_error = ConversationMessageNotFoundError()
    elif change == "edited":
        h.original.content = "materially edited task"
    else:
        h.original.author.id = "other-owner"
    answer = await h.controls.dispatch("control.resume", h.params())
    assert answer["result"]["disposition"] == "rejected"
    assert h.ledger.turn_status_sync(h.key) == TurnStatus.TERMINAL_REJECTED
    assert not h.requests.resumed and h.released == [h.key]


async def test_resume_uses_current_disabled_tools_setting(h):
    h.config.tools.enabled = False
    answer = await h.controls.dispatch("control.resume", h.params())
    assert answer["result"]["disposition"] == "admitted"
    assert h.requests.resumed[0][1].tools is None
    assert h.filter_calls == []


async def test_empty_fetch_is_not_positive_deletion_evidence(h):
    async def empty(_cid, _rid):
        return None
    h.controls.resume_manager._fetch_message = empty
    answer = await h.controls.dispatch("control.resume", h.params())
    assert answer["result"]["disposition"] == "rejected"
    assert h.ledger.turn_status_sync(h.key) == TurnStatus.SUSPENDED
    assert not h.requests.resumed and not h.released


async def test_preserved_hook_rechecks_original_before_lease_without_generic_gate(h, monkeypatch):
    calls = []
    def verify(message):
        assert message is h.original
        calls.append(message)
        if len(calls) == 2:
            raise PermissionError("Admission revoked during reconstruction")

    def forbidden_gate():
        raise AssertionError("Generic phase gate must not grant original-request authority")

    monkeypatch.setattr(resume_module, "_require_phase2_wiring", forbidden_gate)
    h.controls.resume_manager._assert_preserved_request = verify
    answer = await h.controls.dispatch("control.resume", h.params())
    assert answer["result"]["disposition"] == "rejected" and len(calls) == 2
    assert h.ledger.turn_status_sync(h.key) == TurnStatus.SUSPENDED
    assert not h.requests.resumed


async def test_resume_constructor_preserves_gate_without_original_verifier(h, monkeypatch):
    def denied():
        raise RuntimeError("Unwired phase gate")
    monkeypatch.setattr(resume_module, "_require_phase2_wiring", denied)
    kwargs = dict(store=h.ledger, tool_loop=h.controls.resume_manager._tool_loop,
        llm_gateway=None, channel_state=h.channels, sessions=None, delivery=None,
        permissions=h.controls.resume_manager._permissions,
        tool_catalog=h.controls.resume_manager._tool_catalog,
        get_config=lambda: h.config, fetch_message=h.controls.resume_manager._fetch_message)
    with pytest.raises(RuntimeError, match="Unwired phase gate"):
        TurnResumeManager(**kwargs)
    calls = []
    manager = TurnResumeManager(**kwargs, assert_preserved_request=calls.append)
    assert calls == []  # construction alone grants no request execution
    turn, original, reason = await manager._validate_and_rebuild(
        h.key, h.ledger.load_resumable_sync(h.key))
    assert reason is None and original is h.original and calls == [h.original, h.original]
    turn.durability._stop_heartbeats()
    h.ledger.release_acquired_sync(turn.durability.lease)


async def test_preserved_hook_cannot_bind_another_valid_original_to_checkpoint(h):
    calls = []
    h.controls.resume_manager._assert_preserved_request = calls.append
    h.original.id = "another-admitted-request"
    answer = await h.controls.dispatch("control.resume", h.params())
    assert answer["result"]["disposition"] == "rejected" and calls == []
    assert h.ledger.turn_status_sync(h.key) == TurnStatus.SUSPENDED
    assert not h.requests.resumed


async def test_payload_integrity_failure_never_grants_generation(h):
    h.ledger._conn.execute("UPDATE turns SET payload='{}'")
    h.ledger._conn.commit()
    answer = await h.controls.dispatch("control.resume", h.params())
    assert answer["result"]["disposition"] == "rejected"
    assert h.ledger.turn_status_sync(h.key) == TurnStatus.TERMINAL_REJECTED
    assert h.requests.get_request("r")["generation"] == 1 and not h.requests.resumed


async def test_unknown_effects_halt_before_rebuild_and_never_reexecute(h, monkeypatch):
    preserved = h.ledger.load_resumable_sync(h.key)
    preserved["operations"] = [{"tool_name": "run_command", "state": OpState.OUTCOME_UNKNOWN,
                                "effect_class": "external_effect_capable"}]
    from src.tools.effect_classifier import ToolEffectClass

    preserved["operations"][0]["effect_class"] = ToolEffectClass.EXTERNAL_EFFECT_CAPABLE
    monkeypatch.setattr(h.ledger, "load_resumable_sync", lambda _key: preserved)
    answer = await h.controls.dispatch("control.resume", h.params())
    assert answer["result"] == {"disposition": "rejected", "reason": "unknown_effects"}
    assert h.ledger.turn_status_sync(h.key) == TurnStatus.TERMINAL_REJECTED
    assert not h.requests.resumed and h.filter_calls == []


async def test_busy_arriving_during_async_validation_releases_acquired_lease(h, monkeypatch):
    real_validate = h.controls.resume_manager._validate_and_rebuild

    async def raced(key, row):
        result = await real_validate(key, row)
        h.requests.add("racer", state="queued")
        return result

    monkeypatch.setattr(h.controls.resume_manager, "_validate_and_rebuild", raced)
    answer = await h.controls.dispatch("control.resume", h.params())
    assert answer["result"] == {"disposition": "rejected", "reason": "busy_or_revoked"}
    assert h.ledger.turn_status_sync(h.key) == TurnStatus.SUSPENDED
    assert h.requests.get_request("r")["generation"] == 1 and not h.requests.resumed


async def test_revocation_during_validation_releases_without_execution(h, monkeypatch):
    real_validate = h.controls.resume_manager._validate_and_rebuild

    async def raced(key, row):
        result = await real_validate(key, row)
        h.authorized = False
        return result

    monkeypatch.setattr(h.controls.resume_manager, "_validate_and_rebuild", raced)
    answer = await h.controls.dispatch("control.resume", h.params())
    assert answer["result"]["disposition"] == "rejected"
    assert h.ledger.turn_status_sync(h.key) == TurnStatus.SUSPENDED
    assert not h.requests.resumed


async def test_interrupted_checkpoint_resumes_without_restarting_fresh(h):
    h.store.connection.execute("UPDATE desktop_requests SET state='interrupted'")
    answer = await h.controls.dispatch("control.resume", h.params())
    assert answer["result"]["disposition"] == "admitted"
    assert h.requests.resumed[0][1].iteration == 5


async def test_effect_free_unknown_is_repaired_not_reexecuted(h, monkeypatch):
    from src.tools.effect_classifier import ToolEffectClass

    preserved = h.ledger.load_resumable_sync(h.key)
    preserved["operations"] = [{"generation_seq": 7, "tool_call_id": "observed",
                                "tool_name": "parse_time", "state": OpState.OUTCOME_UNKNOWN,
                                "effect_class": ToolEffectClass.EFFECT_FREE_OBSERVATION,
                                "result": None}]
    preserved["payload"]["fields"]["messages"].append(
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "observed", "name": "parse_time",
             "input": {"expression": "tomorrow"}}]})
    monkeypatch.setattr(h.ledger, "load_resumable_sync", lambda _key: preserved)
    answer = await h.controls.dispatch("control.resume", h.params())
    assert answer["result"]["disposition"] == "admitted"
    result = h.requests.resumed[0][1].messages[-1]["content"][0]
    assert result["tool_use_id"] == "observed"
    assert "interrupted observation" in result["content"].lower()
    assert h.ledger._conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0


async def test_launch_failure_preserves_interruption_and_never_replays_control(h, monkeypatch):
    async def failed(_row, _turn):
        raise RuntimeError("task scheduler unavailable")

    monkeypatch.setattr(h.requests, "launch_resume", failed)
    answer = await h.controls.dispatch("control.resume", h.params())
    assert answer["error"]["disposition"] == "outcome_unknown"
    assert h.requests.get_request("r")["state"] == "interrupted"
    assert h.requests.get_request("r")["generation"] == 2
    assert h.ledger.turn_status_sync(h.key) == TurnStatus.SUSPENDED
    retry = await h.controls.dispatch("control.resume", h.params())
    assert retry["error"]["disposition"] == "outcome_unknown"
    assert [event["type"] for event in h.events.between(0)] == [
        "request.started", "request.interrupted"]


async def test_caller_cancellation_during_rebuild_releases_acquired_lease(h, monkeypatch):
    real_validate = h.controls.resume_manager._validate_and_rebuild
    acquired = asyncio.Event()
    continue_validation = asyncio.Event()

    async def blocked(key, row):
        result = await real_validate(key, row)
        acquired.set()
        await continue_validation.wait()
        return result

    monkeypatch.setattr(h.controls.resume_manager, "_validate_and_rebuild", blocked)
    caller = asyncio.create_task(h.controls.dispatch("control.resume", h.params()))
    await acquired.wait()
    caller.cancel()
    continue_validation.set()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert h.ledger.turn_status_sync(h.key) == TurnStatus.SUSPENDED
    assert not h.requests.resumed
    retry = await h.controls.dispatch("control.resume", h.params())
    assert retry["error"]["disposition"] == "outcome_unknown"


async def test_resume_quiescence_matches_existing_request_owner_gate(h):
    h.requests._closed = True
    answer = await h.controls.dispatch("control.resume", h.params())
    assert answer["result"] == {"disposition": "rejected", "reason": "quiescing"}
    assert h.ledger.turn_status_sync(h.key) == TurnStatus.SUSPENDED
    assert not h.requests.resumed


@pytest.mark.parametrize(("unknown_effect", "reset_mode"), [
    (False, "none"), (True, "none"), (False, "reset"), (False, "reset-and-new-turn")])
async def test_integrated_real_suspension_guarded_resume_and_committed_result(
        integrated_graph, unknown_effect, reset_mode):
    """Parent integration gate: real runner, manager, ledger and publication."""
    from src.desktop.controls import ControlService
    from src.llm.errors import LLMCapacityError
    from src.llm.recovery import RecoveryPolicy
    from src.llm.types import LLMResponse, ToolCall

    requests, engine, provider, transcript, cid = integrated_graph
    engine.deps.llm_gateway._recovery_policy_source = lambda: RecoveryPolicy(
        deadline_seconds=0.05, backoff_base=0.001, backoff_cap=0.002, retry_after_cap=0.005)

    async def unavailable(**kwargs):
        provider.calls.append(kwargs)
        if len(provider.calls) == 1:
            return LLMResponse(tool_calls=[ToolCall("preserved-observation", "parse_time", {
                "expression": "in 1 hour"})], stop_reason="tool_use")
        raise LLMCapacityError("Provider capacity temporarily unavailable",
                               provider="compat", model="test")

    provider.chat_with_tools = unavailable
    admitted = requests.submit({"client_submission_id": "actual-resume", "conversation_id": cid,
                                "text": "Say something brief"})
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    rid = admitted["request_id"]
    row = requests.get_request(rid)
    assert row["state"] == "suspended"
    assert row["ledger_generation"]
    calls_before = len(provider.calls)
    checkpoint = engine.deps.turn_store.load_resumable_sync(TurnKey("conversation", cid, rid))
    spent = checkpoint["payload"]["fields"]
    operations_before = len(checkpoint["operations"])
    assert operations_before == 1
    assert checkpoint["operations"][0]["state"] == OpState.APPLIED
    assert spent["iteration"] >= 1 and spent["tools_used_in_loop"] == ["parse_time"]

    reply_text = ["Finished the exact preserved request."]

    async def available(**kwargs):
        provider.calls.append(kwargs)
        return LLMResponse(text=reply_text[0])

    provider.chat_with_tools = available
    breaker = engine.deps.llm_gateway.capacity_breaker_for()
    breaker._opened_at = 0.0
    probe = breaker.acquire_attempt()
    if not isinstance(probe, float):
        breaker.attempt_succeeded(probe)
    new_context = None
    new_session_history = None
    if reset_mode != "none":
        requests.conversations.reset_context(cid, requests.conversations.get(cid)["rev"])
        assert transcript.model_context(cid) == []
        if reset_mode == "reset-and-new-turn":
            reply_text[0] = "NEW LINEAGE ANSWER"
            requests.submit({"client_submission_id": "new-lineage", "conversation_id": cid,
                             "text": "NEW LINEAGE INPUT"})
            await requests.after_commit()
            await asyncio.gather(*requests._tasks)
            assert "Say something brief" not in str(provider.calls[-1]["messages"])
            new_session_history = engine.deps.sessions.get_history(cid)
            reply_text[0] = "Finished the exact preserved request."
        new_context = transcript.model_context(cid)
        calls_before = len(provider.calls)
    manager = TurnResumeManager(
        store=engine.deps.turn_store, tool_loop=engine.runner,
        llm_gateway=engine.deps.llm_gateway, channel_state=engine.deps.channel_state,
        sessions=engine.deps.sessions, delivery=engine.deps.delivery,
        permissions=requests.permissions, tool_catalog=engine.deps.tool_catalog,
        get_config=engine.deps.get_config, fetch_message=requests.fetch_message,
        auto_resume_enabled=False,
        assert_preserved_request=requests.assert_preserved_request)
    controls = ControlService(requests.store, requests.events, requests,
                              engine.deps.channel_state, authority=requests.authority,
                              permissions=requests.permissions, resume_manager=manager)
    params = {"control_command_id": "actual-resume-control", "conversation_id": cid,
              "request_id": rid, "generation": 1}
    if unknown_effect:
        from src.tools.effect_classifier import ToolEffectClass
        # Inject an uncertain external-effect ledger record in this isolated
        # profile. No external command executes. Real resume reads the actual
        # ledger, not a mocked unresolved-ops helper or a synthesized row.
        ledger = engine.deps.turn_store
        ledger._conn.execute("UPDATE operations SET state=?,effect_class=? WHERE message_id=?",
            (OpState.OUTCOME_UNKNOWN, ToolEffectClass.EXTERNAL_EFFECT_CAPABLE, rid))
        ledger._conn.commit()
        answer = await controls.dispatch("control.resume", params)
        assert answer["result"] == {"disposition": "rejected", "reason": "unknown_effects"}
        assert requests.get_request(rid)["generation"] == 1
        assert len(provider.calls) == calls_before
        assert (ledger.turn_status_sync(TurnKey("conversation", cid, rid))
                == TurnStatus.TERMINAL_REJECTED)
        op = ledger._conn.execute(
            "SELECT state FROM operations WHERE message_id=?", (rid,)).fetchone()
        assert op[0] == OpState.MANUAL_RESOLUTION_REQUIRED
        assert await controls.dispatch("control.resume", params) == answer
        assert len(provider.calls) == calls_before
        return
    actual_launch = requests.launch_resume
    restored = []
    async def capture_launch(row, turn):
        assert turn.iteration == spent["iteration"]
        assert turn.continuation_count == spent["continuation_count"]
        assert turn._validation_retries == spent["_validation_retries"]
        assert turn._rescue_passes == spent["_rescue_passes"]
        assert turn.durability._resume_budget == 0.0
        assert turn.durability.generation_seq == checkpoint["payload"]["generation_seq"]
        assert turn.tools_used_in_loop == ["parse_time"]
        assert row["generation"] == 2
        restored.append(turn)
        await actual_launch(row, turn)
    requests.launch_resume = capture_launch
    answer = await controls.dispatch("control.resume", params)
    assert answer == {"ok": True, "result": {"disposition": "admitted"}}
    assert len(restored) == 1
    await asyncio.gather(*requests._tasks)
    assert requests.get_request(rid)["generation"] == 2
    assert requests.get_request(rid)["state"] == "completed"
    assert engine.deps.turn_store.turn_status_sync(
        TurnKey("conversation", cid, rid)) == TurnStatus.TERMINAL_COMPLETED
    rows = transcript.read_conversation(cid)
    assert len([item for item in rows if item["role"] == "user"]) == (
        2 if reset_mode == "reset-and-new-turn" else 1)
    assert rows[-1]["text"] == "Finished the exact preserved request."
    assert len(provider.calls) == calls_before + 1
    operation_count = engine.deps.turn_store._conn.execute(
        "SELECT COUNT(*) FROM operations WHERE message_id=?", (rid,)).fetchone()[0]
    assert operation_count == operations_before
    assert await controls.dispatch("control.resume", params) == answer
    assert len(provider.calls) == calls_before + 1
    if reset_mode != "none":
        assert transcript.model_context(cid) == new_context
        pin = requests.store.connection.execute(
            "SELECT context_position FROM desktop_request_context WHERE request_id=?", (rid,)
        ).fetchone()[0]
        assert pin == 0
        if new_session_history is not None:
            assert engine.deps.sessions.get_history(cid) == new_session_history
        requests.submit({"client_submission_id": "after-resume", "conversation_id": cid,
                         "text": "AFTER RESUME INPUT"})
        reply_text[0] = "AFTER RESUME ANSWER"
        await requests.after_commit()
        await asyncio.gather(*requests._tasks)
        next_history = str(provider.calls[-1]["messages"])
        assert "AFTER RESUME INPUT" in next_history
        assert "Say something brief" not in next_history
        assert "Finished the exact preserved request." not in next_history
        if reset_mode == "reset-and-new-turn":
            assert "NEW LINEAGE INPUT" in next_history
            assert "NEW LINEAGE ANSWER" in next_history
