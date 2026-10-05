"""D12 planning only. Execution remains in the retained Scheduler."""
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
from croniter import croniter


def recover_due(schedule: dict, now: datetime, *, grace_seconds: int = 60,
                count_limit: int = 128) -> bool:
    """Consume missed effects; reminders coalesce into one bounded notice.

    Workflow catch-up execution is bounded at zero: D12 missed actions wait
    for explicit run. Slot counting is bounded even after years of downtime.
    """
    due_value = schedule.get("next_run")
    if not due_value or schedule.get("retry_at") or schedule.get("paused"):
        return False
    try:
        due = datetime.fromisoformat(due_value).astimezone(UTC)
    except (ValueError, TypeError):
        return False
    if now - due <= timedelta(seconds=grace_seconds):
        schedule.pop("missed_run", None)
        return False
    count, truncated = 1, False
    cron = schedule.get("cron")
    if cron:
        zone = ZoneInfo(schedule.get("timezone") or "UTC")
        iterator = croniter(cron, due.astimezone(zone))
        while count < count_limit:
            if iterator.get_next(datetime).astimezone(UTC) > now:
                break
            count += 1
        else:
            truncated = iterator.get_next(datetime).astimezone(UTC) <= now
    schedule["missed_run"] = {
        "due_at": due.isoformat(), "observed_at": now.isoformat(),
        "lateness_seconds": int((now - due).total_seconds()),
        "missed_count": count, "omitted_count": max(0, count - 1),
        "count_truncated": truncated,
        "policy": "coalesced" if schedule.get("action") == "reminder" else "manual",
        "workflow_catchup_limit": 0,
    }
    if schedule.get("action") == "reminder":
        return False
    schedule["recovery_required"] = "Missed action; run explicitly. No effects were replayed."
    if cron:
        schedule["next_run"] = croniter(cron, now.astimezone(zone)).get_next(datetime).astimezone(UTC).isoformat()
    else:
        schedule.pop("next_run", None)
    return True
