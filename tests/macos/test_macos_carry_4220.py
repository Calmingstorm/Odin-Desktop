"""Odin 4.22.0 (#699) on macOS: a failed test's freshness is checked where the test ran.

The executor's route to the Mac's command runner (macos_jobs.exec_command, through the
darwin variant of _exec_command) with the workspace opt-in, nothing faked: git asks in the
test's own repository after its leading ``cd``, against the branch's own upstream, and in
the workspace, never the engine's own folder, when the command has no ``cd``.
"""
from __future__ import annotations

import subprocess

from src.config.schema import ToolsConfig
from src.tools.executor import ToolExecutor

FAILURE = "FAILED tests/test_example.py::test_example - AssertionError\n1 failed"


def git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=Odin Test", "-c", "user.email=test@example.invalid",
                    *args], cwd=cwd, check=True, capture_output=True)


def repository(root):
    """A clone whose branch tracks a remote named ``upstream``, two commits behind it."""
    root.mkdir(parents=True, exist_ok=True)
    remote, work, other = root / "upstream.git", root / "my work", root / "other"
    git("init", "--bare", "-b", "main", str(remote), cwd=root)
    git("clone", "--origin", "upstream", str(remote), str(work), cwd=root)
    git("commit", "--allow-empty", "-m", "first", cwd=work)
    git("push", "--set-upstream", "upstream", "main", cwd=work)
    git("clone", str(remote), str(other), cwd=root)
    for message in ("second", "third"):
        git("commit", "--allow-empty", "-m", message, cwd=other)
    git("push", "origin", "main", cwd=other)
    return work


async def test_a_failed_test_run_is_checked_in_the_repository_it_ran_in(tmp_path, monkeypatch):
    work = repository(tmp_path / "test")
    # The engine runs from a stale checkout of its own: git must never ask there.
    monkeypatch.chdir(repository(tmp_path / "engine"))
    # A workspace of its own, apart from the engine's folder (as an installed profile's).
    route = ToolExecutor(config=ToolsConfig(local_working_dir=str(tmp_path / "workspace")))
    route._memory_path = str(tmp_path / "data" / "memory.json")  # apart from the workspace
    monkeypatch.setattr(route, "_resolve_host", lambda alias: ("127.0.0.1", "owner", None))
    annotated = await route._annotate_with_freshness(
        FAILURE, "localhost", "run_command", f'cd "{work}" && python3 -m pytest -q')
    assert annotated.startswith(FAILURE)
    assert "[STALE BRANCH] main is 2 commit(s) behind upstream/main" in annotated
    missing = await route._annotate_with_freshness(
        FAILURE, "localhost", "run_command", f'cd "{tmp_path / "missing"}" && python3 -m pytest')
    assert missing == FAILURE
    unchanged = await route._annotate_with_freshness(
        FAILURE, "localhost", "run_command", "python3 -m pytest -q")
    assert unchanged == FAILURE  # git asked in the workspace, never the engine's folder
