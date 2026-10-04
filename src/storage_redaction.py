"""Transport-neutral redaction before trajectory and durability storage."""

_EMAIL_BODY_TOOLS = frozenset({"email_send"})


def _deep_scrub_strings(value):
    """Recursively scrub patterns and opaque values under sensitive keys."""
    from .config.sensitivity import is_storage_sensitive_key
    from .llm.secret_scrubber import scrub_output_secrets

    if isinstance(value, str):
        return scrub_output_secrets(value)
    if isinstance(value, dict):
        return {
            key: (
                "[redacted:sensitive-key]"
                if is_storage_sensitive_key(key)
                else _deep_scrub_strings(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_deep_scrub_strings(item) for item in value]
    return value


def _scrub_tool_input_for_storage(tool_name: str, tool_input: dict) -> dict:
    """Redact privacy-sensitive fields from tool input before any storage path."""
    if (
        tool_name in {"computer_act", "computer_session", "computer_observe"}
        and isinstance(tool_input, dict)
    ):
        # Desktop fields and expected text can contain a whole private document.
        # Keep attribution/IDs and shape; never retain text, pixels or a data URL.
        def desktop_scrub(value, key="", depth=0):
            if depth > 30:
                return "[private desktop content: nesting limit]"
            if key in {"text", "value", "content", "data", "image_bytes", "text_equals",
                       "text_contains", "contains_text", "expected_text", "selected_text",
                       "accessible_name", "accessible_description", "clipboard"}:
                length = len(value) if isinstance(value, (str, bytes)) else 0
                return f"[private desktop content: {length} chars]"
            if isinstance(value, dict):
                return {name: desktop_scrub(item, name, depth + 1)
                        for name, item in value.items()}
            if isinstance(value, list):
                return [desktop_scrub(item, depth=depth + 1) for item in value]
            return value

        return _deep_scrub_strings(desktop_scrub(tool_input))
    if tool_name.startswith("mcp_") and isinstance(tool_input, dict):
        # MCP argument shapes are arbitrary third-party contracts and may
        # carry credentials — deep-scrub every string value with the shared
        # secret scrubber before trajectory/durability storage. (Published
        # MCP names always carry the mcp_ prefix; builtins win conflicts, so
        # the prefix cannot capture a native tool.)
        return _deep_scrub_strings(tool_input)
    if tool_name not in _EMAIL_BODY_TOOLS or not isinstance(tool_input, dict):
        return tool_input
    cleaned = dict(tool_input)
    body = cleaned.get("body", "")
    cleaned["body"] = f"[redacted email body: {len(body)} chars]"
    if "attachments" in cleaned and cleaned["attachments"]:
        from pathlib import Path

        cleaned["attachments"] = [Path(p).name for p in cleaned["attachments"]]
    return cleaned
