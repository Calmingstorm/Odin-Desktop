"""Desktop authority adaptation; no host/process/graphical effects."""
import ast
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.desktop.authority import OwnerAuthority
from src.desktop.errors import CapabilityUnavailable
from src.desktop.paths import ProfilePaths
from src.permissions.manager import PermissionManager
from src.tools.browser import BrowserManager
from src.tools.builtin_policy import BuiltinToolPolicy
from src.tools.executor import ToolExecutor
from src.tools.handlers.state import StateTools
from src.tools.output_authorization import (
    owner_output_scope,
    request_scope_authorizer,
    tool_scope_allows,
)
from src.tools.risk_classifier import CommandGovernorResult, RiskLevel


@pytest.fixture
def owner(tmp_path):
    paths = ProfilePaths.from_xdg(environ={
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }, home=tmp_path)
    authority = OwnerAuthority(paths)
    manager = PermissionManager(authority)
    return authority, manager, authority.authenticate_local(peer_uid=os.geteuid())


def bare_executor(manager=None, readiness=None):
    executor = ToolExecutor.__new__(ToolExecutor)
    executor._permission_manager = manager
    executor._builtin_policy = BuiltinToolPolicy(lambda: SimpleNamespace(), lambda: readiness or {})
    return executor


def test_no_manager_is_not_privileged():
    assert bare_executor().check_permission("run_command", "owner")


def test_payload_identity_does_not_confer_authority(owner):
    authority, manager, _ = owner
    assert bare_executor(manager).check_permission("run_command", authority.owner_id)


def test_only_sealed_owner_context_is_accepted(owner):
    authority, manager, context = owner
    executor = bare_executor(manager)
    for candidate in (replace(context, _seal=object()), replace(context, runtime_id="foreign")):
        token = manager.set_request_owner(candidate)
        try:
            assert executor.check_permission("run_command", authority.owner_id)
        finally:
            manager.reset_request_owner(token)
    token = manager.set_request_owner(context)
    try:
        assert executor.check_permission("run_command", authority.owner_id) is None
        assert executor.check_permission("run_command", "another-owner")
    finally:
        manager.reset_request_owner(token)


@pytest.mark.asyncio
async def test_unconfigured_dispatch_denies_before_handler_or_host(owner):
    authority, manager, context = owner
    executor = bare_executor(manager)
    def forbidden(*args, **kwargs):
        pytest.fail("unauthorized execution reached host or handler")
    executor._resolve_handler = forbidden
    executor._acquire_host = forbidden
    token = manager.set_request_owner(context)
    try:
        result = await executor.execute("run_command", {"host": "lab", "command": "printf ready"},
                                        user_id=authority.owner_id)
    finally:
        manager.reset_request_owner(token)
    assert not result.ok and result.error == "tool_unavailable"


@pytest.mark.asyncio
async def test_model_owner_fields_do_not_admit_dispatch(owner):
    authority, manager, _ = owner
    executor = bare_executor(manager, {"run_command": True})
    result = await executor.execute("run_command", {"command": "printf ready",
        "owner_id": authority.owner_id, "owner_authorized": True}, user_id=authority.owner_id)
    assert not result.ok and result.error == "permission_denied"


def test_small_output_retention_requires_authentication(owner):
    authority, manager, _ = owner
    executor = bare_executor(manager, {"run_command": True})
    with pytest.raises(CapabilityUnavailable):
        executor.deliver_output("ready", tool_name="run_command", tool_input={},
                                user_id=authority.owner_id)


def test_output_origin_readiness_revocation_denies(owner):
    authority, manager, context = owner
    readiness = {"run_command": True}
    executor = bare_executor(manager, readiness)
    token = manager.set_request_owner(context)
    try:
        assert executor._authorize_output("run_command", (), authority.owner_id)
        readiness["run_command"] = False
        assert not executor._authorize_output("run_command", (), authority.owner_id)
    finally:
        manager.reset_request_owner(token)


def test_live_scope_revocation_is_not_snapshot():
    allowed = {"read_file"}
    token = request_scope_authorizer.set(lambda: allowed)
    try:
        assert tool_scope_allows("read_file")
        allowed.clear()
        assert not tool_scope_allows("read_file")
    finally:
        request_scope_authorizer.reset(token)


def test_phase2_scope_cannot_be_minted_from_arguments():
    with pytest.raises(CapabilityUnavailable):
        with owner_output_scope(conversation_id="foreign", owner_id="owner"):
            pytest.fail("unadmitted scope entered")


def test_governor_identity_is_not_exact_action_approval():
    executor = bare_executor()
    calls = []
    def check(command, **kwargs):
        calls.append(kwargs)
        return CommandGovernorResult(True, RiskLevel.LOW, "inspection")
    executor.command_governor = SimpleNamespace(check=check)
    assert executor._govern_command("printf ready", "lab")[0]
    assert calls == [{"user_tier": None, "host": "lab"}]
    executor.command_governor = None
    assert not executor._govern_command("printf ready", "lab")[0]


@pytest.mark.asyncio
async def test_native_browser_requires_explicit_bundled_binary():
    manager = BrowserManager()
    with pytest.raises(RuntimeError, match="required bundled Chromium"):
        await manager._ensure_connected()
    assert manager._playwright is None


def test_common_classifier_functions_remain_byte_identical():
    root = Path(__file__).resolve().parents[1]
    baseline = subprocess.check_output(["git", "show",
        "refs/baselines/odin-v4.13.0:src/tools/risk_classifier.py"], cwd=root, text=True)
    current = (root / "src/tools/risk_classifier.py").read_text()
    def functions(source):
        lines = source.splitlines(keepends=True)
        return {node.name: "".join(lines[node.lineno-1:node.end_lineno])
                for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
    assert functions(current) == functions(baseline)
    def governor(source):
        lines = source.splitlines(keepends=True)
        node = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.ClassDef) and node.name == "CommandGovernor")
        return "".join(lines[node.lineno-1:node.end_lineno])
    assert governor(current) == governor(baseline)


def test_common_safety_primitives_byte_identical():
    root = Path(__file__).resolve().parents[1]
    for name in ("effect_classifier.py", "command_shapes.py", "command_authority.py",
                 "local_supervisor.py", "local_supervisor_worker.py", "execution_outcome.py",
                 "workspace.py", "ssh.py", "ssh_pool.py", "process_manager.py"):
        baseline = subprocess.check_output(["git", "show",
            f"refs/baselines/odin-v4.13.0:src/tools/{name}"], cwd=root)
        assert (root / "src/tools" / name).read_bytes() == baseline


def test_attempt_settlement_and_no_replay_logic_byte_identical():
    root = Path(__file__).resolve().parents[1]
    baseline = subprocess.check_output(["git", "show",
        "refs/baselines/odin-v4.13.0:src/tools/executor.py"], cwd=root, text=True)
    current = (root / "src/tools/executor.py").read_text()
    def attempt(source):
        lines = source.splitlines(keepends=True)
        cls = next(node for node in ast.parse(source).body
                   if isinstance(node, ast.ClassDef) and node.name == "ToolExecutor")
        node = next(node for node in cls.body
                    if isinstance(node, ast.AsyncFunctionDef) and node.name == "_try_tool")
        return "".join(lines[node.lineno-1:node.end_lineno])
    assert attempt(current) == attempt(baseline)


def test_lists_do_not_import_legacy_user_data(tmp_path):
    tools = StateTools.__new__(StateTools)
    tools._deps = SimpleNamespace(memory_path=lambda: tmp_path / "memory.json")
    (tmp_path / "grocery_list.json").write_text('{"items":[{"name":"historical"}]}')
    assert tools._load_lists() == {}
    assert not (tmp_path / "lists.json").exists()


@pytest.mark.asyncio
async def test_probe_missing_host_has_no_root_default():
    from src.tools.handlers.browser_web import BrowserWebTools
    deps = SimpleNamespace(
        resolve_host=lambda *args: None,
        acquire_host=lambda *args: pytest.fail("probe acquired unmanaged host"),
        resolve_default_host=lambda owner: "",
        govern_command=lambda *args: None,
        exec_command=lambda *args, **kwargs: pytest.fail("probe executed without target"),
        run_on_host=lambda *args: None,
        annotate_with_freshness=lambda *args: None,
        current_user_id=lambda: "owner",
    )
    tools = BrowserWebTools(deps)
    output, code = await tools._handle_http_probe({"url": "https://example.com"})
    assert code == 1 and "authorized managed host" in output
