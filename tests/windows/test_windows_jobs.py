"""manage_process on this Windows computer: each job in a job object (phase 3 plan C7)."""
from __future__ import annotations

import asyncio
import sys
import time
from types import SimpleNamespace

import pytest

from src.desktop.platform import win32
from src.desktop.platform.windows_jobs import JobShell, WindowsProcessRegistry, create_job_shell
from tests.windows.test_windows_exec import written

PYTHON = getattr(sys, "_base_executable", "") or sys.executable


def alive(pid: int) -> bool:
    handle = win32.OpenProcess(win32.SYNCHRONIZE, False, pid)
    if not handle:
        return False
    try:
        return win32.WaitForSingleObject(handle, 0) != win32.WAIT_OBJECT_0
    finally:
        win32.close(handle)


@pytest.fixture
async def registry(tmp_path):
    jobs = WindowsProcessRegistry(workspace=str(tmp_path), command_shell="auto")
    yield jobs
    await jobs.shutdown()


async def started(jobs, command: str) -> int:
    reply = await jobs.start("127.0.0.1", command)
    assert reply.startswith("Process started (PID "), reply
    return int(reply.split("PID ", 1)[1].split(")", 1)[0])


async def settled(jobs, pid: int, seconds: float = 30):
    info = jobs._processes[pid]
    await asyncio.wait_for(asyncio.shield(info._exit_task), seconds)
    return info


async def test_a_job_runs_in_the_workspace_and_settles_with_its_exit_code(registry, tmp_path):
    pid = await started(registry, "(Get-Location).Path; Write-Output 'hé'; exit 4")
    info = await settled(registry, pid)
    assert isinstance(info.process, JobShell) and info.effective_shell == "powershell"
    assert (info.status, info.exit_code, info.session_confirmed_empty) == ("failed", 4, True)
    text = await registry.poll(pid)
    assert str(tmp_path).lower() in text.lower() and "hé" in text


async def test_what_a_job_started_ends_with_it(registry, tmp_path):
    marker = tmp_path / "child.pid"
    pid = await started(registry, (
        f"$p = Start-Process -PassThru -NoNewWindow '{PYTHON}' "
        f"-ArgumentList '-I','-S','-c','import time; time.sleep(60)'; "
        f"Set-Content -Path '{marker}' -Value $p.Id"))
    info = await settled(registry, pid)
    child = int(marker.read_text().strip())
    assert (info.status, info.session_confirmed_empty) == ("completed", True)
    assert not alive(child)  # as on Linux: the job's descendants end with its leader


async def test_kill_ends_the_whole_job(registry, tmp_path):
    marker = tmp_path / "child.pid"
    pid = await started(registry, (
        f"$p = Start-Process -PassThru -NoNewWindow '{PYTHON}' "
        f"-ArgumentList '-I','-S','-c','import time; time.sleep(60)'; "
        f"Set-Content -Path '{marker}' -Value $p.Id; Start-Sleep 60"))
    for _ in range(300):
        if written(marker):
            break
        await asyncio.sleep(0.1)
    child = int(written(marker))
    assert await registry.kill(pid) == f"Process {pid} killed."
    info = registry._processes[pid]
    assert (info.status, info.session_confirmed_empty) == ("killed", True)
    assert not alive(child) and not alive(pid)
    assert await registry.kill(pid) == f"Process {pid} already killed."


async def test_stdin_reaches_the_job(registry):
    pid = await started(registry, "$line = [Console]::In.ReadLine(); Write-Output \"got $line\"")
    assert await registry.write(pid, "hello\n") == f"Wrote 6 bytes to PID {pid}."
    await settled(registry, pid)
    assert "got hello" in await registry.poll(pid)


async def test_shutdown_ends_running_jobs_and_proves_it(tmp_path):
    jobs = WindowsProcessRegistry(workspace=str(tmp_path), command_shell="auto")
    pid = await started(jobs, "Start-Sleep 60")
    assert await jobs.shutdown() == 1
    assert jobs._processes[pid].session_confirmed_empty and not alive(pid)


async def test_a_refused_shell_starts_nothing(tmp_path):
    jobs = WindowsProcessRegistry(workspace=str(tmp_path), command_shell="bash")
    assert await jobs.start("127.0.0.1", "Write-Output never") == (
        "Error: tools.command_shell=bash: bash isn't available on this Windows host; "
        "command not executed")
    assert jobs._processes == {}


async def test_the_executor_builds_the_windows_registry(tmp_path):
    from src.desktop.platform.windows_tools import ensure_process_registry

    fake = SimpleNamespace(
        _ensure_local_workspace=lambda: str(tmp_path), _exec_remote_target=None,
        _retention_root=lambda: tmp_path / "retained", _acquire_process_cleanup_lease=None,
        _command_shell_mode=lambda: "auto")
    jobs = ensure_process_registry(fake)
    assert isinstance(jobs, WindowsProcessRegistry) and ensure_process_registry(fake) is jobs
    await jobs.shutdown()


async def test_a_settled_job_is_never_asked_about_again(registry):
    pid = await started(registry, "Write-Output done")
    info = await settled(registry, pid)
    shell = info.process
    assert shell._running.job == 0  # released once empty
    assert await shell.terminate_tree() is True  # no query with handle 0
    unsettled = JobShell(SimpleNamespace(process=SimpleNamespace(stdin=None, stdout=None,
                                                                 stderr=None), pid=1, job=0))
    assert await unsettled.terminate_tree() is False


async def test_a_jobs_output_leaves_out_powershells_progress(registry):
    from tests.windows.test_windows_exec import EMIT

    pid = await started(registry, EMIT)
    await settled(registry, pid)
    text = await registry.poll(pid)
    assert "after" in text and "kept" in text  # stdout and the error stream both arrive
    assert "CLIXML" not in text and "Objs" not in text


async def test_a_line_longer_than_a_chunk_arrives_whole(tmp_path):
    shell = await create_job_shell("Write-Output ('x' * 200000 + 'END'); Write-Output tail",
                                   stdout=asyncio.subprocess.PIPE,
                                   stderr=asyncio.subprocess.STDOUT, cwd=str(tmp_path))
    try:
        data = await asyncio.wait_for(shell.stdout.read(), 60)  # what the registry reads
        assert await asyncio.wait_for(shell.wait(), 30) == 0
    finally:
        await shell.terminate_tree()
    assert data == b"x" * 200000 + b"END\r\ntail\r\n"


# --- Settlement and live output (Odin's 3a review, B5 and B7) ---------------------------------


async def test_concurrent_settlements_agree_and_let_go_once(tmp_path):
    shell = await create_job_shell("Start-Sleep 30", stdout=asyncio.subprocess.PIPE,
                                   stderr=asyncio.subprocess.STDOUT, cwd=str(tmp_path))
    assert await asyncio.gather(shell.terminate_tree(), shell.terminate_tree()) == [True, True]
    assert shell._running.job == 0 and await shell.terminate_tree() is True


async def test_live_progress_reaches_a_poll_before_the_job_ends(registry):
    pid = await started(registry, "[Console]::Out.Write('10%' + [char]13); "
                                  "[Console]::Out.Flush(); Start-Sleep 30")
    text, deadline = "", time.monotonic() + 20
    while "10%" not in text and time.monotonic() < deadline:
        await asyncio.sleep(0.5)
        text = await registry.poll(pid)
    assert "10%" in text and registry._processes[pid].status == "running", text
    await registry.kill(pid)
