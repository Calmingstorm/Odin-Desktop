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
