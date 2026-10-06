"""Retained catalog composition with live qualification, not saved-config proof.

Skills and MCP supply only their qualified definitions. Native built-in names
stay reserved even when unavailable. Part B consumes this same catalog after
binding genuine request authority; publication never supplies that authority.
"""
from __future__ import annotations

from ..discord.tool_catalog import ToolCatalog
from ..tools.builtin_policy import BUILTIN_TOOL_NAMES
from ..tools.registry import PHASE1_EXECUTOR_TOOL_NAMES, get_tool_definitions


class DesktopToolCatalog(ToolCatalog):
    def __init__(self, *, builtin_policy, **kwargs):
        super().__init__(get_builtin_definitions=lambda: get_tool_definitions(
            readiness={name: builtin_policy.is_available(name)
                       for name in PHASE1_EXECUTOR_TOOL_NAMES}), **kwargs)
        self.builtin_policy = builtin_policy

    def merged_definitions(self, *, cache_result: bool = True) -> list[dict]:
        # Recheck after the retained merge, including its cache. A disconnected
        # browser or revoked generation must disappear without a cache refresh.
        definitions = super().merged_definitions(cache_result=cache_result)
        return [definition for definition in definitions
                if definition["name"] not in BUILTIN_TOOL_NAMES
                or self.builtin_policy.is_available(definition["name"])]
