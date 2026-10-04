"""Selected profile defaults are storage identity, never effect authority."""

from src.config.schema import ToolHost, ToolsConfig
from src.runtime_paths import runtime_profile_paths
from src.tools.executor import ToolExecutor


async def test_default_executor_resolves_fresh_profile_but_denies_unbound_effects():
    executor = ToolExecutor(
        config=ToolsConfig(hosts={"local": ToolHost(address="127.0.0.1")})
    )
    assert executor.host_registry._trust_dir.is_relative_to(runtime_profile_paths().data_dir)
    result = await executor.execute("run_command", {"host": "local", "command": "true"})
    assert not result.ok
    assert "owner" in result.output.lower()
