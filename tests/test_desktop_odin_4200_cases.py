"""Odin 4.20.0 (PR #671) in Desktop: the 4.20.0 versions of superseded frozen cases.

- Three frozen TestSearchAudit cases in tests/test_native_knowledge.py answered only
  ``audit.search``; Odin 4.20.0 reads calls from the audit stream. Odin's 4.20.0 class
  (all five cases) runs here with the frozen suite's own ``_tools`` helper. The frozen cases
  are retired in tests/desktop_adapters/odin_4200_native_knowledge.py.
- tests/test_campaign_system_coverage_restore.py's test_local_start_refusal_releases_unowned_lease
  asserted that the handler releases a refused start's lease; in Odin 4.20.0 the registry owns
  the lease from the start call on. Its 4.20.0 version runs here on the frozen suite's own
  ``system`` fixture; the frozen case is deselected by the reviewed direct-shared-engine
  exclusion. tests/test_desktop_agent_start_ownership.py drives the real registry's release.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.test_campaign_system_coverage_restore import system  # noqa: F401 (fixture)
from tests.test_native_knowledge import _tools


def _audit_with(entries):
    """An audit double that streams *entries* newest first, like AuditLogger."""
    audit = MagicMock()

    async def newest_first():
        for entry in entries:
            yield entry

    audit.iter_entries_newest_first = newest_first
    return audit


class TestSearchAudit:
    async def test_no_results(self):
        out = await _tools(audit=_audit_with([]))._handle_search_audit({})
        assert "No audit log entries" in out

    async def test_formats_entries(self):
        a = _audit_with([
            {"timestamp": "2026-07-07T12:00:00Z", "tool_name": "run_command",
             "user_name": "aaron", "approved": True, "execution_time_ms": 12,
             "result_summary": "ok"},
            {"timestamp": "2026-07-07T12:01:00Z", "tool_name": "x",
             "user_name": "u", "approved": False, "error": "boom"},
        ])
        out = await _tools(audit=a)._handle_search_audit({"limit": 5})
        assert "2 calls" in out and "run_command" in out and "ERROR: boom" in out

    async def test_filters_coerce_their_values(self):
        a = _audit_with([
            {"timestamp": "2026-07-07T12:00:00Z", "tool_name": "run_command",
             "user_name": "aaron", "approved": True, "execution_time_ms": 12,
             "result_summary": "ok"},
            {"timestamp": "2026-07-07T12:01:00Z", "tool_name": "x",
             "user_name": "u", "approved": True, "execution_time_ms": 9, "error": "boom"},
        ])
        out = await _tools(audit=a)._handle_search_audit(
            {"has_error": 1, "min_duration_ms": "5", "limit": 5})
        assert "(1 call)" in out and "ERROR: boom" in out and "run_command" not in out

    async def test_renders_agent_attribution_and_tool_input(self):
        a = _audit_with([
            {"timestamp": "2026-07-07T12:00:00Z", "tool_name": "run_command",
             "user_name": "aaron", "approved": True, "execution_time_ms": 12,
             "result_summary": "ok", "agent_id": "agent-1", "agent_label": "reviewer",
             "parent_agent_id": "parent-1", "root_agent_id": "root-1",
             "originating_turn_id": "turn-1", "iteration": 2, "call_id": "call-1",
             "status": "success", "tool_input": {"command": "git status"}},
        ])
        out = await _tools(audit=a)._handle_search_audit({})
        assert 'attribution={"agent_id": "agent-1"' in out
        assert '"iteration": 2' in out and 'tool_input={"command": "git status"}' in out

    async def test_renders_audit_metadata(self):
        # A later "which backend?" lookup surfaces the structured record.
        a = _audit_with([
            {"timestamp": "2026-07-07T12:00:00Z", "tool_name": "generate_image",
             "user_name": "aaron", "approved": True, "execution_time_ms": 63000,
             "result_summary": "Image generated (1536x1024, 800 KB) and posted.",
             "audit_metadata": {"backend": "openai", "route": "auto_native",
                                "decoded_width": 1536, "decoded_height": 1024}},
        ])
        out = await _tools(audit=a)._handle_search_audit({"tool_name": "generate_image"})
        assert "backend=openai" in out and "route=auto_native" in out


@pytest.mark.asyncio
async def test_local_start_refusal_leaves_the_lease_to_the_registry(system):  # noqa: F811
    # The registry owns the lease from the start call on: it releases it on
    # every refusal (tests/test_desktop_agent_start_ownership.py drives the real one).
    handler, registry, _, lease = system
    registry.start.return_value = "Cannot start fixture"
    result = await handler._handle_manage_process({"action": "start", "host": "fake",
                                                   "command": "fixture"})
    assert result == ("Cannot start fixture", 1)
    lease.release.assert_not_called()
