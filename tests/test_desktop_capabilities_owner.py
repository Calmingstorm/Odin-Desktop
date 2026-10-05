"""Desktop authority adaptation; no host/process/graphical effects."""
import ast
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.config.schema import ToolHost, ToolsConfig
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


@pytest.mark.parametrize("identity", [None, "", "owner"])
def test_no_manager_matches_upstream_open_default(identity):
    assert bare_executor().check_permission("run_command", identity) is None


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


def test_governor_uses_admin_only_for_authenticated_owner(owner):
    authority, manager, context = owner
    executor = bare_executor(manager)
    calls = []
    def check(command, **kwargs):
        calls.append(kwargs)
        return CommandGovernorResult(True, RiskLevel.LOW, "inspection")
    executor.command_governor = SimpleNamespace(check=check)
    executor.set_user_context(authority.owner_id)
    assert executor._govern_command("printf ready", "lab")[0]
    assert calls == [{"user_tier": None, "host": "lab"}]
    token = manager.set_request_owner(context)
    try:
        assert executor._govern_command("printf ready", "lab")[0]
        assert calls[-1] == {"user_tier": "admin", "host": "lab"}
        executor.set_user_context("non-owner")
        assert executor._govern_command("printf ready", "lab")[0]
        assert calls[-1] == {"user_tier": None, "host": "lab"}
    finally:
        manager.reset_request_owner(token)
        executor.set_user_context(None)
    executor.command_governor = None
    assert executor._govern_command("printf ready", "lab") == (True, "", "")


@pytest.mark.asyncio
async def test_native_browser_requires_explicit_bundled_binary():
    manager = BrowserManager()
    with pytest.raises(RuntimeError, match="required bundled Chromium"):
        await manager._ensure_connected()
    assert manager._playwright is None


def test_common_classifier_functions_remain_byte_identical():
    root = Path(__file__).resolve().parents[1]
    from scripts.maintenance.inventory import baseline_blobs

    baseline = baseline_blobs(root)["src/tools/risk_classifier.py"].decode()
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
    from scripts.maintenance.inventory import baseline_blobs

    blobs = baseline_blobs(root)
    for name in ("effect_classifier.py", "command_shapes.py", "command_authority.py",
                 "local_supervisor.py", "local_supervisor_worker.py", "execution_outcome.py",
                 "workspace.py", "ssh.py", "ssh_pool.py", "process_manager.py"):
        baseline = blobs[f"src/tools/{name}"]
        if name == "ssh_pool.py":
            # PR #14 requires no-follow, foreign-owner guards without a D17
            # permission-mode gate. Fence the exact provisioning adaptation;
            # every master/lease/settlement byte stays
            # upstream-identical, not a broad exemption for the SSH pool.
            changes = (
                (b"from ..odin_log import get_logger\n",
                 b"from ..desktop.paths import private_directory\n"
                 b"from ..odin_log import get_logger\n"),
                (b"        os.makedirs(self.socket_dir, mode=0o700, exist_ok=True)\n",
                 b"        private_directory(Path(os.path.abspath(self.socket_dir)), "
                 b"repair_namespace=False)\n"),
            )
            for before, after in changes:
                assert baseline.count(before) == 1
                baseline = baseline.replace(before, after, 1)
        assert (root / "src/tools" / name).read_bytes() == baseline


def test_attempt_settlement_and_no_replay_logic_byte_identical():
    root = Path(__file__).resolve().parents[1]
    from scripts.maintenance.inventory import baseline_blobs

    baseline = baseline_blobs(root)["src/tools/executor.py"].decode()
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


def probe_executor(owner, tmp_path, monkeypatch):
    """Real owner, real registry and dispatch; only the transport is stubbed."""
    authority, manager, _ = owner
    paths = ProfilePaths.from_xdg(environ={
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }, home=tmp_path)
    executor = ToolExecutor(
        config=ToolsConfig(
            hosts={"lab": ToolHost(address="::1", ssh_user="operator")},
            default_host="lab",
            audit_log_path=str(tmp_path / "audit.jsonl"),
        ),
        permission_manager=manager,
        profile_paths=paths,
        memory_path=str(tmp_path / "memory.json"),
    )
    executor._builtin_policy = BuiltinToolPolicy(
        lambda: SimpleNamespace(tools=executor.config), lambda: {"http_probe": True}
    )
    transport = AsyncMock(return_value=(0, "HTTP/1.1 200 OK"))
    monkeypatch.setattr(executor, "_exec_command", transport)
    assert executor.check_permission("http_probe", authority.owner_id)
    return executor, transport


@pytest.mark.asyncio
@pytest.mark.parametrize("host_input", [{}, {"host": None}, {"host": ""}])
async def test_probe_no_host_matches_upstream_local_fallback(
    owner, tmp_path, monkeypatch, host_input
):
    authority, manager, context = owner
    executor, transport = probe_executor(owner, tmp_path, monkeypatch)
    monkeypatch.setattr(executor, "_resolve_default_host", lambda *_: pytest.fail(
        "http_probe omission must not select a configured/default host"
    ))
    monkeypatch.setattr(executor, "_acquire_host", lambda *_: pytest.fail(
        "http_probe local fallback must not acquire a managed-host generation"
    ))
    token = manager.set_request_owner(context)
    try:
        result = await executor.execute(
            "http_probe", {"url": "https://example.invalid", **host_input},
            user_id=authority.owner_id,
        )
    finally:
        manager.reset_request_owner(token)
    assert result.ok and result.exit_code == 0
    call = transport.await_args
    assert call.args[0] == "127.0.0.1" and call.args[2] == "root"
    assert call.kwargs == {}
    transport.assert_awaited_once()


@pytest.mark.asyncio
async def test_probe_explicit_host_uses_authorized_generation(owner, tmp_path, monkeypatch):
    authority, manager, context = owner
    executor, transport = probe_executor(owner, tmp_path, monkeypatch)
    acquired = []
    acquire = executor._acquire_host

    def acquire_recorded(alias):
        lease = acquire(alias)
        acquired.append(lease)
        return lease

    monkeypatch.setattr(executor, "_acquire_host", acquire_recorded)
    token = manager.set_request_owner(context)
    try:
        result = await executor.execute(
            "http_probe", {"url": "https://example.invalid", "host": "lab"},
            user_id=authority.owner_id,
        )
    finally:
        manager.reset_request_owner(token)
    assert result.ok and result.exit_code == 0
    transport.assert_awaited_once()
    call = transport.await_args
    assert call.args[0] == "::1" and call.args[2] == "operator"
    assert call.kwargs == {"target": acquired[0].target}
    assert acquired[0].target.alias == "lab"
    assert acquired[0]._released


@pytest.mark.asyncio
async def test_probe_unknown_explicit_host_never_falls_back_locally(owner, tmp_path, monkeypatch):
    authority, manager, context = owner
    executor, transport = probe_executor(owner, tmp_path, monkeypatch)
    token = manager.set_request_owner(context)
    try:
        result = await executor.execute(
            "http_probe", {"url": "https://example.invalid", "host": "missing"},
            user_id=authority.owner_id,
        )
    finally:
        manager.reset_request_owner(token)
    assert not result.ok and "Unknown or disallowed host: missing" in result.output
    transport.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("host_input", [{}, {"host": "lab"}])
@pytest.mark.parametrize("identity", ["missing", "unsealed", "foreign"])
async def test_probe_requires_authenticated_owner_before_either_transport(
    owner, tmp_path, monkeypatch, host_input, identity
):
    authority, manager, context = owner
    executor, transport = probe_executor(owner, tmp_path, monkeypatch)
    user_id = None if identity == "missing" else authority.owner_id
    if identity == "foreign":
        user_id = "another-owner"
    token = manager.set_request_owner(context if identity != "unsealed" else None)
    try:
        result = await executor.execute(
            "http_probe", {"url": "https://example.invalid", **host_input}, user_id=user_id,
        )
    finally:
        manager.reset_request_owner(token)
    assert not result.ok and result.error == "permission_denied"
    transport.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("response, expected_code, expected_output", [
    ((7, ""), 7, "http_probe failed (exit 7): curl returned no output"),
    ((7, "curl: connection failed"), 7, "curl: connection failed"),
    ((0, ""), 1, "http_probe: no response received"),
])
async def test_local_probe_keeps_curl_failure_ground_truth(
    owner, tmp_path, monkeypatch, response, expected_code, expected_output
):
    authority, manager, context = owner
    executor, transport = probe_executor(owner, tmp_path, monkeypatch)
    transport.return_value = response
    executor._recovery_enabled = False
    token = manager.set_request_owner(context)
    try:
        result = await executor.execute(
            "http_probe", {"url": "https://example.invalid"}, user_id=authority.owner_id,
        )
    finally:
        manager.reset_request_owner(token)
    assert not result.ok and result.exit_code == expected_code
    assert result.output == expected_output
    transport.assert_awaited_once()
