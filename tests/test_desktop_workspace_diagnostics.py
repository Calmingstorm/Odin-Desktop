"""Read-only diagnostics using disposable local fixtures and inert primitives."""
import asyncio
import os
import subprocess
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.desktop import workspace_diagnostics as diagnostics
from src.tools.executor import ToolExecutor
from src.tools.workspace import WorkspaceError, resolve_workspace


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir(mode=0o700)
    return root


def executor(root):
    return SimpleNamespace(_ensure_local_workspace=lambda: resolve_workspace(str(root)))


def git_fixture(root, *args):
    """Only benign fixture creation commands, never fetch or live repositories."""
    return subprocess.run(
        ["/usr/bin/git", *args], cwd=root,
        env={"PATH": "/usr/bin:/bin", "HOME": str(root), "LANG": "C",
             "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull},
        stdin=subprocess.DEVNULL, capture_output=True,
        check=True, timeout=2,
    ).stdout.decode().strip()


@pytest.mark.asyncio
async def test_snapshot_actual_executor_workspace_and_provider_replacement(workspace, tmp_path):
    (workspace / "note.txt").write_bytes(b"hello")
    other = tmp_path / "replacement"
    other.mkdir(mode=0o700)
    (other / "note.txt").write_bytes(b"other data")
    current = executor(workspace)
    service = diagnostics.WorkspaceDiagnostics(lambda: current)
    result = await service.snapshot()
    assert result["status"] == "ok"
    assert result["usage"]["bytes"] == 5
    assert result["usage"]["files"] == 1
    assert result["disk"]["free_bytes"] > 0
    assert result["git"]["status"] == "not_repository"
    assert result["local_only"] is True
    current = executor(other)
    assert (await service.snapshot())["usage"]["bytes"] == 10
    # This health seam cannot accept a request-selected command or path.
    with pytest.raises(TypeError):
        await service.snapshot(path=str(workspace))
    with pytest.raises(TypeError):
        await service.snapshot(command="fixture")


@pytest.mark.asyncio
async def test_never_invokes_executor_metrics_or_command_routes(workspace):
    owner = executor(workspace)
    owner.get_workspace_metrics = Mock(side_effect=AssertionError("unbounded walk"))
    owner.execute = Mock(side_effect=AssertionError("not a tool route"))
    owner._exec_command = Mock(side_effect=AssertionError("not a shell route"))
    assert (await diagnostics.WorkspaceDiagnostics(lambda: owner).snapshot())["status"] == "ok"
    owner.get_workspace_metrics.assert_not_called()
    owner.execute.assert_not_called()
    owner._exec_command.assert_not_called()


@pytest.mark.asyncio
async def test_revalidates_workspace_and_scrubs_failures(workspace):
    service = diagnostics.WorkspaceDiagnostics(lambda: executor(workspace))
    assert (await service.snapshot())["status"] == "ok"
    workspace.chmod(0o755)
    result = await service.snapshot()
    assert result == {"status": "unavailable", "reason": "workspace_unusable", "local_only": True}
    broken = SimpleNamespace(_ensure_local_workspace=Mock(
        side_effect=WorkspaceError("private fixture")))
    observed = await diagnostics.WorkspaceDiagnostics(lambda: broken).snapshot()
    assert "private fixture" not in str(observed)


@pytest.mark.asyncio
async def test_real_executor_profile_root_contract_without_live_initialization(workspace, tmp_path):
    # Sanctioned executor patch seam: real resolver/protected-root derivation,
    # no transport, backend, profile store or service is initialized.
    owner = ToolExecutor.__new__(ToolExecutor)
    owner.config = SimpleNamespace(local_working_dir=str(workspace))
    owner._memory_path = str(tmp_path / "profile-state" / "memory.json")
    owner._app_config = SimpleNamespace(
        sessions=SimpleNamespace(persist_directory=str(tmp_path / "profile-sessions")))
    service = diagnostics.WorkspaceDiagnostics(lambda: owner)
    assert (await service.snapshot())["status"] == "ok"
    protected = tmp_path / "profile-sessions"
    protected.mkdir(mode=0o700)
    owner.config.local_working_dir = str(protected)
    result = await service.snapshot()
    assert result["reason"] == "workspace_unusable"


def test_walk_skips_symlinks_and_special_files(workspace, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_bytes(b"not counted")
    (workspace / "file-link").symlink_to(outside / "private.txt")
    (workspace / "dir-link").symlink_to(outside, target_is_directory=True)
    os.mkfifo(workspace / "fixture-fifo")
    nested = workspace / "nested"
    nested.mkdir()
    (nested / "fixture.txt").write_bytes(b"counted")
    usage = diagnostics._usage(workspace, time.monotonic() + 1)
    assert usage["bytes"] == 7 and usage["files"] == 1
    assert usage["symlinks_skipped"] == 2
    assert usage["reason"] == "special_file_skipped"
    assert usage["complete"] is False


def test_walk_entry_limit_stops_before_excess_work(workspace, monkeypatch):
    for index in range(5):
        (workspace / f"fixture-{index}").write_bytes(b"x")
    monkeypatch.setattr(diagnostics, "MAX_ENTRIES", 2)
    usage = diagnostics._usage(workspace, time.monotonic() + 1)
    assert usage["entries"] == usage["files"] == usage["bytes"] == 2
    assert usage["complete"] is False and usage["reason"] == "walk_limit"


def test_walk_time_and_depth_limits(workspace, monkeypatch):
    nested = workspace / "nested"
    nested.mkdir()
    (nested / "fixture").write_bytes(b"x")
    usage = diagnostics._usage(workspace, time.monotonic() - 1)
    assert usage["entries"] == 0 and usage["reason"] == "walk_limit"
    monkeypatch.setattr(diagnostics, "MAX_DEPTH", 0)
    usage = diagnostics._usage(workspace, time.monotonic() + 1)
    assert usage["entries"] == 1 and usage["files"] == 0
    assert usage["reason"] == "walk_boundary"


def test_walk_no_follow_open_rechecks_directory_identity(workspace, monkeypatch):
    (workspace / "nested").mkdir()
    real_fstat = os.fstat
    calls = 0

    def changed(fd):
        nonlocal calls
        calls += 1
        info = real_fstat(fd)
        if calls == 2:
            return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino + 1)
        return info

    monkeypatch.setattr(diagnostics.os, "fstat", changed)
    usage = diagnostics._usage(workspace, time.monotonic() + 1)
    assert usage["reason"] == "directory_changed"


def test_git_local_tracking_detached_and_no_upstream(workspace):
    git_fixture(workspace, "init", "--initial-branch=fixture")
    git_fixture(workspace, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                "commit", "--allow-empty", "-m", "Fixture")
    result = diagnostics._git_snapshot(workspace, time.monotonic() + 3)
    assert result == {"status": "no_upstream", "branch": "fixture",
                      "remote_freshness": "not_checked", "network_used": False}
    git_fixture(workspace, "branch", "base")
    git_fixture(workspace, "config", "branch.fixture.remote", ".")
    git_fixture(workspace, "config", "branch.fixture.merge", "refs/heads/base")
    git_fixture(workspace, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                "commit", "--allow-empty", "-m", "Second fixture")
    result = diagnostics._git_snapshot(workspace, time.monotonic() + 3)
    assert result["status"] == "local_tracking"
    assert result["ahead"] == 1 and result["behind"] == 0
    assert result["upstream"] == "base"
    assert result["remote_freshness"] == "not_checked"
    git_fixture(workspace, "checkout", "--detach", "HEAD")
    assert diagnostics._git_snapshot(workspace, time.monotonic() + 3)["status"] == "detached_head"


def test_git_does_not_discover_parent_or_external_metadata(workspace, tmp_path, monkeypatch):
    # No Git invocation at all when the configured workspace lacks local metadata.
    run = Mock(side_effect=AssertionError("external metadata"))
    monkeypatch.setattr(diagnostics, "_git", run)
    assert diagnostics._git_snapshot(workspace, time.monotonic() + 1)["status"] == "not_repository"
    (workspace / ".git").write_text("gitdir: fixture\n")
    assert diagnostics._git_snapshot(workspace, time.monotonic() + 1)["status"] == (
        "external_metadata_unsupported")
    (workspace / ".git").rename(workspace / "fixture-metadata")
    (workspace / ".git").symlink_to(tmp_path, target_is_directory=True)
    assert diagnostics._git_snapshot(workspace, time.monotonic() + 1)["status"] == (
        "external_metadata_unsupported")
    run.assert_not_called()


@pytest.mark.parametrize("state,reason", [("timeout", "timeout"), ("output_limit", "output_limit"),
                                        ("ok", "invalid_counts")])
def test_git_failed_counts_never_claim_zero_or_fresh(workspace, monkeypatch, state, reason):
    (workspace / ".git").mkdir()
    values = {"repository": ("ok", "true"), "head": ("ok", "fixture"),
              "branch": ("ok", "feature/fixture"), "upstream": ("ok", "origin/fixture"),
              "counts": (state, "not counts")}
    monkeypatch.setattr(diagnostics, "_git", lambda root, op, deadline: values[op])
    result = diagnostics._git_snapshot(workspace, time.monotonic() + 1)
    assert result["status"] == "unavailable" and result["reason"] == reason
    assert "behind" not in result and "ahead" not in result
    assert result["remote_freshness"] == "not_checked"


class PipeProcess:
    """Inert pipe, no child process or caller executable."""
    def __init__(self, output=b"", *, eof=True):
        read_fd, self.write_fd = os.pipe()
        self.stdout = os.fdopen(read_fd, "rb", buffering=0)
        os.write(self.write_fd, output)
        if eof:
            os.close(self.write_fd)
            self.write_fd = None
        self.killed = False

    def poll(self):
        return -1 if self.killed else None

    def kill(self):
        self.killed = True
        if self.write_fd is not None:
            os.close(self.write_fd)
            self.write_fd = None

    def wait(self, timeout):
        return 0


def test_literal_argv_environment_and_output_cap(workspace, monkeypatch):
    child = PipeProcess(b"x" * (diagnostics.GIT_OUTPUT_BYTES + 1))
    spawn = Mock(return_value=child)
    monkeypatch.setattr(diagnostics.subprocess, "Popen", spawn)
    monkeypatch.setenv("GIT_DIR", "unrelated-fixture")
    monkeypatch.setenv("GIT_SSH_COMMAND", "unrelated-fixture")
    assert diagnostics._git(workspace, "counts", time.monotonic() + 1) == ("output_limit", "")
    argv, = spawn.call_args.args
    kwargs = spawn.call_args.kwargs
    assert argv[-5:] == ("rev-list", "--left-right", "--count", "HEAD...@{upstream}", "--")
    assert "protocol.allow=never" in argv
    assert kwargs["cwd"] == workspace
    assert "shell" not in kwargs
    assert "GIT_DIR" not in kwargs["env"] and "GIT_SSH_COMMAND" not in kwargs["env"]
    assert kwargs["env"]["GIT_NO_LAZY_FETCH"] == "1"
    assert kwargs["env"]["GIT_ALLOW_PROTOCOL"] == ""
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert child.killed and child.stdout.closed


def test_git_timeout_terminates_only_owned_stub(workspace, monkeypatch):
    child = PipeProcess(eof=False)
    monkeypatch.setattr(diagnostics.subprocess, "Popen", Mock(return_value=child))
    monkeypatch.setattr(diagnostics, "GIT_SECONDS", 0.01)
    assert diagnostics._git(workspace, "branch", time.monotonic() + 1) == ("timeout", "")
    assert child.killed and child.stdout.closed


def test_git_expired_deadline_spawns_nothing(workspace, monkeypatch):
    spawn = Mock(side_effect=AssertionError("deadline"))
    monkeypatch.setattr(diagnostics.subprocess, "Popen", spawn)
    assert diagnostics._git(workspace, "branch", time.monotonic() - 1) == ("timeout", "")
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_timeout_single_flight_and_recovery(workspace, monkeypatch):
    release = threading.Event()
    entered = threading.Event()
    calls = 0

    def resolve():
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(2)
        return workspace

    monkeypatch.setattr(diagnostics, "SNAPSHOT_SECONDS", 0.02)
    service = diagnostics.WorkspaceDiagnostics(
        lambda: SimpleNamespace(_ensure_local_workspace=resolve))
    try:
        first, second = await asyncio.gather(service.snapshot(), service.snapshot())
        assert entered.is_set() and calls == 1
        assert first["status"] == second["status"] == "timeout"
        assert (await service.snapshot())["status"] == "timeout" and calls == 1
    finally:
        release.set()
        await service._pending
    assert (await service.snapshot())["status"] == "ok" and calls == 2


@pytest.mark.asyncio
async def test_scrub_collection_failure(workspace, monkeypatch):
    monkeypatch.setattr(diagnostics, "_usage", Mock(side_effect=OSError("private fixture")))
    result = await diagnostics.WorkspaceDiagnostics(lambda: executor(workspace)).snapshot()
    assert result == {"status": "unavailable", "reason": "collection_failed", "local_only": True}


@pytest.mark.asyncio
async def test_partial_usage_and_unavailable_disk_are_explicit(workspace, monkeypatch):
    (workspace / "fixture-a").write_bytes(b"a")
    (workspace / "fixture-b").write_bytes(b"b")
    monkeypatch.setattr(diagnostics, "MAX_ENTRIES", 1)
    monkeypatch.setattr(diagnostics.shutil, "disk_usage", Mock(side_effect=OSError("fixture")))
    result = await diagnostics.WorkspaceDiagnostics(lambda: executor(workspace)).snapshot()
    assert result["status"] == "partial"
    assert result["usage"]["entries"] == 1 and result["usage"]["complete"] is False
    assert result["disk"] == {}


def test_branch_names_display_only_and_local_behind_not_remote_freshness(workspace, monkeypatch):
    (workspace / ".git").mkdir()
    values = {"repository": ("ok", "true"), "head": ("ok", "fixture"),
              "branch": ("ok", "--fixture\n" + "x" * 1000),
              "upstream": ("ok", "local/fixture\t"), "counts": ("ok", "0\t2")}
    calls = []

    def reader(root, operation, deadline):
        calls.append(operation)
        return values[operation]

    monkeypatch.setattr(diagnostics, "_git", reader)
    result = diagnostics._git_snapshot(workspace, time.monotonic() + 1)
    assert result["status"] == "local_tracking" and result["behind"] == 2
    assert result["ahead"] == 0 and result["remote_freshness"] == "not_checked"
    assert len(result["branch"]) == 256 and "\n" not in result["branch"]
    assert result["upstream"] == "local/fixture"
    assert calls == ["repository", "head", "branch", "upstream", "counts"]


def test_unborn_head_does_not_claim_detached_or_fresh(workspace, monkeypatch):
    (workspace / ".git").mkdir()
    values = {"repository": ("ok", "true"), "head": ("failed", "")}
    monkeypatch.setattr(diagnostics, "_git", lambda root, op, deadline: values[op])
    result = diagnostics._git_snapshot(workspace, time.monotonic() + 1)
    assert result["status"] == "unavailable" and result["reason"] == "head_failed"
    assert "behind" not in result


@pytest.mark.asyncio
async def test_cancelled_wait_does_not_cancel_or_duplicate_worker(workspace, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def resolve():
        nonlocal calls
        calls += 1
        started.set()
        release.wait(2)
        return workspace

    service = diagnostics.WorkspaceDiagnostics(
        lambda: SimpleNamespace(_ensure_local_workspace=resolve))
    waiter = asyncio.create_task(service.snapshot())
    try:
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.001)
        assert started.is_set()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert not service._pending.cancelled()
        next_waiter = asyncio.create_task(service.snapshot())
        await asyncio.sleep(0.01)
        assert calls == 1
        release.set()
        assert (await next_waiter)["status"] == "ok"
    finally:
        release.set()
        await service._pending
