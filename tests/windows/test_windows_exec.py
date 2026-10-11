"""Local commands under Windows PowerShell 5.1, each in its own job (phase 3 plan C1)."""
from __future__ import annotations

import asyncio
import ctypes
import os
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

import pytest

from src.desktop.platform import win32
from src.desktop.platform import windows_exec as wx

PYTHON = getattr(sys, "_base_executable", "") or sys.executable


def alive(pid: int) -> bool:
    handle = win32.OpenProcess(win32.SYNCHRONIZE, False, pid)
    if not handle:
        return False
    try:
        return win32.WaitForSingleObject(handle, 0) != win32.WAIT_OBJECT_0
    finally:
        win32.close(handle)


def end(pid: int) -> None:
    handle = win32.OpenProcess(win32.PROCESS_TERMINATE | win32.SYNCHRONIZE, False, pid)
    if handle:
        win32.TerminateProcess(handle, 1)
        win32.WaitForSingleObject(handle, 5000)
        win32.close(handle)


def written(marker) -> str:
    """What a test process wrote to ``marker``: "" while the file is absent or still held by
    its writer (PowerShell's Set-Content shares no reading while it writes)."""
    try:
        return marker.read_text().strip()
    except (FileNotFoundError, PermissionError):
        return ""


async def run(command: str, **kwargs):
    return await wx.run_local_command(command, timeout=kwargs.pop("timeout", 60), **kwargs)


@pytest.mark.parametrize("command, code, text", [
    ("Write-Output hello", 0, "hello"),
    ("exit 7", 7, ""),
    ("cmd /c exit 3", 3, ""),
    ("Get-Item C:\\odin-surely-missing", 1, "odin-surely-missing"),
    ("throw 'stopped here'", 1, "stopped here"),
    ("Write-Output (", 1, ""),
    ("Write-Output 'h\u00e9llo \u2713'", 0, "h\u00e9llo \u2713"),
    ("cmd /c exit 2; Write-Output after", 0, "after"),
    (f"& '{PYTHON}' -c 'print(chr(233), chr(10003))'", 0, "\u00e9 \u2713"),  # a native child
])
async def test_exit_codes_and_output_follow_bash_c(command, code, text):
    result, output = await run(command)
    assert result == code, output
    assert text in output
    assert output.effective_shell == "powershell"


async def test_a_timeout_ends_the_whole_tree(tmp_path):
    marker = tmp_path / "child.pid"
    command = (f"$p = Start-Process -PassThru -NoNewWindow '{PYTHON}' "
               f"-ArgumentList '-I','-S','-c','import time; time.sleep(60)'; "
               f"Set-Content -Path '{marker}' -Value $p.Id; Start-Sleep 60")
    started = time.monotonic()
    code, output = await run(command, timeout=8)
    assert code == 1 and output.termination_reason == "timeout"
    assert "timed out after 8 seconds" in output
    assert time.monotonic() - started < 30
    child = int(marker.read_text().strip())
    assert not alive(child), "the job's child outlived the timeout"


async def test_streaming_delivers_lines_and_a_timeout_mid_stream():
    lines = []

    async def collect(text):
        lines.append(text)

    code, output = await run("1..3 | ForEach-Object { Write-Output \"line $_\" }",
                             on_output=collect)
    assert code == 0 and [line.strip() for line in lines] == ["line 1", "line 2", "line 3"]
    lines.clear()
    code, output = await run("Write-Output first; Start-Sleep 60", on_output=collect, timeout=5)
    assert code == 1 and output.termination_reason == "timeout"
    assert lines and lines[0].strip() == "first"


async def test_cwd_is_honored_and_stdin_is_empty(tmp_path):
    code, output = await run("(Get-Location).Path; [Console]::In.ReadToEnd().Length",
                             cwd=str(tmp_path))
    assert code == 0
    first, second = output.strip().splitlines()
    assert os.path.normcase(first) == os.path.normcase(str(tmp_path)) and second == "0"


async def test_a_detached_child_survives_a_normal_finish(tmp_path):
    marker = tmp_path / "child.pid"
    code, _ = await run(f"$p = Start-Process -PassThru '{PYTHON}' "
                        f"-ArgumentList '-I','-S','-c','import time; time.sleep(60)'; "
                        f"Set-Content -Path '{marker}' -Value $p.Id")
    assert code == 0
    child = int(marker.read_text().strip())
    try:
        assert alive(child)  # as on Linux, finishing leaves deliberately detached work
    finally:
        end(child)


async def test_bash_and_sh_are_refused_on_windows():
    for mode in ("bash", "sh"):
        code, output = await run("Write-Output never", command_shell=mode)
        assert code == 1 and output.termination_reason == "shell_unavailable"
        assert f"{mode} isn't available on this Windows host" in output
    with pytest.raises(ValueError):
        wx.resolve_local_shell("zsh")


async def test_cancellation_ends_the_job(tmp_path):
    marker = tmp_path / "child.pid"
    task = asyncio.create_task(run(
        f"$p = Start-Process -PassThru -NoNewWindow '{PYTHON}' "
        f"-ArgumentList '-I','-S','-c','import time; time.sleep(60)'; "
        f"Set-Content -Path '{marker}' -Value $p.Id; Start-Sleep 60"))
    for _ in range(200):
        if written(marker):
            break
        await asyncio.sleep(0.1)
    child = int(written(marker))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not alive(child)


async def test_terminate_returns_once_every_member_has_ended(tmp_path):
    marker = tmp_path / "child.pid"
    program = ("import subprocess, sys; "
               "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'], "
               "creationflags=subprocess.CREATE_NO_WINDOW); "
               f"open(r'{marker}', 'w').write(str(child.pid))")
    running = await wx.spawn([PYTHON, "-I", "-S", "-c", program])
    try:
        await asyncio.wait_for(running.process.wait(), 30)  # the leader is gone; its child stays
        child = int(written(marker))
        assert alive(child)
        assert await wx.terminate(running)
        assert not alive(child)  # ended, not only gone from the job's list
    finally:
        wx.release(running)


async def test_terminate_reports_what_it_could_not_verify(monkeypatch):
    running = await wx.spawn([PYTHON, "-I", "-S", "-c", "import time; time.sleep(60)"])
    try:
        assert wx._member(running.job, os.getpid()) == 0  # not in this job
        assert wx._member(running.job, 0) == 0  # no process to open

        def unreadable(job):
            raise OSError("the job can't be read")

        monkeypatch.setattr(wx, "job_process_ids", unreadable)
        assert not await wx.terminate(running, timeout=0.2)  # never seen empty
        monkeypatch.undo()
        assert await wx.terminate(running)
    finally:
        wx.release(running)


def test_the_descriptions_name_windows_powershell():
    tools = [{"name": name, "description": f"{name} body\n\n[affordances: x]"}
             for name in ("run_command", "run_command_multi", "manage_process", "validate_action",
                          "read_file")]
    described = {tool["name"]: tool["description"] for tool in wx.apply_shell_contracts(tools)}
    assert "Local commands run under Windows PowerShell 5.1" in described["run_command"]
    assert "New local jobs run under Windows PowerShell 5.1" in described["manage_process"]
    assert described["read_file"] == "read_file body\n\n[affordances: x]"
    again = wx.apply_shell_contracts(wx.apply_shell_contracts(tools))
    assert again[0]["description"].count("Windows PowerShell 5.1") == 1
    refused = {tool["name"]: tool["description"]
               for tool in wx.apply_shell_contracts(tools, "bash")}
    assert "refused because bash isn't available" in refused["run_command"]


async def test_the_executor_routes_local_commands_to_powershell(tmp_path):
    from src.desktop.platform.windows_tools import exec_command

    fake = SimpleNamespace(
        bulkheads={}, config=SimpleNamespace(command_timeout_seconds=30),
        _ensure_local_workspace=lambda: str(tmp_path), _command_shell_mode=lambda: "auto")
    code, output = await exec_command(fake, "127.0.0.1", "(Get-Location).Path",
                                      use_workspace=True, use_command_shell=True)
    assert code == 0 and os.path.normcase(output.strip()) == os.path.normcase(str(tmp_path))
    code, output = await exec_command(fake, "localhost", "Write-Output internal")
    assert code == 1 and output.termination_reason == "shell_unavailable"  # internal "sh"


async def test_a_spawn_that_cannot_join_its_job_starts_nothing(monkeypatch):
    def refused(job, pid):
        raise OSError("assignment refused")

    monkeypatch.setattr(wx, "_assign", refused)
    with pytest.raises(OSError, match="assignment refused"):
        await wx.spawn(wx.shell_argv("Write-Output never"))


async def test_terminate_reports_an_empty_job():
    running = await wx.spawn(wx.shell_argv("Start-Sleep 60"))
    try:
        assert await wx.terminate(running)
    finally:
        wx.release(running)
    wx.release(running)  # idempotent


# Measured on Windows 11: what a fresh module analysis cache adds to a command's output.
RECORD = (b'<Obj S="progress" RefId="0"><TN RefId="0">'
          b'<T>System.Management.Automation.PSCustomObject</T><T>System.Object</T></TN>'
          b'<MS><I64 N="SourceId">1</I64><PR N="Record"><AV>Preparing modules for first use.</AV>'
          b'<AI>0</AI><Nil /><PI>-1</PI><PC>-1</PC><T>Completed</T><SR>-1</SR><SD> </SD></PR></MS>'
          b'</Obj>')
BLOCK = (b'<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">'
         + RECORD + b'<Obj S="progress" RefId="1"><TNRef RefId="0" /><MS><I64 N="SourceId">2</I64>'
         b'</MS></Obj></Objs>')
# PowerShell prints the record in some logon contexts (every run of a batch logon, measured)
# and not in others, so the tests write the measured bytes where PowerShell writes them: the
# header first, the block last with no newline, both on the error stream.
EMIT = ("[Console]::Error.Write(\"#< CLIXML`r`n\"); Write-Output after; "
        "[Console]::Error.WriteLine('kept'); "
        f"[Console]::Error.Write({wx.ps_quote(BLOCK.decode())})")


async def test_powershells_own_progress_is_not_output():
    raw = subprocess.run(wx.shell_argv(EMIT), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, timeout=120,
                         creationflags=subprocess.CREATE_NO_WINDOW).stdout
    assert b"#< CLIXML\r\n" in raw and raw.endswith(BLOCK), raw  # what the runner is given
    code, output = await run(EMIT)
    assert (code, sorted(str(output).split())) == (0, ["after", "kept"])
    lines = []

    async def collect(text):
        lines.append(text)

    code, output = await run(EMIT, on_output=collect)
    assert (code, sorted("".join(lines).split())) == (0, ["after", "kept"])


def test_only_powershells_progress_is_taken_out():
    text = (b"#< CLIXML\r\nfirst\r\n" + BLOCK + b"after\r\nsay #< CLIXML\r\n"
            b'<Objs Version="1" xmlns="x">kept</Objs>\r\n' + BLOCK).decode()
    assert wx.strip_progress(text) == (
        'first\r\nafter\r\nsay #< CLIXML\r\n<Objs Version="1" xmlns="x">kept</Objs>\r\n')


async def test_the_job_filter_loses_nothing_but_progress():
    long_line = b"x" * 200_000 + b"END\r\n"  # past the 64 KiB chunk with no newline
    source, target = asyncio.StreamReader(), asyncio.StreamReader()
    parts = (b"#< CLIXML\r\nfirst\r\n", long_line, BLOCK[:60], BLOCK[60:] + b"tail\r\n", BLOCK)
    for part in parts:
        source.feed_data(part)
    source.feed_eof()
    await wx.filter_progress(source, target)
    assert await target.read() == b"first\r\n" + long_line + b"tail\r\n"


# --- Verified settlement, live output and the run_script texts (Odin's 3a review) -------------


async def test_a_member_that_cant_be_pinned_is_never_verified_ended(monkeypatch):
    running = await wx.spawn([PYTHON, "-I", "-S", "-c", "import time; time.sleep(60)"])
    try:
        def unopenable(*args):
            ctypes.set_last_error(5)  # access denied proves nothing about the process
            return 0

        monkeypatch.setattr(wx.win32, "OpenProcess", unopenable)
        assert wx._member(running.job, running.pid) is None
        assert not await wx.terminate(running, timeout=1)  # the job empties, unverified

        def vanished(*args):
            ctypes.set_last_error(87)  # no such process: it has ended
            return 0

        monkeypatch.setattr(wx.win32, "OpenProcess", vanished)
        assert wx._member(running.job, running.pid) == 0
        assert await wx.terminate(running, timeout=5)
    finally:
        monkeypatch.undo()
        wx.release(running)


async def test_the_filter_passes_live_output_on_at_once():
    source, target = asyncio.StreamReader(), asyncio.StreamReader()
    filtering = asyncio.ensure_future(wx.filter_progress(source, target))
    source.feed_data(b"10%\r20%\r")  # no newline, no end of output
    assert await asyncio.wait_for(target.read(8), 2) == b"10%\r20%\r"
    source.feed_data(b"Name: ")
    assert await asyncio.wait_for(target.read(6), 2) == b"Name: "
    source.feed_data(b"x\r\n")
    assert await asyncio.wait_for(target.read(3), 2) == b"x\r\n"
    source.feed_data(b"#< CLI")  # at a line's start this might begin a record: it waits ...
    source.feed_data(b"XML\r\n" + BLOCK + b"30%\r")  # ... and was one
    assert await asyncio.wait_for(target.read(4), 2) == b"30%\r"
    source.feed_eof()
    await filtering
    assert await target.read() == b""


def test_run_scripts_texts_say_where_each_default_applies():
    from src.tools.registry import TOOLS

    (run_script,) = [tool for tool in TOOLS if tool["name"] == "run_script"]
    (adjusted,) = wx.apply_shell_contracts([run_script])
    assert "Interpreters: bash (default)" not in adjusted["description"]
    assert "on this Windows computer powershell (default)" in adjusted["description"]
    assert "on remote hosts bash (default)" in adjusted["description"]
    assert adjusted["input_schema"]["properties"]["interpreter"]["description"] == (
        "Interpreter (default: powershell on this Windows computer, bash on remote hosts)")
    assert run_script["input_schema"]["properties"]["interpreter"]["description"] == (
        "Interpreter (default: bash)")  # Linux's own definition is untouched
    assert wx.apply_shell_contracts([adjusted]) == [adjusted]


@pytest.mark.parametrize("chunks, expected", [
    ([b"10%\r20%\r"], [b"10%\r20%\r", b""]),  # CR-only progress goes on at once
    ([b"#< CL", b"IXML\r\n", BLOCK[:60], BLOCK[60:] + b"after\r\n"],
     [b"", b"", b"", b"after\r\n", b""]),  # a record split across reads waits, then goes
    ([b"say ", b"#< CLIXML\r\n"], [b"say ", b"#< CLIXML\r\n", b""]),  # mid-line: not a header
    ([b"#", b"!\n"], [b"", b"#!\n", b""]),  # a lone '#' waits for its next byte
    ([b"value <Ob", b"server>\n"], [b"value ", b"<Observer>\n", b""]),
    ([b'<Objs Version="1" xmlns="x"><S S="Error">e</S></Objs>\n'],
     [b'<Objs Version="1" xmlns="x"><S S="Error">e</S></Objs>\n', b""]),  # not progress
    ([b'<Objs Version="1.1.0.1" ' + b"x" * 70000], [b'<Objs Version="1.1.0.1" ' + b"x" * 70000,
                                                     b""]),  # past the bound: not a record
    ([b"tail #"], [b"tail #", b""]),
    ([b"#"], [b"", b"#"]),  # held to the end, then given back
])
def test_the_progress_filter_holds_only_what_might_be_a_record(chunks, expected):
    progress = wx.ProgressFilter()
    assert [*(progress.feed(chunk) for chunk in chunks), progress.finish()] == expected


async def test_bytes_held_to_the_end_still_arrive():
    source, target = asyncio.StreamReader(), asyncio.StreamReader()
    source.feed_data(b"#")
    source.feed_eof()
    await wx.filter_progress(source, target)
    assert await target.read() == b"#"


async def test_a_membership_question_that_fails_proves_nothing(monkeypatch):
    running = await wx.spawn([PYTHON, "-I", "-S", "-c", "import time; time.sleep(60)"])
    try:
        monkeypatch.setattr(wx.win32, "IsProcessInJob", lambda *args: 0)
        assert wx._member(running.job, running.pid) is None
    finally:
        monkeypatch.undo()
        assert await wx.terminate(running)
        wx.release(running)


def test_a_script_takes_a_free_name_and_cleans_up_a_failed_write(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    names = iter(["taken", "free"])
    monkeypatch.setattr(wx.secrets, "token_hex", lambda size: next(names))
    (tmp_path / "s.taken.ps1").write_bytes(b"someone else's")
    owner = wx.ScriptFile()
    wx.write_script("Write-Output hi", "s.ps1", "powershell", owner)
    assert owner.path == str(tmp_path / "s.free.ps1")
    owner.remove()
    assert (tmp_path / "s.taken.ps1").read_bytes() == b"someone else's"
    monkeypatch.setattr(wx.secrets, "token_hex", lambda size: "taken")
    with pytest.raises(FileExistsError, match="no free name"):
        wx.write_script("Write-Output hi", "s.ps1", "powershell", wx.ScriptFile())

    def failing(handle, data):
        raise OSError(112, "There is not enough space on the disk")

    monkeypatch.setattr(wx.secrets, "token_hex", lambda size: "fresh")
    monkeypatch.setattr(wx.win32, "write_all", failing)
    with pytest.raises(OSError, match="not enough space"):
        wx.write_script("Write-Output hi", "s.ps1", "powershell", wx.ScriptFile())
    assert sorted(path.name for path in tmp_path.iterdir()) == ["s.taken.ps1"]



async def test_an_unresolved_member_stays_unresolved_across_attempts(monkeypatch):
    running = await wx.spawn([PYTHON, "-I", "-S", "-c", "import time; time.sleep(60)"])
    try:
        def unopenable(*args):
            ctypes.set_last_error(5)  # access denied proves nothing, attempt after attempt
            return 0

        monkeypatch.setattr(wx.win32, "OpenProcess", unopenable)
        assert not await wx.terminate(running, timeout=1)  # timed out, unverified
        assert not await wx.terminate(running, timeout=1)  # the retry still knows the member
        attempt = asyncio.ensure_future(wx.terminate(running, timeout=30))
        await asyncio.sleep(0.3)
        attempt.cancel()
        with pytest.raises(asyncio.CancelledError):
            await attempt
        assert not await wx.terminate(running, timeout=1)  # so does one after a cancelled one
        assert None in running.members.values()
        monkeypatch.undo()  # it can be asked now: it has ended
        assert await wx.terminate(running, timeout=5)
    finally:
        monkeypatch.undo()
        wx.release(running)
    assert running.members == {}
