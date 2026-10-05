"""Storage defaults do not claim Phase 2 readiness; D17 keeps open ACL fallback."""

from unittest.mock import Mock

from src.config.schema import ToolHost, ToolsConfig
from src.runtime_paths import runtime_profile_paths
from src.tools.executor import ToolExecutor


async def test_default_executor_resolves_fresh_profile_but_denies_unbound_effects(monkeypatch):
    executor = ToolExecutor(
        config=ToolsConfig(hosts={"local": ToolHost(address="127.0.0.1")})
    )
    assert executor.host_registry._trust_dir.is_relative_to(runtime_profile_paths().data_dir)
    assert executor.check_permission("run_command", None) is None
    dispatch = Mock(side_effect=AssertionError("unwired capability reached a handler"))
    monkeypatch.setattr(executor, "_resolve_handler", dispatch)
    result = await executor.execute("run_command", {"host": "local", "command": "true"})
    assert not result.ok
    assert result.error == "tool_unavailable"
    assert "no ready handler" in result.output.lower()
    dispatch.assert_not_called()
