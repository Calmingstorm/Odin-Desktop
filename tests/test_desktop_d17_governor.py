"""D17 uses Odin's admin governor, with inert transport and original audit."""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.audit.logger import AuditLogger
from src.config.schema import GovernorConfig, ToolsConfig
from src.discord.tool_loop import ToolLoopRunner
from src.tools.risk_classifier import (
    CommandFacts,
    CommandGovernor,
    RiskAssessment,
    RiskLevel,
    classify_command,
)
from tests.desktop_adapters.tools_cases import ToolExecutor, owner_fixture, owner_id

# Harmless classifier false positives. Never submit a destructive shell string.
CRITICAL_INSPECTION = "printf '%s' 'mkfs documentation'"


def test_owner_override_is_enabled_by_default():
    assert GovernorConfig().owner_can_override is True


@pytest.mark.parametrize("override", [True, False])
@pytest.mark.parametrize("level,exfil,floor,force,host_policy", [
    (RiskLevel.LOW, False, None, None, ""),
    (RiskLevel.CRITICAL, False, RiskLevel.CRITICAL, None, ""),
    (RiskLevel.CRITICAL, True, RiskLevel.CRITICAL, None, ""),
    (RiskLevel.HIGH, False, RiskLevel.HIGH, "fixture-force-form", ""),
    (RiskLevel.HIGH, False, RiskLevel.HIGH, None, "strict"),
    (RiskLevel.CRITICAL, False, RiskLevel.HIGH, None, "strict"),
])
def test_owner_matches_baseline_admin_precedence(
    tmp_path, monkeypatch, override, level, exfil, floor, force, host_policy,
):
    # Exercise the original decision matrix without constructing or executing
    # attack commands. Only classifier facts are injected; governor is real.
    import src.tools.risk_classifier as risk

    monkeypatch.setattr(risk, "assess_command", lambda _command: CommandFacts(
        RiskAssessment(level, "inert fixture"), "fixture", exfil, floor, exfil,
    ))
    monkeypatch.setattr(risk, "detect_unconditional_git_force_push", lambda _command: force)
    overrides = {"lab": host_policy} if host_policy else {}
    config = ToolsConfig(governor=GovernorConfig(
        owner_can_override=override, host_overrides=overrides,
    ))
    with owner_fixture(tmp_path):
        executor = ToolExecutor(config)
        expected = CommandGovernor(admin_can_override=override, host_overrides=overrides).check(
            "printf ready", user_tier="admin", host="lab",
        )
        allowed, denial, note = executor._govern_command("printf ready", "lab")
        assert allowed is expected.allowed
        assert denial == ("" if expected.allowed else expected.denial_message())
        if expected.allowed and expected.risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            assert expected.reason in note
        else:
            assert note == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [True, False])
async def test_owner_critical_override_matches_baseline_and_audit(tmp_path, caplog, override):
    config = ToolsConfig(
        hosts={"lab": {"address": "127.0.0.1"}}, default_host="lab",
        governor=GovernorConfig(owner_can_override=override),
    )
    with owner_fixture(tmp_path) as state:
        executor = ToolExecutor(config)
        transport = AsyncMock(return_value=(0, "mkfs documentation"))
        executor._exec_command = transport
        assert classify_command(CRITICAL_INSPECTION).level == RiskLevel.CRITICAL
        # Classifier is the byte-identical baseline module. Compare actual
        # executor identity/config plumbing to Odin's explicit admin call.
        baseline = CommandGovernor(admin_can_override=override).check(
            CRITICAL_INSPECTION, user_tier="admin", host="lab",
        )
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            allowed, denial, note = executor._govern_command(CRITICAL_INSPECTION, "lab")
        assert allowed is baseline.allowed is override
        if override:
            assert "admin override" in note and "critical risk" in note
            assert denial == ""
            assert "admin override, critical" in caplog.text
            assert executor.command_governor.stats.get_summary()["allowed_high_risk"] == 1
        else:
            assert note == "" and "blocked" in denial.lower()
            assert executor.command_governor.stats.get_summary()["blocked"] == 1
        result = await executor.execute("run_command", {
            "host": "lab", "command": CRITICAL_INSPECTION,
        }, user_id=owner_id())
        assert result.ok is override
        assert transport.await_count == (1 if override else 0)
        if override:
            assert "admin override" in result.output

        # Exercise the retained terminal audit writer, not a fabricated row.
        audit_path = state.paths.data_dir / "d17-audit.jsonl"
        runner = ToolLoopRunner.__new__(ToolLoopRunner)
        runner._audit = AuditLogger(str(audit_path))
        turn = SimpleNamespace(message=SimpleNamespace(
            author=SimpleNamespace(id=owner_id()), channel=SimpleNamespace(id="conversation"),
            id="turn",), iteration=1)
        await runner._audit_tool_outcome(
            turn, "run_command", {"host": "lab", "command": CRITICAL_INSPECTION},
            result.output, 1, None if result.ok else result.error, result, call_id="d17-call",
        )
        rows = [json.loads(line) for line in audit_path.read_text().splitlines()]
        execution = next(row for row in rows if row.get("tool_name") == "run_command")
        assert execution["risk_level"] == "critical"
        if override:
            assert "admin override" in execution["result_summary"]


@pytest.mark.parametrize("identity", [None, "payload-owner"])
def test_non_owner_never_acquires_admin_override(tmp_path, identity):
    with owner_fixture(tmp_path):
        executor = ToolExecutor()
        executor.set_user_context(identity)
        allowed, denial, note = executor._govern_command(CRITICAL_INSPECTION, "lab")
        assert not allowed and denial and not note
