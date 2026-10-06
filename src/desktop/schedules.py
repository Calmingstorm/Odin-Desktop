"""Authenticated protocol schedules domain composed with Odin's scheduler."""
from datetime import UTC, datetime

from croniter import croniter

from .conversations import ConversationError

CREATE_FIELDS = frozenset({"description", "action", "channel_id", "cron", "run_at",
    "cron_timezone", "message", "tool_name", "tool_input", "report_format", "steps",
    "trigger", "webhook_config", "max_retries", "retry_backoff_seconds"})
UPDATE_FIELDS = (CREATE_FIELDS - {"action"}) | {"paused"}


class ScheduleService:
    """No payload requester identity or web token is owner authority."""
    methods = frozenset({"schedules.list", "schedules.save", "schedules.delete",
        "schedules.run", "schedules.reset_failures", "schedules.history",
        "schedules.validate_cron"})

    def __init__(self, scheduler, *, authority, conversations, assert_request=None):
        self.scheduler, self.authority = scheduler, authority
        self.conversations, self.assert_request = conversations, assert_request
        self.ingress = None

    def _owned(self, id, owner_id):
        for item in self.scheduler.list_all():
            if item["id"] == id:
                if item.get("requester_id") != owner_id:
                    raise PermissionError("Schedule belongs to another owner")
                return item
        raise ConversationError("not_found", "Schedule not found")

    def _destination(self, value):
        if type(value) is not str or not value:
            raise ValueError("channel_id must name an existing conversation")
        self.conversations.get(value)
        return value

    async def recover(self):
        """Persist constructor reconciliation before callback/loop activation."""
        async with self.scheduler._lock:
            await self.scheduler._publish(self.scheduler.list_all())

    async def invoke(self, method, params, *, owner, nested_payload_validated=False):
        if not self.authority.accepts(owner):
            raise PermissionError("Authenticated profile owner required")
        owner_id = owner.owner_id
        if method not in self.methods or type(params) is not dict:
            raise ValueError("Unknown schedule method or invalid parameters")
        if method == "schedules.list":
            return [s for s in self.scheduler.list_all() if s.get("requester_id") == owner_id]
        if method == "schedules.validate_cron":
            expression = params.get("expression", "")
            if not isinstance(expression, str) or not croniter.is_valid(expression):
                return {"valid": False, "next_runs": []}
            iterator = croniter(expression, datetime.now(UTC))
            return {"valid": True, "next_runs": [iterator.get_next(datetime).isoformat()
                                                for _ in range(5)]}
        if method == "schedules.history":
            id = params.get("id")
            if id and type(id) is not str:
                raise ValueError("id must be a string")
            limit = params.get("limit", 50)
            if type(limit) is not int or not 1 <= limit <= 200:
                raise ValueError("limit must be between 1 and 200")
            entries = await self.scheduler.history.query(id, limit=limit)
            return [entry for entry in entries if
                entry.get("run_binding", {}).get("owner_id") == owner_id]
        id = params.get("id")
        if method == "schedules.save":
            values = dict(params)
            values.pop("id", None)
            if id:
                current = self._owned(id, owner_id)
                if "action" in values and values.pop("action") != current["action"]:
                    raise ValueError("action cannot be changed")
                allowed = UPDATE_FIELDS
            else:
                allowed = CREATE_FIELDS
                if (not isinstance(values.get("description"), str)
                        or not values["description"].strip()):
                    raise ValueError("description is required")
                values["description"] = values["description"].strip()
                values.setdefault("action", "reminder")
                if values["action"] not in {"reminder", "check", "workflow", "webhook", "digest"}:
                    raise ValueError("Invalid schedule action")
            if values.keys() - allowed:
                raise ValueError("Unsupported schedule fields")
            if "paused" in values and type(values["paused"]) is not bool:
                raise ValueError("paused must be boolean")
            for key in ("max_retries", "retry_backoff_seconds"):
                if key in values and type(values[key]) is not int:
                    raise ValueError(f"{key} must be integer")
            if "run_at" in values:
                instant = datetime.fromisoformat(values["run_at"])
                if instant.tzinfo is None or instant <= datetime.now(UTC):
                    raise ValueError("run_at must be offset-aware and in the future")
            if "channel_id" in values or not id:
                values["channel_id"] = self._destination(values.get("channel_id"))
            if id:
                result = await self.scheduler.update(
                    id, nested_payload_validated=nested_payload_validated, **values)
            else:
                result = await self.scheduler.add(requester_id=owner_id,
                    nested_payload_validated=nested_payload_validated, **values)
            if self.ingress is not None:
                await self.ingress.sync()
            return result
        self._owned(id, owner_id)
        if method == "schedules.delete":
            await self.scheduler.delete(id)
            if self.ingress is not None:
                await self.ingress.sync()
            return {"status": "deleted"}
        if method == "schedules.run":
            return await self.scheduler.run_now(id)
        return await self.scheduler.reset_failures(id)

    async def for_request(self, method, params, message, *, nested_payload_validated=False):
        if self.assert_request is None:
            raise PermissionError("Request admission unavailable")
        self.assert_request(message)
        owner = self.authority.authenticate_local(peer_uid=self.authority.owner_uid)
        if message.owner_id != owner.owner_id:
            raise PermissionError("Foreign request owner")
        return await self.invoke(method, params, owner=owner,
                                 nested_payload_validated=nested_payload_validated)
