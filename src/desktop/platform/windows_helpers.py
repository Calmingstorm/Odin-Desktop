"""Windows: the local helpers' own commands on this computer (phase 3 plan C12).

* Branch freshness asks git four POSIX-shell questions on the host where tests ran, in the
  test's own folder when the command changed into one. On this computer they're asked in
  PowerShell's words (the same git commands, Windows' redirections, ``Set-Location`` for
  the folder); any other host keeps Odin's commands.
* ``http_probe`` builds a curl command. On this computer ``curl.exe`` runs straight from
  that command's own arguments, in a job of its own: Windows PowerShell 5.1 would take
  ``curl`` for Invoke-WebRequest and drop the double quotes inside native arguments
  (every JSON body). Other hosts keep the command.
"""
from __future__ import annotations

import asyncio
import functools
import os
import shlex

from ...tools.branch_freshness import FRESHNESS_CHECK_TIMEOUT
from .windows_exec import ps_quote, release, spawn, terminate
from .windows_payloads import curl_policy_args, packaged_file

# --- Branch freshness -----------------------------------------------------------------------

_GIT = {
    "git rev-parse --abbrev-ref HEAD 2>/dev/null":
        "git rev-parse --abbrev-ref HEAD 2>$null; exit $LASTEXITCODE",
    "git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null":
        "git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>$null; exit $LASTEXITCODE",
    "git fetch --quiet 2>&1": "git fetch --quiet 2>$null; exit $LASTEXITCODE",
    "git rev-list --count 'HEAD..@{u}' 2>/dev/null":
        "git rev-list --count 'HEAD..@{u}' 2>$null; exit $LASTEXITCODE",
}
_IN_FOLDER = "cd -- "


def powershell_git(command: str) -> str:
    """A freshness query in PowerShell's words; any other command is refused.

    Odin asks in the test's folder as ``cd -- '<folder>' && git ...``: here that is
    ``Set-Location -LiteralPath``, and a missing folder fails the question as ``cd``
    would.
    """
    folder = None
    if command.startswith(_IN_FOLDER) and " && git " in command:
        quoted, rest = command[len(_IN_FOLDER):].split(" && git ", 1)
        parts = shlex.split(quoted)
        if len(parts) != 1 or not parts[0]:
            raise ValueError(f"no PowerShell form for {command!r}")
        folder, command = parts[0], "git " + rest
    if command not in _GIT:
        raise ValueError(f"no PowerShell form for {command!r}")
    if folder is None:
        return _GIT[command]
    return (f"Set-Location -LiteralPath {ps_quote(folder)}; if (-not $?) {{ exit 1 }}; "
            f"{_GIT[command]}")


async def check_branch_freshness(exec_fn, address: str, ssh_user: str,
                                 timeout: int = FRESHNESS_CHECK_TIMEOUT, *,
                                 directory: str | None = None):
    """``check_branch_freshness`` on Windows: this computer's questions go to PowerShell."""
    from ...tools.branch_freshness import check_branch_freshness as freshness
    from ...tools.ssh import is_local_address

    if not is_local_address(address):
        return await freshness.linux_original(
            exec_fn, address, ssh_user, timeout, directory=directory)

    async def local(address: str, command: str, ssh_user: str):
        return await exec_fn(address, powershell_git(command), ssh_user, use_command_shell=True)

    return await freshness.linux_original(local, address, ssh_user, timeout, directory=directory)


# --- http_probe -----------------------------------------------------------------------------

def resolve_handler(self, tool_name: str):
    """``ToolExecutor._resolve_handler`` on Windows: the table's ``http_probe`` handler is the
    Windows one, bound to the same owner (``browser_web.py`` stays upstream's byte for
    byte). An instance override still wins, and every other tool resolves as on Linux."""
    from ...tools.executor import EXECUTOR_HANDLERS, ToolExecutor
    from .windows_tools import handle_http_probe

    handler = ToolExecutor._resolve_handler.linux_original(self, tool_name)
    if tool_name != "http_probe" or handler is None:
        return handler
    owner_key, attr = EXECUTOR_HANDLERS[tool_name]
    owner = getattr(self, "_handler_owners", {}).get(owner_key)
    if owner is None or handler != getattr(owner, attr, None):
        return handler  # an override: it governs, as on Linux
    return functools.partial(handle_http_probe, owner)


def curl_exe() -> str:
    bundled = packaged_file("tools/curl/curl.exe")
    if bundled is not None:
        return str(bundled)
    path = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "curl.exe")
    if not os.path.isfile(path):
        raise FileNotFoundError(
            "curl.exe isn't on this computer (Windows 10 1803 and later ship it)")
    return path


async def run_argv(argv: list[str], timeout: int) -> tuple[int, str]:
    """``argv`` in a job of its own, its output and errors together; ended whole on timeout
    or cancellation (``run_local_command``'s contract, without a shell)."""
    from ...observability.diagnostics import safe_error
    from ...tools.execution_outcome import mark_dispatch_uncertain
    from ...tools.ssh import _truncate_output

    try:
        running = await spawn(argv)
    except OSError as exc:
        return 1, f"Local exec error: {safe_error(exc)}"
    try:
        stdout, _ = await asyncio.wait_for(running.process.communicate(), timeout=timeout)
    except TimeoutError:
        mark_dispatch_uncertain()
        await terminate(running)
        return 1, f"Command timed out after {timeout} seconds"
    except asyncio.CancelledError:
        await terminate(running)
        raise
    except Exception as exc:
        mark_dispatch_uncertain()
        await terminate(running)
        return 1, f"Local exec error: {safe_error(exc)}"
    finally:
        release(running)
    return running.process.returncode or 0, _truncate_output(
        stdout.decode("utf-8", errors="replace"))


async def probe(executor, address: str, command: str, ssh_user: str, *, target=None):
    """``http_probe``'s transport: curl.exe from the command's arguments on this computer."""
    from ...tools.executor import BulkheadFullError, _current_tool_timeout_ctx, is_local_address

    if not is_local_address(address):
        return await executor._exec_command(address, command, ssh_user, target=target)
    argv = shlex.split(command)
    if argv[:1] != ["curl"]:
        raise ValueError("http_probe runs curl")
    try:
        argv = [curl_exe(), *curl_policy_args(), *argv[1:]]
    except FileNotFoundError as exc:
        return 1, str(exc)
    timeout = _current_tool_timeout_ctx.get() or executor.config.command_timeout_seconds
    bulkhead = executor.bulkheads.get("subprocess")
    if bulkhead:
        try:
            async with bulkhead.acquire():
                return await run_argv(argv, timeout)
        except BulkheadFullError:
            return 1, "Error: subprocess bulkhead full — too many concurrent local commands"
    return await run_argv(argv, timeout)
