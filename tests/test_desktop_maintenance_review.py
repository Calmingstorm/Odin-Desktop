"""PR 2 items 5-7: frozen safety policy, Linux local check and reservations.

Only immutable archive bytes, temporary skill/profile paths and mocked host
commands are used. No endpoints, subprocesses or native desktop lifecycle.
"""

from __future__ import annotations

import hashlib
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.tools.builtin_policy import BUILTIN_TOOL_NAMES, BuiltinToolPolicy
from src.tools.hosts import HostEnrollmentManager, HostRegistry
from src.tools.recovery import (
    UNSAFE_TO_RETRY,
    RecoveryCategory,
    classify_error,
    decide_recovery_action,
    executor_execution_budget,
)
from src.tools.registry import PHASE1_EXECUTOR_TOOL_NAMES, TOOLS, get_tool_definitions
from src.tools.risk_classifier import RiskLevel, classify_tool
from src.tools.skill_manager import SkillManager

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_SHA256 = "845d783bd4ee46cd44e63d56532512fd9cef10d08b1432e45047d155c6b348d0"
RETIRED = ("add_reaction", "create_poll", "purge_messages", "set_permission")
COMPUTER = ("computer_session", "computer_observe", "computer_act")


@pytest.mark.parametrize("path", ["src/tools/risk_classifier.py", "src/tools/recovery.py"])
def test_safety_policy_is_byte_identical_to_immutable_v413_archive(path):
    archive = ROOT / "maintenance/odin-v4.13.0.tar.gz"
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == ARCHIVE_SHA256
    with tarfile.open(archive, "r:gz") as frozen:
        source = frozen.extractfile(path)
        assert source is not None
        assert (ROOT / path).read_bytes() == source.read()


def _skill_code(name):
    return (
        f'SKILL_DEFINITION = {{"name": "{name}", "description": "harmless fixture", '
        '"input_schema": {"type": "object", "properties": {}}}\n'
        'async def execute(inp, context):\n'
        '    return "Error: Connection refused"\n'
    )


@pytest.mark.parametrize("name", RETIRED)
async def test_retired_named_skill_preserves_baseline_risk_and_no_retry(tmp_path, name):
    assert name not in {tool["name"] for tool in TOOLS}
    assert name not in BUILTIN_TOOL_NAMES
    manager = SkillManager(str(tmp_path), SimpleNamespace())
    manager.create_skill(name, _skill_code(name))
    assert name in manager._skills
    skill = manager._skills[name]
    output = await skill.execute_fn({}, None)
    assert output == "Error: Connection refused"
    # Static classification is name based even when dispatch resolves to a
    # user skill. Catalog removal must not silently change that policy.
    expected = RiskLevel.MEDIUM if name == "add_reaction" else RiskLevel.LOW
    assert classify_tool(skill.name, {}).level == expected
    assert skill.name in UNSAFE_TO_RETRY
    category = classify_error(output)
    assert category == RecoveryCategory.SSH_TRANSIENT
    assert decide_recovery_action(tool_name=skill.name, category=category).action == "skip"
    assert executor_execution_budget(skill.name, 5, recovery_enabled=True) == 5
    assert decide_recovery_action(
        tool_name=skill.name, category=RecoveryCategory.AUTH_FAILURE
    ).action == "hint"


def test_unlisted_name_control_retains_default_risk_and_retry():
    assert classify_tool("harmless_fixture", {}).level == RiskLevel.LOW
    assert decide_recovery_action(
        tool_name="harmless_fixture", category=RecoveryCategory.SSH_TRANSIENT
    ).action == "retry"
    assert executor_execution_budget("harmless_fixture", 5, recovery_enabled=True) > 5


@pytest.mark.parametrize("selected_os,ok", [("linux", True), ("macos", False)])
async def test_local_host_check_uses_baseline_linux_command(tmp_path, monkeypatch, selected_os, ok):
    run = AsyncMock(return_value=(0, b"odin-host-test linux\n"))
    monkeypatch.setattr("src.tools.hosts.control._run_argv", run)
    manager = HostEnrollmentManager(HostRegistry({}, trust_dir=tmp_path))
    candidate = await manager.prepare(
        "local",
        {"address": "127.0.0.1", "os": selected_os, "confirm_local": True},
        allow_tofu=False,
    )
    tested = await manager.test(candidate.token)
    run.assert_awaited_once_with(
        ["sh", "-c", "printf 'odin-host-test linux\\n'"], 15.0
    )
    assert tested.test_result["ok"] is ok
    if not ok:
        assert "observed linux; selected macos" in tested.test_result["detail"]


@pytest.mark.parametrize("name", COMPUTER)
def test_computer_names_remain_reserved_even_with_fabricated_readiness(name):
    assert name in BUILTIN_TOOL_NAMES
    assert name not in PHASE1_EXECUTOR_TOOL_NAMES
    assert name not in {tool["name"] for tool in TOOLS}
    readiness = {name: True}
    assert name not in {tool["name"] for tool in get_tool_definitions(readiness=readiness)}
    policy = BuiltinToolPolicy(
        lambda: SimpleNamespace(tools=SimpleNamespace(disabled_tools=[])), lambda: readiness
    )
    assert not policy.is_available(name)
