"""Serving-account quota failure recovery through real transport and SSE readers."""
import asyncio
import json
from unittest.mock import MagicMock

import pytest

from tests.test_codex_limit_aware import pool_with_accounts


class Reply:
    def __init__(self, events=(), status=200, reorder=None, error=None):
        self.status = status
        self.headers = {
            "x-codex-primary-used-percent": "10", "x-codex-primary-window-minutes": "300"
        }
        self.content = self
        self.events, self.reorder, self.error = events, reorder, error
        self.body = b'{"error":{"message":"rate limited"}}'

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self.lines()

    async def lines(self):
        for index, event in enumerate(self.events):
            if index == 1 and self.reorder:
                self.reorder()
                await asyncio.sleep(0)
            yield f"data: {json.dumps(event)}\n".encode()
        if self.error:
            raise self.error

    async def read(self, n):
        chunk, self.body = self.body[:n], self.body[n:]
        return chunk


def client_for(pool, *replies, retries=1):
    from src.llm.openai_codex import CodexChatClient
    client = CodexChatClient(
        pool, "test", max_retries=retries, retry_base_delay=0, retry_max_delay=0
    )
    client._session = MagicMock(closed=False)
    client._session.post.side_effect = replies
    return client


def completed():
    return [
        {"type": "response.output_text.delta", "delta": "reply"},
        {"type": "response.completed", "response": {}},
    ]


def failed_pool():
    pool = pool_with_accounts(2)
    pool.set_quota_check_failure(0, "HTTP 401")
    pool.set_quota_check_failure(1, "timeout")
    return pool


def test_clear_opaque_key_idempotent():
    from src.llm.account_key import opaque_account_key
    pool = failed_pool()
    pool._accounts.reverse()
    pool.clear_quota_check_failure(None)
    pool.clear_quota_check_failure("account-0")
    assert pool.quota_check_failure(1) == "HTTP 401"
    key = opaque_account_key("account-0")
    pool.clear_quota_check_failure(key)
    pool.clear_quota_check_failure(key)
    assert pool.quota_check_failure(1) is None
    assert pool.quota_check_failure(0) == "timeout"
    del pool._quota_check_failures
    pool.clear_quota_check_failure(key)
    assert not hasattr(pool, "_quota_check_failures")


@pytest.mark.parametrize("path", ["text", "tools"])
@pytest.mark.parametrize("serving", [0, 1])
@pytest.mark.parametrize("reorder", [False, True])
@pytest.mark.asyncio
async def test_success_serving_account_only(path, serving, reorder):
    from src.llm.account_key import opaque_account_key
    pool = failed_pool()
    pool._current_index = serving
    original = dict(pool._quota_check_failures)
    key = opaque_account_key(f"account-{serving}")

    def during_read():
        assert pool._quota_check_failures == original
        if reorder:
            pool._accounts.reverse()
            pool._current_index = 1 - serving

    client = client_for(pool, Reply(completed(), reorder=during_read))
    result = await (
        client._stream_request({}) if path == "text" else client._stream_tool_request({})
    )
    assert (str(result) if path == "text" else result.text) == "reply"
    assert result.account_key == key
    assert pool._quota_check_failures == {k: v for k, v in original.items() if k != key}
    headers = client._session.post.call_args.kwargs["headers"]
    assert headers["ChatGPT-Account-Id"] == f"account-{serving}"
    assert pool.quota.snapshot_for(key) is not None


@pytest.mark.parametrize("path", ["text", "tools"])
@pytest.mark.parametrize("failure", ["429", "failed", "timeout", "eof", "incomplete", "empty"])
@pytest.mark.asyncio
async def test_unsuccessful_reply_retains_failures(path, failure):
    from src.llm.errors import LLMIncompleteResponseError, LLMRateLimitError, LLMTransportError
    pool = failed_pool()
    original = dict(pool._quota_check_failures)
    events = [{"type": "response.output_text.delta", "delta": "partial"}]
    error, expected = None, LLMTransportError
    if failure == "failed":
        events.append({"type": "response.failed", "response": {"error": {"message": "failed"}}})
    elif failure == "timeout":
        error = TimeoutError("stream timed out")
    elif failure == "incomplete":
        events.append({"type": "response.incomplete", "response": {}})
        expected = LLMIncompleteResponseError
    elif failure == "empty":
        events = [{"type": "response.completed", "response": {}}]
    elif failure == "429":
        expected = LLMRateLimitError
    client = client_for(pool, Reply(events, status=429 if failure == "429" else 200, error=error))
    if failure == "empty":
        result = await (
            client._stream_request({}) if path == "text" else client._stream_tool_request({})
        )
        assert not (str(result) if path == "text" else result.text)
    elif failure == "incomplete" and path == "tools":
        result = await client._stream_tool_request({})
        assert result.stop_reason == "incomplete" and result.text == "partial"
    else:
        with pytest.raises(expected):
            await (
                client._stream_request({}) if path == "text" else client._stream_tool_request({})
            )
    assert pool._quota_check_failures == original
    assert client._session.post.call_count == 1


@pytest.mark.asyncio
async def test_retry_success_clears_reacquired_account_only():
    pool = failed_pool()
    client = client_for(pool, Reply(status=429), Reply(completed()), retries=2)
    assert await client._stream_request({}) == "reply"
    assert pool.quota_check_failure(0) == "HTTP 401"
    assert pool.quota_check_failure(1) is None
    ids = [c.kwargs["headers"]["ChatGPT-Account-Id"] for c in client._session.post.call_args_list]
    assert ids == ["account-0", "account-1"]
