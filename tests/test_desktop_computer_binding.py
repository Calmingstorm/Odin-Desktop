"""Real owner/request admission with stub controller and no native desktop."""
# ruff: noqa: E501
import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.computer.controller import ComputerController
from src.computer.models import ComputerError, RequestContext
from src.computer.store import ComputerStore
from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.computer_binding import (
    ComputerForegroundBinding,
    bind_foreground,
    create_foreground,
)
from src.desktop.conversations import ConversationError, ConversationStore
from src.desktop.events import EventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.requests import RequestService
from src.desktop.transcript import TranscriptStore
from src.desktop.turn_state import TurnStateService
from src.discord.channel_state import ChannelStateRegistry
from src.permissions.manager import PermissionManager
from src.tools.output_authorization import request_tool_scope
from src.turn_state import TurnKey, TurnStateStore, TurnStatus


class Engine:
    def __init__(self, ledger):
        self.deps = SimpleNamespace(turn_store=ledger, channel_state=ChannelStateRegistry())
        self.hook = None
        self.errors = []

    async def run(self, message, **_kwargs):
        self.requests.assert_request(message)
        ticket = self.computer.enter_request(message)
        turn = SimpleNamespace(message=message, user_id=message.owner_id,
            _ch_id=message.conversation_id, _req_id=message.request_id,
            _cancel=asyncio.Event(), _trajectory=SimpleNamespace(source="conversation",
                channel_id=message.conversation_id, message_id=message.request_id))
        try:
            await self.hook(message, turn)
            return ("committed answer", False, False, [], False)
        except BaseException as error:
            self.errors.append(error)
            raise
        finally:
            await self.computer.leave_request(ticket)

    async def record_result(self, *_args):
        pass


class Delivery:
    def guarded_reply(self, context, text):
        return (context, text)

    async def send_reply(self, *_args, **_kwargs):
        pass


@pytest.fixture
def graph(tmp_path):
    paths = ProfilePaths.from_xdg("binding", home=tmp_path, environ={})
    authority = OwnerAuthority(paths)
    owner = authority.authenticate_local(peer_uid=authority.owner_uid)
    permissions = PermissionManager(authority)
    identity = permissions.set_request_owner(owner)
    store = JournalStore(paths.data_dir / "journal.sqlite3", "binding")
    events = EventJournal(store)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    ledger = TurnStateStore(paths.data_dir / "turn-state" / "turns.sqlite3")
    engine = Engine(ledger)
    requests = RequestService(store, conversations, transcript, engine=engine,
        permissions=permissions, authority=authority, delivery=Delivery())
    controller = SimpleNamespace(finish_turn=AsyncMock(), _recoveries={},
        session=AsyncMock(return_value={"state": "closed"}),
        observe=AsyncMock(), act=AsyncMock())
    config = SimpleNamespace(computer=SimpleNamespace(enabled=True))
    computer = ComputerForegroundBinding(requests, controller=controller, config=config)
    controller.authorize = computer._authorize
    engine.requests, engine.computer = requests, computer
    cid = conversations.create()["conversation"]["id"]
    yield SimpleNamespace(**locals())
    ledger.close()
    store.close()
    permissions.reset_request_owner(identity)
    authority.release_runtime()


async def execute(g, hook, *, cid=None, sid="one"):
    g.engine.hook = hook
    result = g.requests.submit({"client_submission_id": sid,
        "conversation_id": cid or g.cid, "text": "Inspect a stub session"})
    await g.requests.after_commit()
    await asyncio.gather(*g.requests._tasks)
    if g.engine.errors:
        raise g.engine.errors[0]
    assert g.requests.get_request(result["request_id"])["state"] == "completed"
    return result


def call(name="computer_session", operation="status"):
    return SimpleNamespace(name=name, id="call-one", input={"operation": operation})


@pytest.mark.asyncio
async def test_actual_admission_owner_conversation_and_call_task(graph):
    g = graph
    async def hook(message, st):
        async def runner_child():
            with g.computer.foreground(st, call()):
                context = g.computer._context(st)
                assert context == RequestContext(g.owner.owner_id, g.cid,
                    f"{message.request_id}:1", "localhost")
                assert g.computer.grant_allows("computer_session", message.owner_id, g.cid)
                assert not g.computer._authorize(replace(context))
                assert not g.computer.grant_allows("computer_act", message.owner_id, g.cid)
                assert not g.computer.grant_allows("computer_session", "foreign", g.cid)
                assert not g.computer.grant_allows("computer_session", message.owner_id, "foreign")
                async def unrelated_child():
                    assert not g.computer.grant_allows("computer_session", message.owner_id, g.cid)
                    assert not g.computer._authorize(context)
                await asyncio.create_task(unrelated_child())
                assert (await g.computer._handle_computer_session({"operation": "status"})).ok
            assert not g.computer._authorize(context)
        await asyncio.create_task(runner_child())
    await execute(g, hook)
    assert g.controller.session.await_count == 1
    assert g.controller.finish_turn.await_count == 1
    assert not g.computer._active_requests


@pytest.mark.asyncio
async def test_unadmitted_envelopes_session_tokens_and_inspection_never_supply_authority(graph):
    g = graph
    admitted = g.requests.submit({"client_submission_id": "queued", "conversation_id": g.cid,
                                 "text": "Inspect a stub"})
    message = g.requests.fetch_request(g.cid, admitted["request_id"])
    for candidate in (message, replace(message, _seal=object()), SimpleNamespace(
            owner_id=g.owner.owner_id, conversation_id=g.cid, token="private")):
        with pytest.raises(PermissionError):
            g.computer.enter_request(candidate)
    context = RequestContext(g.owner.owner_id, g.cid, admitted["request_id"], "localhost")
    assert not g.computer._authorize(context)
    assert not (await g.computer._handle_computer_session({"operation": "status"})).ok
    g.controller.session.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["loop", "foreign_message", "owner", "conversation", "turn", "cancel"])
async def test_background_foreign_or_cancelled_turns_refuse(graph, mutation):
    g = graph
    async def hook(message, st):
        if mutation == "loop":
            st._trajectory.source = "loop"
        elif mutation == "foreign_message":
            st.message = replace(message)
        elif mutation == "owner":
            st.user_id = "foreign"
        elif mutation == "conversation":
            st._ch_id = "foreign"
        elif mutation == "turn":
            st._req_id = "foreign"
        else:
            st._cancel.set()
        with pytest.raises(PermissionError):
            with g.computer.foreground(st, call()):
                pytest.fail("A foreign/background turn entered computer admission")
    await execute(g, hook)
    g.controller.session.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["scope", "generation", "stop", "owner", "cancel", "disable"])
async def test_live_rechecks_and_cleanup_does_not_restore_authority(graph, mutation):
    g = graph
    async def hook(message, st):
        with g.computer.foreground(st, call()):
            assert g.computer.grant_allows("computer_session", message.owner_id, g.cid)
            ticket = None
            if mutation == "scope":
                ticket = request_tool_scope.set(set())
            elif mutation == "owner":
                ticket = g.permissions.set_request_owner(replace(g.owner, _seal=object()))
            elif mutation == "disable":
                g.config.computer.enabled = False
            elif mutation == "cancel":
                st._cancel.set()
            else:
                column, value = ("generation", 2) if mutation == "generation" else ("state", "stop_requested")
                with g.store.transaction() as db:
                    db.execute(f"UPDATE desktop_requests SET {column}=? WHERE request_id=?",
                               (value, message.request_id))
            assert not g.computer.grant_allows("computer_session", message.owner_id, g.cid)
            assert not (await g.computer._handle_computer_session({"operation": "status"})).ok
            if mutation == "scope":
                request_tool_scope.reset(ticket)
            elif mutation == "owner":
                g.permissions.reset_request_owner(ticket)
            elif mutation == "generation":
                with g.store.transaction() as db:
                    db.execute("UPDATE desktop_requests SET generation=1 WHERE request_id=?", (message.request_id,))
            elif mutation == "stop":
                with g.store.transaction() as db:
                    db.execute("UPDATE desktop_requests SET state='running' WHERE request_id=?", (message.request_id,))
            await g.computer.finish_turn(st)
    await execute(g, hook)
    g.controller.session.assert_not_awaited()
    assert g.controller.finish_turn.await_count == 2


@pytest.mark.asyncio
async def test_vision_is_not_waived_by_admitted_owner(graph):
    async def hook(_message, st):
        for block in (call(operation="start"), call("computer_observe"), call("computer_act")):
            with pytest.raises(PermissionError, match="vision"):
                with graph.computer.foreground(st, block):
                    pytest.fail("No native vision transport was provided")
    await execute(graph, hook)
    graph.controller.session.assert_not_awaited()


@pytest.mark.asyncio
async def test_nonvisual_grant_cannot_be_used_to_start_or_observe(graph):
    async def hook(_message, st):
        with graph.computer.foreground(st, call()):
            assert not (await graph.computer._handle_computer_session({"operation": "start"})).ok
            assert not (await graph.computer._handle_computer_observe({})).ok
    await execute(graph, hook)
    graph.controller.session.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_retirement_fences_inherited_child_and_successor(graph):
    g = graph
    ready, proceed = asyncio.Event(), asyncio.Event()
    pending = []
    old = []
    async def first(message, st):
        async def child():
            with g.computer.foreground(st, call()):
                old.append(g.computer._context(st))
                ready.set()
                await proceed.wait()
                assert not g.computer._authorize(old[0])
        pending.append(asyncio.create_task(child()))
        await ready.wait()
    await execute(g, first)
    async def second(message, st):
        with g.computer.foreground(st, call()):
            assert g.computer._context(st).turn_id != old[0].turn_id
            assert not g.computer._authorize(old[0])
        proceed.set()
        await pending[0]
    await execute(g, second, sid="two")


@pytest.mark.asyncio
async def test_one_foreground_per_conversation_and_other_conversations_progress(graph):
    g = graph
    other = g.conversations.create()["conversation"]["id"]
    both = asyncio.Event()
    started = []
    async def hook(message, st):
        with pytest.raises(PermissionError):
            g.computer.enter_request(message)
        with g.computer.foreground(st, call()):
            started.append(g.computer._context(st))
            if len(started) == 2:
                both.set()
            await asyncio.wait_for(both.wait(), 2)
            assert g.computer._authorize(g.computer._context(st))
    g.engine.hook = hook
    for sid, cid in (("one", g.cid), ("two", other)):
        g.requests.submit({"client_submission_id": sid, "conversation_id": cid, "text": "Inspect stub"})
    await g.requests.after_commit()
    await asyncio.gather(*g.requests._tasks)
    assert len(started) == 2 and started[0].channel_id != started[1].channel_id
    assert not g.computer._active_requests


@pytest.mark.asyncio
async def test_cleanup_failure_retires_request_without_replay(graph):
    g = graph
    g.controller.finish_turn.side_effect = RuntimeError("cleanup unverified")
    async def hook(_message, st):
        with g.computer.foreground(st, call()):
            assert (await g.computer._handle_computer_session({"operation": "status"})).ok
    g.engine.hook = hook
    result = g.requests.submit({"client_submission_id": "one", "conversation_id": g.cid,
                               "text": "Inspect stub"})
    await g.requests.after_commit()
    await asyncio.gather(*g.requests._tasks)
    assert g.requests.get_request(result["request_id"])["state"] == "failed"
    assert not g.computer._active_requests
    assert g.controller.session.await_count == 1
    await g.requests.after_commit()
    assert g.controller.session.await_count == 1


@pytest.mark.asyncio
async def test_controller_quarantine_and_generation_remain_downstream(graph, tmp_path):
    g = graph
    store = ComputerStore(tmp_path / "computer.sqlite3", tmp_path / "evidence")
    controller = ComputerController(store, lambda _app: pytest.fail("Native backend must not launch"),
                                    g.computer._authorize, enabled=True)
    g.computer.controller = controller
    async def hook(_message, st):
        with g.computer.foreground(st, call()):
            context = g.computer._context(st)
            grant = store.create_session(context, "fixture")
            grant = store.set_state(grant.session_id, "quarantined", revoke=True)
            assert store.get_session(grant.session_id).state == "quarantined"
            with pytest.raises(ComputerError):
                await controller.session(context, {"operation": "resume",
                    "session_id": grant.session_id, "generation": grant.generation})
            with pytest.raises(ComputerError, match="stale_generation"):
                controller._grant(context, {"session_id": grant.session_id, "generation": grant.generation + 1})
    try:
        await execute(g, hook)
    finally:
        await controller.close()
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown_release", [False, True])
async def test_native_image_delivery_freshness_and_no_replay_use_retained_controller(graph, tmp_path, unknown_release):
    from src.computer.vision import VisionError
    from src.llm.openai_codex import CodexChatClient
    from tests.test_computer_actions_r4 import Backend
    g = graph
    backend = Backend()  # Synthetic PNG and input receipts only, no subprocess.
    if unknown_release:
        async def uncertain(_payload):
            return {"status": "unknown", "injected": True, "released": False}
        backend.hook = uncertain
        backend.stop = AsyncMock(return_value={"stopped": False, "released": False})
    store = ComputerStore(tmp_path / "computer.sqlite3", tmp_path / "evidence")
    controller = ComputerController(store, lambda _app: backend, g.computer._authorize, enabled=True)
    g.computer.controller = controller
    adapter = CodexChatClient(auth=object(), model="synthetic-transport")
    async def hook(_message, st):
        st._computer_serving = SimpleNamespace(provider="codex", client=adapter, model=adapter.model)
        start = call(operation="start")
        with g.computer.foreground(st, start):
            grant = await controller.session(g.computer._context(st), {"operation": "start", "app": "xed"})
        block = call("computer_observe")
        with g.computer.foreground(st, block):
            image = await g.computer._handle_computer_observe({"session_id": grant["session_id"], "generation": 1})
            assert isinstance(image, dict) and "__image_block__" in image
            await g.computer.validate_delivery(st, block, image)
            with pytest.raises(VisionError):
                # Pixels captured in one invocation cannot be recycled as a
                # second delivery. validate_delivery clears issued identities.
                await g.computer.validate_delivery(st, block, image)
        live = controller._live[grant["session_id"]]
        observation = next(reversed(live.observations.values()))
        inp = {"session_id": grant["session_id"], "generation": 1,
            "consent_generation": 1, "source_id": "opaque", "source_revision": 1,
            "action_id": "synthetic-action", "observation_id": observation.observation_id,
            "operation": "click", "x": 1, "y": 0,
            "expect": {"type": "pointer_at", "x": 1, "y": 0}}
        with g.computer.foreground(st, call("computer_act")):
            context = g.computer._context(st)
            result = await controller.act(context, inp)
            assert result["status"] == ("unknown" if unknown_release else "verified")
            replay = await controller.act(context, inp)
            assert "next_observation" not in replay and len(backend.calls) == 1
            with pytest.raises(ComputerError, match="action_id_conflict"):
                await controller.act(context, {**inp, "x": 0,
                    "expect": {"type": "pointer_at", "x": 0, "y": 0}})
            if unknown_release:
                assert store.get_session(grant["session_id"]).state == "quarantined"
                with pytest.raises(ComputerError):
                    await controller.act(context, {**inp, "action_id": "new-action"})
                assert len(backend.calls) == 1
                return
            backend.source = replace(backend.source, source_revision=2)
            # The completed action retired its old delivered observation before
            # any source-revision comparison can grant a successor operation.
            with pytest.raises(ComputerError, match="stale_observation"):
                await controller.validate_action_binding(store.get_session(grant["session_id"]),
                    observation.observation_id)
    try:
        await execute(g, hook)
    finally:
        await controller.close()
        store.close()


@pytest.mark.asyncio
async def test_resumed_request_generation_is_new_computer_turn(graph):
    g = graph
    contexts = []
    async def hook(_message, st):
        with g.computer.foreground(st, call()):
            contexts.append(g.computer._context(st))
    first = await execute(g, hook)
    with g.store.transaction() as db:
        db.execute("UPDATE desktop_requests SET generation=2,state='running' WHERE request_id=?",
                   (first["request_id"],))
    message = g.requests.fetch_request(g.cid, first["request_id"])
    await g.requests._execute(message)
    assert g.requests.get_request(first["request_id"])["state"] == "completed"
    assert contexts[0].turn_id == first["request_id"] + ":1"
    assert contexts[1].turn_id == first["request_id"] + ":2"
    assert not g.computer._authorize(contexts[0])


@pytest.mark.asyncio
async def test_bind_foreground_reuses_management_controller_and_ownership(graph):
    g = graph
    old = SimpleNamespace(_owns_store=True, settings=g.config.computer)
    service = SimpleNamespace(_started=True, _closed=False, controller=g.controller,
        settings=SimpleNamespace(config=g.config), _authorize=lambda _context: False,
        _integration=old)
    facade = bind_foreground(service, g.requests)
    assert facade.controller is g.controller and facade._owns_store
    assert facade.settings is old.settings
    assert service._integration is facade
    assert facade.published_available is False
    assert bind_foreground(service, g.requests) is facade
    with pytest.raises(RuntimeError):
        bind_foreground(service, object())


@pytest.mark.asyncio
async def test_standalone_factory_opens_only_private_store_not_backend(graph, tmp_path, monkeypatch):
    config = SimpleNamespace(computer=SimpleNamespace(enabled=False,
        storage_dir=str(tmp_path / "native-state")))
    monkeypatch.setattr(ComputerForegroundBinding, "_backend",
                        lambda *_args: pytest.fail("Native backend must not be created"))
    facade = create_foreground(graph.requests, config)
    assert not facade.published_available and facade._owns_store
    assert facade.controller.authorize.__self__ is facade
    try:
        assert facade.controller.store.db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    finally:
        await facade.close()


def posture(g, **kwargs):
    return TurnStateService(g.permissions, g.authority, store_provider=lambda: g.ledger, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("registry", ["callback", "table"])
async def test_background_origin_cannot_enter_even_with_valid_admitted_request(graph, registry):
    g = graph
    async def hook(message, _st):
        # This executes after genuine foreground admission so the extra
        # background fence is exercised, not hidden by assert_request refusal.
        if registry == "callback":
            g.requests.is_background = lambda _message: True
        else:
            with g.store.transaction() as db:
                db.execute("CREATE TABLE desktop_background_requests (request_id TEXT PRIMARY KEY)")
                db.execute("INSERT INTO desktop_background_requests VALUES (?)", (message.request_id,))
        with pytest.raises(PermissionError, match="lineage"):
            g.computer._binding()
    await execute(g, hook)


@pytest.mark.asyncio
async def test_turn_state_real_read_only_private_snapshot_and_bounded_limit(graph):
    g = graph
    lease, disposition = g.ledger.admit_turn_sync(TurnKey("conversation", g.cid, "preserved"),
        guild_id=None, user_id=g.owner.owner_id, content_digest="digest",
        code_version="test", prompt_policy_hash="policy", tool_catalog_hash="catalog",
        session_snapshot={"private": "never-publish-checkpoint"})
    assert disposition == "admitted"
    before = g.ledger._conn.execute("SELECT status,revision,lease_token FROM turns").fetchone()
    result = await posture(g).handle("turn_state.list", {"limit": 1})
    assert result["availability"] == "available" and result["schema_version"] == 1
    assert result["data"]["turns"][0]["status"] == TurnStatus.ACTIVE
    assert "never-publish-checkpoint" not in json.dumps(result)
    assert "lease_token" not in json.dumps(result)
    assert before == g.ledger._conn.execute("SELECT status,revision,lease_token FROM turns").fetchone()
    for params in ({"limit": 0}, {"limit": 201}, {"limit": True}, {"owner_id": g.owner.owner_id}):
        with pytest.raises(ConversationError):
            await posture(g).handle("turn_state.list", params)
    with pytest.raises(ConversationError):
        await posture(g).handle("turn_state.resume", {})


@pytest.mark.asyncio
async def test_turn_state_unavailable_distinct_from_disabled_and_unauthorized(graph):
    g = graph
    assert (await posture(g, enabled=lambda: False).handle("turn_state.list", {}))["availability"] == "not_enabled"
    reader = TurnStateService(g.permissions, g.authority, store_provider=lambda: None)
    assert (await reader.handle("turn_state.list", {}))["availability"] == "unavailable"
    identity = g.permissions.set_request_owner(None)
    try:
        with pytest.raises(ConversationError, match="owner"):
            await reader.handle("turn_state.list", {})
    finally:
        g.permissions.reset_request_owner(identity)


@pytest.mark.asyncio
async def test_turn_state_reader_failure_and_readback_revocation(graph, monkeypatch):
    import sqlite3

    import src.desktop.turn_state as domain
    g = graph
    def failed(_path, _limit):
        raise sqlite3.OperationalError("private database details")
    monkeypatch.setattr(domain, "read_turn_snapshot", failed)
    result = await posture(g).handle("turn_state.list", {})
    assert result["availability"] == "unavailable"
    assert "private database" not in json.dumps(result)
    def revoked(_path, _limit):
        # Durable owner identity revocation while the independent reader waits.
        g.authority.durability_degraded = True
        return {"turns": [{"private": "not authorized at readback"}]}
    monkeypatch.setattr(domain, "read_turn_snapshot", revoked)
    try:
        with pytest.raises(ConversationError, match="owner"):
            await posture(g).handle("turn_state.list", {})
    finally:
        g.authority.durability_degraded = False


@pytest.mark.asyncio
async def test_turn_state_attention_is_not_historical_unknown_diagnostic(graph):
    g = graph
    for request, status, effect in (("healthy", TurnStatus.ACTIVE, None),
            ("suspended", TurnStatus.SUSPENDED, None),
            ("historical", TurnStatus.TERMINAL_COMPLETED, "OUTCOME_UNKNOWN"),
            ("manual", TurnStatus.TERMINAL_COMPLETED, "MANUAL_RESOLUTION_REQUIRED")):
        key = TurnKey("conversation", g.cid, request)
        lease, _ = g.ledger.admit_turn_sync(key, guild_id=None, user_id=g.owner.owner_id,
            content_digest="digest", code_version="test", prompt_policy_hash="policy",
            tool_catalog_hash="catalog", session_snapshot={})
        if status == TurnStatus.SUSPENDED:
            g.ledger.suspend_sync(lease, {"private": "checkpoint"})
        elif status != TurnStatus.ACTIVE:
            g.ledger.finish_sync(lease, status)
        if effect is not None:
            g.ledger._conn.execute("INSERT INTO operations (source, channel_id, message_id, "
                "turn_generation, generation_seq, tool_call_id, tool_name, iteration, state, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,0,?,0,0)",
                ("conversation", g.cid, request, lease.generation, 1, "effect", "stub", effect))
            g.ledger._conn.commit()
    result = (await posture(g).handle("turn_state.list", {"limit": 1}))["data"]
    assert result["turns"][0]["message_id"] == "manual"
    assert result["counts"]["attention_required"] == 2
    assert result["diagnostics"]["outcome_unknown"]["operations"] == 1
    assert result["omitted_attention_turns"] == 1
    complete = (await posture(g).handle("turn_state.list", {}))["data"]["turns"]
    assert "historical" not in {turn["message_id"] for turn in complete}
    assert not next(turn for turn in complete if turn["message_id"] == "healthy")["requires_attention"]
