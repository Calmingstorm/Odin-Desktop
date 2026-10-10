"""run_script on this Windows computer (phase 3 plan C5)."""
from __future__ import annotations

import asyncio
import functools
import os
import subprocess
import tempfile
import threading
from types import SimpleNamespace

import pytest

from src.desktop.platform import windows_exec as wx
from src.desktop.platform.windows_files import dacl_is_private
from src.desktop.platform.windows_tools import exec_command, handle_run_script
from tests.windows.test_windows_adversarial import security_of


def tool(tmp_path, *, address="127.0.0.1", allowed=True, exec_override=None):
    fake = SimpleNamespace(
        _current_user_id="owner", output_streamer=None, _branch_freshness_enabled=False,
        _resolve_default_host=lambda user: "localhost",
        _resolve_host=lambda alias: (address, "root", "windows"),
        _govern_command=lambda script, host: (allowed, "Error: refused by the governor", ""),
        bulkheads={}, config=SimpleNamespace(command_timeout_seconds=60),
        _ensure_local_workspace=lambda: str(tmp_path), _command_shell_mode=lambda: "auto")
    fake._exec_command = exec_override or functools.partial(exec_command, fake)
    return fake


async def run(fake, script, **fields):
    """``(exit code, text)``; the handler returns ``(text, code)`` or bare text."""
    result = await handle_run_script(fake, {"script": script, **fields})
    if isinstance(result, tuple):
        text, code = result
        return code, text
    return 0, result


async def test_powershell_is_the_default_and_its_output_is_utf8(tmp_path):
    code, text = await run(tool(tmp_path), "Write-Output 'h\u00e9 \u2713'\n(Get-Location).Path")
    first, second = text.strip().splitlines()
    assert code == 0 and first == "h\u00e9 \u2713"
    assert os.path.normcase(second) == os.path.normcase(str(tmp_path))  # the workspace


@pytest.mark.parametrize("script, code", [
    ("Write-Output a\nexit 3", 3),
    ("Write-Output a\nthrow 'stopped'", 1),
    ("Write-Output a\ncmd /c exit 5", 0),  # as powershell -File: only exit and errors count
])
async def test_a_powershell_script_ends_as_powershell_file_would(tmp_path, script, code):
    result, text = await run(tool(tmp_path), script)
    assert result == code
    assert text.startswith(f"Script failed (exit {code}):") if code else "a" in text


async def test_using_and_param_blocks_still_come_first(tmp_path):
    script = ("using namespace System.Text\nparam([string]$Name = 'p')\n"
              "$b = [StringBuilder]::new(); $null = $b.Append($Name); $b.ToString()")
    code, text = await run(tool(tmp_path), script)
    assert (code, text.strip()) == (0, "p")


async def test_the_script_file_is_named_from_filename_and_removed(tmp_path):
    code, text = await run(tool(tmp_path), "Write-Output $PSCommandPath", filename="my report?.ps1")
    path = text.strip()
    assert code == 0 and os.path.basename(path).startswith("my_report_.")
    assert path.endswith(".ps1") and not os.path.exists(path)


async def test_python_runs_with_a_python_3(tmp_path):
    code, text = await run(tool(tmp_path), "import sys\nprint(sys.version_info[0], 'h\u00e9')",
                           interpreter="python")
    assert (code, text.strip()) == (0, "3 h\u00e9")


async def test_missing_and_posix_interpreters_are_refused_plainly(tmp_path, monkeypatch):
    refused = await handle_run_script(tool(tmp_path), {"script": "echo x", "interpreter": "bash"})
    assert str(refused).startswith("bash isn't available on this Windows computer. Use one of: ")
    assert "powershell" in str(refused)
    monkeypatch.setattr(wx.shutil, "which", lambda name: None)
    code, text = await run(tool(tmp_path), "console.log(1)", interpreter="node")
    assert code == 1 and "node isn't installed on this computer" in text


async def test_the_governor_still_sees_the_script(tmp_path):
    assert await handle_run_script(tool(tmp_path, allowed=False), {"script": "Write-Output x"}) \
        == "Error: refused by the governor"


async def test_a_remote_host_keeps_bash_and_the_shell_pipeline(tmp_path):
    sent = []

    async def remote(address, command, ssh_user, **kwargs):
        sent.append(command)
        return 0, "remote"

    fake = tool(tmp_path, address="192.0.2.10", exec_override=remote)
    assert await run(fake, "echo hi") == (0, "remote")
    assert "mktemp /tmp/odin_script.sh." in sent[0] and 'bash "$TMPF"' in sent[0]


def test_python_falls_back_from_the_store_stub_to_odins_own(tmp_path, monkeypatch):
    apps = tmp_path / "Microsoft" / "WindowsApps"
    apps.mkdir(parents=True)
    stub = apps / "python.exe"
    stub.write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(wx.shutil, "which", lambda name: str(stub) if name == "python" else None)
    assert wx.interpreter_command("python3") == [wx.sys._base_executable or wx.sys.executable]
    (apps / "PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0").mkdir()
    assert wx.interpreter_command("python") == [str(stub)]  # a Store install is real
    launcher = "C:\\Windows\\py.exe"
    monkeypatch.setattr(wx.shutil, "which", lambda name: launcher if name == "py" else None)
    assert wx.interpreter_command("python") == [launcher, "-3"]


def test_powershell_quoting_doubles_every_quote_it_honors():
    assert wx.ps_quote("C:\\O'Brien\u2019s\\x.ps1") == "'C:\\O''Brien\u2019\u2019s\\x.ps1'"


# --- The script file's life and privacy (Odin's 3a review, B8 and B9) -------------------------


async def test_a_cancelled_script_leaves_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    proceed, discarded = threading.Event(), asyncio.Event()
    real_write, real_discard = wx.write_script, wx._discard

    def held_write(*args):
        proceed.wait(10)  # the worker is still writing when its caller is cancelled
        return real_write(*args)

    def watched_discard(created):
        real_discard(created)
        discarded.set()

    monkeypatch.setattr(wx, "write_script", held_write)
    monkeypatch.setattr(wx, "_discard", watched_discard)
    task = asyncio.ensure_future(wx.run_local_script(tool(tmp_path), "127.0.0.1", "root",
                                                     "powershell", "Write-Output hi", "late.ps1"))
    await asyncio.sleep(0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    proceed.set()
    await asyncio.wait_for(discarded.wait(), 10)
    assert list(tmp_path.iterdir()) == []


def test_a_script_that_cant_be_written_leaves_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    with pytest.raises(UnicodeEncodeError):
        wx.write_script("Write-Output '\ud800'", "broken.ps1", "powershell")
    assert list(tmp_path.iterdir()) == []


async def test_the_script_file_is_private_whatever_temp_allows(tmp_path, monkeypatch):
    folder = tmp_path / "shared"
    folder.mkdir()
    subprocess.run(["icacls", str(folder), "/grant", "*S-1-1-0:(OI)(CI)R"], check=True,
                   capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    path = wx.write_script("Write-Output hi", "private.ps1", "powershell")
    try:
        assert dacl_is_private(security_of(path))
    finally:
        os.unlink(path)
    code, text = await run(tool(tmp_path), "Write-Output 'from a private file'")
    assert code == 0 and "from a private file" in text
    assert list(folder.iterdir()) == []
