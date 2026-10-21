"""Native child tasks read only their admitted durable transcript."""
import asyncio

import pytest

from src.llm.types import LLMResponse, ToolCall

pytest_plugins = ["tests.test_desktop_engine_services"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,arguments", [
    ("read_conversation", {"limit": 10}),
    ("search_history", {"query": "durable history marker", "limit": 10}),
])
async def test_real_native_history_child_reads_current_transcript(graph, tool, arguments):
    requests, _engine, provider, transcript, cid = graph
    transcript.commit(cid, "assistant", "durable history marker")
    foreign = requests.conversations.create()["conversation"]["id"]
    transcript.commit(foreign, "assistant", "foreign private marker")
    provider.responses = [
        LLMResponse(tool_calls=[ToolCall("history-call", tool, arguments)]),
        LLMResponse(text="History retrieved."),
    ]
    requests.submit({"client_submission_id": "history", "conversation_id": cid,
                     "text": "Read the durable history"})
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    results = [block["content"] for message in provider.calls[-1]["messages"]
               if isinstance(message.get("content"), list)
               for block in message["content"] if block.get("type") == "tool_result"]
    assert results and "durable history marker" in str(results)
    assert "foreign private marker" not in str(results)
    assert "Permission denied" not in str(results)
    assert requests.snapshot(cid)["recent"][-1]["outcome"] == "completed"


@pytest.mark.asyncio
async def test_real_native_history_limits_blank_queries_and_bound_requests(graph):
    """Odin 4.20.0 (PR #671) in Desktop: history search on the real native route."""
    requests, engine, provider, transcript, cid = graph
    foreign = requests.conversations.create()["conversation"]["id"]
    transcript.commit(foreign, "assistant", "the heron count is 42")
    transcript.commit(foreign, "assistant", "a second heron note")
    provider.responses = [
        LLMResponse(tool_calls=[
            ToolCall("limited", "search_history", {"query": "heron", "limit": 1}),
            ToolCall("blank", "search_history", {"query": "   "}),
        ]),
        LLMResponse(text="History retrieved."),
    ]
    requests.submit({"client_submission_id": "heron", "conversation_id": cid,
                     "text": "what was the heron count?"})
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    results = [str(block["content"]) for message in provider.calls[-1]["messages"]
               if isinstance(message.get("content"), list)
               for block in message["content"] if block.get("type") == "tool_result"]
    assert len(results) == 2
    limited, blank = results
    assert "Found 1 result(s) for 'heron'" in limited
    assert "heron" in limited.split("\n", 1)[1]
    assert "what was the heron count" not in limited  # the invoking prompt never answers
    assert "A search query is required." in blank
    assert requests.snapshot(cid)["recent"][-1]["outcome"] == "completed"

    # Outside an admitted request the same owner refuses to search at all.
    history = engine.deps.native_owners["transcript_history"]
    with pytest.raises(PermissionError, match="Untrusted request envelope"):
        await history.search_history(object(), {"query": "heron"})
