"""Phase 1 pins: neutral imports, hard wiring gates, unchanged safety logic."""

import ast
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.maintenance.inventory import baseline_blobs

ROOT = Path(__file__).resolve().parents[1]


def _baseline(path):
    return baseline_blobs(ROOT)[path].decode()


def _methods(source, class_name):
    cls = next(node for node in ast.parse(source).body
               if isinstance(node, ast.ClassDef) and node.name == class_name)
    return {node.name: ast.get_source_segment(source, node) for node in cls.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_all_unadapted_loop_phase_bodies_are_byte_identical():
    path = "src/discord/tool_loop.py"
    baseline = _methods(_baseline(path), "ToolLoopRunner")
    desktop = _methods((ROOT / path).read_text(), "ToolLoopRunner")
    adapted = {
        "run", "run_resumed", "_prepare_chat_turn", "_scoped_tools_for_request",
        "_call_llm", "run_autonomous", "_finalize_loop", "__init__",
        "_run_one_tool_captured", "_audit_tool_outcome",
        # Step 6B replaces only the proxy/removed prompt parameter and adds
        # admitted owner checks. Real execution is exercised by background_core.
        "_prepare_loop_turn", "dispatch_loop_tool_inner",
    }
    assert baseline.keys() == desktop.keys()
    for name in baseline.keys() - adapted:
        assert desktop[name] == baseline[name], name


def test_resume_no_replay_revision_and_waiter_logic_is_byte_identical():
    path = "src/discord/turn_resume.py"
    baseline = _methods(_baseline(path), "TurnResumeManager")
    desktop = _methods((ROOT / path).read_text(), "TurnResumeManager")
    for name in (
        "_repair_unmatched_tool_use", "_unresolved_ops", "_auto_resume_waiter",
        "_session_revision", "_release_calibration", "_append_session",
    ):
        assert desktop[name] == baseline[name], name


def test_loop_policy_preserves_all_behavioral_asymmetries():
    path = "src/discord/tool_loop.py"
    before = ast.parse(_baseline(path))
    after = ast.parse((ROOT / path).read_text())
    for name in ("CHAT_POLICY", "AUTONOMOUS_POLICY"):
        old = next(node for node in before.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == name
                           for target in node.targets))
        new = next(node for node in after.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == name
                           for target in node.targets))
        if name == "CHAT_POLICY":
            next(keyword for keyword in old.value.keywords
                 if keyword.arg == "trajectory_source").value.value = "conversation"
        assert ast.dump(new) == ast.dump(old), name


def test_storage_helper_extraction_is_structurally_identical():
    before = ast.parse(_baseline("src/discord/tool_loop_helpers.py"))
    after = ast.parse((ROOT / "src/storage_redaction.py").read_text())
    for name in ("_deep_scrub_strings", "_scrub_tool_input_for_storage"):
        old = next(node for node in before.body
                   if isinstance(node, ast.FunctionDef) and node.name == name)
        new = next(node for node in after.body
                   if isinstance(node, ast.FunctionDef) and node.name == name)
        for node in ast.walk(old):
            if isinstance(node, ast.ImportFrom) and node.level == 2:
                node.level = 1
        assert ast.dump(new) == ast.dump(old), name


def test_neutral_import_tree_without_discord():
    # A clean interpreter is important: an already-imported fake transport
    # module must not conceal an operative dependency in this proof.
    code = '''
import importlib.abc, sys
class RejectTransport(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "discord" or fullname.startswith("discord."):
            raise AssertionError("operative transport import: " + fullname)
sys.meta_path.insert(0, RejectTransport())
import src.storage_redaction
import src.discord.tool_loop_helpers
import src.discord.tool_loop
import src.discord.turn_resume
assert "discord" not in sys.modules
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_uncomposed_execution_entrypoints_fail_before_any_dependency_access():
    from src.discord.tool_loop import (
        Phase2WiringRequired,
        ToolLoopRunner,
        _best_effort_typing,
        _LoopMessageProxy,
    )
    from src.discord.turn_resume import TurnResumeManager

    runner = ToolLoopRunner.__new__(ToolLoopRunner)
    with pytest.raises(Phase2WiringRequired):
        ToolLoopRunner(None)
    for operation in (
        runner.run(None, []), runner.run_resumed(None),
        runner._prepare_chat_turn(None, [], None, None, None),
        runner.run_autonomous("", None, None, "owner"),
    ):
        with pytest.raises(Phase2WiringRequired):
            await operation
    # Desktop presence is not transport input and publishes no model candidate.
    async with _best_effort_typing(None):
        pass
    with pytest.raises(Phase2WiringRequired):
        _LoopMessageProxy(None, "owner")
    with pytest.raises(Phase2WiringRequired):
        TurnResumeManager(store=None, tool_loop=None, llm_gateway=None,
                          channel_state=None, sessions=None, delivery=None,
                          permissions=None, tool_catalog=None, get_config=None,
                          fetch_message=None)
    manager = TurnResumeManager.__new__(TurnResumeManager)
    with pytest.raises(Phase2WiringRequired):
        manager.on_turn_suspended(None, "generation")
    with pytest.raises(Phase2WiringRequired):
        await manager.try_explicit_resume(None)
    with pytest.raises(Phase2WiringRequired):
        await manager._run_auto_resume(None, {}, set())


@pytest.mark.asyncio
@pytest.mark.parametrize("condition,expected,rejected", [
    ("denied", "The conversation store currently denies access to the original message", False),
    ("unavailable", "The conversation store could not fetch the original message yet", False),
    ("missing", "the original message is gone", True),
    ("empty", "the original message could not be fetched yet", False),
    ("timeout", "the original message could not be fetched yet", False),
    ("other", "the original message could not be fetched yet", False),
    ("generic_permission", "the original message could not be fetched yet", False),
])
async def test_resume_receipts_match_actual_store_conditions(condition, expected, rejected):
    from src.discord.turn_resume import (
        ConversationAccessDenied,
        ConversationFetchUnavailable,
        ConversationMessageNotFound,
        TurnResumeManager,
    )
    from src.turn_state.store import TurnKey

    errors = {
        "denied": ConversationAccessDenied(),
        "unavailable": ConversationFetchUnavailable(),
        "missing": ConversationMessageNotFound(),
        "timeout": TimeoutError(), "other": RuntimeError(),
        "generic_permission": PermissionError(),
    }
    async def fetch(*args):
        if condition in errors:
            raise errors[condition]
        return None

    rejections = []
    manager = TurnResumeManager.__new__(TurnResumeManager)
    manager._fetch_message = fetch
    manager._store = SimpleNamespace(
        reject_resumable_sync=lambda *args: rejections.append(args),
    )
    manager._release_workload = None
    key = TurnKey(source="conversation", channel_id="c", message_id="m")
    assert await manager._validate_and_rebuild(key, {}) == (None, None, expected)
    assert bool(rejections) is rejected


@pytest.mark.asyncio
@pytest.mark.parametrize("changed,reason", [
    ("author", "the original author no longer matches"),
    ("content", "the original message was edited"),
])
async def test_resume_refuses_materially_changed_original_before_reconstruction(changed, reason):
    from src.discord.turn_resume import TurnResumeManager
    from src.turn_state.codec import compute_content_digest
    from src.turn_state.store import TurnKey

    original = SimpleNamespace(
        author=SimpleNamespace(id="other" if changed == "author" else "owner"),
        content="changed" if changed == "content" else "original",
    )
    async def fetch(*args):
        return original
    rejections = []
    manager = TurnResumeManager.__new__(TurnResumeManager)
    manager._fetch_message = fetch
    manager._store = SimpleNamespace(reject_resumable_sync=lambda *args: rejections.append(args))
    manager._release_workload = None
    key = TurnKey(source="conversation", channel_id="c", message_id="m")
    row = {"user_id": "owner", "content_digest": compute_content_digest("original")}
    assert await manager._validate_and_rebuild(key, row) == (None, None, reason)
    assert len(rejections) == 1


def test_request_preamble_keeps_history_no_replay_bytes_without_bot_origin_surface():
    from src.discord.tool_loop_helpers import build_request_preamble
    source = _baseline("src/discord/tool_loop_helpers.py")
    node = next(node for node in ast.parse(source).body
                if isinstance(node, ast.FunctionDef) and node.name == "build_request_preamble")
    namespace = {"Any": object}
    exec(ast.get_source_segment(source, node), namespace)
    values = dict(request_id="r", request_time="time", user_display="owner",
                  user_id="o", message_id="m", channel_description="Conversation: c")
    for has_history in (True, False):
        assert build_request_preamble(**values, has_history=has_history) == namespace[
            "build_request_preamble"](**values, has_history=has_history)
    with pytest.raises(TypeError):
        build_request_preamble(**values, has_history=True, from_another_bot=True)


def test_owner_filter_has_no_bypass_parameter_and_missing_authority_denies():
    from src.discord.tool_loop import ToolLoopRunner
    runner = ToolLoopRunner.__new__(ToolLoopRunner)
    runner._get_config = lambda: SimpleNamespace(tools=SimpleNamespace(enabled=True))
    runner._tool_catalog = SimpleNamespace(merged_definitions=lambda: [{"name": "read_file"}])
    runner._permissions = SimpleNamespace()
    assert runner._scoped_tools_for_request(user_id="owner") is None
    del runner._tool_catalog
    assert runner._scoped_tools_for_request(
        user_id="owner", current_tools=[{"name": "read_file"}],
    ) is None
    with pytest.raises(TypeError):
        runner._scoped_tools_for_request(user_id="owner", bypass_rbac=True)
