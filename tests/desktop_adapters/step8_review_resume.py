"""Frozen resume corpus on the real authenticated durable desktop graph.

InputMessage is observation/input only. No fake message is ever presented to
the runner. RequestService allocates, seals and task-binds every execution.
"""
from __future__ import annotations

import ast
import asyncio
import contextvars
import copy
import hashlib
from types import ModuleType, SimpleNamespace
from uuid import uuid4

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, register_module
from src.config.schema import Config
from src.desktop.commands import JournalStore
from src.desktop.controls import ControlService
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import DurableDelivery, PublicationEventJournal
from src.desktop.requests import RequestService
from src.desktop.services import build_engine_services
from src.desktop.transcript import TranscriptStore
from src.discord.turn_resume import TurnResumeManager
from src.llm.recovery import RecoveryPolicy
from src.turn_state import TurnStateStore
from tests.desktop_adapters.process_cases import temporary_owner
from tests.desktop_adapters.step8_wait import _paths, _put
from tests.fakes import FakeLLM, FakeMessage

SOURCE_PATH = "tests/test_resume_admission.py"
SOURCE_SHA256 = "995d1fb1df090aeb4ed5f5983859ae712f56de87f7f86e6e58c72ae20a8a41ce"
# Fixture dependencies only: qualification metadata belongs to the exact adapter.
RETIRED = {
    "TestExplicitResume.test_wrong_author_gets_notice": (
        "Removed Discord multi-author intake; local canonical owner authentication remains "
        "enforced."),
    **{f"TestMentionAnchoredResumeTrigger.{name}": (
        "Removed Discord mention-anchored intake; desktop bare resume remains supported.")
       for name in (
        "test_leading_mention_resume_triggers", "test_nickname_mention_form_triggers",
        "test_trailing_mention_is_not_a_command", "test_mention_plus_sentence_is_not_a_command",
        "test_foreign_mention_is_not_stripped",
        "test_mention_recognized_trigger_still_fails_closed")},
}
_owner = contextvars.ContextVar("step8_review_resume_owner", default=None)


class ObservedEngine:
    def __init__(self, engine):
        self.engine, self.results = engine, []

    def __getattr__(self, name):
        return getattr(self.engine, name)

    async def run(self, *args, **kwargs):
        result = await self.engine.run(*args, **kwargs)
        self.results.append(result)
        return result


class Harness:
    def __init__(self, script, tmp_path):
        owner = _owner.get()
        if owner is None or not owner.manager.is_owner(owner.authority.owner_id):
            raise RuntimeError("resume corpus requires the authenticated canonical owner")
        self.owner = owner
        self.journal = JournalStore(tmp_path / "transport.sqlite3", "review-resume")
        self.events = PublicationEventJournal(self.journal)
        self.conversations = ConversationStore(self.journal, self.events)
        self.transcript = TranscriptStore(self.journal, self.events, self.conversations)
        self.delivery = DurableDelivery(self.journal, self.events,
                                        transcript_commit=self.transcript.commit)
        cfg = Config()
        cfg.openai_codex.enabled = cfg.ollama.enabled = False
        cfg.openai_compatible.enabled = True
        cfg.llm_provider.model = "compat:fake-model"
        cfg.context.directory = str(owner.paths.data_dir / "context")
        cfg.learning.enabled = cfg.search.enabled = cfg.browser.enabled = False
        cfg.tools.local_working_dir = str(owner.workspace)
        cfg.tools.ssh_pool.enabled = False
        self.fake = FakeLLM(script)
        self.fake.drain_and_close = self.fake.close
        self.store = TurnStateStore(tmp_path / "ts" / "turns.sqlite3")
        self.engine = build_engine_services(cfg, owner.paths, owner.manager,
            delivery=self.delivery, compatible_client=self.fake, turn_store=self.store)
        self.observed = ObservedEngine(self.engine)
        self.requests = RequestService(self.journal, self.conversations, self.transcript,
            engine=self.observed, permissions=owner.manager, authority=owner.authority,
            delivery=self.delivery)
        self.engine.bind_requests(self.requests)
        self.delivery.assert_context = self.requests.assert_delivery_context
        self.cid = self.conversations.create()["conversation"]["id"]
        d = self.engine.deps
        d.llm_gateway._recovery_policy_source = lambda: RecoveryPolicy(
            deadline_seconds=0.15, backoff_base=0.01, backoff_cap=0.02, retry_after_cap=0.05)
        self.released_workloads = []
        self.manager = TurnResumeManager(store=self.store, tool_loop=self.engine.runner,
            llm_gateway=d.llm_gateway, channel_state=d.channel_state, sessions=d.sessions,
            delivery=self.delivery, permissions=owner.manager, tool_catalog=d.tool_catalog,
            get_config=d.get_config, fetch_message=self.requests.fetch_message,
            assert_preserved_request=self.requests.assert_preserved_request,
            launch_auto_resume=self.requests.launch_auto_resume,
            release_workload=self.released_workloads.append)
        self.engine.runner._on_turn_suspended = self.manager.on_turn_suspended
        self.controls = ControlService(self.journal, self.events, self.requests, d.channel_state,
            authority=owner.authority, permissions=owner.manager, resume_manager=self.manager)
        self.bot = SimpleNamespace(tool_executor=d.tool_executor, tool_loop=self.engine.runner,
            llm_gateway=d.llm_gateway, sessions=d.sessions, delivery=self.delivery,
            native_tools=d.native_tools, pipeline=self)
        self.messages = {}
        self.triggers = {}
        self.resumed_results = []
        real_resumed = self.engine.runner.run_resumed

        async def observe_resumed(*args, **kwargs):
            result = await real_resumed(*args, **kwargs)
            self.resumed_results.append(result)
            return result

        self.engine.runner.run_resumed = observe_resumed
        real_reply = self.delivery.send_reply

        async def observe_reply(message, text, **kwargs):
            result = await real_reply(message, text, **kwargs)
            context = self.delivery._context(message)
            if context.generation > 1:
                observed = self.triggers.get(context.request_id) or self.messages.get(
                    (context.conversation_id, context.request_id))
                if observed is not None:
                    observed.replies.append({"content": text, "files": None})
            return result

        self.delivery.send_reply = observe_reply
        owner.graphs.append(self)

    def register(self, msg):
        if getattr(msg, "_review_registered", False):
            return
        answer = self.requests.submit({"client_submission_id": uuid4().hex,
            "conversation_id": self.cid, "text": msg.content})
        msg.id = answer["request_id"]
        msg.channel = SimpleNamespace(id=self.cid, sent_texts=[])
        msg.author = SimpleNamespace(id=self.owner.authority.owner_id)
        msg._review_registered = True
        self.messages[(self.cid, msg.id)] = msg

    async def settle(self):
        await self.requests.after_commit()
        while self.requests._tasks:
            await asyncio.gather(*list(self.requests._tasks))

    async def run(self, msg, content=None):
        if getattr(msg, "_review_trigger", False):
            return await self.resume(msg)
        self.register(msg)
        await self.settle()
        return self.observed.results[-1]

    async def resume(self, msg, summary=None):
        cid = str(msg.channel.id)
        if not self.journal.connection.execute(
                "SELECT 1 FROM desktop_conversations WHERE id=?", (cid,)).fetchone():
            # The frozen foreign channel is input-only. Allocate a real empty
            # conversation rather than accepting its transport identity.
            cid = self.conversations.create()["conversation"]["id"]
            msg.channel = SimpleNamespace(id=cid, sent_texts=[])
        rows = self.requests.snapshot(cid)["recent"]
        preserved = [r for r in rows if r["outcome"] in ("suspended", "interrupted")]
        is_resume = TurnResumeManager.is_resume_trigger(msg.content) and bool(preserved)
        before = len(self.resumed_results)
        if is_resume:
            self.triggers[preserved[-1]["request_id"]] = msg
        notices_before = len(self.transcript.read_conversation(cid))
        answer = await self.requests.handle_async("submission.send", {
            "client_submission_id": uuid4().hex, "conversation_id": cid,
            "text": msg.content}, controls=self.controls)
        if not is_resume:
            # Preserve the old helper's None observation, but actually execute
            # the admitted ordinary desktop request and settle it honestly.
            await self.settle()
            return None
        await self.settle()
        if len(self.resumed_results) > before:
            result = self.resumed_results[-1]
            return result
        notices = self.transcript.read_conversation(cid)[notices_before:]
        text = "\n".join(r.get("text", "") for r in notices if r["role"] == "notice")
        msg.replies.append({"content": text, "files": None})
        disposition = answer.get("result", {}).get("disposition")
        return text, False, disposition == "outcome_unknown", [], False

    def row(self, cols="status, payload"):
        return self.store._conn.execute(f"SELECT {cols} FROM turns").fetchone()

    def edit_original(self, original):
        original.content = "do the long thing (edited)"
        with self.journal.transaction() as db:
            db.execute("UPDATE desktop_requests SET text=? WHERE request_id=?",
                       (original.content, original.id))

    def delete_original(self, original):
        async def missing(*args):
            from src.discord.turn_resume import ConversationMessageNotFound
            raise ConversationMessageNotFound("confirmed missing original")
        self.manager._fetch_message = missing
        self.messages.clear()

    def mismatch_original_author(self, row):
        self.store._conn.execute("UPDATE turns SET user_id=?", ("foreign-owner",))
        self.store._conn.commit()
        row["user_id"] = "foreign-owner"


def resume_msg(original, content="resume", author=None):
    msg = FakeMessage(content, author=author or original.author, channel=original.channel)
    msg._review_trigger = True
    return msg


async def owner_fixture(tmp_path):
    with temporary_owner(tmp_path / "review-resume-owner") as state:
        state.graphs = []
        token = _owner.set(state)
        try:
            yield state
        finally:
            try:
                for graph in state.graphs:
                    await graph.manager.close()
                    await graph.requests.close()
                    await graph.engine.close()
                    graph.journal.close()
            finally:
                _owner.reset(token)


def _rules(original):
    """Exact frozen-node selectors, each hash-bound to the pinned source bytes."""
    rules = []
    def add(node, source, reason, expression=False):
        replacement = (
            ast.parse(source, mode="eval").body if expression else ast.parse(source).body[0])
        rules.append({"line": node.lineno, "column": node.col_offset,
            "before_sha256": hashlib.sha256(dump(node).encode()).hexdigest(),
            "after_sha256": hashlib.sha256(dump(replacement).encode()).hexdigest(),
            "after_source": source, "expression": expression, "reason": reason})
    # This import replaces the obsolete Harness construction only, not cases.
    for node in original.body:
        if isinstance(node, ast.ClassDef) and node.name == "Harness":
            add(node, "from tests.desktop_adapters.step8_review_resume import Harness",
                "Canonical owner durable service composition")
        if isinstance(node, ast.FunctionDef) and node.name == "resume_msg":
            add(node, "from tests.desktop_adapters.step8_review_resume import resume_msg",
                "Text-only observed resume input")
    for node in ast.walk(original):
        special = {
            162: ("h.mismatch_original_author(row)",
                  "Mismatch persisted checkpoint author against canonical actual request owner"),
            238: ("h.edit_original(original)",
                  "Edit durable original request text, not observational fake"),
            248: ("h.delete_original(original)",
                  "Positive not-found store fetch, not empty adapter read"),
            261: ("from src.discord import turn_resume as conversation_errors",
                  "Removed Discord HTTP exception import"),
            295: ("from src.discord import turn_resume as conversation_errors",
                  "Removed Discord HTTP exception import"),
            267: ("raise conversation_errors.ConversationMessageNotFound('confirmed missing')",
                  "Positive current conversation store not-found error"),
            301: ("raise conversation_errors.ConversationAccessDenied('access denied')",
                  "Current conversation store permission error"),
            553: ("task = asyncio.create_task(h.run(original))",
                  "Crash specimen starts original RequestService task, never unbound runner"),
            575: ("h.manager._store = h.engine.deps.turn_store = "
                  "h.bot.tool_loop._turn_store = restarted",
                  "Restarted real checkpoint owner used by manager and runner"),
            1091: ("h.controls._rebuild = boom",
                   "Inject failure at actual recognized desktop resume reconstruction seam"),
            1060: ("real_list = h.store.load_resumable_sync",
                   "First actual desktop preserved checkpoint read"),
            1070: ("h.store.load_resumable_sync = fail_once",
                   "Inject first-read failure at current desktop admission read"),
            355: ("send_chunked = h.bot.delivery.send_reply",
                  "Observe actual guarded desktop delivery boundary"),
            364: ("monkeypatch.setattr(h.bot.delivery, 'send_reply', gated_delivery)",
                  "Hold real guarded delivery, not unused Discord chunker"),
        }
        if isinstance(node, ast.stmt) and node.lineno in special:
            source, reason = special[node.lineno]
            add(node, source, reason)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "gated_delivery":
            # Only signature adapts the actual publication API, preserving gate body.
            replacement = copy.deepcopy(node)
            replacement.args.kwarg = ast.arg(arg="kwargs")
            replacement.body[-1].value.value.keywords.append(
                ast.keyword(arg=None, value=ast.Name(id="kwargs", ctx=ast.Load())))
            add(node, ast.unparse(replacement),
                "Forward guarded reply kwargs at the actual publication boundary")
        if isinstance(node, ast.Constant) and node.value == "discord":
            add(node, "'conversation'", "Retained TurnKey source is desktop conversation", True)
        if (isinstance(node, ast.Attribute)
                and node.attr in {"try_explicit_resume", "_explicit_resume_recognized"}
                and isinstance(node.ctx, ast.Load)):
            root = ast.unparse(node.value).removesuffix(".manager")
            add(node, root + ".resume",
                "Real RequestService.handle_async and ControlService.dispatch", True)
    return rules


def adapt(source, *, hunks=None):
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("resume-admission frozen source bytes changed")
    original = ast.parse(source, filename=SOURCE_PATH)
    tree = copy.deepcopy(original)
    rules = _rules(original)
    if hunks is not None and hunks != rules:
        raise ValueError("resume exact setup allowlist changed")
    lookup = {(r["line"], r["column"], r["before_sha256"]): r for r in rules}
    if len(lookup) != len(rules):
        raise ValueError("resume duplicate setup rule")
    seen = set()
    class Exact(ast.NodeTransformer):
        def visit(self, node):
            key = (getattr(node, "lineno", None), getattr(node, "col_offset", None),
                   hashlib.sha256(dump(node).encode()).hexdigest())
            if key in lookup:
                if key in seen:
                    raise ValueError("resume setup matched twice")
                seen.add(key)
                rule = lookup[key]
                replacement = (
                    ast.parse(rule["after_source"], mode="eval").body if rule["expression"]
                    else ast.parse(rule["after_source"]).body[0])
                return ast.copy_location(replacement, node)
            return super().visit(node)
    tree = Exact().visit(tree)
    # Rules inside the replaced setup helpers have no live role.
    covered = {k for k in lookup if 44 <= k[0] <= 84 or 107 <= k[0] <= 108}
    if seen | covered != set(lookup):
        raise ValueError("resume setup rules did not cover frozen AST")
    ast.fix_missing_locations(tree)
    restored = copy.deepcopy(tree)
    for path, node in _paths(original):
        key = (getattr(node, "lineno", None), getattr(node, "col_offset", None),
               hashlib.sha256(dump(node).encode()).hexdigest())
        if key in seen:
            _put(restored, path, copy.deepcopy(node))
    if dump(restored) != dump(original):
        raise ValueError("resume full AST reverse replay failed")
    # A passing normalized comparison would conceal assertion-source changes.
    # Keep the diagnostic proposal fail-closed. Harness is independently useful
    # for real IPC tests, but this frozen suite has not been restored.
    if corpus(original) != corpus(tree):
        raise ValueError("blocked resume assertion/signature/decorator/parameter drift")
    return original, tree, rules


def load(namespace):
    original, tree, rules = adapt(frozen_source(SOURCE_PATH))
    module = ModuleType("frozen_step8_review_resume")
    module.__file__ = SOURCE_PATH
    exec(compile(tree, SOURCE_PATH, "exec"), module.__dict__)
    for selector in RETIRED:
        cls, case = selector.split(".")
        delattr(getattr(module, cls), case)
    register_module(namespace, module, prefix="step8_review_resume", full_class_name=True)
    return original, tree, rules
