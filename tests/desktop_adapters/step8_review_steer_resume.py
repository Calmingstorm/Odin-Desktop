"""Frozen steering/resume assertions in real desktop request worker tasks.

Transport fixtures never confer authority. RequestService allocates the sealed
message, owns the executing task and admits the real durable handle. Snapshot
round-trips deliberately stay within that admitted worker, as in the upstream
case (they are not a claim about cross-process automatic resume).
"""
from __future__ import annotations

import ast
import asyncio
import contextvars
import copy
import hashlib
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, register_module
from src.config.schema import Config
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import DurableDelivery, PublicationEventJournal
from src.desktop.requests import RequestService
from src.desktop.services import build_engine_services
from src.desktop.transcript import TranscriptStore
from tests.desktop_adapters.process_cases import temporary_owner
from tests.fakes import text_response

SOURCE_PATH = "tests/test_chat_steering_resume.py"
SOURCE_SHA256 = "fd1316042f023dbabdd8f2d522bff522df54328bb04d984b619bbf93cb2f7f89"
CORPUS_SELECTIONS = {"test_chat_steering_resume": None}
CORPUS_EXCLUSIONS = {}
PREFIX = "step8_review_steer_resume"
_active = contextvars.ContextVar("steering_resume_admitted_graph", default=None)

# Every replacement is pinned to the complete original node, not a string-wide
# identity rewrite. There are no assertion substitutions.
SETUP_HUNKS = [
    (26, 0, "10695a02a23f1bea015841c5347938d07ec3d4b025355d0fe2d94989b42eafb7", "statement",
     "from tests.fakes import FakeLLM, FakeMessage, text_response, tool_call_response"),
    (87, 0, "b737522a1b272f0ecdae671ae27fdbda33ecf2ec54f482d264af87d9592833d7", "statement",
     "def _queue(bot, text: str) -> str:\n    return bot.channel_state.request_steer("
     "bot.message.channel.id, text, user_id=bot.message.author.id)"),
    (184, 10, "4c932a29b4c24d091185e1a55b09f6c9908add27c0d071a7fce5108a32b4abc7",
     "expression", "admitted_components(fake)"),
    (231, 10, "4c932a29b4c24d091185e1a55b09f6c9908add27c0d071a7fce5108a32b4abc7",
     "expression", "admitted_components(fake)"),
    (275, 10, "4c932a29b4c24d091185e1a55b09f6c9908add27c0d071a7fce5108a32b4abc7",
     "expression", "admitted_components(fake)"),
    (304, 10, "4c932a29b4c24d091185e1a55b09f6c9908add27c0d071a7fce5108a32b4abc7",
     "expression", "admitted_components(fake)"),
    (330, 10, "4c932a29b4c24d091185e1a55b09f6c9908add27c0d071a7fce5108a32b4abc7",
     "expression", "admitted_components(fake)"),
    (371, 10, "4c932a29b4c24d091185e1a55b09f6c9908add27c0d071a7fce5108a32b4abc7",
     "expression", "admitted_components(fake)"),
    (186, 14, "8d1ba15b415afdad4e7242c069c32b55e1b567b2c32d1f36048614bb8a343c9c",
     "expression", "admitted_message('perform the original task')"),
    (233, 14, "b18bcac8b06497a441adb8587bdde9e8ddd0662c6ea795952ed227d26777db19",
     "expression", "admitted_message('wait for the worker')"),
    (277, 14, "4d98b69530eb10ba7f168883e4f13f615872ca87c1711c1a88f05bf6012746f5",
     "expression", "admitted_message('parse a date')"),
    (306, 14, "1564ff64a9dadbdfdda02428f932f9604993f69e5a9592320f7badfe296e5c94",
     "expression", "admitted_message('stop me')"),
    (332, 14, "cdec056e4562f88d834be32d5fc1dbcc37389af4cf30a5ea5ff9ee9c16362954",
     "expression", "admitted_message('this will fail')"),
    (352, 19, "b59a76018f662ae6575ba9645b6ab13fae24cb95fe5d51c8e2d894f505838558",
     "expression", "admitted_message('new unrelated request')"),
    (373, 14, "71a36ea1595e161572fa7fa50b166987d88e0dce47ce844982e43cebe469f3ed",
     "expression", "admitted_message('capacity limited request')"),
    (202, 4, "7c44f05b7cff322a776f667397b19705cc136d58d9710bec80d255c1413adefd", "statement",
     "bot.channel_state.close_steer_inbox(original._ch_id, original._req_id)"),
    (251, 4, "0e2fbd55e8235feb47be62456cb2541acacbdc0003c0feda944a09861988ea97", "statement",
     "bot.channel_state.close_steer_inbox(original._ch_id, original._req_id)"),
    (209, 8, "108c73c8cb90d0de9bb7595c65df64fb144c06e6d94acdcf6313f4427fc0b51d",
     "keyword", "original.durability"),
    (258, 8, "108c73c8cb90d0de9bb7595c65df64fb144c06e6d94acdcf6313f4427fc0b51d",
     "keyword", "original.durability"),
    (382, 4, "ec354ab22de74d3ffabdfac567e637e0c38c4798e7d326dbffc32babccee7dfd",
     "statement", "pass"),
    (389, 4, "ca43c6d73b42080cf0d509d8cc80b1222e7089e9cf45130d7f7a7471d17b17a5",
     "statement", "require_real_durability(turn)"),
]


def _paths(node, path=()):
    yield path, node
    for field, value in ast.iter_fields(node):
        if isinstance(value, list):
            for index, child in enumerate(value):
                if isinstance(child, ast.AST):
                    yield from _paths(child, (*path, field, index))
        elif isinstance(value, ast.AST):
            yield from _paths(value, (*path, field))


def _put(tree, path, value):
    target = tree
    for part in path[:-1]:
        target = target[part] if isinstance(part, int) else getattr(target, part)
    if isinstance(path[-1], int):
        target[path[-1]] = value
    else:
        setattr(target, path[-1], value)


def adapt(source, *, hunks=None):
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("steering resume frozen bytes changed")
    rules = SETUP_HUNKS if hunks is None else hunks
    if len({r[:3] for r in rules}) != len(rules):
        raise ValueError("steering resume duplicate setup hunk")
    if rules != SETUP_HUNKS:
        raise ValueError("steering resume exact admitted setup allowlist changed")
    original = ast.parse(source, filename=SOURCE_PATH)
    tree = copy.deepcopy(original)
    replay = []
    for line, column, digest, kind, replacement in rules:
        matches = [(p, n) for p, n in _paths(original)
                   if getattr(n, "lineno", None) == line
                   and getattr(n, "col_offset", None) == column
                   and hashlib.sha256(dump(n).encode()).hexdigest() == digest]
        if len(matches) != 1:
            raise ValueError("steering resume setup must match exactly once")
        path, node = matches[0]
        if kind == "statement":
            value = ast.parse(replacement).body[0]
        elif kind == "keyword":
            value = ast.keyword(arg=node.arg, value=ast.parse(replacement, mode="eval").body)
        else:
            value = ast.parse(replacement, mode="eval").body
        _put(tree, path, ast.copy_location(value, node))
        replay.append((path, node))
    ast.fix_missing_locations(tree)
    old, new = corpus(original), corpus(tree)
    if old["assertions"] != new["assertions"] or old["cases"] != new["cases"]:
        raise ValueError("steering resume assertion/signature/decorator drift")
    if new["classes"] != [c for c in old["classes"] if not c[0].endswith("._SuspendingDurability")]:
        raise ValueError("steering resume unexpected class drift")
    restored = copy.deepcopy(tree)
    for path, node in replay:
        _put(restored, path, copy.deepcopy(node))
    if dump(restored) != dump(original):
        raise ValueError("steering resume complete AST reverse replay failed")
    return original, tree


class ProviderBoundary:
    """Only provider substitution; no permission, task or durability replacement."""
    def __init__(self):
        self.fake = None

    async def chat(self, *args, **kwargs):
        if self.fake is None:
            raise RuntimeError("inherited case did not install scripted provider")
        return await self.fake.chat(*args, **kwargs)

    async def chat_with_tools(self, *args, **kwargs):
        if self.fake is None:
            raise RuntimeError("inherited case did not install scripted provider")
        return await self.fake.chat_with_tools(*args, **kwargs)

    async def drain_and_close(self):
        if self.fake is not None:
            await self.fake.close()


class RunnerObservation:
    """Delegate unchanged calls and retain actual turns/results for evidence."""
    def __init__(self, graph):
        object.__setattr__(self, "graph", graph)

    def __getattr__(self, name):
        return getattr(self.graph.engine.runner, name)

    def __setattr__(self, name, value):
        # The one inherited monkeypatch is _call_llm for the capacity branch.
        setattr(self.graph.engine.runner, name, value)

    async def _prepare_chat_turn(self, *args, **kwargs):
        turn = await self.graph.engine.runner._prepare_chat_turn(*args, **kwargs)
        require_real_durability(turn)
        self.graph.turns.append(turn)
        return turn

    async def _run_chat_iterations(self, turn):
        result = await self.graph.engine.runner._run_chat_iterations(turn)
        self.graph.results.append(result)
        return result

    async def run_resumed(self, turn):
        require_real_durability(turn)
        self.graph.turns.append(turn)
        result = await self.graph.engine.runner.run_resumed(turn)
        self.graph.results.append(result)
        return result


def require_real_durability(turn):
    from src.turn_state.durability import TurnDurability
    graph = _active.get()
    if graph is None:
        raise RuntimeError("steering resume requires a real admitted worker")
    graph.requests.assert_request(turn.message)
    row = graph.requests.get_request(turn.message.request_id)
    if (type(turn.durability) is not TurnDurability or not turn.durability.enabled
            or turn.durability.lease is None
            or turn.durability._store is not graph.engine.deps.turn_store
            or row["ledger_generation"] != turn.durability.lease.generation
            or turn.user_id != graph.state.authority.owner_id):
        raise RuntimeError("steering resume requires the actual admitted durable handle")


def admitted_components(fake):
    graph = _active.get()
    if graph is None:
        raise RuntimeError("steering resume requires a real admitted worker")
    graph.requests.assert_request(graph.message)
    graph.provider.fake = fake
    return graph


def admitted_message(text):
    graph = _active.get()
    if graph is None or graph.message.content != text:
        raise RuntimeError("steering resume message must be actual admitted input")
    graph.requests.assert_request(graph.message)
    return graph.message


class CaseEngine:
    def __init__(self, graph):
        self.graph = graph

    def __getattr__(self, name):
        return getattr(self.graph.engine, name)

    async def run(self, message, **_input):
        graph = self.graph
        graph.message = message
        graph.requests.assert_request(message)
        token = _active.set(graph)
        try:
            try:
                graph.locals = await graph.callback()
                # The unrelated-request suffix only prepares a turn. Once its
                # original assertions finish, settle through actual guards.
                if not graph.results:
                    graph.provider.fake.responses[:] = [text_response("new request complete")]
                    result = await graph.engine.runner._run_with_guards(graph.turns[-1])
                    graph.results.append(result)
                else:
                    result = graph.results[-1]
                    turn = graph.turns[-1]
                    await turn.durability.settle_terminal(
                        cancelled=turn._cancel.is_set(), is_error=result[2])
                if graph.case_name.endswith(
                        "suspension_closes_pending_mailbox_without_consuming_it"):
                    from src.turn_state.store import TurnStatus
                    turn = graph.turns[-1]
                    assert turn.durability.suspended
                    assert (graph.engine.deps.turn_store.turn_status_sync(message.turn_key)
                            == TurnStatus.SUSPENDED)
                graph.completed = True
                return result
            except BaseException as error:
                graph.failure = error
                raise
        finally:
            _active.reset(token)


class Graph:
    def __init__(self, state):
        self.state = state
        self.journal = JournalStore(
            state.paths.data_dir / "steering-resume.sqlite3", "steering-resume")
        events = PublicationEventJournal(self.journal)
        conversations = ConversationStore(self.journal, events)
        transcript = TranscriptStore(self.journal, events, conversations)
        delivery = DurableDelivery(self.journal, events, transcript_commit=transcript.commit)
        cfg = Config()
        cfg.openai_codex.enabled = False
        cfg.ollama.enabled = False
        cfg.openai_compatible.enabled = True
        cfg.llm_provider.model = "compat:fake-model"
        cfg.context.directory = str(state.paths.data_dir / "context")
        cfg.learning.enabled = False
        cfg.search.enabled = False
        cfg.browser.enabled = False
        cfg.tools.local_working_dir = str(state.workspace)
        cfg.tools.ssh_pool.enabled = False
        self.provider = ProviderBoundary()
        self.engine = build_engine_services(cfg, state.paths, state.manager,
                                            delivery=delivery, compatible_client=self.provider)
        self.requests = RequestService(self.journal, conversations, transcript,
                                       engine=CaseEngine(self), permissions=state.manager,
                                       authority=state.authority, delivery=delivery)
        self.engine.bind_requests(self.requests)
        self.cid = conversations.create()["conversation"]["id"]
        self.channel_state = self.engine.deps.channel_state
        self.tool_loop = RunnerObservation(self)
        self.turns = []
        self.results = []
        self.message = None
        self.locals = None
        self.completed = False
        self.failure = None

    async def invoke(self, text, callback, *, submission):
        self.callback = callback
        self.completed = False
        self.failure = None
        response = self.requests.submit({"client_submission_id": submission,
                                         "conversation_id": self.cid, "text": text})
        row = self.requests.get_request(response["request_id"])
        assert row["state"] == "queued" and row["owner"] == self.state.authority.owner_id
        await self.requests.after_commit()
        await asyncio.gather(*list(self.requests._tasks))
        if self.failure is not None:
            raise self.failure
        if not self.completed:
            raise RuntimeError("steering resume admitted case never completed")
        row = self.requests.get_request(response["request_id"])
        assert row["ledger_generation"] is not None
        assert row["state"] in {"completed", "cancelled", "failed", "suspended"}
        return self.locals


TEXTS = {
    "test_run_resumed_seeds_sequence_after_consumed_checkpoint_directives":
        "perform the original task",
    "test_resumed_post_tool_steer_does_not_resurrect_skipped_wait_judgment": "wait for the worker",
    "test_runtime_post_tool_drain_replans_with_directive_in_next_generation": "parse a date",
    "test_runtime_stop_after_entry_drain_never_generates_for_consumed_directive": "stop me",
    "test_runtime_error_closes_pending_mailbox_without_replay_to_next_turn": "this will fail",
    "test_runtime_suspension_closes_pending_mailbox_without_consuming_it":
        "capacity limited request",
}


def _split_error_case(module, tree):
    """Keep exact assertion nodes, execute suffix in a second real worker.

    The split is the upstream line-352 next_message statement, not arbitrary
    replacement control flow. First-half locals seed a separately compiled
    suffix namespace; its message/prepare calls use the newly admitted request.
    """
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                and n.name ==
                "test_runtime_error_closes_pending_mailbox_without_replay_to_next_turn")
    if (hashlib.sha256(dump(node).encode()).hexdigest()
            != "5737090d36b3d0f99b0afb446d7329c5aa2f807d2c359379f93bb945a5fc7a5d"):
        raise ValueError("steering resume exact split case changed")
    boundary = next(i for i, n in enumerate(node.body) if n.lineno == 352)
    first, second = copy.deepcopy(node), copy.deepcopy(node)
    first.body = first.body[:boundary] + [ast.parse("return locals()").body[0]]
    second.name = "_second_request_suffix"
    second.body = second.body[boundary:]
    left = [value for _symbol, value in corpus(first)["assertions"]]
    right = [value for _symbol, value in corpus(second)["assertions"]]
    expected = [value for _symbol, value in corpus(node)["assertions"]]
    if left + right != expected:
        raise ValueError("steering resume split changed assertion corpus")
    first_tree = ast.fix_missing_locations(ast.Module(body=[first], type_ignores=[]))
    exec(compile(first_tree, SOURCE_PATH, "exec"), module.__dict__)
    second_tree = ast.fix_missing_locations(ast.Module(body=[second], type_ignores=[]))
    return second_tree


def load(namespace):
    original, tree = adapt(frozen_source(SOURCE_PATH))
    module = ModuleType("frozen_step8_review_steer_resume")
    module.__file__ = SOURCE_PATH
    module.__dict__.update(admitted_components=admitted_components,
                           admitted_message=admitted_message,
                           require_real_durability=require_real_durability)
    exec(compile(tree, SOURCE_PATH, "exec"), module.__dict__)
    module._isolated_cwd.__module__ = namespace["__name__"]
    namespace["_isolated_cwd"] = module._isolated_cwd
    second_tree = _split_error_case(module, tree)
    # The pure compression/snapshot cases execute directly, including the plain
    # disabled-durability _bare_turn, which never runs a model or runner.
    for name in TEXTS:
        inherited = getattr(module, name)

        async def execute(*, _name=name, _case=inherited, tmp_path, monkeypatch=None):
            with temporary_owner(tmp_path / "steering-resume-owner") as state:
                graph = Graph(state)
                graph.case_name = _name
                try:
                    async def callback():
                        if _name.endswith("suspension_closes_pending_mailbox_without_consuming_it"):
                            return await _case(monkeypatch)
                        return await _case()
                    saved = await graph.invoke(TEXTS[_name], callback, submission="original")
                    if _name.endswith("error_closes_pending_mailbox_without_replay_to_next_turn"):
                        suffix_ns = dict(module.__dict__)
                        suffix_ns.update(saved)
                        exec(compile(second_tree, SOURCE_PATH, "exec"), suffix_ns)
                        graph.results = []
                        await graph.invoke(
                            "new unrelated request", suffix_ns["_second_request_suffix"],
                                           submission="unrelated")
                finally:
                    await graph.requests.close()
                    await graph.engine.close()
                    graph.journal.close()

        # Expose only pytest fixture parameters, never closure defaults.
        if name.endswith("suspension_closes_pending_mailbox_without_consuming_it"):
            async def wrapper(tmp_path, monkeypatch, _execute=execute):
                await _execute(tmp_path=tmp_path, monkeypatch=monkeypatch)
        else:
            async def wrapper(tmp_path, _execute=execute):
                await _execute(tmp_path=tmp_path)
        import inspect
        wrapper.__signature__ = inspect.Signature([
            inspect.Parameter("tmp_path", inspect.Parameter.POSITIONAL_OR_KEYWORD),
            *([inspect.Parameter("monkeypatch", inspect.Parameter.POSITIONAL_OR_KEYWORD)]
              if name.endswith("suspension_closes_pending_mailbox_without_consuming_it") else [])])
        setattr(module, name, wrapper)
    register_module(namespace, module, prefix=PREFIX)
    return original, tree
