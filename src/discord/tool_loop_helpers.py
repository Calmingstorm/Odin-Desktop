"""Shared leaf helpers for the tool-execution pipelines.

Originally the "safe pure pieces" carved out of the old ~700-line chat
tool loop. RFC-002 P1 widened the charter slightly: this is now the
shared LEAF module for symbols the tool loop, the message intake, the
background-task runner, and the transport adapters all need — it imports
nothing from ``src.discord``. Storage redaction lives in the neutral
``src.storage_redaction`` leaf and is re-exported here.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from ..tools.executor import _ERROR_RESULT_PREFIXES

# Friendly fallback when the LLM returns an empty response after retries
# (moved verbatim from client.py, RFC-002 P1).
_EMPTY_RESPONSE_FALLBACK = "I couldn't generate a response. Please try again."

from ..storage_redaction import (
    _EMAIL_BODY_TOOLS,
    _deep_scrub_strings,
    _scrub_tool_input_for_storage,
)


def ensure_failure_visible(result_text: str, ok: bool) -> str:
    """Make a structurally-failed tool result visible to the model.

    execute() carries ok=False on ToolResult, but the model only sees
    str(result) — the raw output. When that text lacks an error prefix
    (e.g. run_command_multi's per-host markdown aggregate wrapping a
    denial), the model reads a refused action as success. Prefix it.
    """
    from ..tools.output_delivery import DeliveredOutput

    if isinstance(result_text, DeliveredOutput):
        # Canonical envelopes carry status separately. Prefixing invalidates
        # JSON and can exceed the complete serialized-envelope budget.
        return result_text
    if ok or result_text.lstrip().startswith((*_ERROR_RESULT_PREFIXES, "Failed to ")):
        return result_text
    return f"Error (tool reported failure):\n{result_text}"


def build_request_preamble(
    *,
    request_id: str,
    request_time: str,
    user_display: str,
    user_id: Any,
    message_id: Any,
    channel_description: str,
    has_history: bool,
) -> dict:
    """Build the developer-role separator message that delimits the current
    request from the history block above it.

    Returns a message dict `{role, content}` ready to insert into the LLM
    message list. For the no-history case, returns a thin channel-context
    message instead of a full separator.
    """
    msg_id_note = f"Current message ID: {message_id}"
    if not has_history:
        return {
            "role": "developer",
            "content": f"{channel_description}\n{msg_id_note}",
        }

    sep_text = (
        f"=== CURRENT REQUEST [req-{request_id}] ===\n"
        f"Time: {request_time}\n"
        f"From: {user_display} (ID: {user_id})\n"
        f"{channel_description}\n"
        f"{msg_id_note}\n"
        "--- HISTORY ABOVE | REQUEST BELOW ---\n"
        "Messages above are HISTORY — context for understanding what happened. "
        "History is NOT a task queue. Each message above was a SEPARATE request. "
        "Act ONLY on the new message below — do not replay other requests from history. "
        "If asked to 'redo' or 'do what was asked', identify the ONE specific task "
        "being referenced — do not sweep through history re-executing everything. "
        "Evaluate tools fresh. Do not repeat prior refusals."
    )
    return {"role": "developer", "content": sep_text}


def compute_request_id(content: Any) -> str:
    """Stable 8-char hash over the message content, for debug/trace IDs.

    The original logic used sha256(content) truncated to 8 hex chars; we
    keep that contract exactly so existing logs remain recognisable.
    """
    content_str = content if isinstance(content, str) else str(content)
    return hashlib.sha256(content_str.encode()).hexdigest()[:8]


def current_request_time() -> str:
    """UTC timestamp in the exact shape the loop has always produced."""
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
