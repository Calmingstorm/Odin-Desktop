"""Actual retained catalog merge and live qualification with stubbed backends."""
from __future__ import annotations

from types import SimpleNamespace

from src.config.schema import Config
from src.desktop.tool_catalog import DesktopToolCatalog
from src.tools.builtin_policy import BuiltinToolPolicy


def test_builtin_readiness_is_rechecked_after_cached_merge():
    config = Config()
    config.browser.enabled = True
    ready = {"browser_read_page": True, "run_command": True}
    policy = BuiltinToolPolicy(lambda: config, lambda: ready)
    catalog = DesktopToolCatalog(
        builtin_policy=policy, get_config=lambda: config,
        skill_manager=SimpleNamespace(get_tool_definitions=lambda: []),
        computer_available=lambda: False,
    )
    names = {tool["name"] for tool in catalog.merged_definitions()}
    assert {"browser_read_page", "run_command"} <= names
    assert "browser_screenshot" not in names
    ready["browser_read_page"] = False
    names = {tool["name"] for tool in catalog.merged_definitions()}
    assert "browser_read_page" not in names
    assert "run_command" in names


def test_qualified_skill_and_mcp_merge_cannot_shadow_unready_builtin():
    config = Config()
    def definition(name):
        return {"name": name, "description": "fixture",
                "input_schema": {"type": "object", "properties": {}}}
    skills = [definition("run_command"), definition("sample_skill")]
    mcp = [definition("run_command"), definition("sample_skill"), definition("mcp_sample")]
    catalog = DesktopToolCatalog(
        builtin_policy=BuiltinToolPolicy(lambda: config, lambda: {}),
        get_config=lambda: config,
        skill_manager=SimpleNamespace(get_tool_definitions=lambda: skills),
        get_mcp_definitions=lambda: mcp,
        computer_available=lambda: False,
    )
    assert [tool["name"] for tool in catalog.merged_definitions()] == [
        "sample_skill", "mcp_sample",
    ]
    skills.clear()
    mcp.clear()
    catalog.invalidate()
    assert catalog.merged_definitions() == []
