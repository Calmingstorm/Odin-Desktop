"""Runtime projection preserves ingress observations without inventing readiness."""
from types import SimpleNamespace

from tests.test_desktop_runtime import make_service


def test_absent_ingress_is_explicitly_unavailable(tmp_path):
    status = make_service(tmp_path).status()
    assert status["webhook_ingress"] == {
        "reason": "unavailable", "address": None,
        "eligible_schedules": 0, "unknown_deliveries": 0,
    }


def test_runtime_projects_actual_ingress_status_not_enabled_setting(tmp_path):
    service = make_service(tmp_path)
    observed = {"reason": "not_bound", "address": None,
                "eligible_schedules": 1, "unknown_deliveries": 2}
    service.core.webhooks = SimpleNamespace(status=lambda: dict(observed))
    service.config.webhook = SimpleNamespace(enabled=True)
    assert service.status()["webhook_ingress"] == observed
    assert "Webhook ingress: not_bound" in service.status()["summary"]
    observed.update(reason="accepting", address=("127.0.0.1", 45678))
    accepting = service.status()["webhook_ingress"]
    assert accepting["reason"] == "accepting"
    assert list(accepting["address"]) == ["127.0.0.1", 45678]
    observed.update(reason="no_eligible_schedule", address=None, eligible_schedules=0)
    assert service.status()["webhook_ingress"] == observed
