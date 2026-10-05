"""Current-conversation history native handler.

Admission and durable transcript wiring are Phase 2. The reader, when supplied
by that composition root, enforces authenticated request ownership and visible
transcript revisions. No foreign conversation selector is accepted.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ...llm.secret_scrubber import scrub_output_secrets


class ChannelOpsTools:
    def __init__(self, *, read_visible_history: Callable[..., Awaitable[list[str]]] | None = None):
        self.read_visible_history = read_visible_history

    async def _handle_read_conversation(self, request, inp: dict) -> str:
        """Read recent messages from the current conversation.

        Returns formatted visible conversation history including messages from
        all recorded participants — not just the bot's own session history.
        """
        if set(inp) - {"limit"}:
            return "Only 'limit' is accepted; the conversation is the one this request came from."
        if self.read_visible_history is None:
            return (
                "Conversation history is unavailable: "
                "Phase 2 admission and transcript wiring is not implemented."
            )
        if request is None:
            return "No conversation context available."
        limit = max(1, min(int(inp.get("limit", 10)), 100))
        try:
            messages = await self.read_visible_history(request, limit=limit)
            if not messages:
                return "No messages found in conversation."
            result = scrub_output_secrets("\n".join(messages))
            return (
                f"[Conversation history: {len(messages)} messages read. "
                "This is context for YOU — do not paste or echo these messages. "
                "Respond with your own summary, analysis, or action.]\n" + result
            )
        except PermissionError:
            return "Permission denied — cannot read this conversation."
        except Exception as e:
            return f"Failed to read conversation: {scrub_output_secrets(str(e))}"
