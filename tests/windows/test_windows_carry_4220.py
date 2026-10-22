"""Odin 4.22.0 (PR #729) on Windows: the carried fixes through Windows' own routes.

- apply_patch (#677): after a successful commit the original file gets its own access back,
  so another hard link to it keeps the ACL it had, not the private one it was given for its
  stay in the recovery slot.
- Branch freshness (#699): a failed test's freshness is checked in the repository the test
  ran in (a leading ``cd``) against the branch's own upstream, through PowerShell here: the
  executor's route, the Windows variant and this computer's git, with nothing faked.
"""
from __future__ import annotations

import functools
import os
import subprocess

from src.config.schema import ToolsConfig
from src.desktop.platform.windows_files import dacl_is_private
from src.desktop.platform.windows_tools import exec_command
from src.tools.branch_freshness import check_branch_freshness
from src.tools.executor import ToolExecutor
from tests.windows.test_windows_adversarial import security_of
from tests.windows.test_windows_helpers import executor, git
from tests.windows.test_windows_patch import (  # noqa: F401 (transaction is a fixture)
    acl,
    patch,
    shared,
    transaction,
)

FAILURE = "FAILED tests/test_example.py::test_example - AssertionError\n1 failed"


def test_a_patched_files_other_hard_link_keeps_its_own_acl(tmp_path, transaction):  # noqa: F811
    root = shared(tmp_path / "shared")
    (root / "keep.txt").write_bytes(b"alpha\n")
    subprocess.run(["icacls", str(root / "keep.txt"), "/grant", "*S-1-5-32-545:(M)"],
                   check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    os.link(root / "keep.txt", root / "alias.txt")
    before = acl(root / "alias.txt")
    transaction.run(root, patch("*** Update File: keep.txt", "@@", "-alpha", "+beta"))
    assert (root / "keep.txt").read_bytes() == b"beta\n"
    assert (root / "alias.txt").read_bytes() == b"alpha\n"
    assert acl(root / "alias.txt") == before
    assert not dacl_is_private(security_of(root / "alias.txt"))
    assert not list(root.glob(".odin-patch-*"))


def repository(root):
    """A clone whose branch tracks a remote named ``upstream``, two commits behind it."""
    root.mkdir(parents=True, exist_ok=True)
    tmp_path = root
    remote, work, other = root / "upstream.git", root / "my work", root / "other"
    git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    git("clone", "--origin", "upstream", str(remote), str(work), cwd=tmp_path)
    git("commit", "--allow-empty", "-m", "first", cwd=work)
    git("push", "--set-upstream", "upstream", "main", cwd=work)
    git("clone", str(remote), str(other), cwd=tmp_path)
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
        FAILURE, "localhost", "run_command", f'cd "{work}" && python -m pytest -q')
    assert annotated.startswith(FAILURE)
    assert "[STALE BRANCH] main is 2 commit(s) behind upstream/main" in annotated
    missing = await route._annotate_with_freshness(
        FAILURE, "localhost", "run_command", f'cd "{tmp_path / "missing"}" && python -m pytest')
    assert missing == FAILURE  # a folder that is not there is never checked elsewhere
    unchanged = await route._annotate_with_freshness(
        FAILURE, "localhost", "run_command", "python -m pytest -q")
    assert unchanged == FAILURE  # git asked in the workspace, never the engine's folder


async def test_detached_heads_and_branches_without_upstream_are_reported(tmp_path):
    work = repository(tmp_path / "test")
    run = functools.partial(exec_command, executor())
    git("checkout", "-b", "local-only", cwd=work)
    status = await check_branch_freshness(run, "127.0.0.1", "owner", directory=str(work))
    assert (status.error, status.local_branch, status.is_stale) == (
        "no upstream", "local-only", False)
    git("checkout", "--detach", "main", cwd=work)
    status = await check_branch_freshness(run, "127.0.0.1", "owner", directory=str(work))
    assert (status.error, status.is_stale) == ("detached HEAD", False)
