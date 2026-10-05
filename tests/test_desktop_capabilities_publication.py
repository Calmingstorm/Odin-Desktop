"""Phase 1 publication is readiness, not documentation or delivery authority."""

import os
from types import SimpleNamespace

import pytest

from src.tools.agent_tool_policy import apply_agent_limits
from src.tools.autonomous_loop import LoopManager
from src.tools.builtin_policy import (
    BUILTIN_TOOL_NAMES,
    BuiltinToolPolicy,
    unavailable_rejection,
)
from src.tools.registry import (
    PHASE1_EXECUTOR_TOOL_NAMES,
    get_documentation_tool_definitions,
    get_tool_definitions,
)
from src.tools.result_validator import ToolResult
from src.tools.runtime_delivery import (
    deliver_runtime_output,
    deliver_runtime_result,
    ensure_failure_visible,
)


@pytest.fixture
def owner_context(tmp_path):
    from src.desktop.authority import OwnerAuthority
    from src.desktop.paths import ProfilePaths
    from src.permissions.manager import PermissionManager

    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path)
    authority = OwnerAuthority(paths)
    manager = PermissionManager(authority)
    token = manager.set_request_owner(authority.authenticate_local(peer_uid=os.geteuid()))
    try:
        yield manager, authority.owner_id
    finally:
        manager.reset_request_owner(token)


def configure_retention_recorder(executor, owner_context):
    from src.tools.executor import ToolExecutor

    manager, owner_id = owner_context
    executor._permission_manager = manager
    type(executor).check_permission = ToolExecutor.check_permission
    config = SimpleNamespace(tools=SimpleNamespace(disabled_tools=[]))
    executor._builtin_policy = BuiltinToolPolicy(lambda: config, lambda: {"read_file": True})
    return owner_id


def test_publication_defaults_closed_and_missing_readiness_is_false():
    assert get_tool_definitions() == []
    assert get_tool_definitions(readiness={}) == []
    tools = get_tool_definitions(readiness={"run_command": True})
    assert [tool["name"] for tool in tools] == ["run_command"]
    assert get_tool_definitions(readiness={"run_command": False}) == []


@pytest.mark.parametrize("ready", [False, None, 1, "true", {}, []])
def test_truthy_values_are_not_capability_readiness(ready):
    assert get_tool_definitions(readiness={"run_command": ready}) == []


def test_documentation_is_explicit_separate_and_cloned():
    docs = get_documentation_tool_definitions()
    assert docs
    docs[0]["input_schema"]["properties"].clear()
    docs[0]["description"] = "changed"
    fresh = get_documentation_tool_definitions()
    assert fresh[0]["description"] != "changed"
    assert fresh[0]["input_schema"]["properties"]
    assert get_tool_definitions() == []


def test_publication_preserves_order_affordances_and_isolates_profiles():
    docs = get_documentation_tool_definitions()
    readiness = {tool["name"]: True for tool in docs[::3]}
    published = get_tool_definitions(readiness=readiness)
    assert [tool["name"] for tool in published] == [
        tool["name"] for tool in docs
        if readiness.get(tool["name"]) is True and tool["name"] in PHASE1_EXECUTOR_TOOL_NAMES
    ]
    assert all("[affordances:" in tool["description"] for tool in published)
    published[0]["input_schema"]["properties"].clear()
    assert get_tool_definitions(readiness=readiness)[0]["input_schema"]["properties"]
    assert get_tool_definitions(readiness={}) == []


def test_removed_tools_are_neither_published_nor_reserved():
    removed = {"set_permission", "add_reaction", "create_poll", "purge_messages", "read_channel"}
    assert not removed.intersection(BUILTIN_TOOL_NAMES)
    assert get_tool_definitions(readiness=dict.fromkeys(removed, True)) == []


def test_live_policy_revocation_disabled_switch_and_reservation():
    config = SimpleNamespace(tools=SimpleNamespace(disabled_tools=[]))
    live = {"run_command": True}
    policy = BuiltinToolPolicy(lambda: config, lambda: live)
    assert policy.is_available("run_command")
    live.clear()
    assert not policy.is_available("run_command")
    assert "run_command" in BUILTIN_TOOL_NAMES
    live["run_command"] = True
    config.tools.disabled_tools = ["run_command"]
    assert policy.is_disabled("run_command")
    assert not policy.is_available("run_command")
    assert not policy.is_available("unknown")


def test_live_policy_without_or_unreadable_provider_is_closed():
    config = SimpleNamespace(tools=SimpleNamespace(disabled_tools=[]))
    assert not BuiltinToolPolicy(lambda: config).is_available("run_command")

    def broken():
        raise OSError("state unavailable")

    assert not BuiltinToolPolicy(lambda: config, broken).is_available("run_command")
    assert not BuiltinToolPolicy(lambda: config, lambda: None).is_available("run_command")


def test_unavailable_dispatch_is_typed_and_does_not_claim_execution():
    result = unavailable_rejection("run_command")
    assert result.ok is False
    assert result.error == "tool_unavailable"
    assert result.tool_name == "run_command"
    assert "was not executed" in result.output


def test_agent_limit_changes_only_approved_conversation_limit_fragment():
    docs = get_documentation_tool_definitions()
    original = next(tool for tool in docs if tool["name"] == "spawn_agent")
    config = SimpleNamespace(agents=SimpleNamespace(
        max_concurrent_agents=17, max_lifetime_seconds=1234,
    ))
    rendered = next(tool for tool in apply_agent_limits(docs, config)
                    if tool["name"] == "spawn_agent")
    assert rendered["description"] == original["description"].replace(
        "Max 5/conversation; lifetime limit for NEW agents: 14400 seconds.",
        "Max 17/conversation; lifetime limit for NEW agents: 1234 seconds.",
    )
    assert "Max 17/conversation" in rendered["description"]
    assert "Max 5/conversation" in original["description"]


def test_no_ownerless_runtime_retention_or_media_success():
    kwargs = dict(tool_name="example", tool_input={}, user_id="untrusted")
    with pytest.raises(RuntimeError, match="Do not replay the tool"):
        deliver_runtime_output(object(), "evidence", **kwargs)
    original = ToolResult(output="evidence", ok=False, uncertain_outcome=True)
    with pytest.raises(RuntimeError, match="Do not replay the tool"):
        deliver_runtime_result(object(), original, **kwargs)
    assert original.uncertain_outcome is True
    assert original.output == "evidence"


def test_retention_keeps_structural_failure_and_uncertainty(owner_context):
    # Pure recording stub only: no fabricated owner authority or durable sink.
    class Recorder:
        def deliver_output(self, text, **kwargs):
            self.recorded = (text, kwargs)
            return text

    executor = Recorder()
    owner_id = configure_retention_recorder(executor, owner_context)
    original = ToolResult(output="partial evidence", ok=False, uncertain_outcome=True)
    result = deliver_runtime_result(executor, original, tool_name="read_file",
                                    tool_input={}, user_id=owner_id)
    assert executor.recorded[1]["status"] == "outcome_unknown"
    assert result.uncertain_outcome is True
    assert result.ok is False
    assert result.output == "Error (tool reported failure):\npartial evidence"
    assert original.output == "partial evidence"
    assert ensure_failure_visible("Command failed", False) == "Command failed"


def test_provider_media_evidence_requires_executor_but_is_not_text_delivery(owner_context):
    class Recorder:
        def deliver_output(self, text, **kwargs):
            pytest.fail("image must not be treated as text retention")

    image = {"__image_block__": {"type": "image", "data": "evidence"}}
    executor = Recorder()
    owner_id = configure_retention_recorder(executor, owner_context)
    assert deliver_runtime_result(executor, image, tool_name="read_file",
                                  tool_input={}, user_id=owner_id) is image
    with pytest.raises(PermissionError, match="authenticated owner request"):
        deliver_runtime_result(executor, image, tool_name="read_file",
                               tool_input={}, user_id="untrusted")
    with pytest.raises(PermissionError, match="Output capability unavailable"):
        deliver_runtime_result(executor, image, tool_name="generate_image",
                               tool_input={}, user_id=owner_id)
    with pytest.raises(RuntimeError, match="Do not replay the tool"):
        deliver_runtime_result(object(), image, tool_name="analyze_image",
                               tool_input={}, user_id="untrusted")


def test_retention_shaped_object_does_not_grant_output_authority():
    class Unauthenticated:
        def deliver_output(self, text, **kwargs):
            pytest.fail("unauthenticated retention invoked")

    executor = Unauthenticated()
    kwargs = dict(tool_name="read_file", tool_input={}, user_id="claimed-owner")
    with pytest.raises(PermissionError, match="Output authority unavailable"):
        deliver_runtime_output(executor, "evidence", **kwargs)
    original = ToolResult(output="partial", ok=False, uncertain_outcome=True)
    with pytest.raises(PermissionError, match="Output authority unavailable"):
        deliver_runtime_result(executor, original, **kwargs)
    assert original.uncertain_outcome is True


def test_phase2_schema_readiness_cannot_publish_or_admit_unwired_handlers():
    docs = get_documentation_tool_definitions()
    native = {tool["name"]: True for tool in docs
              if tool["name"] not in PHASE1_EXECUTOR_TOOL_NAMES}
    assert native
    assert get_tool_definitions(readiness=native) == []
    config = SimpleNamespace(tools=SimpleNamespace(disabled_tools=[]))
    policy = BuiltinToolPolicy(lambda: config, lambda: native)
    assert all(not policy.is_available(name) for name in native)
    assert all(name in BUILTIN_TOOL_NAMES for name in native)


def test_phase1_handler_allowlist_matches_real_executor_table():
    from src.tools.executor import EXECUTOR_HANDLERS

    assert PHASE1_EXECUTOR_TOOL_NAMES == frozenset(EXECUTOR_HANDLERS)


def test_loop_start_fails_before_tasks_callbacks_or_send():
    manager = LoopManager()
    calls = []

    async def callback(*args):
        calls.append(args)

    result = manager.start_loop("goal", object(), "owner", "Owner", callback)
    assert "unavailable" in result
    assert "No loop was started" in result
    assert manager.active_count == 0
    assert manager._loops == {}
    assert calls == []


@pytest.mark.asyncio
async def test_loop_delivery_has_no_fake_send_success():
    manager = LoopManager()
    sink = SimpleNamespace(send=lambda text: pytest.fail("unwired delivery invoked"))
    info = SimpleNamespace(mode="notify", id="loop")
    with pytest.raises(RuntimeError, match="Do not replay the iteration"):
        await manager._post_response(info, sink, "retained output")
