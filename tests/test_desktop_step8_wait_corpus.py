"""Complete bounded wait assertions, authentic admission, and loader rejection."""
import ast
import hashlib

import pytest

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from tests.desktop_adapters import step8_wait
from tests.desktop_adapters.step8_wait import load

load(globals())


@pytest.fixture(autouse=True)
async def step8_wait_owner(request, tmp_path):
    if not request.node.name.startswith("test_step8_wait_"):
        yield
        return
    async for state in step8_wait.owner_fixture(tmp_path):
        yield state


def test_wait_loader_complete_corpus():
    original, adapted = step8_wait.adapt(frozen_source(step8_wait.SOURCE_PATH))
    assert corpus(original) == corpus(adapted)
    assert len(corpus(original)["cases"]) == 11
    assert len(corpus(original)["assertions"]) == 23
    assert step8_wait.CORPUS_SELECTIONS == {"test_bounded_process_wait": None}
    assert step8_wait.CORPUS_EXCLUSIONS == {}


def test_wait_loader_changed_bytes():
    with pytest.raises(ValueError, match="bytes changed"):
        step8_wait.adapt(frozen_source(step8_wait.SOURCE_PATH) + b"\n")


def test_wait_loader_wrong_duplicate_assertion_hunks():
    source = frozen_source(step8_wait.SOURCE_PATH)
    line, column, digest, replacement = step8_wait.SETUP_HUNKS[0]
    with pytest.raises(ValueError, match="exact admitted"):
        step8_wait.adapt(source, hunks=[(line + 1, column, digest, replacement)])
    with pytest.raises(ValueError, match="duplicate"):
        step8_wait.adapt(source, hunks=step8_wait.SETUP_HUNKS * 2)
    node = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Assert))
    rule = (node.lineno, node.col_offset, hashlib.sha256(dump(node).encode()).hexdigest(),
            "assert False")
    with pytest.raises(ValueError, match="exact admitted"):
        step8_wait.adapt(source, hunks=[rule])


def test_wait_loader_collateral_replay(monkeypatch):
    original_put = step8_wait._put

    def corrupt(tree, path, node):
        original_put(tree, path, node)
        tree.body.append(ast.parse("unadmitted = 1").body[0])

    monkeypatch.setattr(step8_wait, "_put", corrupt)
    with pytest.raises(ValueError, match="complete AST reverse replay"):
        step8_wait.adapt(frozen_source(step8_wait.SOURCE_PATH))


def test_wait_build_requires_real_owner():
    with pytest.raises(RuntimeError, match="authenticated temporary owner"):
        step8_wait.build([])


async def test_wait_authentic_gate_rejects_fake_and_unbound_seal(tmp_path):
    from tests.fakes import FakeMessage

    async for _state in step8_wait.owner_fixture(tmp_path):
        bot, _fake = step8_wait.build([])
        with pytest.raises(PermissionError, match="current admitted request owner"):
            await bot.tool_loop.run(FakeMessage("not admitted"), history=[])
        response = bot.requests.submit({"client_submission_id": "queued-only",
                                        "conversation_id": bot.cid, "text": "queued"})
        sealed = bot.requests.fetch_request(bot.cid, response["request_id"])
        with pytest.raises(PermissionError, match="current admitted request owner"):
            await bot.engine.run(sealed)
        assert bot.requests.get_request(response["request_id"])["state"] == "queued"
        assert bot.observed.results == []


async def test_wait_real_service_observes_unmodified_tuple_and_authority(tmp_path):
    from tests.fakes import FakeMessage, text_response

    async for state in step8_wait.owner_fixture(tmp_path):
        bot, fake = step8_wait.build([text_response("durably completed")])
        message = FakeMessage("transport content only")
        result = await step8_wait.run_loop(bot, message)
        assert result == bot.observed.results[0]
        assert len(result) == 5 and result[0] == "durably completed" and not result[2]
        rows = bot.journal.connection.execute("SELECT * FROM desktop_requests").fetchall()
        assert len(rows) == 1
        durable = dict(rows[0])
        assert durable["owner"] == state.authority.owner_id
        assert durable["owner"] != str(message.author.id)
        assert durable["ledger_generation"] is not None
        assert len(fake.calls) == 1
