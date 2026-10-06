"""Selected inherited webhook obligations, not a replacement ingress test suite."""
from __future__ import annotations

import ast
import hashlib

import pytest

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from src.config.schema import set_active_config_path
from tests.desktop_adapters.webhook_cases import (
    CASE_MAP,
    EVIDENCE,
    SELECTIONS,
    SOURCE_SHA256,
    export_cases,
    verified_tree,
)
from tests.desktop_adapters.webhook_ingress import _fixtures


@pytest.fixture(autouse=True)
async def isolate_config_transaction_state(tmp_path, monkeypatch):
    # The retained lock implementation uses tempfile.gettempdir(). Keep its
    # lock directory as well as config bytes in this case's temporary profile.
    import tempfile
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    state = {"root": tmp_path, "servers": []}
    token = _fixtures.set(state)
    set_active_config_path(None)
    try:
        yield
    finally:
        for server in state["servers"]:
            await server.close()
        _fixtures.reset(token)
        set_active_config_path(None)


for _stem in SELECTIONS:
    export_cases(globals(), _stem)


@pytest.mark.parametrize("stem", list(SELECTIONS))
def test_webhook_complete_source_and_ast_sealed_before_selection(stem):
    source = frozen_source(f"tests/{stem}.py")
    original = ast.parse(source)
    adapted = verified_tree(stem)
    assert hashlib.sha256(source).hexdigest() == SOURCE_SHA256[stem]
    assert corpus(original) == corpus(adapted)
    edits = EVIDENCE[f"tests/{stem}.py"]["setup_edits"]
    if stem == "test_github_webhook":
        assert len(edits) == 1
        assert edits[0]["symbol"] == "_make_server"
        # Independently restrict the complete AST delta to this one helper
        # body. Inherited test bodies and their literal data remain identical.
        before = next(n for n in original.body if getattr(n, "name", "") == "_make_server")
        after = next(n for n in adapted.body if getattr(n, "name", "") == "_make_server")
        assert hashlib.sha256(dump(before).encode()).hexdigest() == edits[0]["before_sha256"]
        assert hashlib.sha256(dump(after).encode()).hexdigest() == edits[0]["after_sha256"]
        before.body = ast.parse("return desktop_make_server(secret=secret, "
                               "channel_id=channel_id, github_channel_id=github_channel_id)").body
    else:
        assert edits == []
    assert dump(original) == dump(adapted)


def test_webhook_projection_resolves_each_exact_original_case_once():
    assert len(CASE_MAP.values()) == len(set(CASE_MAP.values()))
    for stem, selected in SELECTIONS.items():
        if selected is not None:
            assert {key.removeprefix(f"tests/{stem}.py::") for key in CASE_MAP
                    if key.startswith(f"tests/{stem}.py::")} == set(selected)


async def test_inherited_capture_observes_real_durable_ingress_and_scheduler():
    import hmac
    import json

    from aiohttp.test_utils import TestClient, TestServer

    from tests.desktop_adapters.webhook_ingress import make_server

    server = make_server(secret="temporary-inherited-key", channel_id="999")
    seen = []

    async def observe(channel, text):
        seen.append((channel, text))

    server.set_send_message(observe)
    body = json.dumps({"repository": {"full_name": "acme/widget"},
                       "pusher": {"name": "alice"}, "commits": [],
                       "ref": "refs/heads/main"}).encode()
    signature = hmac.new(b"temporary-inherited-key", body, hashlib.sha256).hexdigest()
    async with TestClient(TestServer(server._app)) as client:
        response = await client.post("/webhook/github", data=body, headers={
            "X-Hub-Signature-256": "sha256=" + signature,
            "X-GitHub-Event": "push", "Content-Type": "application/json"})
        assert response.status == 200
        assert await response.json() == {"status": "delivered"}
    schedule = server.scheduler.list_all()[0]
    messages = server.transcript.list(server.cid)["items"]
    receipts = server.store.connection.execute(
        "SELECT schedule_id,destination,source,state,run_binding FROM desktop_webhook_receipts"
    ).fetchall()
    assert len(messages) == len(receipts) == len(server.executions) == 1
    assert server.executions == [schedule["id"]]
    assert seen == [("999", messages[0]["text"])]
    assert receipts[0][:4] == (schedule["id"], server.cid, "github", "delivered")
    assert json.loads(receipts[0][4])["conversation_id"] == server.cid
    assert messages[0]["id"].startswith("m_wh_")
    assert schedule["settlement"] == "success"
