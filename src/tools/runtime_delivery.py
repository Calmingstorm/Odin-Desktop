"""Pure retained-output boundary, not durable conversation delivery.

The executor must supply authenticated owner-scoped retention. No ownerless
fallback promises delivery when Phase 2 conversation consumers are absent.
"""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import replace

from .media_result import image_result_parts
from .output_delivery import (
    DeliveredOutput,
    delivery_scope,
    evidence_digest,
    get_delivery_budget,
)
from .output_retention import RetentionError
from .result_capture import result_capture
from .result_validator import ToolResult


@contextmanager
def execution_delivery_scope(owner, channel=None, *, allowed_tools=None):
    """Bind origin and full capture only for this invocation, including cancellation."""
    previous_owner, previous_channel = delivery_scope.get()
    token = delivery_scope.set((str(owner or previous_owner),
                                str(channel if channel is not None else previous_channel)))
    from .output_authorization import host_access_capture, request_tool_scope

    scope_token = request_tool_scope.set(
        allowed_tools if allowed_tools is not None else request_tool_scope.get())
    try:
        with result_capture(), host_access_capture():
            yield
    finally:
        request_tool_scope.reset(scope_token)
        delivery_scope.reset(token)


def deliver_runtime_output(executor, text, *, tool_name, tool_input, user_id,
                           channel_id=None, status="succeeded", budget=None):
    """Use the executor's authorization/store owner even for native tools."""
    method = getattr(type(executor), "deliver_output", None)
    if callable(method):
        _require_retention_authority(executor, tool_name, user_id)
        options = {} if budget is None else {"budget": budget}
        return method(executor, text, tool_name=tool_name, tool_input=tool_input,
                      user_id=user_id, channel_id=channel_id, status=status, **options)
    # A schema, caller-supplied ID or result string is not an authenticated
    # retention owner. Do not claim delivery or discard evidence through an
    # ownerless truncation fallback. The original effect may already have run.
    raise RuntimeError(
        "Output retention unavailable: no authenticated executor consumer is "
        "configured. Do not replay the tool."
    )


def _require_retention_authority(executor, tool_name, user_id):
    """Check owner and live readiness even for out-of-band provider evidence."""
    permission = getattr(type(executor), "check_permission", None)
    policy = getattr(executor, "_builtin_policy", None)
    if not callable(permission) or policy is None:
        raise PermissionError("Output authority unavailable. Do not replay the tool.")
    denial = permission(executor, tool_name, user_id)
    if denial or not policy.is_available(tool_name):
        raise PermissionError(
            (denial or "Output capability unavailable.") + " Do not replay the tool."
        )


def ensure_failure_visible(result_text: str, ok: bool) -> str:
    """Preserve structural failure visibility without a transport dependency."""
    from .tool_text import _ERROR_RESULT_PREFIXES

    if isinstance(result_text, DeliveredOutput):
        # Canonical envelopes carry status separately. Prefixing invalidates
        # JSON and can exceed the complete serialized-envelope budget.
        return result_text
    if ok or result_text.lstrip().startswith((*_ERROR_RESULT_PREFIXES, "Failed to ")):
        return result_text
    return f"Error (tool reported failure):\n{result_text}"


def deliver_runtime_result(executor, result, **kwargs):
    from .execution_outcome import ToolFailure, is_tool_failure

    if not callable(getattr(type(executor), "deliver_output", None)):
        raise RuntimeError(
            "Output retention unavailable: no authenticated executor consumer is "
            "configured. Do not replay the tool."
        )
    _require_retention_authority(executor, kwargs.get("tool_name"), kwargs.get("user_id"))
    if not isinstance(result, ToolResult) and is_tool_failure(result):
        result = ToolResult(
            output=result, ok=False, error="tool reported failure",
            uncertain_outcome=isinstance(result, ToolFailure) and result.uncertain_outcome,
        )
    if isinstance(result, ToolResult):
        status = ("outcome_unknown" if result.uncertain_outcome
                  else "succeeded" if result.ok else "failed")
        text = result.output
        if result.attachments:
            # Binary retention assigns fresh manifest/blob IDs. Compare the
            # complete original evidence, including every byte, not references.
            # Reuse trusted full text identity, not RankedOutput's summary or
            # DeliveredOutput's fresh cursor-bearing presentation.
            evidence = hashlib.sha256(evidence_digest(text).encode("ascii"))
            for attachment in result.attachments:
                metadata = json.dumps({
                    "media_type": attachment.media_type,
                    "content_index": attachment.content_index,
                    "kind": attachment.kind,
                }, sort_keys=True).encode("utf-8")
                evidence.update(len(metadata).to_bytes(8, "big"))
                evidence.update(metadata)
                evidence.update(len(attachment.data).to_bytes(8, "big"))
                evidence.update(attachment.data)
            retain = getattr(type(executor), "retain_attachments", None)
            try:
                if not callable(retain):
                    raise RetentionError("Binary retention unavailable.")
                reference = retain(
                    executor, result.attachments, tool_name=kwargs["tool_name"],
                    user_id=kwargs.get("user_id"), channel_id=kwargs.get("channel_id"),
                    status=status,
                )
            except (RetentionError, OSError, sqlite3.Error, UnicodeError) as exc:
                reference = {
                    "kind": "tool_attachment_manifest", "attachment_count": len(result.attachments),
                    "retention": "failed", "cursor": None,
                    "error": (str(exc) if isinstance(exc, RetentionError)
                              else "Binary retention storage unavailable.")
                             + " No bytes retained; no continuation exists. "
                             "Do not replay the tool.",
                }
            # Bundle admission is atomic. Always reserve space for its one
            # discoverable manifest cursor, even if subsequent TEXT retention
            # exhausts quota. Never truncate file references into a lost middle.
            pointer = "\n[output retention] " + json.dumps(reference, ensure_ascii=True)
            budget = get_delivery_budget(getattr(executor, "config", None)) - len(pointer)
            text = deliver_runtime_output(
                executor, ensure_failure_visible(text, result.ok), status=status,
                budget=budget, **kwargs)
            output = DeliveredOutput(text + pointer, evidence_digest=evidence.hexdigest())
            output.truncated = bool(getattr(text, "truncated", False))
            return replace(result, attachments=(), output=output,
                           truncated=result.truncated or output.truncated)
        output = deliver_runtime_output(
            executor, ensure_failure_visible(text, result.ok), status=status, **kwargs)
        return replace(result, attachments=(), output=output,
                       truncated=result.truncated or bool(
                           isinstance(output, DeliveredOutput) and output.truncated))
    if image_result_parts(result) is not None:
        # Provider-facing evidence only, not an artifact-publication receipt.
        return result
    return deliver_runtime_output(executor, result, **kwargs)
