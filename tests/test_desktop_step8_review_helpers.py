"""Exact inherited review candidates plus fail-closed adapter guard tests."""
# ruff: noqa: E501
import ast
import copy
import hashlib

import pytest

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from src.config.schema import ToolsConfig
from tests.desktop_adapters import step8_review_helpers as adapter

LOADED = adapter.load(globals())


@pytest.fixture(autouse=True)
async def review_owner(request, tmp_path):
    if request.node.name.startswith("test_adapter_"):
        yield
        return
    async with adapter.owner_fixture(tmp_path) as state:
        yield state


@pytest.mark.parametrize("stem", list(adapter.SUITES))
def test_adapter_complete_ast_and_corpus(stem):
    path = f"tests/{stem}.py"
    original, adapted = LOADED[path]
    assert corpus(original) == corpus(adapted)
    assert adapter.adapt(stem, frozen_source(path))[1] is not adapted


def test_adapter_changed_bytes_rejected():
    stem = "test_tool_loop_helpers"
    with pytest.raises(ValueError, match="bytes changed"):
        adapter.adapt(stem, frozen_source(f"tests/{stem}.py") + b"\n")


def test_adapter_wrong_and_duplicate_hunks_rejected():
    stem = "test_tool_loop_helpers"
    source = frozen_source(f"tests/{stem}.py")
    rules = copy.deepcopy(adapter.SETUP_HUNKS[stem])
    line, col, digest, replacement, expression = rules[0]
    rules[0] = (line + 1, col, digest, replacement, expression)
    with pytest.raises(ValueError, match="allowlist"):
        adapter.adapt(stem, source, hunks=rules)
    with pytest.raises(ValueError, match="duplicate"):
        adapter.adapt(stem, source, hunks=[rules[1], rules[1]])


def test_adapter_assertion_rewrite_rejected():
    stem = "test_tool_loop_helpers"
    source = frozen_source(f"tests/{stem}.py")
    node = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Assert))
    rule = (node.lineno, node.col_offset, hashlib.sha256(dump(node).encode()).hexdigest(), "assert False", False)
    with pytest.raises(ValueError, match="allowlist"):
        adapter.adapt(stem, source, hunks=[rule])


def test_adapter_collateral_ast_mutation_rejected(monkeypatch):
    original_put = adapter._put

    def collateral(tree, path, replacement):
        original_put(tree, path, replacement)
        tree.body.append(ast.parse("collateral = 1").body[0])

    monkeypatch.setattr(adapter, "_put", collateral)
    stem = "test_tool_loop_helpers"
    with pytest.raises(ValueError, match="complete AST reverse replay"):
        adapter.adapt(stem, frozen_source(f"tests/{stem}.py"))


def test_adapter_bot_branch_fails_closed():
    with pytest.raises(TypeError, match="bot-origin"):
        adapter.build_request_preamble(from_another_bot=True)


async def test_adapter_owner_gate_not_permissive(tmp_path):
    with pytest.raises(RuntimeError, match="authentic temporary owner"):
        adapter.desktop_executor(config=ToolsConfig())
    async with adapter.owner_fixture(tmp_path):
        executor = adapter.desktop_executor(config=ToolsConfig())
        seen = []

        async def handler(_input):
            seen.append(True)
            return "fixture"

        executor._handle_run_command = handler
        result = await executor.execute("run_command", {"command": "fixture"}, user_id="not-owner")
        assert not result.ok and result.error == "permission_denied"
        assert seen == []


async def test_adapter_unknown_classification_preserves_guards(tmp_path):
    from src.tools.output_authorization import request_tool_scope

    async with adapter.owner_fixture(tmp_path):
        executor = adapter.desktop_executor(config=ToolsConfig())

        def middleware_must_not_run(*_args):
            raise AssertionError("unknown classification touched middleware")

        executor.check_permission = middleware_must_not_run
        result = await executor.execute("not_registered", {}, user_id="not-owner")
        assert not result.ok and result.error == "permission_denied"
        result = await executor.execute("not_registered", {})
        assert not result.ok and result.error == "unknown_tool"
        executor.computer_reserved = lambda name: name == "not_registered"
        result = await executor.execute("not_registered", {})
        assert not result.ok and result.error == "permission_denied"
        executor.computer_reserved = None
        token = request_tool_scope.set(frozenset())
        try:
            result = await executor.execute("not_registered", {})
            assert not result.ok and result.error == "permission_denied"
        finally:
            request_tool_scope.reset(token)


async def test_adapter_known_handler_still_requires_readiness(tmp_path):
    async with adapter.owner_fixture(tmp_path):
        executor = adapter.desktop_executor(config=ToolsConfig())
        seen = []

        async def handler(_input):
            seen.append(True)
            return "fixture"

        executor._handle_run_command = handler
        executor.set_builtin_policy(None)
        result = await executor.execute("run_command", {"command": "fixture"})
        assert not result.ok and result.error == "tool_unavailable"
        assert seen == []
