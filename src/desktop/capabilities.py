"""Capability readiness never substitutes for execution authorization."""
from collections.abc import Mapping


def publish_capabilities(
    tools: list[dict], readiness: Mapping[str, bool] | None = None
) -> list[dict]:
    ready = readiness or {}
    return [tool for tool in tools if ready.get(tool.get("name")) is True]
