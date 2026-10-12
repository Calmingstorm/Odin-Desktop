"""Windows: background jobs for ``manage_process`` on this computer (phase 3 plan C7).

Odin's process registry already treats its supervised shell as the owner of a job:
it waits for the leader through ``wait`` and ends everything the job started through
``terminate_tree``, which must report an empty job before a record settles. On
Windows that shell is Windows PowerShell in a job object of its own:

* ``wait`` resolves when PowerShell exits, whatever still holds its pipes.
* ``terminate_tree`` ends every process in the job and is True only once the job
  is seen empty. The job handle is dropped then, never before, so a survivor is
  never left outside a job the registry can still end.

Output spooling, cursors, retention, remote jobs and the tool's text are the
registry's own, unchanged. Only the local start differs (``start_local_reserved``
in ``windows_tools``, lifted from the Linux original).
"""
from __future__ import annotations

import asyncio

from ...tools.local_supervisor import SupervisedShell
from ...tools.process_manager import ProcessRegistry
from .windows_exec import (
    SHELL_NAME,
    JobProcess,
    filter_progress,
    powershell,
    release,
    shell_argv,
    spawn,
    terminate,
)

_EXIT_POLL_SECONDS = 0.1
# Linux's worker allows its grace plus twelve seconds for a whole-tree settlement.
_SETTLE_SECONDS = 12.0


class JobShell(SupervisedShell):
    """Windows PowerShell in its own job, in the shape the registry expects of its shell."""

    def __init__(self, running: JobProcess):  # no supervisor worker or control socket here
        process = running.process
        self._running = running
        self._empty = False  # once True, settled for good
        self._settling = asyncio.Lock()  # the exit watch, kill and shutdown settle one at a time
        self.stdin = process.stdin
        self.stdout = process.stdout
        self.stderr = process.stderr
        if process.stdout is not None:  # PowerShell's own progress records aren't output
            self.stdout = asyncio.StreamReader()
            self._filter = asyncio.ensure_future(filter_progress(process.stdout, self.stdout))
        self.pid = running.pid
        self.returncode: int | None = None
        self.effective_shell = SHELL_NAME
        self.shell_executable = powershell()

    async def wait(self) -> int:
        """The leader's exit code, as soon as it exits; open pipes don't delay it."""
        process = self._running.process
        while process.returncode is None:
            await asyncio.sleep(_EXIT_POLL_SECONDS)
        self.returncode = process.returncode
        return self.returncode

    async def terminate_tree(self, grace: float = 3.0) -> bool:
        """End every process in the job; True only once each of them has ended.

        Callers settle one at a time, so the job handle is never let go while another is
        still asking about it, and a success is never undone by a later caller.
        """
        async with self._settling:
            if self._empty:
                return True
            if not self._running.job:
                return False  # never ask about job 0: Windows would answer for the engine's job
            if await terminate(self._running, timeout=grace + _SETTLE_SECONDS):
                self._empty = True
                self.returncode = self._running.process.returncode
                release(self._running)
            return self._empty


async def create_job_shell(command, *, stdin=None, stdout=None, stderr=None,
                           start_new_session=True, cwd=None, env=None, shell_choice=None):
    """``create_supervised_shell`` on Windows: Windows PowerShell in a job of its own."""
    running = await spawn(shell_argv(command), cwd=cwd, env=env, stdin=stdin, stdout=stdout,
                          stderr=stderr)
    return JobShell(running)


class WindowsProcessRegistry(ProcessRegistry):
    """Odin's process registry with local jobs started as :class:`JobShell`."""

    async def _start_local_reserved(self, *args, **kwargs) -> str:
        from .windows_tools import start_local_reserved

        return await start_local_reserved(self, *args, **kwargs)
