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

if case == "services-real-shape":
    # Render/AX fixture only, not evidence of a real service. The separate Broker
    # gate exercises these envelopes against python -m src and a real stdio child.
    original_mcp = fixture.METHODS["mcp.status"]
    original_health = fixture.METHODS["health.get"]

    def mcp_status(core, params, writer):
        result = original_mcp(core, params, writer)
        result["revision"] = "a11y-real-shape-revision"
        result["servers"].append({
            "name": "locked-local", "transport": "stdio", "enabled": True,
            "state": "unavailable", "last_error": "Profile keyring is unavailable or locked",
            "blocked_reason": "", "discovered_count": 0, "published_count": 0,
            "excluded_count": 0, "published_tools": [], "original_tools": [],
            "header_keys": [], "env_keys": [], "url_display": None,
        })
        return result

    def computer_status(core, params, writer):
        return {"session": None, "readiness": {
            "management_available": True, "foreground_available": False,
            "native_qualified": False, "input_supported": False, "dispatch": "none",
            "reason": "foreground_binding_and_native_qualification_pending",
        }}

    def health(core, params, writer):
        result = original_health(core, params, writer)
        result["browser"] = {"state": "unavailable", "ready": False,
                             "reason": "Packaged browser is absent", "retry_available": True}
        return result

    fixture.METHODS.update({"mcp.status": mcp_status, "computer.status": computer_status,
                            "health.get": health})
sys.exit(asyncio.run(fixture.main()))
