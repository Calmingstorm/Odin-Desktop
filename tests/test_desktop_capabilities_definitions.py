"""Desktop capability catalog adaptations approved for Phase 1."""

from __future__ import annotations

from src.tools.affordances import Risk, get_affordance
from src.tools.registry import TOOLS


def _tool(name: str) -> dict:
    return next(tool for tool in TOOLS if tool["name"] == name)


def test_discord_only_tools_are_absent_from_catalog_and_affordances() -> None:
    removed = {"set_permission", "add_reaction", "create_poll", "purge_messages"}
    assert removed.isdisjoint(tool["name"] for tool in TOOLS)
    for name in removed:
        # No explicit affordance survives to make a removed capability look live.
        assert get_affordance(name).risk == Risk.HIGH


def test_read_conversation_has_no_foreign_conversation_selector() -> None:
    tool = _tool("read_conversation")
    assert tool["input_schema"]["properties"].keys() == {"limit"}
    assert tool["input_schema"]["properties"]["limit"]["description"] == (
        "Number of messages to read (default 10, max 100)"
    )
    assert "CURRENT conversation" in tool["description"]
    assert "visible conversation history from all recorded participants" in tool["description"]
    assert "do NOT pass a conversation ID" in tool["description"]
    assert "do NOT paste or echo them" in tool["description"]


def test_scheduling_destination_uses_conversation_id() -> None:
    schema = _tool("update_schedule")["input_schema"]
    assert "channel_id" not in schema["properties"]
    assert "conversation_id" in schema["properties"]
    assert "conversation_id" in _tool("update_schedule")["description"]


def test_approved_catalog_substitutions_are_exact_and_limited() -> None:
    expected = {
        "browser_screenshot": "Takes a screenshot of a URL (renders JavaScript) and posts to the conversation. Works on dashboards, SPAs, and dynamic pages unlike fetch_url. For text, use browser_read_page.",
        "post_file": "Fetches a file from a managed host and posts it as a conversation attachment. Max 25MB. For generated content, use generate_file.",
        "generate_file": "Creates a file (script, code, CSV, report, etc.) and posts it as a conversation attachment. For files on a host, use post_file.",
        "generate_image": "Generates an image from a text prompt with the native OpenAI image backend and posts it to the conversation. Output dimensions and aspect ratio are selected by the provider.",
        "delegate_task": "Runs a multi-step task in the background, posting progress to the conversation. Steps run sequentially with conditions (substring match, ! to negate), on_failure (abort/continue), store_as ({var.name}), {prev_output} substitution. IMPORTANT: each step using run_command MUST have tool_input with 'command' key. Example step: {\"tool_name\": \"run_command\", \"description\": \"List files\", \"tool_input\": {\"command\": \"ls -la /tmp\"}}. Track with list_tasks, stop with cancel_task.",
    }
    for name, description in expected.items():
        assert _tool(name)["description"] == description

    assert "Results are NOT posted to the conversation" in _tool("spawn_agent")["description"]
    assert "Max 5/conversation" in _tool("spawn_agent")["description"]
    assert "conversation message logs in this profile" in _tool("search_history")["description"]
    assert "Original caller, conversation, tool permission and host scope are rechecked" in (
        _tool("get_tool_output")["description"]
    )

    for name in ("schedule_task", "update_schedule"):
        description = _tool(name)["input_schema"]["properties"]["report_format"]["description"]
        assert "paginated conversation report renderer" in description
    assert "paginated_embed_v1" in _tool("schedule_task")["input_schema"]["properties"]["report_format"]["description"]
    assert "paginated_embed_v1" not in _tool("update_schedule")["input_schema"]["properties"]["report_format"]["description"]


def test_affordance_metadata_tracks_current_conversation_history() -> None:
    assert get_affordance("read_conversation").risk == Risk.NONE
    assert get_affordance("read_channel").risk == Risk.HIGH
