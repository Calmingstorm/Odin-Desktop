from __future__ import annotations

import copy
from collections.abc import Mapping

from .defs.agents import TOOLS_SECTION as _AGENTS
from .defs.browser_web import TOOLS_SECTION as _BROWSER_WEB
from .defs.channel_process_loops import TOOLS_SECTION as _CHANNEL_PROCESS_LOOPS
from .defs.integrations_email import TOOLS_SECTION as _INTEGRATIONS_EMAIL
from .defs.media_scheduling import TOOLS_SECTION as _MEDIA_SCHEDULING
from .defs.memory_skills import TOOLS_SECTION as _MEMORY_SKILLS
from .defs.output_delivery import TOOLS_SECTION as _OUTPUT_DELIVERY
from .defs.system_files import TOOLS_SECTION as _SYSTEM_FILES
from .defs.tasks_knowledge import TOOLS_SECTION as _TASKS_KNOWLEDGE

# RFC-004 P1: TOOLS is the exact-order concatenation of the section
# slices in src/tools/defs/. ORDER IS BEHAVIOR (prompt catalog) — the
# characterization contract (test_tool_parity) pins the full order, and
# sections are positional slices, never semantic regroupings.
TOOLS: list[dict] = [
    *_SYSTEM_FILES,
    *_MEDIA_SCHEDULING,
    *_MEMORY_SKILLS,
    *_TASKS_KNOWLEDGE,
    *_BROWSER_WEB,
    *_CHANNEL_PROCESS_LOOPS,
    *_AGENTS,
    *_INTEGRATIONS_EMAIL,
    *_OUTPUT_DELIVERY,
]

TOOL_MAP: dict[str, dict] = {t["name"]: t for t in TOOLS}

# RFC-004 P7 startup assertion (plan advisory #5): duplicate names in the
# section slices would collapse silently in TOOL_MAP — fail at import
# instead. (The exact count/order is pinned by the characterization
# contract, where changing it is a reviewed edit rather than a prod crash.)
assert len(TOOL_MAP) == len(TOOLS), "duplicate tool name across defs/ sections"

# Phase 1 imports real executor handler domains, not native/durable consumer
# wiring. This set pins the retained handler table; readiness cannot fabricate
# a Phase 2 handler. Dependencies being bundled does not bypass this boundary.
PHASE1_EXECUTOR_TOOL_NAMES: frozenset[str] = frozenset({
    "get_tool_output", "run_command", "run_script", "run_command_multi",
    "read_file", "apply_patch", "memory_manage", "manage_list", "manage_process",
    "browser_read_page", "browser_read_table", "browser_click", "browser_fill",
    "browser_evaluate", "web_search", "fetch_url", "http_probe", "analyze_pdf",
    "validate_action", "email_send", "email_search", "email_read", "email_list_recent",
})

# NOTE: the old MUTATING_TOOLS / READ_ONLY_TOOLS frozensets were removed — they
# were imported only by a schema test and NOT consulted by any runtime
# authorization path (the governor uses risk_classifier; mutation detection uses
# post_validation.detect_mutation). Keeping them was an approval-bypass trap: a
# reviewer moving a tool between the sets would think they'd changed
# authorization while nothing actually changed.


# Cache for get_tool_definitions — avoids rebuilding dicts on every message.
_tool_defs_cache: list[dict] | None = None


def get_documentation_tool_definitions(command_shell: str | None = None) -> list[dict]:
    """Return the static documentation catalog, NOT an execution publication.

    Each description is decorated with an affordance footer (cost / risk /
    latency / preconditions) so the LLM can price a call before making it.

    Results are cached. Call invalidate_tool_defs_cache()
    if TOOLS list is modified at runtime (e.g. by tests).
    Explicit command_shell decorates fresh local facts; None is the stable,
    host-independent documentation catalog. Live publication must use
    get_tool_definitions with explicit readiness from the owning engine.
    Clones keep one profile's schema edits out of another profile's catalog.
    """
    from .affordances import decorate_description

    global _tool_defs_cache
    if _tool_defs_cache is None:
        _tool_defs_cache = [
            {
                "name": t["name"],
                "description": decorate_description(t["name"], t["description"]),
                "input_schema": t["input_schema"],
                **({"is_core": True} if t.get("is_core") else {}),
            }
            for t in TOOLS
        ]
    if command_shell is None:
        return copy.deepcopy(_tool_defs_cache)
    from .command_shell import apply_shell_contracts

    return apply_shell_contracts(copy.deepcopy(_tool_defs_cache), command_shell)


def get_tool_definitions(
    command_shell: str | None = None, *, readiness: Mapping[str, bool] | None = None,
) -> list[dict]:
    """Publish only tools with explicit live readiness, never the static catalog.

    Missing readiness fails closed. Installed dependencies and documented
    schemas do not establish configured handlers or execution authority.
    Publication does not replace the dispatch-time owner and readiness checks.
    """
    from ..desktop.capabilities import publish_capabilities

    return publish_capabilities(
        [tool for tool in get_documentation_tool_definitions(command_shell)
         if tool["name"] in PHASE1_EXECUTOR_TOOL_NAMES],
        {} if readiness is None else readiness,
    )


def invalidate_tool_defs_cache() -> None:
    """Clear the tool definitions cache.

    Call after modifying TOOLS at runtime (e.g. in tests) or after
    config changes that affect tool availability.
    """
    global _tool_defs_cache
    _tool_defs_cache = None
