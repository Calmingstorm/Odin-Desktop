"""Windows: local commands under Windows PowerShell 5.1, each in its own job (phase 3 plan, C1).

* The shell is ``powershell.exe`` by its absolute path, given the command as
  ``-EncodedCommand``, so no quoting reaches a command line. A prelude sets UTF-8
  output, and the exit code follows ``bash -c``: the status of the last command
  (a failed native command's own code, 1 for a failed cmdlet, else 0); ``exit N``
  and terminating errors end the script as they would on their own.
* Each command starts suspended, joins its own job (inside the engine's), and only
  then runs, so no child can start outside that job. Timeout and cancellation end
  the whole job and wait (bounded) for it to empty. A normal finish leaves
  deliberately detached children running, as Linux leaves its process group.
* The console is hidden, so no window flashes, and stdin is empty.
"""
from __future__ import annotations

import asyncio
import base64
import codecs
import contextlib
import ctypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from . import win32
from .windows_process import job_process_ids

SHELL_NAME = "powershell"
SHELL_LABEL = "Windows PowerShell 5.1"
_TERMINATE_SECONDS = 5.0

# UTF-8 both ways. Python writes a pipe in the ANSI code page unless told otherwise, so
# its output is UTF-8 here as on Linux (a command can still set its own).
_PRELUDE = """$ProgressPreference = 'SilentlyContinue'
$__odin_utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $__odin_utf8
$OutputEncoding = $__odin_utf8
if (-not $env:PYTHONIOENCODING) { $env:PYTHONIOENCODING = 'utf-8' }
$global:LASTEXITCODE = 0
"""
# Bash -c's rule: the status of the last command. $? here is the status of the
# command's own last statement; a failed native command leaves its exit code.
_TRAILER = """
if (-not $?) { if ($global:LASTEXITCODE) { exit $global:LASTEXITCODE } else { exit 1 } }
exit 0
"""


def powershell() -> str:
    """Windows PowerShell 5.1, by absolute path under the system folder."""
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    return os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


def encode_command(command: str) -> str:
    """``command`` between the prelude and the trailer, as ``-EncodedCommand`` wants it.

    The command runs at the script's top level, so a terminating error or ``exit``
    ends it as it would on its own, and the trailer sees its last statement.
    """
    script = _PRELUDE + command + "\n" + _TRAILER
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def shell_argv(command: str) -> list[str]:
    # Text output: otherwise PowerShell serializes the error stream as CLIXML.
    return [powershell(), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
            "Bypass", "-OutputFormat", "Text", "-EncodedCommand", encode_command(command)]


# --- Jobs -------------------------------------------------------------------------------------


@dataclass
class JobProcess:
    """A process started inside its own job. ``job`` is closed by :func:`release`."""

    process: asyncio.subprocess.Process
    job: int
    pid: int


def _create_job():
    job = win32.CreateJobObjectW(None, None)
    if not job:
        raise win32.error()
    return job


def _resume_main_thread(pid: int) -> None:
    """Resume the threads of a process created suspended (it has exactly one)."""
    snapshot = win32.CreateToolhelp32Snapshot(win32.TH32CS_SNAPTHREAD, 0)
    if snapshot in (None, win32.INVALID_HANDLE_VALUE):
        raise win32.error()
    resumed = 0
    try:
        entry = win32.THREADENTRY32()
        entry.dwSize = ctypes.sizeof(entry)
        found = win32.Thread32First(snapshot, ctypes.byref(entry))
        while found:
            if entry.th32OwnerProcessID == pid:
                thread = win32.OpenThread(win32.THREAD_SUSPEND_RESUME, False, entry.th32ThreadID)
                if not thread:
                    raise win32.error()
                try:
                    if win32.ResumeThread(thread) == 0xFFFFFFFF:
                        raise win32.error()
                finally:
                    win32.close(thread)
                resumed += 1
            found = win32.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        win32.close(snapshot)
    if not resumed:
        raise OSError("the new process has no thread to resume")


def _assign(job, pid: int) -> None:
    handle = win32.OpenProcess(win32.PROCESS_SET_QUOTA | win32.PROCESS_TERMINATE, False, pid)
    if not handle:
        raise win32.error()
    try:
        if not win32.AssignProcessToJobObject(job, handle):
            code = ctypes.get_last_error()
            win32.TerminateProcess(handle, 1)
            raise win32.error(code)
    finally:
        win32.close(handle)


async def spawn(argv: list[str], *, cwd: str | None = None, env: dict | None = None,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT) -> JobProcess:
    """Start ``argv`` suspended, put it in a new job, then let it run."""
    job = _create_job()
    try:
        process = await asyncio.create_subprocess_exec(
            *argv, stdin=stdin, stdout=stdout, stderr=stderr, cwd=cwd, env=env,
            creationflags=win32.CREATE_SUSPENDED | subprocess.CREATE_NO_WINDOW)
    except BaseException:
        win32.close(job)
        raise
    try:
        _assign(job, process.pid)
        _resume_main_thread(process.pid)
    except BaseException:
        win32.TerminateJobObject(job, 1)
        with contextlib.suppress(Exception):
            process.kill()
        win32.close(job)
        raise
    return JobProcess(process, job, process.pid)


def _member(job, pid: int) -> int | None:
    """A handle to wait on ``pid``; 0 when it has affirmatively ended (no such process, or
    the PID now names one outside ``job``); None when it couldn't be pinned, which proves
    nothing and is asked again."""
    handle = win32.OpenProcess(win32.SYNCHRONIZE | win32.PROCESS_QUERY_LIMITED_INFORMATION,
                               False, pid)
    if not handle:
        return 0 if ctypes.get_last_error() == win32.ERROR_INVALID_PARAMETER else None
    member = win32.BOOL()
    if not win32.IsProcessInJob(handle, job, ctypes.byref(member)):
        win32.close(handle)
        return None
    if member.value:
        return handle
    win32.close(handle)
    return 0


async def terminate(running: JobProcess, timeout: float = _TERMINATE_SECONDS) -> bool:
    """End every process in the job; True once each one has ended (within ``timeout``).

    A process leaves the job's list a moment before it has finished ending, so every
    member is held by a handle, from before the job is ended, and waited for. A member
    that couldn't be pinned keeps the answer False until it is (or is shown to be gone).
    """
    deadline = time.monotonic() + timeout
    handles: dict[int, int | None] = {}  # held to the end, so no PID is reused meanwhile

    def listed() -> list[int] | None:
        try:
            members = job_process_ids(running.job)
        except OSError:
            members = None
        unpinned = [pid for pid, handle in handles.items() if handle is None]
        for pid in {*(members or ()), *unpinned}:
            if handles.get(pid) is None:
                handles[pid] = _member(running.job, pid)
        return members

    def ended() -> bool:
        return all(handle is not None
                   and (not handle or win32.WaitForSingleObject(handle, 0) == win32.WAIT_OBJECT_0)
                   for handle in handles.values())

    try:
        listed()
        win32.TerminateJobObject(running.job, 1)  # an already empty job is not an error
        while listed() != [] or not ended():
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.02)
    finally:
        for handle in handles.values():
            if handle:
                win32.close(handle)
    try:
        await asyncio.wait_for(running.process.wait(), max(0.1, deadline - time.monotonic()))
    except TimeoutError:
        return False
    return True


def release(running: JobProcess) -> None:
    """Drop the job handle. Survivors keep running inside the engine's job."""
    job, running.job = running.job, 0
    if job:
        win32.close(job)


# --- run_local_command --------------------------------------------------------------------


OutputCallback = Callable[[str], Awaitable[None]]


# Windows PowerShell reports its own progress ("Preparing modules for first use.", while
# it builds a user's module analysis cache) on stderr as CLIXML whatever $ProgressPreference
# says: a header line, then a block with no newline after it, so the block can share a line
# with real output. Neither is the command's output.
_PROGRESS = re.compile(
    r"(?m)^#< CLIXML\r?\n|<Objs Version=\"[^\"]*\" xmlns=\"http://schemas\.microsoft\.com/"
    r"powershell/2004/04\">(?:<Obj S=\"progress\".*?</Obj>)+</Objs>")


_PROGRESS_BYTES = re.compile(_PROGRESS.pattern.encode("ascii"))


def strip_progress(text: str) -> str:
    """``text`` without PowerShell's progress records."""
    return _PROGRESS.sub("", text)


_HEADER_LINES = (b"#< CLIXML\r\n", b"#< CLIXML\n")
_BLOCK_START = b'<Objs Version="'
_HOLD_LIMIT = 65536  # a record is about 1 KB: anything longer that might start one doesn't


class ProgressFilter:
    """Bytes in, the same bytes out without PowerShell's progress records. What can't begin
    a record goes straight on (a CR-only progress line, a prompt without a newline); only a
    possible record's beginning waits, and never more than ``_HOLD_LIMIT`` bytes of it."""

    def __init__(self) -> None:
        self._pending = b""
        self._line_start = True  # whether the pending bytes begin a line

    def feed(self, data: bytes) -> bytes:
        self._pending += data
        return self._take(final=False)

    def finish(self) -> bytes:
        return self._take(final=True)

    def _take(self, *, final: bool) -> bytes:
        # A sentinel keeps a header from matching at the start of a line already begun.
        marked = (b"" if self._line_start else b"\0") + self._pending
        data = _PROGRESS_BYTES.sub(b"", marked)[0 if self._line_start else 1:]
        hold = len(data) if final else self._hold(data)
        out, self._pending = data[:hold], data[hold:]
        if out:
            self._line_start = out.endswith(b"\n")
        return out

    def _hold(self, data: bytes) -> int:
        """Where the bytes that might still become a record begin (``len(data)``: none)."""
        hold = len(data)
        last_line = data.rfind(b"\n") + 1
        if (last_line or self._line_start) and data[last_line:] and any(
                header.startswith(data[last_line:]) for header in _HEADER_LINES):
            hold = last_line
        start = data.find(_BLOCK_START)
        while start != -1:
            if b"</Objs>" not in data[start:]:
                hold = min(hold, start)
                break
            start = data.find(_BLOCK_START, start + 1)
        for size in range(len(_BLOCK_START) - 1, 0, -1):
            if data.endswith(_BLOCK_START[:size]):
                hold = min(hold, len(data) - size)
                break
        return len(data) if len(data) - hold > _HOLD_LIMIT else hold


async def filter_progress(source: asyncio.StreamReader, target: asyncio.StreamReader) -> None:
    """Copy a PowerShell's output without its progress records, as it comes."""
    progress = ProgressFilter()
    try:
        while chunk := await source.read(65536):
            if out := progress.feed(chunk):
                target.feed_data(out)
        if out := progress.finish():
            target.feed_data(out)
    finally:
        target.feed_eof()


async def _stream(running: JobProcess, timeout: int, on_output: OutputCallback) -> tuple[int, str]:
    """Linux's bounded line framing (``ssh._read_lines_with_callback``), with job termination."""
    from ...tools.command_shell import CommandOutput
    from ...tools.execution_outcome import mark_dispatch_uncertain
    from ...tools.ssh import _truncate_output

    process = running.process
    lines: list[str] = []
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    pending = ""

    async def emit(text: str) -> None:
        text = strip_progress(text)
        if text:
            lines.append(text)
            await on_output(text)

    def timed_out(output: str) -> tuple[int, str]:
        text = _truncate_output(output + f"\nCommand timed out after {timeout} seconds")
        return 1, CommandOutput(text, shell=SHELL_NAME, reason="timeout",
                                returncode=process.returncode)

    try:
        async with asyncio.timeout(timeout):
            while True:
                raw = await process.stdout.read(16384)
                if not raw:
                    break
                pending += decoder.decode(raw)
                while "\n" in pending:
                    line, pending = pending.split("\n", 1)
                    await emit(line + "\n")
                if len(pending) >= 16384:
                    await emit(pending)
                    pending = ""
            pending += decoder.decode(b"", final=True)
            if pending:
                await emit(pending)
        try:
            await asyncio.wait_for(process.wait(), timeout=min(timeout, 10))
        except TimeoutError:
            mark_dispatch_uncertain()
            await terminate(running)
            return timed_out("".join(lines))
    except TimeoutError:
        mark_dispatch_uncertain()
        await terminate(running)
        return timed_out("".join(lines) + pending)
    except asyncio.CancelledError:
        await terminate(running)
        raise
    except Exception:
        mark_dispatch_uncertain()
        await terminate(running)
        raise
    return process.returncode or 0, _truncate_output("".join(lines))


async def run_local_command(command: str, timeout: int = 30, on_output=None,
                            cwd: str | None = None, command_shell: str = "auto"):
    """``ssh.run_local_command`` on Windows: PowerShell, the job, the same result contract."""
    from ...observability.diagnostics import command_display, safe_error
    from ...odin_log import get_logger
    from ...tools.command_shell import CommandOutput, ShellUnavailableError, resolve_local_shell
    from ...tools.execution_outcome import mark_dispatch_uncertain
    from ...tools.ssh import _truncate_output

    log = get_logger("ssh")
    log.info("Local exec: %s", command_display(command))
    running = None
    choice = None
    try:
        choice = resolve_local_shell(command_shell)
        running = await spawn(shell_argv(command), cwd=cwd)
        if on_output is not None:
            code, output = await _stream(running, timeout, on_output)
            reason = getattr(output, "termination_reason", None)
            return code, CommandOutput(output, shell=choice.name, reason=reason,
                                       returncode=running.process.returncode)
        stdout, _ = await asyncio.wait_for(running.process.communicate(), timeout=timeout)
        output = strip_progress(stdout.decode("utf-8", errors="replace"))
        return running.process.returncode or 0, CommandOutput(
            _truncate_output(output), shell=choice.name, returncode=running.process.returncode)
    except ShellUnavailableError as exc:
        return 1, CommandOutput(str(exc), shell="unresolved", reason="shell_unavailable")
    except TimeoutError:
        if running is not None:
            mark_dispatch_uncertain()
            await terminate(running)
        return 1, CommandOutput(
            f"Command timed out after {timeout} seconds",
            shell=choice.name if choice else "unresolved", reason="timeout",
            returncode=running.process.returncode if running is not None else None)
    except asyncio.CancelledError:
        if running is not None:
            await terminate(running)
        raise
    except Exception as exc:
        if running is not None:
            mark_dispatch_uncertain()
            await terminate(running)
        log.error("Local command failed: %s", safe_error(exc))
        return 1, f"Local exec error: {safe_error(exc)}"
    finally:
        if running is not None:
            release(running)


# --- This computer as a host ----------------------------------------------------------------

def supported_host_os(address: str) -> set[str]:
    """Linux and macOS for SSH hosts, as in Odin; a local address is this Windows computer."""
    from ...tools.ssh import is_local_address

    allowed = {"linux", "macos"}
    if is_local_address(str(address)):
        allowed.add("windows")
    return allowed


async def local_host_test(timeout: float) -> tuple[int, str]:
    """The Hosts panel's check of this computer, through the local command runner."""
    code, output = await run_local_command("Write-Output 'odin-host-test windows'",
                                           timeout=int(timeout))
    return code, str(output)


# --- run_script on this computer --------------------------------------------------------------

SCRIPT_EXTENSIONS = {"powershell": ".ps1", "python": ".py", "python3": ".py", "node": ".js",
                     "ruby": ".rb", "perl": ".pl"}
_REMOTE_INTERPRETERS = frozenset({"bash", "sh", "python3", "python", "node", "ruby", "perl"})
_STORE_PYTHON = "PythonSoftwareFoundation.Python."


class ScriptRefusedError(Exception):
    """This computer can't run the script with the interpreter asked for."""


def _local(executor, alias) -> bool:
    from ...tools.ssh import is_local_address

    resolved = executor._resolve_host(alias) if alias else None
    return bool(resolved) and is_local_address(resolved[0])


def default_interpreter(executor, alias) -> str:
    """powershell for this computer; bash for a remote host, as in Odin."""
    return "powershell" if _local(executor, alias) else "bash"


def interpreters_for(executor, alias) -> set[str]:
    return set(SCRIPT_EXTENSIONS) if _local(executor, alias) else set(_REMOTE_INTERPRETERS)


def unsupported_interpreter(interpreter: str, allowed: set[str]) -> str:
    if interpreter in {"bash", "sh"} and "powershell" in allowed:
        return f"{interpreter} isn't available on this Windows computer."
    return f"Unsupported interpreter: {interpreter}."


def _store_stub(path: str) -> bool:
    """WindowsApps' python.exe opens the Microsoft Store unless a Store Python is installed."""
    folder = os.path.dirname(path)
    apps = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps")
    if os.path.normcase(folder) != os.path.normcase(apps):
        return False
    try:
        return not any(name.startswith(_STORE_PYTHON) for name in os.listdir(folder))
    except OSError:
        return True


def interpreter_command(interpreter: str) -> list[str]:
    """The program and leading arguments that run a script file; PowerShell needs none."""
    if interpreter == "powershell":
        return []
    if interpreter in {"python", "python3"}:
        launcher = shutil.which("py")
        if launcher:
            return [launcher, "-3"]
        found = shutil.which("python")
        if found and not _store_stub(found):
            return [found]
        return [getattr(sys, "_base_executable", "") or sys.executable]  # Odin's own Python
    found = shutil.which(interpreter)
    if not found:
        raise ScriptRefusedError(
            f"{interpreter} isn't installed on this computer (not found on PATH).")
    return [found]


def ps_quote(text: str) -> str:
    """A PowerShell single-quoted string; its curly quotes close strings too, so they double."""
    return "'" + re.sub("(['\u2018\u2019\u201a\u201b])", r"\1\1", text) + "'"


def write_script(script: str, filename: str | None, interpreter: str) -> str:
    """The script in a new temporary file, private from the moment it exists: its own
    owner-only DACL, whatever the temporary folder lets others do. PowerShell's gets a BOM.
    A script that can't be written leaves no file."""
    extension = SCRIPT_EXTENSIONS[interpreter]
    stem = os.path.basename(filename or "") or "odin_script"
    if stem.lower().endswith(extension):
        stem = stem[:-len(extension)]
    stem = re.sub(r"[^A-Za-z0-9_.-]", "_", stem)[:64] or "odin_script"
    # Windows PowerShell 5.1 reads a file without a BOM in the ANSI code page.
    data = script.encode("utf-8-sig" if interpreter == "powershell" else "utf-8")
    folder = tempfile.gettempdir()
    with win32.SecurityDescriptor(win32.PRIVATE_SDDL) as descriptor:
        for _ in range(100):
            path = os.path.join(folder, f"{stem}.{secrets.token_hex(8)}{extension}")
            try:
                handle = win32.create_file(path, win32.GENERIC_WRITE, 0, win32.CREATE_NEW,
                                           win32.FILE_ATTRIBUTE_NORMAL, descriptor.attributes())
            except FileExistsError:
                continue
            break
        else:
            raise FileExistsError("no free name for the script's temporary file")
    try:
        win32.write_all(handle, data)
    except BaseException:
        win32.close(handle)
        with contextlib.suppress(OSError):
            os.unlink(path)
        raise
    win32.close(handle)
    return path


def _discard(created: asyncio.Future) -> None:
    """A file a cancelled caller never received goes as soon as it exists."""
    if not created.cancelled() and created.exception() is None:
        with contextlib.suppress(OSError):
            os.unlink(created.result())


async def run_local_script(executor, address: str, ssh_user: str, interpreter: str, script: str,
                           filename: str | None, on_output=None):
    """``run_script`` on this computer: a private temporary file, run by the local command runner.

    PowerShell runs it as ``powershell -File`` would (``exit N``; 1 for an uncaught error;
    otherwise 0) with UTF-8 output. Other interpreters exit with their own status.
    """
    try:
        program = interpreter_command(interpreter)
    except ScriptRefusedError as exc:
        return 1, str(exc)
    created = asyncio.ensure_future(asyncio.to_thread(write_script, script, filename, interpreter))
    try:
        path = await asyncio.shield(created)
    except asyncio.CancelledError:
        created.add_done_callback(_discard)  # the worker can't be stopped; its file can
        raise
    try:
        command = "& " + " ".join(ps_quote(part) for part in [*program, path])
        return await executor._exec_command(address, command, ssh_user, on_output=on_output,
                                            use_workspace=True, use_command_shell=True)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)


# --- Routed variants of src/tools/command_shell.py ----------------------------------------


def resolve_local_shell(mode: str = "auto"):
    """``resolve_local_shell`` on Windows: ``auto`` is Windows PowerShell; bash and sh refuse."""
    from ...tools.command_shell import ShellChoice, ShellUnavailableError

    if mode not in {"auto", "bash", "sh"}:
        raise ValueError("tools.command_shell must be auto, bash or sh")
    if mode != "auto":
        raise ShellUnavailableError(
            f"tools.command_shell={mode}: {mode} isn't available on this Windows host; "
            "command not executed")
    return ShellChoice(SHELL_NAME, powershell())


# run_script's own text names bash as the default everywhere; on Windows it says where.
_INTERPRETERS = "Interpreters: bash (default), python3, python, sh, node, ruby, perl. "
_WINDOWS_INTERPRETERS = (
    "Interpreters: on this Windows computer powershell (default), python3, python, node, ruby, "
    "perl; on remote hosts bash (default), python3, python, sh, node, ruby, perl. ")
_INTERPRETER_FIELD = ("Interpreter (default: powershell on this Windows computer, bash on remote "
                      "hosts)")


def _windows_interpreters(tool: dict) -> dict:
    description = tool["description"].replace(_INTERPRETERS, _WINDOWS_INTERPRETERS)
    tool = {**tool, "description": description}
    schema = tool.get("input_schema")
    if schema and "interpreter" in schema.get("properties", {}):
        properties = schema["properties"]
        tool["input_schema"] = {**schema, "properties": {
            **properties, "interpreter": {**properties["interpreter"],
                                          "description": _INTERPRETER_FIELD}}}
    return tool


def apply_shell_contracts(definitions: list[dict], mode: str = "auto") -> list[dict]:
    """``apply_shell_contracts`` on Windows: the descriptions name Windows PowerShell 5.1."""
    if mode == "auto":
        command = f"Local commands run under {SHELL_LABEL}"
        jobs = f"New local jobs run under {SHELL_LABEL}"
        checks = f"Local command checks run under {SHELL_LABEL}"
        scripts = (
            "On this Windows computer a PowerShell script ends with its exit N, 1 for an uncaught "
            "error, otherwise 0. python and python3 use the Python launcher, python on PATH or "
            "Odin's own Python; node, ruby and perl come from PATH; bash and sh aren't available "
            "here.")
    else:
        missing = f"{mode} isn't available on this Windows host"
        command = f"New local commands are refused because {missing}"
        jobs = f"New local jobs are refused because {missing}"
        checks = f"New local command checks are refused because {missing}"
        scripts = f"Scripts on this computer are refused because {missing}."
    foreground = f"{command}; remote commands use the remote account's login shell."
    clauses = {
        "run_command": foreground,
        "run_command_multi": foreground,
        "manage_process": f"{jobs}; remote jobs run under /bin/sh.",
        "validate_action": f"{checks}; remote command checks use the remote account's login shell.",
        "run_script": scripts,
    }
    markers = (" Local commands run under ", " New local commands are refused because ",
               " New local jobs run under ", " New local jobs are refused because ",
               " Local command checks run under ", " New local command checks are refused because ",
               " On this Windows computer a PowerShell script ends with",
               " Scripts on this computer are refused because ")
    result = []
    for tool in definitions:
        name = tool["name"]
        description = tool["description"]
        if name in clauses:
            body, separator, footer = description.partition("\n\n[affordances:")
            for marker in markers:
                body = body.partition(marker)[0]
            description = body + " " + clauses[name] + separator + footer
        tool = {**tool, "description": description}
        result.append(_windows_interpreters(tool) if name == "run_script" else tool)
    return result
