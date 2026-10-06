"""Complete safe inherited runner cases and fail-closed loader proofs."""
# ruff: noqa: E501
import ast
import hashlib

import pytest

from scripts.maintenance.fixture_corpus import dump, frozen_source
from tests.desktop_adapters import step8_runner
from tests.desktop_adapters.process_cases import temporary_owner
from tests.desktop_adapters.step8_runner import load

load(globals())


@pytest.fixture(autouse=True)
def step8_runner_owner(request, tmp_path):
    if not request.node.name.startswith("test_step8_runner_"):
        yield
        return
    with temporary_owner(tmp_path / "owner") as state:
        step8_runner.bind_owner()
        yield state


def test_step8_loader_rejects_changed_bytes():
    path = "tests/test_command_shell_framing.py"
    with pytest.raises(ValueError, match="bytes changed"):
        step8_runner.adapt(path, frozen_source(path) + b"\n", step8_runner.SUITES["test_command_shell_framing"])


def test_step8_loader_rejects_wrong_or_duplicate_hunk():
    path = "tests/test_command_shell_framing.py"
    source = frozen_source(path)
    rules = list(step8_runner.SETUP_HUNKS["test_command_shell_framing"])
    line, column, digest, replacement, expression = rules[0]
    rules[0] = (line + 1, column, digest, replacement, expression)
    with pytest.raises(ValueError, match="exact admitted allowlist"):
        step8_runner.adapt(path, source, step8_runner.SUITES["test_command_shell_framing"], hunks=rules)
    with pytest.raises(ValueError, match="duplicate"):
        step8_runner.adapt(path, source, step8_runner.SUITES["test_command_shell_framing"], hunks=[rules[1], rules[1]])


def test_step8_loader_rejects_assertion_mutation():
    path = "tests/test_command_shell_framing.py"
    source = frozen_source(path)
    tree = ast.parse(source)
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.Assert))
    rule = (node.lineno, node.col_offset, hashlib.sha256(dump(node).encode()).hexdigest(), "assert False", False)
    with pytest.raises(ValueError, match="exact admitted allowlist"):
        step8_runner.adapt(path, source, step8_runner.SUITES["test_command_shell_framing"], hunks=[rule])


def test_step8_loader_retains_complete_pinned_corpus():
    for stem, expected in step8_runner.SUITES.items():
        original, adapted = step8_runner.adapt(f"tests/{stem}.py", frozen_source(f"tests/{stem}.py"), expected)
        assert original is not adapted
    assert step8_runner.CORPUS_SELECTIONS == {stem: None for stem in step8_runner.SUITES}
    assert step8_runner.CORPUS_EXCLUSIONS == {}


def test_step8_loader_rejects_collateral_ast_edits(monkeypatch):
    path = "tests/test_command_shell_framing.py"
    original_put = step8_runner._put

    def collateral(tree, location, replacement):
        original_put(tree, location, replacement)
        tree.body.append(ast.parse("collateral_setup = 1").body[0])

    monkeypatch.setattr(step8_runner, "_put", collateral)
    with pytest.raises(ValueError, match="complete AST reverse replay"):
        step8_runner.adapt(path, frozen_source(path), step8_runner.SUITES["test_command_shell_framing"])


async def test_step8_loader_fixture_is_not_permissive(tmp_path):
    with pytest.raises(RuntimeError, match="authentication is absent"):
        step8_runner.process_executor(tmp_path)
    with temporary_owner(tmp_path / "guard") as state:
        executor = step8_runner.process_executor(tmp_path)
        denied = await executor.execute("run_command", {"host": "testhost", "command": "printf fixture"}, user_id="not-owner")
        assert not denied.ok and denied.error == "permission_denied"
        state.authority.release_runtime()
        denied = await executor.execute("run_command", {"host": "testhost", "command": "printf fixture"}, user_id=state.authority.owner_id)
        assert not denied.ok and denied.error == "permission_denied"
