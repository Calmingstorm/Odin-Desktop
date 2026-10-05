"""Retained attachment and execution orchestration at its upstream path.

Admission, task-owned delivery and control wiring belong to Phase 2. Entry
points fail before message inspection, attachment IO, session mutation or
provider/tool execution. Shared attachment retention, branch context, tool
handoff, accounting and reflection remain here for the real adapter to reuse;
there is no transport facade or implicit owner authority.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..async_utils import fire_and_forget
from ..error_presentation import format_user_facing_error
from ..odin_log import get_logger
from ..sessions.manager import CHAT_RESPONSE_MAX_CHARS, summarize_tool_response
from .response_guards import scrub_response_secrets

if TYPE_CHECKING:
    from ..permissions.manager import PermissionManager
    from ..sessions.manager import SessionManager
    from .channel_state import ChannelStateRegistry
    from .delivery import DeliveryService
    from .housekeeping import Housekeeping
    from .llm_gateway import LLMGateway
    from .prompts import PromptBuilder
    from .tool_loop import ToolLoopRunner
    from .turn_recorder import TurnRecorder
    from .turn_resume import TurnResumeManager

log = get_logger("intake")


class Phase2AdmissionRequiredError(RuntimeError):
    """No effect-capable ingress without authenticated durable admission."""


def _require_phase2_admission() -> None:
    raise Phase2AdmissionRequiredError(
        "Phase 2 authenticated owner/conversation admission, secret rejection, "
        "revision-bound request ownership and durable delivery are not wired"
    )


@dataclass(frozen=True)
class MessageIntakeDeps:
    """Dependencies of retained attachment processing, not a transport gateway."""

    get_config: Callable  # live root — replaced by config hot-reload
    sessions: SessionManager
    tool_executor: Any = None  # authorized full attachment output retention


class MessageIntake:
    def __init__(self, deps: MessageIntakeDeps) -> None:
        self._get_config = deps.get_config
        self._sessions = deps.sessions
        self._tool_executor = getattr(deps, "tool_executor", None)

    async def _process_attachments(
        self, message: Any, content: str = ""
    ) -> tuple[str, list[dict]]:
        """Process attachments via AttachmentProcessor.

        Returns (inline_text, image_blocks). Identity and retained-output
        authorization must come from Phase 2 admission before attachment IO.
        """
        _require_phase2_admission()
        if not message.attachments:
            return "", []

        from .attachments import AttachmentProcessor, infer_attachment_intent

        config = self._get_config()
        cfg = config.attachments if hasattr(config, "attachments") else None
        processor = AttachmentProcessor(
            **({"temp_dir": cfg.temp_directory,
                "inline_max_bytes": cfg.inline_text_max_bytes,
                "preview_max_chars": cfg.preview_max_chars,
                "large_preview_chars": cfg.large_preview_chars,
                "archive_max_bytes": cfg.archive_max_bytes,
                "archive_max_files": cfg.archive_max_files,
                "archive_extract_max_bytes": cfg.archive_extract_max_bytes,
                "archive_preview_total_chars": cfg.archive_preview_total_chars,
                "archive_preview_file_max_bytes": cfg.archive_preview_file_max_bytes,
                "image_max_bytes": cfg.image_max_bytes,
                "pdf_max_bytes": cfg.pdf_max_bytes,
                "retention_hours": cfg.retention_hours,
                } if cfg else {})
        )

        recent_assistant = None
        session = self._sessions.get(str(message.conversation_id))
        if session and session.messages:
            for m in reversed(session.messages):
                if m.role == "assistant":
                    recent_assistant = m.content
                    break

        intent = infer_attachment_intent(content, recent_assistant)

        result = await processor.process(
            message.attachments,
            conversation_id=str(message.conversation_id),
            request_id=str(message.request_id),
            intent=intent,
        )

        if result.warnings:
            for w in result.warnings:
                log.warning("Attachment warning: %s", w)

        text = result.inline_text
        retained = getattr(result, "retained_content", None)
        if retained and self._tool_executor is not None:
            try:
                manifest = self._tool_executor.retain_attachments(
                    retained, tool_name="get_tool_output", user_id=str(message.owner_id),
                    channel_id=str(message.conversation_id),
                )
                text += "\n[Full attachment contents, in labelled source order. "
                text += "Retrieve via the existing authorized get_tool_output path; "
                text += "decode and concatenate binary pages before ingestion.]\n"
                text += json.dumps(manifest)
            except Exception:
                log.exception("Attachment output retention failed")
                text += "\n[Full-content output retrieval unavailable; no cursor was issued.]"
        return text, result.image_blocks

    async def handle(self, message: Any) -> None:
        """Reject ingress until authenticated durable admission is implemented."""
        _require_phase2_admission()


@dataclass(frozen=True)
class MessagePipelineDeps:
    """The true dependency surface of the message pipeline."""

    channel_state: ChannelStateRegistry  # per-channel locks, pending files, ops
    sessions: SessionManager
    permissions: PermissionManager  # authenticated OwnerContext, never tiers
    llm_gateway: LLMGateway  # owns the swappable provider clients
    prompt_builder: PromptBuilder
    turn_recorder: TurnRecorder  # context traces + operational reflection
    tool_loop: ToolLoopRunner  # the tools route
    delivery: DeliveryService  # task-owned durable publication (Phase 2)
    housekeeping: Housekeeping  # post-turn cache maintenance
    # Suspended-turn resume manager (None = feature off). Default keeps every
    # existing construction working; wiring passes the real manager.
    turn_resume: TurnResumeManager | None = None


class MessagePipeline:
    def __init__(self, deps: MessagePipelineDeps) -> None:
        self._channel_state = deps.channel_state
        self._sessions = deps.sessions
        self._permissions = deps.permissions
        self._llm_gateway = deps.llm_gateway
        self._prompt_builder = deps.prompt_builder
        self._turn_recorder = deps.turn_recorder
        self._tool_loop = deps.tool_loop
        self._delivery = deps.delivery
        self._housekeeping = deps.housekeeping
        self._turn_resume = deps.turn_resume

    async def run(
        self,
        message: Any,
        content: str,
        *,
        image_blocks: list[dict] | None = None,
        parent_conversation_id: str | None = None,
        parent_name: str | None = None,
    ) -> None:
        _require_phase2_admission()
        channel_id = str(message.conversation_id)

        # Acquire per-channel lock — messages queue naturally via the lock
        lock = self._channel_state.channel_locks.setdefault(channel_id, asyncio.Lock())

        async with lock:
            # Parent metadata must be authorized by admission, never inferred
            # from a transport-specific thread object. Seeding remains locked.
            if parent_conversation_id is not None:
                self._inherit_parent_context(
                    channel_id, parent_conversation_id, parent_name,
                )

            await self._run_inner(
                message,
                content,
                channel_id,
                image_blocks=image_blocks or [],
            )

    def _inherit_parent_context(
        self, conversation_id: str, parent_id: str, parent_name: str | None = None,
    ) -> None:
        """Seed an empty branch with bounded parent context under its lock.

        Phase 2 must authorize both conversation revisions before mutation.
        The helper keeps the shared inheritance algorithm, not an ingress.
        """
        _require_phase2_admission()
        parent_name = parent_name or parent_id
        branch_session = self._sessions.get_or_create(conversation_id)
        if not branch_session.messages:
            parent_session = self._sessions.get_or_create(parent_id)
            if parent_session.messages or parent_session.summary:
                inherited_tag = f"[INHERITED FROM {parent_name}]"
                branch_session.summary = (
                    f"{inherited_tag} {parent_session.summary}"
                    if parent_session.summary else ""
                )
                recent = parent_session.messages[-6:]
                if recent:
                    parent_context = "\n".join(
                        f"{m.role}: {m.content[:300]}" for m in recent
                    )
                    context_block = (
                        f"{inherited_tag} Parent conversation context:\n{parent_context}"
                    )
                    if branch_session.summary:
                        branch_session.summary += f"\n{context_block}"
                    else:
                        branch_session.summary = context_block
                log.info(
                    "Branch %s inherited context from parent %s (%s)",
                    conversation_id, parent_name, parent_id,
                )

    async def _run_inner(
        self,
        message: Any,
        content: str,
        channel_id: str,
        *,
        image_blocks: list[dict] | None = None,
    ) -> None:
        _require_phase2_admission()
        user_id = str(message.owner_id)
        if not self._permissions.is_owner(user_id):
            raise PermissionError("An authenticated profile OwnerContext is required")
        # Prefix with display name so the LLM knows who's talking
        display_name = message.owner_name or user_id
        tagged_content = f"[{display_name}]: {content}"
        self._sessions.add_message(channel_id, "user", tagged_content, user_id=user_id)

        # Preserve result-scoped accounting before string scrubbing/fallbacks.
        # Transport failures are not accepted generations; partial replies are.
        direct_response = None
        direct_started_ns = 0
        direct_duration_ms = 0
        direct_history = []
        direct_prompt = ""
        direct_message_id = str(message.request_id)
        try:
            already_sent = False
            is_error = False
            tools_used: list[str] = []
            handoff = False

            if not self._llm_gateway.active_client:
                await self._delivery.send_with_retry(
                    message,
                    "No LLM provider available. Please try again later.",
                )
                self._sessions.remove_last_message(channel_id, "user")
                return
            # A bare `resume`/`continue` with preserved work resumes the
            # suspended turn instead of starting a fresh one. Check BEFORE
            # prompt/history assembly: compaction can call the LLM, while
            # unresolved operations must remain a genuine zero-LLM path.
            _resumed = None
            if self._turn_resume is not None:
                try:
                    _resumed = await self._turn_resume.try_explicit_resume(message)
                except Exception:
                    log.exception(
                        "Explicit resume attempt failed — falling through "
                        "to a normal turn"
                    )
                    _resumed = None
            _trace = None
            _sp = None
            task_history: list = []
            if _resumed is None:
                _trace = self._turn_recorder._new_context_trace()
                if _trace is not None:
                    with _trace.phase("system_prompt"):
                        _sp = self._prompt_builder.build_full_prompt(
                            conversation_id=message.conversation_id,
                            user_id=user_id,
                            query=content,
                            trace=_trace,
                        )
                else:
                    _sp = self._prompt_builder.build_full_prompt(
                        conversation_id=message.conversation_id,
                        user_id=user_id,
                        query=content,
                    )
                log.info("Routing to Codex with tools")
                # Abbreviated, relevance-filtered history avoids poisoning
                # from stale responses; get_task_history handles compaction.
                if _trace is not None:
                    with _trace.phase("history"):
                        task_history = await self._sessions.get_task_history(
                            channel_id,
                            max_messages=160,
                            current_query=content,
                            trace=_trace,
                        )
                else:
                    task_history = await self._sessions.get_task_history(
                        channel_id,
                        max_messages=160,
                        current_query=content,
                    )
                if image_blocks and task_history and task_history[-1]["role"] == "user":
                    last = task_history[-1]
                    text = (
                        last["content"]
                        if isinstance(last["content"], str)
                        else str(last["content"])
                    )
                    # Vision turns legitimately swap str content for
                    # a block list; the LLM layer handles both shapes.
                    task_history[-1] = {
                        "role": "user",
                        "content": image_blocks + [{"type": "text", "text": text}],  # type: ignore[dict-item]
                    }
                    log.info(
                        "Attached %d image(s) to message for Claude vision",
                        len(image_blocks),
                    )
            try:
                if _resumed is not None:
                    (
                        response,
                        already_sent,
                        is_error,
                        tools_used,
                        handoff,
                    ) = _resumed
                else:
                    (
                        response,
                        already_sent,
                        is_error,
                        tools_used,
                        handoff,
                    ) = await self._tool_loop.run(
                        message,
                        task_history,
                        system_prompt_override=_sp,
                        trace=_trace,
                    )
            except TimeoutError as codex_err:
                _err = format_user_facing_error(codex_err)
                log.warning("Codex tool loop timed out: %s", _err)
                response = f"Tool execution timed out: {_err}"
                is_error = True
            except Exception as codex_err:
                # Keep raw HTTP bodies out of user text and journal messages.
                _err = format_user_facing_error(codex_err)
                log.error("Codex tool loop unexpected error: %s", _err, exc_info=True)
                response = f"Tool execution failed: {_err}"
                is_error = True
                handoff = False
            # Skill requested Codex handoff; retain result-scoped accounting.
            if handoff and self._llm_gateway.active_client and not is_error:
                log.info("Skill handoff to Codex for response")
                _skill_response = response
                chat_prompt = self._prompt_builder.build_chat_prompt(
                    conversation_id=message.conversation_id,
                    user_id=user_id,
                    query=content,
                )
                history = self._sessions.get_history(channel_id)
                codex_messages = list(history) + [
                    {"role": "assistant", "content": f"[Tool result: {response}]"},
                    {
                        "role": "user",
                        "content": (
                            "Respond to the user based on the tool result above. "
                            "Be conversational and helpful."
                        ),
                    },
                ]
                try:
                    direct_started_ns = time.monotonic_ns()
                    response = await self._llm_gateway.chat(
                        messages=codex_messages,
                        system=chat_prompt,
                    )
                    direct_response = response
                    direct_history = codex_messages
                    direct_prompt = chat_prompt
                    direct_duration_ms = (time.monotonic_ns() - direct_started_ns) // 1_000_000
                    # The tool-loop turn is already saved under request_id.
                    direct_message_id = f"{message.request_id}:handoff"
                    if not response:
                        log.warning("Codex handoff returned empty, using skill result directly")
                        response = _skill_response
                    already_sent = False
                except Exception as e:
                    log.warning("Codex handoff failed, using skill result directly: %s", e)
                    response = _skill_response
                    from ..llm.errors import LLMIncompleteResponseError

                    if isinstance(e, LLMIncompleteResponseError):
                        direct_response = e.partial_text
                        direct_history = codex_messages
                        direct_prompt = chat_prompt
                        direct_message_id = f"{message.request_id}:handoff"
                        direct_duration_ms = (
                            time.monotonic_ns() - direct_started_ns
                        ) // 1_000_000
                        response = (
                            e.partial_text + "\n\n[Provider marked this response incomplete.]"
                        )
                        is_error = True
                    already_sent = False
        except TimeoutError as e:
            _err = format_user_facing_error(e)
            await self._delivery.set_status(None, task_end=True)
            log.error("Timeout processing message: %s", _err, exc_info=True)
            leaked = self._channel_state.pending_files.pop(channel_id, None)
            if leaked:
                log.warning(
                    "Cleaned %d leaked pending file(s) for channel %s", len(leaked), channel_id
                )
            await self._delivery.send_with_retry(
                message, scrub_response_secrets(f"Something went wrong: {_err}")
            )
            self._sessions.remove_last_message(channel_id, "user")
            return
        except asyncio.CancelledError:
            # CancelledError is a BaseException, so it bypasses the Exception
            # handlers here — without this the just-appended user turn is left
            # orphaned in history (no assistant reply). Clean up synchronously
            # (no awaits, which could re-raise mid-cancellation) and re-raise so
            # the cancellation still propagates.
            self._channel_state.pending_files.pop(channel_id, None)
            self._sessions.remove_last_message(channel_id, "user")
            raise
        except Exception as e:
            _err = format_user_facing_error(e)
            await self._delivery.set_status(None, task_end=True)
            log.error("Unexpected error processing message: %s", _err, exc_info=True)
            leaked = self._channel_state.pending_files.pop(channel_id, None)
            if leaked:
                log.warning(
                    "Cleaned %d leaked pending file(s) for channel %s", len(leaked), channel_id
                )
            await self._delivery.send_with_retry(
                message, scrub_response_secrets(f"Something went wrong: {_err}")
            )
            self._sessions.remove_last_message(channel_id, "user")
            return

        await self._delivery.set_status(None, task_end=True)

        # Scrub secrets from LLM response before logging, saving, or sending.
        # Tool output is already scrubbed (scrub_output_secrets in _run_tool),
        # but the LLM may echo, reconstruct, or hallucinate secrets in its
        # natural-language response text.
        response = scrub_response_secrets(response)

        if direct_response is not None:
            await self._turn_recorder._save_direct_chat_trajectory(
                message_id=direct_message_id, channel_id=channel_id,
                user_id=user_id, user_name=display_name, user_content=content,
                system_prompt=direct_prompt, history=direct_history,
                response=direct_response, final_response=response, is_error=is_error,
                duration_ms=direct_duration_ms,
            )

        log.info("Final response to send: %r", response[:200])
        if not is_error:
            if tools_used:
                # Summarize verbose tool-loop responses before persisting
                # to prevent long multi-tool outputs from dominating history
                history_response = summarize_tool_response(response, tools_used)
            else:
                # Save text-only (chat) responses too — the LLM needs to
                # remember what it said.  Truncate to keep history lean.
                history_response = (
                    response[:CHAT_RESPONSE_MAX_CHARS]
                    if len(response) > CHAT_RESPONSE_MAX_CHARS
                    else response
                )
            self._sessions.add_message(channel_id, "assistant", history_response)
            self._sessions.prune()
            self._housekeeping.maybe_cleanup()
            try:
                await asyncio.to_thread(self._sessions.save)
            except Exception as save_err:
                log.warning("Session save failed: %s", save_err)
        else:
            # Save a sanitized error marker instead of the full error response.
            # The user sees the full error in chat, but raw refusals and
            # fabrications are NOT persisted to prevent context poisoning.
            _preserved = False
            if self._turn_resume is not None:
                try:
                    _preserved = await self._turn_resume.is_suspended(
                        channel_id, str(message.request_id)
                    )
                except Exception:
                    _preserved = False
            if _preserved:
                _tools_note = (
                    f" after using tools ({', '.join(tools_used[:5])})"
                    if tools_used
                    else ""
                )
                sanitized = (
                    "[Previous request was interrupted by a model-capacity "
                    f"outage{_tools_note}. Its work is PRESERVED and resumable — "
                    "it auto-resumes when capacity returns, or the user can "
                    "say 'resume'.]"
                )
            elif tools_used:
                sanitized = (
                    f"[Previous request used tools ({', '.join(tools_used[:5])}) "
                    f"but encountered an error. The user may ask to retry.]"
                )
            else:
                sanitized = "[Previous request encountered an error before tool execution.]"
            self._sessions.add_message(channel_id, "assistant", sanitized)
            self._sessions.prune()
            try:
                await asyncio.to_thread(self._sessions.save)
            except Exception as save_err:
                log.warning("Session save failed: %s", save_err)

        # Post-operation reflection — learn from what actually happened, including
        # failures. Must run for both the success and error paths (previously this
        # was nested under the success branch, so is_error was never observed).
        if tools_used:
            # Pop synchronously inside the channel-locked request body so a
            # fast follow-up request can never swap details under the
            # fire-and-forget reflection task.
            op_details = self._channel_state.last_op_details.pop(channel_id, None)
            fire_and_forget(
                self._turn_recorder._operational_reflection(
                    content,
                    tools_used,
                    response,
                    is_error,
                    user_id,
                    tool_details=op_details,
                ),
                name="operational_reflection",
            )

        if not already_sent:
            # Phase 2 delivery must settle text and pending artifacts durably.
            await self._delivery.send_chunked(message, response)
        else:
            # A text receipt is not artifact settlement. Do not pop pending
            # bytes or invent publication until the durable sink is wired.
            _require_phase2_admission()
