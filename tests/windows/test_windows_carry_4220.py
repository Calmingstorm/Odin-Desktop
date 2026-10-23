"""Odin 4.22.0 (PR #729) on Windows: the carried fixes through Windows' own routes.

- apply_patch (#677): after a successful commit the original file gets its own access back,
  so another hard link to it keeps the ACL it had, not the private one it was given for its
  stay in the recovery slot.
- Branch freshness (#699): a failed test's freshness is checked in the repository the test
  ran in (a leading ``cd``) against the branch's own upstream, through PowerShell here: the
  executor's route, the Windows variant and this computer's git, with nothing faked. Odin's
  ``command_directory`` reads a ``cd`` by POSIX rules: a single-quoted folder or one with
  forward slashes. A double-quoted folder with backslashes is not read, so the check runs
  in the workspace and never warns from the wrong repository.
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
    for test in (f"cd '{work}' && python -m pytest -q",
                 f'cd "{work.as_posix()}" && python -m pytest -q'):
        annotated = await route._annotate_with_freshness(FAILURE, "localhost", "run_command", test)
        assert annotated.startswith(FAILURE)
        assert "[STALE BRANCH] main is 2 commit(s) behind upstream/main" in annotated, test
    unread = await route._annotate_with_freshness(
        FAILURE, "localhost", "run_command", f'cd "{work}" && python -m pytest -q')
    assert unread == FAILURE  # POSIX rules do not read it: the workspace is asked, not a repo
    missing = await route._annotate_with_freshness(
        FAILURE, "localhost", "run_command", f"cd '{tmp_path / 'missing'}' && python -m pytest")
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


def stale_clone_into(root, target):
    """Make the (empty) *target* a clone two commits behind its upstream."""
    root.mkdir(parents=True, exist_ok=True)
    remote, other = root / "upstream.git", root / "other"
    git("init", "--bare", "-b", "main", str(remote), cwd=root)
    git("clone", "--origin", "upstream", str(remote), str(target), cwd=root)
    git("commit", "--allow-empty", "-m", "first", cwd=target)
    git("push", "--set-upstream", "upstream", "main", cwd=target)
    git("clone", str(remote), str(other), cwd=root)
    for message in ("second", "third"):
        git("commit", "--allow-empty", "-m", message, cwd=other)
    git("push", "origin", "main", cwd=other)


async def test_a_long_scripts_leading_cd_is_read_in_full(tmp_path, monkeypatch):
    """Odin's review R3 on Windows' run_script: the whole script, not its first 120
    characters, is read for its leading cd. The workspace is a stale clone; the test
    repository has no upstream, so no warning may appear."""
    import sys
    from pathlib import Path

    repo = tmp_path / ("a-test-repository-with-a-long-name-" + "x" * 80)
    repo.mkdir()
    (repo / "test_fail.py").write_text("def test_fails():\n    assert 1 == 2\n")
    git("init", "-q", "-b", "main", str(repo), cwd=tmp_path)
    git("add", "test_fail.py", cwd=repo)
    git("commit", "-q", "-m", "a failing test, no upstream", cwd=repo)
    route = ToolExecutor(config=ToolsConfig(local_working_dir=str(tmp_path / "workspace")))
    route._memory_path = str(tmp_path / "data" / "memory.json")
    workspace = Path(route._ensure_local_workspace())  # made private, empty
    stale_clone_into(tmp_path / "remotes", workspace)
    monkeypatch.setattr(route, "_resolve_host", lambda alias: ("127.0.0.1", "owner", None))
    monkeypatch.setattr(route, "_govern_command", lambda script, host: (True, None, ""))
    python = sys.executable  # this test environment's interpreter, which has pytest
    # A PowerShell script ends with its last native command's status only when told to.
    script = (f"cd '{repo}'; & '{python}' -m pytest -q -p no:cacheprovider test_fail.py; "
              "exit $LASTEXITCODE")
    assert len(script.split("; ", 1)[0]) > 120  # the cd ends past the old cut
    result = await route.system_tools._handle_run_script(
        {"host": "localhost", "script": script, "interpreter": "powershell"})
    text = result[0] if isinstance(result, tuple) else result
    assert text.startswith("Script failed") and "1 failed" in text
    assert "[STALE BRANCH]" not in text  # the workspace's stale clone was never asked
    plain = await route.system_tools._handle_run_script(
        {"host": "localhost", "interpreter": "powershell",
         "script": f"& '{python}' -m pytest -q -p no:cacheprovider '{repo}\\test_fail.py'; "
                   "exit $LASTEXITCODE"})
    plain_text = plain[0] if isinstance(plain, tuple) else plain
    assert "[STALE BRANCH] main is 2 commit(s) behind upstream/main" in plain_text
