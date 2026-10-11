"""Windows: MCP stdio servers, each in a kill-on-close job of its own (phase 3 plan C9).

Linux starts a server in its own session and signals that process group to stop it. Windows
has no process groups to signal, so a server starts suspended in a job of its own: whatever
it starts joins the job, and closing the job's handle ends anything left. Stopping keeps
Linux's order: stdin closed (the server's own way out), then the whole job ended and seen
empty, and the same closed callback.

The command is found as Linux's exec finds it: a path from the server's working folder, a
bare name in the server's own PATH (not this process's folder or working folder, which
Windows would search first), with PATHEXT's extensions. A ``.cmd`` such as ``npx`` runs
through cmd.exe as Windows runs it, each part quoted so cmd.exe passes it on unchanged.
"""
from __future__ import annotations

import asyncio
import os
import re
import tempfile

from ...odin_log import get_logger
from .windows_exec import release, spawn, terminate

# A drive's absolute path, or a share's (\\server\share, \\?\ included).
_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]{2}[^\\/]+[\\/]+[^\\/]+)")

log = get_logger("mcp.stdio")

# Windows' own operational variables: without SystemRoot a child can't open a socket, and
# node, npx and Python want the profile folders. None of them carries a credential.
WINDOWS_ENV = (
    "SystemRoot", "SystemDrive", "windir", "ComSpec", "PATHEXT", "TEMP", "TMP", "USERPROFILE",
    "APPDATA", "LOCALAPPDATA", "ProgramData", "ProgramFiles", "ProgramFiles(x86)",
    "ProgramW6432", "CommonProgramFiles", "CommonProgramFiles(x86)", "CommonProgramW6432",
    "ALLUSERSPROFILE", "PUBLIC", "HOMEDRIVE", "HOMEPATH", "USERNAME", "USERDOMAIN",
    "COMPUTERNAME", "NUMBER_OF_PROCESSORS", "OS", "PROCESSOR_ARCHITECTURE",
    "PROCESSOR_IDENTIFIER", "PROCESSOR_LEVEL", "PROCESSOR_REVISION",
)
_DEFAULT_PATHEXT = ".COM;.EXE;.BAT;.CMD"
_BATCH = {".bat", ".cmd"}
# What cmd.exe still changes inside double quotes: a variable (%, and ! when delayed expansion
# is on), a quote that would end the quoting, and a line break that would end the command.
_BATCH_UNSAFE = re.compile(r'["%!\r\n]')


def _lookup(env: dict[str, str], name: str) -> str | None:
    """``env[name]`` the way Windows reads it: names ignore case."""
    return next((value for key, value in env.items() if key.upper() == name.upper()), None)


def _put(env: dict[str, str], name: str, value: str) -> None:
    for key in [key for key in env if key.upper() == name.upper()]:
        del env[key]
    env[name] = value


def build_child_env(configured: dict[str, str] | None) -> dict[str, str]:
    """``build_child_env`` on Windows: Linux's allowlist and Windows' own variables, then the
    server's configured env (one entry per name, whatever its case)."""
    from ...tools.mcp.transport_stdio import _ENV_ALLOWLIST

    env: dict[str, str] = {}
    for name in (*WINDOWS_ENV, *_ENV_ALLOWLIST):
        if (value := os.environ.get(name)) is not None:
            _put(env, name, value)
    for name, value in (configured or {}).items():
        _put(env, str(name), str(value))
    return env


def find_program(command: str, env: dict[str, str], cwd: str) -> str | None:
    """Where ``command`` is: a path from ``cwd``, or a bare name in ``env``'s PATH, whose
    relative folders are the child's (from ``cwd``), as Linux's exec in the child finds them.
    A name with an extension is tried as given first; PATHEXT's extensions are then tried in
    turn, so they add a missing extension but never refuse one the command names."""
    extensions = [ext for ext in (_lookup(env, "PATHEXT") or _DEFAULT_PATHEXT).split(";") if ext]
    if os.path.dirname(command):
        bases = [os.path.join(cwd, command)]
    else:
        folders = [folder.strip('"') for folder in (_lookup(env, "PATH") or "").split(os.pathsep)]
        bases = [os.path.join(cwd, folder, command) for folder in folders if folder]
    named = bool(os.path.splitext(command)[1])
    for base in bases:
        for candidate in ([base] if named else []) + [base + ext for ext in extensions]:
            if os.path.isfile(candidate):
                return os.path.abspath(candidate)
    return None


def batch_line(server: str, program: str, args: list[str]) -> str:
    """The command line for a batch launcher such as ``npx.cmd``. cmd.exe reads its command
    line again, so every part is quoted (``& | < > ^ ( )`` stay literal inside the quotes),
    and a part cmd.exe would still change is refused instead of passed changed. Launchers
    forward ``%*`` to a native program, whose C runtime reads backslashes before a quote as
    escapes, so a part's trailing backslashes are doubled and arrive as they were given."""
    from ...tools.mcp.errors import MCPConnectError

    if any(_BATCH_UNSAFE.search(part) for part in (program, *args)):
        raise MCPConnectError(f"{server}: a batch launcher can't receive an argument with a "
                              "quote, %, ! or a line break unchanged")
    return " ".join('"' + re.sub(r"(\\+)$", r"\1\1", part) + '"' for part in (program, *args))


async def start(self) -> None:
    """``StdioTransport.start`` on Windows: the server in a kill-on-close job of its own."""
    from ...tools.mcp.errors import MCPConnectError
    from ...tools.mcp.protocol import MAX_STDOUT_LINE_BYTES
    from ...tools.mcp.transport_stdio import build_child_env as child_env

    if self._process is not None:
        raise MCPConnectError(f"{self.server_name}: transport already started")
    if not self.command:
        raise MCPConnectError(f"{self.server_name}: stdio requires 'command'")
    if self.cwd and not os.path.isdir(self.cwd):
        raise MCPConnectError(f"{self.server_name}: cwd does not exist: {self.cwd}")
    effective_cwd = self.cwd or tempfile.gettempdir()
    env = child_env(self.env)
    program = find_program(self.command, env, effective_cwd)
    if program is None:
        raise MCPConnectError(f"{self.server_name}: command not found: {self.command}")
    batch = os.path.splitext(program)[1].lower() in _BATCH
    line = batch_line(self.server_name, program, self.args) if batch else None
    try:
        running = await spawn(
            [program, *self.args], cwd=effective_cwd, env=env, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            limit=MAX_STDOUT_LINE_BYTES + 1024, kill_on_close=True, command_line=line)
    except OSError as e:
        raise MCPConnectError(f"{self.server_name}: failed to start: {e}") from e
    self._windows_job = running
    self._process = running.process
    self._spawned_pgid = None  # no process group on Windows: the job is the group
    self._reader_task = asyncio.create_task(self._pump_stdout())
    self._stderr_task = asyncio.create_task(self._pump_stderr())


async def shutdown_inner(self) -> None:
    """``_shutdown_inner`` on Windows: stdin close → the job ended → seen empty; never raises."""
    from ...tools.mcp import transport_stdio as stdio

    proc = self._process
    if proc is None:
        self._fire_closed("transport shut down", final=True)
        return
    running = self._windows_job
    final_reason = "transport shut down"
    try:
        if proc.returncode is None and proc.stdin is not None:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=stdio._STDIN_CLOSE_GRACE)
            except TimeoutError:
                pass
        # Windows has no TERM to send: the job ends whole, the server and all it started,
        # within Linux's TERM and KILL graces together.
        if not await terminate(running, timeout=stdio._TERM_GRACE + stdio._KILL_GRACE):
            final_reason = ("process survived termination grace" if proc.returncode is None
                            else "process tree survived termination grace")
            log.warning("MCP %s: %s", self.server_name, final_reason)
    except Exception:
        log.exception("MCP %s: shutdown cleanup failed", self.server_name)
    finally:
        release(running)
        for task in (self._reader_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._reader_task = None
        self._stderr_task = None
        self._fire_closed(final_reason, final=True)


def validate_server_config(name: str, config: dict) -> None:
    """``validate_server_config`` on Windows: a server's working folder is a Windows absolute
    path (a drive's or a share's) without NUL bytes, where Linux asks for one starting with
    "/"; every other rule is Linux's own."""
    from ...tools.mcp.errors import MCPConfigError
    from ...tools.mcp.manager import validate_server_config as router

    cwd = str(config.get("cwd") or "")
    if cwd and ("\0" in cwd or not _ABSOLUTE.match(cwd)):
        raise MCPConfigError(f"{name}: cwd must be an absolute path without NUL bytes")
    router.linux_original(name, {**config, "cwd": ""})
