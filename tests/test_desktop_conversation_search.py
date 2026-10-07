"""Search uses committed durable transcript, not transient model context."""
import asyncio

import pytest

from src.desktop.commands import CommandJournal, JournalStore
from src.desktop.conversations import ConversationError, ConversationStore
from src.desktop.events import EventJournal
from src.desktop.search import TranscriptSearch
from src.desktop.transcript import TranscriptStore
from src.search.errors import InvalidSearchQuery, SearchExecutionError


@pytest.fixture
def graph(tmp_path):
    store = JournalStore(tmp_path / "private" / "journal.sqlite", "testing")
    events = EventJournal(store, max_events=2)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    search = TranscriptSearch(transcript, events,
                              current_conversation=lambda request: request["bound"])
    yield store, events, conversations, transcript, search
    store.close()


def create(graph, title="Chat"):
    return graph[2].create(title=title)["conversation"]["id"]


def test_literal_search_all_owner_conversations_and_artifact_name(graph):
    _, events, _, transcript, search = graph
    a, b = create(graph, "A"), create(graph, "B")
    first = transcript.commit(a, "user", "Northern LIGHTS")
    second = transcript.commit(b, "assistant", "A northern night")
    artifact = transcript.commit(a, "assistant", "Delivered report", artifacts=[{
        "ref": "artifact-a", "name": "northern-lights.csv", "mime": "text/csv",
        "size": 20, "kind": "file", "available": True}])
    transcript.commit(b, "assistant", "unrelated")
    result = search.handle("search.query", {"query": "NORTHERN", "limit": 2})
    assert [hit["message_id"] for hit in result["hits"]] == [artifact["id"], second["id"]]
    assert result["next_cursor"] == "2"
    assert result["watermark"] == events.high
    tail = search.query({"query": "NORTHERN", "limit": 2, "cursor": "2"})
    assert [hit["message_id"] for hit in tail["hits"]] == [first["id"]]
    assert tail["next_cursor"] is None
    assert search.query({"query": "northern lights"})["hits"][0]["message_id"] == first["id"]
    assert len(search.query({"query": "northern", "conversation_id": a})["hits"]) == 2
    assert set(result["hits"][0]) == {
        "conversation_id", "message_id", "role", "snippet", "created_at"}


def test_literal_search_case_insensitive_substring_and_newest_first(graph):
    cid = create(graph)
    earlier = graph[3].commit(cid, "user", "prefix needle suffix")
    later = graph[3].commit(cid, "assistant", "NEEDLE again")
    result = graph[4].query({"query": "Needle"})
    assert [hit["message_id"] for hit in result["hits"]] == [later["id"], earlier["id"]]


def test_snippets_whitespace_context_and_max_page(graph):
    cid = create(graph)
    text = "left " * 30 + "needle\n\ncontext" + " right" * 30
    for _ in range(54):
        graph[3].commit(cid, "user", text)
    result = graph[4].query({"query": "needle", "limit": 50})
    assert len(result["hits"]) == 50
    assert result["next_cursor"] == "50"
    assert all(hit["snippet"].startswith("…") and hit["snippet"].endswith("…")
               and "needle context" in hit["snippet"] and "\n" not in hit["snippet"]
               for hit in result["hits"])


@pytest.mark.parametrize("params", [
    {}, {"query": ""}, {"query": "   "}, {"query": 13}, {"query": "bad\x00query"},
    {"query": "\ud800"}, {"query": "valid", "limit": True},
    {"query": "valid", "limit": 0}, {"query": "valid", "limit": 51},
    {"query": "valid", "cursor": "-1"}, {"query": "valid", "cursor": "bad"},
    {"query": "valid", "cursor": 1}, {"query": "valid", "cursor": "01"},
    {"query": "valid", "conversation_id": 14},
])
def test_malformed_query_and_paging_are_bad_request_never_empty(graph, params):
    with pytest.raises(ConversationError) as failure:
        graph[4].handle("search.query", params)
    assert failure.value.code == "bad_request"


def test_literal_fts_punctuation_is_not_an_operator_or_error(graph):
    cid = create(graph)
    graph[3].commit(cid, "user", "Quoted \"word\" and OR NEAR( strings")
    assert len(graph[4].query({"query": "OR NEAR("})["hits"]) == 1
    assert graph[4].query({"query": "absent"})["hits"] == []


def test_around_is_chronological_with_exact_bounds_and_foreign_hit_refusal(graph):
    cid, foreign = create(graph), create(graph)
    messages = [graph[3].commit(cid, "user", f"message {number}") for number in range(106)]
    result = graph[4].around({"conversation_id": cid, "message_id": messages[52]["id"],
                              "before": 50, "after": 50})
    assert [message["id"] for message in result["items"]] == [
        message["id"] for message in messages[2:103]]
    assert result["has_before"] and result["has_after"]
    assert all("conversation_id" not in message and "position" not in message
               for message in result["items"])
    solo = graph[4].around({"conversation_id": cid, "message_id": messages[0]["id"],
                           "before": 0, "after": 0})
    assert [message["id"] for message in solo["items"]] == [messages[0]["id"]]
    assert not solo["has_before"] and solo["has_after"]
    for target in [foreign, "absent"]:
        with pytest.raises(ConversationError) as failure:
            graph[4].around({"conversation_id": target, "message_id": messages[52]["id"]})
        assert failure.value.code == "not_found"


def test_around_matches_public_payload_but_scrubs_derived_views(graph, monkeypatch):
    cid = create(graph)
    marker = "test-secret-marker"
    monkeypatch.setattr("src.desktop.search.scrub_output_secrets",
                        lambda value: value.replace(marker, "[REDACTED]"))
    message = graph[3].commit(cid, "assistant", f"visible {marker}", artifacts=[{
        "ref": "report", "name": f"report-{marker}.txt", "mime": "text/plain", "size": 1,
        "kind": "file", "available": True}])
    listed = graph[3].list(cid)["items"]
    snapshot = graph[3].snapshot(cid)["messages"]["items"]
    around = graph[4].around({"conversation_id": cid, "message_id": message["id"],
                              "before": 0, "after": 0})["items"]
    assert around == listed == snapshot
    assert marker in around[0]["text"]
    assert marker in around[0]["artifacts"][0]["name"]
    assert marker not in graph[4].query({"query": "visible"})["hits"][0]["snippet"]
    history = " ".join(asyncio.run(graph[4].read_visible_history({"bound": cid})))
    assert marker not in history


@pytest.mark.parametrize("extra", [
    {"before": -1}, {"after": 51}, {"before": "1"}, {"after": False}])
def test_around_invalid_bounds_rejected(graph, extra):
    with pytest.raises(ConversationError) as failure:
        graph[4].around({"conversation_id": "a", "message_id": "m", **extra})
    assert failure.value.code == "bad_request"


def test_redaction_before_search_snippet_and_around(graph):
    cid = create(graph)
    message = graph[3].commit(
        cid, "assistant", "visible password=short and retained explanation", artifacts=[{
            "ref": "report", "name": "password=short", "mime": "text/plain", "size": 1,
            "kind": "file", "available": True}])
    search = graph[4]
    assert search.query({"query": "short"})["hits"] == []
    hit = search.query({"query": "visible"})["hits"][0]
    assert "short" not in hit["snippet"] and "[REDACTED]" in hit["snippet"]
    result = search.around({"conversation_id": cid, "message_id": message["id"]})
    assert "short" in result["items"][0]["text"]
    assert "short" not in search.query({"query": "visible"})["hits"][0]["snippet"]


def test_deleted_transcript_disappears_from_search_and_old_cursor(graph):
    a, b = create(graph), create(graph)
    graph[3].commit(a, "user", "needle in a")
    graph[3].commit(b, "user", "needle in b")
    cursor = graph[4].query({"query": "needle", "limit": 1})["next_cursor"]
    graph[2].delete(b, graph[2].get(b)["rev"])
    assert {hit["conversation_id"] for hit in graph[4].query({"query": "needle"})["hits"]} == {a}
    assert graph[4].query({"query": "needle", "cursor": cursor})["hits"] == []
    with pytest.raises(ConversationError) as failure:
        graph[4].query({"query": "needle", "conversation_id": b})
    assert failure.value.code == "not_found"


def test_rolled_back_transcript_and_events_do_not_become_searchable(graph):
    cid = create(graph)
    high = graph[1].high
    with pytest.raises(RuntimeError):
        with graph[0].transaction():
            graph[3].commit(cid, "assistant", "uncommitted needle")
            raise RuntimeError("harmless transaction rollback")
    assert graph[4].query({"query": "needle"}) == {
        "hits": [], "next_cursor": None, "watermark": high}


def test_not_found_read_does_not_poison_outer_durable_receipt(graph):
    def handler():
        try:
            graph[4].query({"query": "needle", "conversation_id": "missing"})
        except ConversationError as error:
            return error.response()
        pytest.fail("Missing conversation unexpectedly found")

    commands = CommandJournal(graph[0])
    response = commands.execute("nested-search", "example.command", {}, handler)
    assert response["error"]["code"] == "not_found"
    assert commands.check("nested-search", "example.command", {}) == response


def test_model_limits_are_bounded_and_read_is_chronological(graph):
    cid = create(graph)
    for number in range(30):
        graph[3].commit(cid, "user", f"needle number {number}")
    bound = graph[4].for_request({"bound": cid})
    assert len(asyncio.run(bound.search_history("needle", limit=20))) == 20
    lines = asyncio.run(bound.read_conversation(limit=3))
    assert [line.rsplit(" ", 1)[-1] for line in lines] == ["27", "28", "29"]
    with pytest.raises(InvalidSearchQuery):
        asyncio.run(bound.search_history("needle", limit=21))
    with pytest.raises(ConversationError):
        asyncio.run(bound.read_conversation(limit=101))


def test_native_read_conversation_callback_is_bound_and_scrubbed(graph):
    from src.discord.native_tools.channel_ops import ChannelOpsTools

    cid, other = create(graph), create(graph)
    graph[3].commit(cid, "assistant", "current password=short explanation")
    graph[3].commit(other, "assistant", "foreign explanation")
    tools = ChannelOpsTools(read_visible_history=graph[4].read_visible_history)
    request = {"bound": cid}
    result = asyncio.run(tools._handle_read_conversation(request, {"limit": 1}))
    assert "1 messages read" in result
    assert "current" in result and "[REDACTED]" in result
    assert "short" not in result and "foreign" not in result
    refusal = asyncio.run(tools._handle_read_conversation(
        request, {"conversation_id": other, "limit": 1}))
    assert "Only 'limit' is accepted" in refusal
    assert "foreign explanation" not in refusal


def test_bound_model_search_spans_the_profile_without_a_selector(graph):
    a, b = create(graph), create(graph)
    graph[3].commit(a, "user", "alpha intervening beta")
    graph[3].commit(a, "assistant", "alpha only")
    graph[3].commit(b, "user", "alpha beta elsewhere")
    request = {"bound": a, "conversation_id": b}
    bound = graph[4].for_request(request)
    # Profile-scoped, as Odin searches every channel: each hit names its own conversation.
    results = asyncio.run(bound.search_history("alpha beta"))
    assert {(item["conversation_id"], item["content"]) for item in results} == {
        (a, "alpha intervening beta"), (b, "alpha beta elsewhere")}
    assert all(isinstance(item["timestamp"], float) for item in results)
    # Reading stays current-conversation only; neither surface takes a selector.
    lines = asyncio.run(bound.read_conversation(limit=1))
    assert len(lines) == 1 and "alpha only" in lines[0] and "elsewhere" not in str(lines)
    with pytest.raises(TypeError):
        asyncio.run(bound.read_conversation(conversation_id=b))
    with pytest.raises(TypeError):
        asyncio.run(bound.search_history("alpha", conversation_id=b))
    unbound = TranscriptSearch(graph[3], graph[1])
    with pytest.raises(PermissionError):
        asyncio.run(unbound.read_visible_history(request))
    with pytest.raises(PermissionError):
        asyncio.run(graph[4].read_visible_history(None))
    with pytest.raises(PermissionError):
        asyncio.run(unbound.search_history(request, "alpha"))
    with pytest.raises(InvalidSearchQuery):
        asyncio.run(bound.search_history("bad\x00query"))


def test_optional_semantic_rrf_uses_visible_profile_payload_not_index_payload(graph):
    cid, other = create(graph), create(graph)
    message = graph[3].commit(cid, "assistant", "a wise explanation")
    elsewhere = graph[3].commit(other, "assistant", "another wise explanation")
    stray = graph[3].commit(other, "assistant", "a stray wise note")
    calls = []

    async def semantic(scope, query, *, limit):
        calls.append((scope, query, limit))
        return [{"message_id": stray["id"], "conversation_id": cid},  # mislabelled: dropped
                {"message_id": message["id"], "conversation_id": cid,
                 "content": "untrusted password=short"},
                {"message_id": "deleted"}, {"message_id": message["id"]},
                {"message_id": elsewhere["id"], "conversation_id": other}]

    search = TranscriptSearch(graph[3], graph[1], current_conversation=lambda request: request,
                              semantic_search=semantic)
    results = asyncio.run(search.search_history(cid, "wisdom"))
    assert {(item["conversation_id"], item["content"]) for item in results} == {
        (cid, "a wise explanation"), (other, "another wise explanation")}
    assert "short" not in str(results)
    assert calls == [(None, "wisdom", 20)]


def test_profile_ranking_runs_off_the_event_loop(graph, monkeypatch):
    import threading

    from src.desktop import search as search_module

    cid = create(graph)
    graph[3].commit(cid, "user", "needle off the loop")
    released, waited = threading.Event(), []
    real = search_module._lexical_ranking

    def held(*args):
        # Only the event loop releases this; a blocked loop would time out here.
        waited.append(released.wait(timeout=5))
        return real(*args)

    monkeypatch.setattr(search_module, "_lexical_ranking", held)

    async def scenario():
        task = asyncio.create_task(graph[4].search_history({"bound": cid}, "needle"))
        await asyncio.sleep(0.05)
        released.set()
        return await task

    results = asyncio.run(scenario())
    assert waited == [True]
    assert [item["content"] for item in results] == ["needle off the loop"]


def test_semantic_await_deletion_discards_hit(graph):
    cid = create(graph)
    message = graph[3].commit(cid, "assistant", "visible needle")

    async def remove(scope, query, *, limit):
        # Profile-scoped retrieval; the requesting conversation is deleted meanwhile.
        assert scope is None
        graph[2].delete(cid, graph[2].get(cid)["rev"])
        return [{"message_id": message["id"]}]

    search = TranscriptSearch(graph[3], graph[1], current_conversation=lambda request: request,
                              semantic_search=remove)
    with pytest.raises(ConversationError) as failure:
        asyncio.run(search.search_history(cid, "needle"))
    assert failure.value.code == "not_found"


def test_hit_in_a_conversation_deleted_mid_search_is_dropped(graph):
    cid, other = create(graph), create(graph)
    graph[3].commit(cid, "assistant", "needle kept here")
    gone = graph[3].commit(other, "assistant", "needle about to go")

    async def remove_other(scope, query, *, limit):
        graph[2].delete(other, graph[2].get(other)["rev"])
        return [{"message_id": gone["id"], "conversation_id": other}]

    search = TranscriptSearch(graph[3], graph[1], current_conversation=lambda request: request,
                              semantic_search=remove_other)
    results = asyncio.run(search.search_history(cid, "needle"))
    assert [(item["conversation_id"], item["content"]) for item in results] == [
        (cid, "needle kept here")]


def test_fts_backend_failure_is_scrubbed_explicit_error(graph, monkeypatch):
    from src.search.fts import FullTextIndex

    cid = create(graph)
    graph[3].commit(cid, "user", "needle")

    def fail(self, *args, **kwargs):
        raise RuntimeError("private database path with password=short")

    monkeypatch.setattr(FullTextIndex, "search_sessions", fail)
    with pytest.raises(SearchExecutionError) as failure:
        asyncio.run(graph[4].search_history({"bound": cid}, "needle"))
    assert str(failure.value) == "Transcript search is unavailable"


def test_model_artifact_name_hits_return_name_and_read_history_is_scrubbed(graph):
    cid = create(graph)
    graph[3].commit(cid, "assistant", "delivered password=short", artifacts=[{
        "ref": "r", "name": "quarterly-report.txt", "mime": "text/plain",
        "size": 1, "kind": "file", "available": True}])
    result = asyncio.run(graph[4].search_history({"bound": cid}, "quarterly"))
    assert len(result) == 1 and "quarterly-report.txt" in result[0]["content"]
    assert "short" not in result[0]["content"]
    assert "short" not in str(asyncio.run(graph[4].read_visible_history({"bound": cid})))


def test_semantic_failure_and_request_rebinding_are_explicit_errors(graph):
    cid, other = create(graph), create(graph)
    graph[3].commit(cid, "assistant", "needle")
    request = {"bound": cid}

    async def failure(cid_, query, *, limit):
        raise RuntimeError("private diagnostic password=short")

    search = TranscriptSearch(graph[3], graph[1], current_conversation=lambda req: req["bound"],
                              semantic_search=failure)
    with pytest.raises(SearchExecutionError, match="^Transcript search is unavailable$"):
        asyncio.run(search.search_history(request, "needle"))

    async def rebind(cid_, query, *, limit):
        request["bound"] = other
        return []

    search.semantic_search = rebind
    with pytest.raises(PermissionError, match="context changed"):
        asyncio.run(search.search_history(request, "needle"))


def test_child_frozen_inheritance_does_not_alias_visible_history(graph):
    parent = create(graph)
    graph[3].commit(parent, "user", "inherited parent needle")
    child = graph[2].create(parent_id=parent)["conversation"]["id"]
    graph[3].commit(child, "assistant", "child local needle")
    graph[3].commit(parent, "assistant", "later parent needle")
    results = asyncio.run(graph[4].search_history({"bound": child}, "needle"))
    # Profile-scoped search returns the parent's messages under the parent,
    # never aliased as the child's own history.
    assert {(item["conversation_id"], item["content"]) for item in results} == {
        (child, "child local needle"), (parent, "inherited parent needle"),
        (parent, "later parent needle")}
    assert "parent" not in str(asyncio.run(graph[4].read_visible_history({"bound": child})))


def test_restart_context_reset_and_compaction_preserve_searchable_transcript(graph, tmp_path):
    from src.sessions.manager import Message, SessionManager

    cid = create(graph)
    graph[3].commit(cid, "user", "original durable needle")
    graph[3].commit(cid, "assistant", "original durable answer")
    sessions = SessionManager(4, 24, str(tmp_path / "model-sessions"), token_budget=100)
    session = sessions.get_or_create(cid)
    session.messages = [Message(role="user", content="long temporary context " * 100)
                        for _ in range(20)]
    sessions._fallback_compact(session)
    assert len(session.messages) < 20
    graph[2].reset_context(cid, graph[2].get(cid)["rev"])
    graph[0].close()
    reopened = JournalStore(tmp_path / "private" / "journal.sqlite", "testing")
    try:
        events = EventJournal(reopened)
        conversations = ConversationStore(reopened, events)
        transcript = TranscriptStore(reopened, events, conversations)
        search = TranscriptSearch(transcript, events)
        hits = search.query({"query": "durable"})["hits"]
        assert len(hits) == 2
        assert {hit["snippet"] for hit in hits} == {
            "original durable needle", "original durable answer"}
    finally:
        reopened.close()
