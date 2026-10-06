"""Full review-delivery corpus, plus fail-closed and admitted-path evidence."""
import ast
import asyncio
import hashlib
import json

import pytest

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from src.tools.runtime_delivery import deliver_runtime_output
from tests.desktop_adapters import step8_review_delivery as adapter

adapter.load(globals())


@pytest.fixture(autouse=True)
async def review_delivery_owner(request, tmp_path):
    if not request.node.name.startswith("test_step8_review_delivery_"):
        yield
        return
    async with adapter.owner_fixture(tmp_path) as state:
        yield state


def test_delivery_loader_complete_corpus():
    original, adapted = adapter.adapt(frozen_source(adapter.SOURCE_PATH))
    assert corpus(original) == corpus(adapted)
    assert len(corpus(original)["cases"]) == 7
    assert len(corpus(original)["assertions"]) == 31
    assert adapter.CORPUS_SELECTIONS == {"test_delivery_review_regressions": None}
    assert adapter.CORPUS_EXCLUSIONS == {}


def test_delivery_loader_changed_bytes():
    with pytest.raises(ValueError, match="bytes changed"):
        adapter.adapt(frozen_source(adapter.SOURCE_PATH) + b"\n")


def test_delivery_loader_wrong_duplicate_assertion_hunks():
    source = frozen_source(adapter.SOURCE_PATH)
    line, column, digest, replacement = adapter.SETUP_HUNKS[0]
    with pytest.raises(ValueError, match="exact setup"):
        adapter.adapt(source, hunks=[(line + 1, column, digest, replacement)])
    with pytest.raises(ValueError, match="duplicate"):
        adapter.adapt(source, hunks=adapter.SETUP_HUNKS * 2)
    node = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Assert))
    rule = (node.lineno, node.col_offset, hashlib.sha256(dump(node).encode()).hexdigest(),
            "assert False")
    with pytest.raises(ValueError, match="exact setup"):
        adapter.adapt(source, hunks=[rule])


def test_delivery_loader_collateral_replay(monkeypatch):
    original_put = adapter._put
    def corrupt(tree, path, node):
        original_put(tree, path, node)
        tree.body.append(ast.parse("unadmitted = 1").body[0])
    monkeypatch.setattr(adapter, "_put", corrupt)
    with pytest.raises(ValueError, match="complete AST reverse replay"):
        adapter.adapt(frozen_source(adapter.SOURCE_PATH))


def test_delivery_ownerless_runtime_still_fails_closed():
    with pytest.raises(RuntimeError, match="no authenticated executor consumer.*Do not replay"):
        deliver_runtime_output(object(), "HEAD" + "x" * 30000 + "TAIL",
                               tool_name="test", tool_input={}, user_id="owner")


async def test_delivery_runtime_authentication_and_readiness_rechecked(tmp_path):
    async with adapter.owner_fixture(tmp_path) as state:
        ex = adapter.runtime_failure_executor(tmp_path)
        with pytest.raises(PermissionError):
            deliver_runtime_output(ex, "short", tool_name="search_history", tool_input={},
                                   user_id="foreign")
        state.graphs[0][-1].tools.disabled_tools = ["search_history"]
        with pytest.raises(PermissionError, match="capability unavailable"):
            deliver_runtime_output(ex, "short", tool_name="search_history", tool_input={},
                                   user_id=state.authority.owner_id)


async def test_delivery_failed_retention_survives_real_request(tmp_path):
    from unittest.mock import AsyncMock

    from tests.fakes import text_response, tool_call_response

    async with adapter.owner_fixture(tmp_path) as state:
        ex = adapter.runtime_failure_executor(tmp_path)
        engine, requests, journal, transcript, conversations, _cfg = state.graphs[0]
        body = "HEAD-SENTINEL\npassword=fixtureSecret\n" + "record\n" * 7000 + "TAIL-SENTINEL"
        # The inherited executor seam stubs only harmless command output. Real
        # executor retention, runtime delivery and guarded publication all run.
        ex._handle_run_command = AsyncMock(return_value=body)
        fake = engine.deps.llm_gateway.compatible_client
        fake.responses = [
            tool_call_response(("run_command", {"host": "testhost", "command": "fixture"})),
            text_response("guarded final"),
        ]
        cid = conversations.create()["conversation"]["id"]
        response = requests.submit({"client_submission_id": "delivery-proof",
                                    "conversation_id": cid, "text": "fixture delivery"})
        await requests.after_commit()
        await asyncio.gather(*list(requests._tasks))
        assert requests.get_request(response["request_id"])["state"] == "completed"
        assert ex._handle_run_command.await_count == 1
        outputs = [block["content"] for call in fake.calls for m in call["messages"]
                   if isinstance(m.get("content"), list) for block in m["content"]
                   if isinstance(block, dict) and block.get("type") == "tool_result"]
        assert outputs
        page = json.loads(outputs[-1])
        assert page["retention"] == "failed" and page["cursor"] is None
        assert "HEAD-SENTINEL" in page["head"] and "TAIL-SENTINEL" in page["tail"]["text"]
        assert "fixtureSecret" not in outputs[-1]
        assert transcript.read_conversation(cid)[-1]["text"] == "guarded final"


async def test_delivery_native_runtime_failed_retention_survives_real_request(tmp_path):
    from tests.fakes import text_response, tool_call_response

    async with adapter.owner_fixture(tmp_path) as state:
        adapter.runtime_failure_executor(tmp_path)
        engine, requests, _journal, transcript, conversations, _cfg = state.graphs[0]
        cid = conversations.create()["conversation"]["id"]
        body = ("deliveryneedle HEAD-SENTINEL\npassword=fixtureSecret\n"
                + "record\n" * 7000 + "TAIL-SENTINEL")
        transcript.commit(cid, "user", body)
        fake = engine.deps.llm_gateway.compatible_client
        fake.responses = [
            tool_call_response(("search_history", {"query": "deliveryneedle", "limit": 1})),
            text_response("native guarded final"),
        ]
        response = requests.submit({"client_submission_id": "native-delivery-proof",
                                    "conversation_id": cid, "text": "retrieve fixture evidence"})
        await requests.after_commit()
        await asyncio.gather(*list(requests._tasks))
        assert requests.get_request(response["request_id"])["state"] == "completed"
        outputs = [block["content"] for call in fake.calls for m in call["messages"]
                   if isinstance(m.get("content"), list) for block in m["content"]
                   if isinstance(block, dict) and block.get("type") == "tool_result"]
        assert len(outputs) == 1
        page = json.loads(outputs[0])
        assert page["retention"] == "failed" and page["cursor"] is None
        assert "HEAD-SENTINEL" in page["head"]
        assert "fixtureSecret" not in outputs[0]
        # RankedOutput's human-readable summary clips each full match at 300
        # characters; failed-retention framing preserves that supplied summary.
        # The unretained full match is not silently promised as a cursor.
        assert page["error"] and page["truncated"]
        assert transcript.read_conversation(cid)[-1]["text"] == "native guarded final"
