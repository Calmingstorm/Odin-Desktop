"""User-facing exception presentation — the single formatter for error text
that reaches an end user.

Conversation boundaries share this policy; no transport owns it.

The formatter is total and non-throwing (any internal failure falls back to
the exception type name) and its output is bounded, HTML-free,
control-character-free, mention-safe, and secret-scrubbed. It never renders
HTML response bodies. Full diagnostics stay in logs via ``exc_info`` at
the call sites. Transport-specific structured exceptions belong in adapters.
"""

from __future__ import annotations

import unicodedata

from .llm.secret_scrubber import scrub_output_secrets

_HTML_MARKERS = ("<html", "<!doctype")


def _clean_detail(detail: str) -> str:
    """Shared normalization for ANY exception-derived text fragment.

    Every fragment that can carry upstream-controlled bytes — ``str(exc)``
    first lines and HTTP ``response.reason`` phrases alike — must pass
    through here before reaching a user: category-C strip (C0, DEL, C1,
    format chars; tab deliberately retained — a plain ``ch >= " "`` check
    lets U+007F and U+0080..U+009F through), HTML-page fragments dropped,
    mass mentions neutralized with a zero-width space, and secrets scrubbed
    (exception text can echo connection strings and keys — scrubbing inside
    the formatter means no boundary can forget to).
    """
    detail = "".join(
        ch for ch in detail if ch == "\t" or not unicodedata.category(ch).startswith("C")
    )
    if any(m in detail.lower() for m in _HTML_MARKERS):
        return ""
    detail = detail.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
    detail = scrub_output_secrets(detail)
    return detail.strip()


def sanitize_error_text(text: str, limit: int = 200) -> str:
    """Bounded, HTML-free, mention-safe, secret-scrubbed form of an
    error-reason STRING for operator-visible storage (subsystem status
    reasons, transition history). String-input sibling of
    ``format_user_facing_error`` — same normalization, same total
    non-throwing contract; safe-looking literals ("manual", "capacity")
    pass through unchanged.
    """
    try:
        lines = [ln.strip() for ln in str(text).strip().splitlines() if ln.strip()]
        return _clean_detail(lines[0] if lines else "")[:limit]
    except Exception:
        return ""


def format_user_facing_error(exc: BaseException, limit: int = 200) -> str:
    """Bounded one-line exception summary safe to show an end user.

    ``limit`` bounds THIS function's output; call sites may prepend short
    context prefixes ("LLM API error: ", "LLM error: "), so a stored or
    displayed string can exceed it by the prefix length — the safety
    properties (HTML-free, control-free, mention-safe, scrubbed) are
    prefix-independent.

    Every exception detail passes through ``_clean_detail``. Local storage
    or IPC failures never acquire an invented HTTP status.
    """
    name = type(exc).__name__
    try:
        try:
            text = str(exc)
        except Exception:
            text = ""
        lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
        detail = _clean_detail(lines[0] if lines else "")
        funnel = getattr(exc, "routing_funnel", None)
        if isinstance(funnel, list) and funnel:
            steps: list[str] = []
            for item in funnel[:8]:
                if not isinstance(item, dict):
                    continue
                label = item.get("name") or item.get("step") or item.get("filter")
                count = item.get("count")
                if not isinstance(count, int):
                    count = item.get("remaining")
                if isinstance(label, str):
                    rendered = _clean_detail(label)
                    if rendered:
                        steps.append(
                            f"{rendered}: {count}" if isinstance(count, int) else rendered
                        )
            if steps:
                detail = f"{detail}; routing: {' -> '.join(steps)}" if detail else (
                    f"routing: {' -> '.join(steps)}"
                )
        out = f"{name}: {detail}" if detail else name
        return out[:limit]
    except Exception:
        return name
