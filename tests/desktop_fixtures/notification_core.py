"""Fixture-only conversation/ack service. NOT a real-core delivery proof.

The step-one real core has no notification/conversation services. Qualification
methods are deliberately absent from production core and renderer IPC.
"""
import asyncio
import importlib.util
import sys
from pathlib import Path

from private_notification_server import assert_isolated

assert_isolated()
source = Path(__file__).resolve().parents[2] / "app/fixture-core/fixture_core.py"
spec = importlib.util.spec_from_file_location("notification_fixture_core", source)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class NotificationCore(fixture.Core):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.read_receipts = []
        seeded = [("notify-main", "Notification target"), ("notify-other", "Other conversation")]
        for cid, title in seeded:
            self.conversations[cid] = {"id": cid, "title": title, "rev": 1, "parent_id": None,
                                       "updated_at": fixture.now(), "unread": 7, "archived": False}
            self.messages[cid] = [
                {"id": f"{cid}-{i}", "role": "assistant", "text": f"Committed fixture history {i}",
                 "created_at": fixture.now()} for i in range(120)
            ]

    def qualification(self, _params, _writer):
        return {
            "acks": dict(self.notification_acks), "reads": list(self.read_receipts),
            "fixture_only": True,
        }

    def mark_read(self, params, writer):
        result = super().m_conv_mark_read(params, writer)
        self.read_receipts.append(dict(params))
        return result


fixture.Core = NotificationCore
fixture.METHODS["notification.qualification"] = NotificationCore.qualification
fixture.READ_METHODS.add("notification.qualification")
fixture.NO_RECEIPT_METHODS.add("notification.qualification")
fixture.METHODS["conversations.mark_read"] = NotificationCore.mark_read
sys.exit(asyncio.run(fixture.main()))
