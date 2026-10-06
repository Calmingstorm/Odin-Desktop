"""Scheduling-domain native tool handlers (RFC-001 Phase 5b).

Verbatim moves from OdinBot. The class exposes its dependencies under the
same attribute names the methods historically used on the bot, so bodies
are unchanged; the bot keeps one-line delegates for the dispatch table's
late-bound host resolution and the test patch seam.
"""

from __future__ import annotations

from ...odin_log import get_logger
from ...scheduler.scheduler import ScheduleConnectionUnavailableError
from ...tools.nested_payload import ValidatedNestedPayload, validate_nested_payload

log = get_logger("discord")


class SchedulingTools:
    def __init__(self, *, scheduler, tool_catalog=None, service_provider=None,
                 request_provider=None) -> None:
        self.scheduler = scheduler
        self.tool_catalog = tool_catalog
        self.service_provider, self.request_provider = service_provider, request_provider

    def _admitted_service(self, message=None):
        if self.service_provider is None or self.request_provider is None:
            raise RuntimeError("Phase 2 scheduled destination admission unavailable")
        request = self.request_provider(message)
        return self.service_provider(), request

    # -- creation-time validation ---------------------------------------------

    def _validate_schedule_payload(self, inp: dict) -> str | None:
        """Validate schedule_task input at creation time, not fire time.

        Catches the class of LLM mistake where a 'check' action is queued
        with no tool_input, or a 'workflow' step is missing tool_input —
        those errors used to surface only at fire time as a crashing
        coroutine, hours or days later. Returning a specific message
        at creation makes the LLM retry with a complete payload.
        """
        action = inp.get("action", "reminder")
        if action == "reminder":
            if not inp.get("message"):
                return "action=reminder requires a non-empty 'message'."
        elif action == "check":
            tool_name = inp.get("tool_name")
            if not tool_name:
                if inp.get("command"):
                    inp["tool_name"] = "run_command"
                    tool_name = "run_command"
                else:
                    return "action=check requires 'tool_name'."
            tool_input = inp.get("tool_input")
            if tool_input is None or (isinstance(tool_input, dict) and not tool_input):
                shortcut_cmd = inp.get("command")
                if shortcut_cmd and tool_name == "run_command":
                    tool_input = {"command": shortcut_cmd}
                    if inp.get("host"):
                        tool_input["host"] = inp["host"]
                    inp["tool_input"] = tool_input
                else:
                    tool_input = self._extract_tool_input_from_steps(inp)
                    if tool_input:
                        inp["tool_input"] = tool_input
                    else:
                        return (
                            f"action=check with tool_name='{tool_name}' requires 'tool_input' "
                            f"populated with the parameters that tool expects, OR use the "
                            f"'command' shortcut field directly "
                            f"(e.g. schedule_task(action='check', command='uname -r'))."
                        )
        elif action == "workflow":
            steps = inp.get("steps")
            if not steps or not isinstance(steps, list):
                return "action=workflow requires a non-empty 'steps' array."
            for i, step in enumerate(steps, 1):
                if not isinstance(step, dict):
                    return f"workflow step {i} must be an object."
                if not step.get("tool_name"):
                    return f"workflow step {i} is missing 'tool_name'."
                step_input = step.get("tool_input")
                if step.get("tool_name") in ("run_command", "run_script"):
                    if not isinstance(step_input, dict) or not step_input:
                        return (
                            f"workflow step {i} ({step['tool_name']}) requires a non-empty "
                            f"'tool_input' dict — for run_command include 'command', "
                            f"for run_script include 'script'."
                        )
        return None

    @staticmethod
    def _extract_tool_input_from_steps(inp: dict) -> dict | None:
        """Graceful fallback: gpt-5.4 consistently puts command params in
        steps[].tool_input but omits top-level tool_input for action=check.
        If steps has exactly one entry with a populated tool_input, use it."""
        steps = inp.get("steps")
        if not steps or not isinstance(steps, list):
            return None
        populated = [
            s
            for s in steps
            if isinstance(s, dict) and isinstance(s.get("tool_input"), dict) and s["tool_input"]
        ]
        if len(populated) == 1:
            return populated[0]["tool_input"]
        return None

    # -- handlers ----------------------------------------------------------------

    async def _handle_schedule_task(self, message, inp: dict) -> str:
        """Create a scheduled task."""
        service, message = self._admitted_service(message)
        # Codex inputs arrive already decoded and checked by RequestToolAdapter.
        # Other providers keep the historical schedule input behavior.
        nested_validated = isinstance(inp, ValidatedNestedPayload)
        validation_error = self._validate_schedule_payload(inp)
        if validation_error:
            return f"Failed to create schedule: {validation_error}"
        try:
            values = dict(
                description=inp.get("description", "Unnamed task"),
                action=inp.get("action", "reminder"),
                channel_id=message.conversation_id,
                cron=inp.get("cron"),
                run_at=inp.get("run_at"),
                message=inp.get("message"),
                tool_name=inp.get("tool_name"),
                tool_input=inp.get("tool_input"),
                steps=inp.get("steps"),
                trigger=inp.get("trigger"),
                cron_timezone=inp.get("cron_timezone"),
                report_format=inp.get("report_format"),
            )
            schedule = await service.for_request("schedules.save",
                {k: v for k, v in values.items() if v is not None}, message,
                nested_payload_validated=nested_validated)
            if schedule.get("trigger"):
                trigger_desc = ", ".join(f"{k}={v}" for k, v in schedule["trigger"].items())
                return (
                    f"Scheduled webhook-triggered task (ID: {schedule['id']}): "
                    f"{schedule['description']}. Trigger: {trigger_desc}"
                )
            next_run = schedule.get("next_run", "unknown")
            stype = "recurring" if schedule.get("cron") else "one-time"
            return (
                f"Scheduled {stype} task (ID: {schedule['id']}): "
                f"{schedule['description']}. Next run: {next_run}"
            )
        except ScheduleConnectionUnavailableError as e:
            return f"Scheduling unavailable: {e}"
        except ValueError as e:
            return f"Failed to create schedule: {e}"
        except Exception as e:
            return f"Error creating schedule: {e}"

    def _handle_list_schedules(self) -> str:
        """List all scheduled tasks."""
        service, message = self._admitted_service()
        service.assert_request(message)
        schedules = [
            s for s in self.scheduler.list_all()
            if s.get("requester_id") == message.owner_id
        ]
        if not schedules:
            return "No scheduled tasks."
        lines = []
        for s in schedules:
            if s.get("trigger"):
                trigger_desc = ", ".join(f"{k}={v}" for k, v in s["trigger"].items())
                stype = f"trigger: {trigger_desc}"
            elif s.get("cron"):
                stype = f"cron `{s['cron']}`"
            else:
                stype = "one-time"
            next_run = s.get("next_run", "on trigger" if s.get("trigger") else "N/A")
            last_run = s.get("last_run", "never")
            paused_tag = " **[PAUSED]**" if s.get("paused") else ""
            inert_reason = f" | inert: {s['inert_reason']}" if s.get("inert_reason") else ""
            lines.append(
                f"- **{s['id']}**: {s['description']} ({stype}){paused_tag} "
                f"| next: {next_run} | last: {last_run}{inert_reason}"
            )
        return f"**Scheduled tasks ({len(schedules)}):**\n" + "\n".join(lines)

    async def _handle_update_schedule(self, inp: dict) -> str:
        """Update an existing schedule."""
        service, message = self._admitted_service()
        nested_validated = isinstance(inp, ValidatedNestedPayload)
        if (
            nested_validated
            and isinstance(inp.get("tool_input"), dict)
            and not inp.get("tool_name")
        ):
            current = next(
                (s for s in self.scheduler.list_all() if s.get("id") == inp.get("schedule_id")),
                None,
            )
            target_name = (current or {}).get("tool_name")
            if target_name:
                try:
                    validate_nested_payload(
                        "schedule_task",
                        {
                            "action": "check",
                            "tool_name": target_name,
                            "tool_input": inp["tool_input"],
                        },
                        self._nested_catalog(),
                    )
                except ValueError as e:
                    return f"Error: {e}"
        schedule_id = inp.get("schedule_id", "")
        if not schedule_id:
            return "Error: 'schedule_id' is required."
        kwargs = {}
        for key in (
            "description",
            "cron",
            "run_at",
            "message",
            "tool_name",
            "tool_input",
            "steps",
            "conversation_id",
            "channel_id",
            "cron_timezone",
            "report_format",
            "max_retries",
            "retry_backoff_seconds",
            "webhook_config",
        ):
            if key in inp:
                kwargs[key] = inp[key]
        trigger = inp.get("trigger")
        if trigger is not None:
            kwargs["trigger"] = trigger
        if "paused" in inp:
            val = inp["paused"]
            if not isinstance(val, bool):
                return "Error: 'paused' must be a boolean (true/false)."
            kwargs["paused"] = val
        if not kwargs:
            return "Error: no fields to update."
        # Updating a legacy schedule's description/format must not retroactively
        # mark its old, never-validated workflow steps as adapter-validated.
        if "conversation_id" in kwargs:
            kwargs["channel_id"] = kwargs.pop("conversation_id")
        try:
            result = await service.for_request(
                "schedules.save", {"id": schedule_id, **kwargs}, message,
                nested_payload_validated=(
                    nested_validated and ("steps" in kwargs or "tool_input" in kwargs)
                ),
            )
        except ScheduleConnectionUnavailableError as e:
            return f"Scheduling unavailable: {e}"
        except ValueError as e:
            if getattr(e, "code", None) == "not_found":
                return f"Schedule {schedule_id} not found."
            return f"Error: {e}"
        if result is None:
            return f"Schedule {schedule_id} not found."
        if result.get("inert_reason"):
            return f"Schedule {schedule_id} remains paused and inert: {result['inert_reason']}"
        return f"Updated schedule {schedule_id}."

    def _nested_catalog(self):
        """Canonical tool definitions for selected target validation."""
        catalog = getattr(self, "tool_catalog", None)
        if catalog is not None:
            return catalog.merged_definitions()
        # ToolExecutor is available via the scheduler handler owner in production;
        # static definitions still validate direct unit/legacy entry points.
        from ...tools.registry import get_tool_definitions

        return get_tool_definitions()

    async def _handle_delete_schedule(self, inp: dict) -> str:
        """Delete a scheduled task."""
        service, message = self._admitted_service()
        schedule_id = inp.get("schedule_id", "")
        if await service.for_request("schedules.delete", {"id": schedule_id}, message):
            return f"Deleted schedule {schedule_id}."
        return f"Schedule {schedule_id} not found."

    def _handle_parse_time(self, inp: dict) -> str:
        """Parse a natural language time expression to ISO datetime."""
        expression = inp.get("expression", "")
        if not expression:
            return "Error: 'expression' is required (e.g. 'in 2 hours', 'tomorrow at 9am')"
        from ...tools.time_parser import parse_time

        try:
            result = parse_time(expression)
            return f"Parsed '{expression}' → {result}"
        except ValueError as e:
            return f"Error: {e}"
