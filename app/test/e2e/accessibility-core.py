"""E2E-only adversarial/delayed fixture; ordinary fixture behavior remains unchanged."""
import asyncio
import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location("fixture", Path(__file__).parents[2] / "fixture-core/fixture_core.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
case = sys.argv.pop(1)


class AccessibilityCore(fixture.Core):
    def __init__(self, *args):
        super().__init__(*args)
        if case == "history":
            conv = self.m_conv_create({"title": "History keyboard fixture"}, None)["conversation"]
            cid = conv["id"]
            for n in range(130):
                self.commit_message(cid, {"id": f"history-{n}", "role": "assistant",
                                         "text": f"History anchor {n}", "created_at": fixture.now()}, unread=False)
        if case == "work-settlement":
            self.work["fixture-unknown-settlement"] = {
                "kind": "agent", "id": "fixture-unknown-settlement", "title": "Unknown release audit",
                "state": "completed", "detail": {"exit_code": 0, "result": "done"},
                "settlement": {"state": "unknown", "resource_release": "unproven",
                               "remote_effects": "unknown", "unsettled_descendants": 0},
                "actions": ["steer"],
            }

    def dispatch(self, writer, frame):
        # Real transport response delay, not a mocked renderer or simulated focus.
        if case == "history" and frame.get("method") in {"messages.list", "conversation.snapshot", "search.query"}:
            asyncio.get_running_loop().call_later(0.7, super().dispatch, writer, frame)
        else:
            super().dispatch(writer, frame)

    async def run_request(self, req):
        # The app must ignore every uncommitted draft event, including rejected content.
        self.emit("message.draft", "request", req["id"], {
            "conversation_id": req["conversation_id"], "request_id": req["id"],
            "message": {"id": "rejected-draft", "role": "assistant", "text": "UNPUBLISHED_REJECTED_A11Y_DRAFT"}
        })
        await super().run_request(req)


fixture.Core = AccessibilityCore
sys.exit(asyncio.run(fixture.main()))
