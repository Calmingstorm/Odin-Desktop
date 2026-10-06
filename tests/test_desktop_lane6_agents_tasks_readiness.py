"""Real canonical native owner availability and live revocation regression."""

from tests.test_desktop_lane6_agents_tasks_cancel import (
    lane6_agents_tasks_cancel_graph as lane6_agents_tasks_cancel_graph,
)


def test_lane6_agents_tasks_native_skill_readiness_tracks_real_owner(
    lane6_agents_tasks_cancel_graph,
):
    graph = lane6_agents_tasks_cancel_graph
    deps = graph.engine.deps
    policy = deps.tool_executor._builtin_policy
    for name in (
        "create_skill",
        "edit_skill",
        "delete_skill",
        "enable_skill",
        "disable_skill",
        "install_skill",
        "list_skills",
        "skill_status",
        "invoke_skill",
    ):
        assert deps.native_tools.skills.handles(name)
        assert policy.is_available(name)
    assert not policy.is_available("export_skill")
    graph.config.tools.disabled_tools = ["create_skill"]
    assert not policy.is_available("create_skill")
    graph.config.tools.disabled_tools = []
    assert policy.is_available("create_skill")
    graph.engine.requests = None
    assert not policy.is_available("create_skill")
    graph.engine.requests = graph.requests


def test_lane6_agents_tasks_unpublished_dynamic_output_is_unavailable(
    lane6_agents_tasks_cancel_graph,
):
    policy = lane6_agents_tasks_cancel_graph.engine.deps.tool_executor._builtin_policy
    assert not policy.is_available("unpublished_fixture_skill")
    assert not policy.is_available("mcp_unpublished_fixture_tool")
