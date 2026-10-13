"""macOS: local commands and background jobs, through the macOS supervisor worker.

Odin's parent side is reused unchanged. The worker (macos_supervisor_worker) speaks the Linux
worker's protocol, so SupervisedShell, the command reader, terminate_process_tree and the process
registry drive a macOS command exactly as a Linux one. Three entry points are lifted from their
Linux originals, whose files Desktop keeps byte-identical to Odin, with only the worker swapped:
create_supervised_shell (local_supervisor), run_local_command (ssh) and the registry's local start
(process_manager). Remote execution stays Linux's own.

The worker's cleanup is best effort (session observation, see its notes). The registry therefore
labels its local jobs' scope ``session_best_effort``: Work reports a converged stop as best effort,
and the tool text and poll metadata carry the caveat, as Odin does for a remote process group.
"""
# ruff: noqa: E501
from __future__ import annotations

import asyncio
import json
import socket
import sys
from pathlib import Path

from src.tools import local_supervisor as _ls
from src.tools.process_manager import ProcessRegistry

SCOPE = "session_best_effort"
CAVEAT = "detached or raced descendants are unverified"
_CAVEAT_TEXT = f" containment={SCOPE}; {CAVEAT}."
_META_RESERVE = 160  # room for the two metadata fields within the page budget


_internal_bin: Path | None = None


def _internal_environment(env):
    """The environment for an engine-built command: the engine's interpreter first as python3.

    Commands the engine writes for itself (apply_patch's runner) need a current python3. On macOS,
    /usr/bin/python3 is Apple's older interpreter, or a stub that offers to install developer
    tools; neither is the engine's. A private folder in the verified per-user temporary folder
    holds a python3 link to the engine's interpreter, ahead of the rest of PATH. Commands a model
    writes keep the user's own PATH.
    """
    import os
    import tempfile

    from .darwin import user_temp_root

    global _internal_bin
    if _internal_bin is None or not (_internal_bin / "python3").is_symlink():
        folder = Path(tempfile.mkdtemp(prefix="odin-desktop-bin-", dir=user_temp_root()))
        os.symlink(sys.executable, folder / "python3")
        _internal_bin = folder
    environment = dict(os.environ if env is None else env)
    environment["PATH"] = os.pathsep.join(
        [str(_internal_bin), *[part for part in environment.get("PATH", "").split(os.pathsep)
                               if part]])
    return environment


# Lifted from the Linux original (src/tools/local_supervisor.py), with the macOS worker.
async def create_supervised_shell(command, *, stdin=None, stdout=None, stderr=None,
                                  start_new_session=True, cwd=None, env=None, shell_choice=None):
    from src.tools.command_shell import resolve_local_shell, shell_environment

    choice = shell_choice or resolve_local_shell("sh")
    env = shell_environment(choice, env)
    loop = asyncio.get_running_loop()
    if loop in _ls._closing_loops:
        raise _ls.SupervisorError('Local command supervision is shutting down')
    if not start_new_session:
        raise ValueError('supervised shells require a private session')
    parent, child = socket.socketpair()
    parent.setblocking(False)
    spawn_task = asyncio.create_task(asyncio.create_subprocess_exec(
        sys.executable, '-I', str(Path(__file__).with_name('macos_supervisor_worker.py')),
        '--control-fd', str(child.fileno()), '--command', command,
        '--shell', choice.name, '--shell-executable', choice.executable,
        pass_fds=(child.fileno(),), start_new_session=True,
        stdin=stdin, stdout=stdout, stderr=stderr, cwd=cwd, env=env,
    ))
    owner = asyncio.current_task()
    assert owner is not None
    _ls._pending.add(owner)
    shell = None
    try:
        worker = await asyncio.shield(spawn_task)
        child.close()
        reader, writer = await asyncio.open_connection(sock=parent, limit=4096)
        shell = _ls.SupervisedShell(worker, reader, writer)
        shell.effective_shell = choice.name
        shell.shell_executable = choice.executable
        await asyncio.wait_for(asyncio.shield(shell._started), timeout=10)
        return shell
    except BaseException:
        child.close()
        if shell is None and parent.fileno() >= 0:
            # Cancellation can arrive after fork but before protocol setup.
            # Recover the worker handle, then obtain real settlement evidence.
            try:
                worker = await asyncio.shield(spawn_task)
                reader, writer = await asyncio.open_connection(sock=parent, limit=4096)
                shell = _ls.SupervisedShell(worker, reader, writer)
                await asyncio.wait_for(asyncio.shield(shell._started), timeout=10)
            except BaseException:
                if not spawn_task.done() or (
                    not spawn_task.cancelled() and spawn_task.exception() is None
                ):
                    _ls._unverified_startup = True
                    from src.restart import block_reexec

                    block_reexec('local supervisor startup cleanup unverified')
        if shell is not None:
            try:
                await shell.terminate_tree(grace=.1)
            except Exception:
                pass  # preserve original launch failure/cancellation
        else:
            parent.close()
            if not spawn_task.done() or (
                not spawn_task.cancelled() and spawn_task.exception() is None
            ):
                # No protocol means no clean-settlement evidence. Persist the
                # veto before any cancellable cleanup or worker-status wait.
                _ls._unverified_startup = True
                from src.restart import block_reexec

                block_reexec('local supervisor startup cleanup unverified')
            try:
                worker = await spawn_task
                await asyncio.wait_for(worker.wait(), timeout=15)
            except Exception:
                if not spawn_task.cancelled() and spawn_task.exception() is None:
                    _ls._unverified_startup = True
                    from src.restart import block_reexec

                    block_reexec('local supervisor startup cleanup unverified')
        raise
    finally:
        child.close()
        _ls._pending.discard(owner)


# Lifted from the Linux original (src/tools/ssh.py), with the macOS create_supervised_shell.
async def run_local_command(
    command: str,
    timeout: int = 30,
    on_output=None,
    cwd: str | None = None,
    command_shell: str = "sh",
    internal: bool = False,
) -> tuple[int, str]:
    """Run a command locally via subprocess. Returns (exit_code, output).

    Used for localhost hosts — no SSH overhead, no key needed.
    POSIX is the shared default. Raw-command routes supply the configured
    shell explicitly; internal command builders must not inherit live config.
    When *on_output* is provided, stdout is streamed line-by-line to the
    callback in addition to being collected for the return value.

    *cwd* is the resolved local workspace (``tools.local_working_dir``). It only
    changes where a BARE RELATIVE path lands: explicit ``cd``, absolute paths,
    and ``git -C <path>`` are unaffected, so deliberately working inside the
    install remains possible. ``None`` inherits the process cwd — the
    pre-2026-07-27 behaviour, kept only for internal callers that legitimately
    depend on the application directory.
    """
    from src.observability.diagnostics import command_display, safe_error
    from src.tools.ssh import (
        _read_lines_with_callback,
        _truncate_output,
        log,
        mark_dispatch_uncertain,
        terminate_process_tree,
        workspace_env,
    )

    log.info("Local exec: %s", command_display(command))
    from src.tools.command_shell import CommandOutput, ShellUnavailableError, resolve_local_shell

    proc = None
    choice = None
    try:
        # PWD/OLDPWD are normalized alongside cwd: cwd= alone leaves an
        # inherited OLDPWD pointing at the install, so a bare `cd -` would walk
        # right back into it (review finding, 2026-07-27).
        choice = resolve_local_shell(command_shell)
        env = workspace_env(Path(cwd)) if cwd else None
        if internal:  # macOS: engine-built commands use the engine's own python3
            env = _internal_environment(env)
        # start_new_session puts the shell at the head of its own process
        # group, so timeout/cancellation cleanup can take out descendants
        # (`sh -c 'x & ...'`) instead of just the shell leader.
        proc = await create_supervised_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
            cwd=cwd,
            env=env,
            shell_choice=choice,
        )
        if on_output is not None:
            code, output = await _read_lines_with_callback(
                proc, timeout, on_output, owned_pgid=proc.pid,
            )
            reason = getattr(output, "termination_reason", None)
            return code, CommandOutput(
                output, shell=choice.name, reason=reason, returncode=proc.returncode,
            )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode("utf-8", errors="replace")
        return proc.returncode or 0, CommandOutput(
            _truncate_output(output), shell=choice.name, returncode=proc.returncode,
        )

    except ShellUnavailableError as exc:
        return 1, CommandOutput(str(exc), shell="unresolved", reason="shell_unavailable")
    except TimeoutError:
        if proc is not None:
            mark_dispatch_uncertain()
            await terminate_process_tree(proc, owned_pgid=proc.pid)
        return 1, CommandOutput(
            f"Command timed out after {timeout} seconds",
            shell=choice.name if choice else "unresolved", reason="timeout",
            returncode=proc.returncode if proc is not None else None,
        )
    except asyncio.CancelledError:
        # Loop drain at shutdown/restart cancels in-flight commands; the
        # child tree must die with this process, not outlive the exec —
        # owned_pgid keeps the group signallable even when the shell already
        # exited naturally, leaving a descendant holding stdout.
        if proc is not None:
            await terminate_process_tree(proc, owned_pgid=proc.pid)
        raise
    except Exception as e:
        if proc is not None:
            mark_dispatch_uncertain()
            await terminate_process_tree(proc, owned_pgid=proc.pid)
        log.error("Local command failed: %s", safe_error(e))
        return 1, f"Local exec error: {safe_error(e)}"


async def exec_command(
    self,
    address: str,
    command: str,
    ssh_user: str = "root",
    timeout: int | None = None,
    on_output=None,
    use_workspace: bool = False,
    target=None,
    use_command_shell: bool = False,
) -> tuple[int, str]:
    """``ToolExecutor._exec_command`` on macOS: local commands through the macOS worker.

    The local half is Linux's, bulkhead included; anything else is Linux's own method.
    """
    from src.tools.executor import (
        BulkheadFullError,
        ToolExecutor,
        _current_tool_timeout_ctx,
        is_local_address,
    )

    if not is_local_address(address):
        return await ToolExecutor._exec_command.linux_original(
            self, address, command, ssh_user, timeout, on_output, use_workspace, target,
            use_command_shell)
    if timeout is None:
        timeout = _current_tool_timeout_ctx.get() or self.config.command_timeout_seconds
    cwd = self._ensure_local_workspace() if use_workspace else None
    shell = self._command_shell_mode() if use_command_shell else "sh"
    internal = not use_command_shell  # raw command routes opt into the configured shell
    bh = self.bulkheads.get("subprocess")
    if bh:
        try:
            async with bh.acquire():
                return await run_local_command(command, timeout=timeout, on_output=on_output,
                                               cwd=cwd, command_shell=shell, internal=internal)
        except BulkheadFullError:
            return 1, "Error: subprocess bulkhead full — too many concurrent local commands"
    return await run_local_command(command, timeout=timeout, on_output=on_output, cwd=cwd,
                                   command_shell=shell, internal=internal)


# Lifted from the Linux original (ProcessRegistry._start_local_reserved), with the macOS
# create_supervised_shell and the best-effort scope recorded on the job.
async def start_local_reserved(
    self, host: str, command: str, timeout: int = 300, *, owner_id: str | None = None,
    host_alias: str = "", host_identity: str = "", origin_channel: str = "",
    scope_id: str = "", host_binding: dict | None = None, host_lease=None,
) -> str:
    """Start a background process locally. Returns confirmation with PID.

    ``host_lease`` is the generation-bound admission evidence the handler
    already acquired for this start (H2). It is held for the job's WHOLE
    lifetime — admission evidence while it runs, plus the live lease
    reference that lets ``force_revoke_host``/``shutdown`` see and fence
    this exact generation — and released only when the job settles or is
    torn down. Never persisted.
    """
    from src.tools.process_manager import JOB_TOKEN_ENV, MAX_LIFETIME_SECONDS, Path, ProcessInfo, WorkspaceError, asyncio, command_display, log, os, safe_text, secrets, time, workspace_env  # noqa: E501, I001
    from src.tools.ssh import is_local_address

    if not is_local_address(host):
        return "Error: remote process start requires a generation-bound host lease."

    alias = host_alias or host
    if alias in self._revoking_aliases or (host_lease is not None and host_lease.revoked):
        return self._refuse_start(host_lease, "Error: host force-revoked; process not started.")
    revoke_epoch = self._local_revoke_epochs.get(alias, 0)

    try:
        # start_new_session puts the shell at the head of its own process
        # group, so kill()/shutdown() can take out descendants
        # (`sh -c 'x & ...'`) instead of just the shell leader.
        workspace = self._resolve_workspace()
        job_token = secrets.token_hex(8)
        env = dict(workspace_env(Path(workspace))) if workspace else dict(os.environ)
        env[JOB_TOKEN_ENV] = job_token
    except WorkspaceError as e:
        # The workspace is unusable. This is a REFUSAL, not a spawn error:
        # it must read as a failure to the tool loop, not as a started
        # process (PR #239 round-4 — the plain string was classified ok).
        return self._refuse_start(
            host_lease, f"Error: cannot start background process — {e}"
        )
    try:
        from src.tools.command_shell import ShellUnavailableError, resolve_local_shell

        mode = self._command_shell() if callable(self._command_shell) else self._command_shell
        shell_choice = resolve_local_shell(mode)
        proc = await create_supervised_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.PIPE,
            start_new_session=True,
            cwd=workspace,
            env=env,
            shell_choice=shell_choice,
        )
    except ShellUnavailableError as exc:
        return self._refuse_start(host_lease, f"Error: {exc}")
    except asyncio.CancelledError:
        # Cancellation is not a refusal, but it is still an exit path: the
        # generation reference must be processed before it propagates, or
        # a cancelled start leaks a lease for a job that never existed.
        self._release_start_lease(host_lease)
        raise
    except Exception as e:
        return self._refuse_start(host_lease, f"Failed to start process: {e}")

    pid = proc.pid
    info = ProcessInfo(
        pid=pid,
        command=command,
        host=host,
        start_time=time.time(),
        process=proc,
        effective_shell=shell_choice.name,
        shell_executable=shell_choice.executable,
        job_token=job_token,
        owner_id=owner_id,
        host_alias=host_alias,
        host_identity=host_identity,
        origin_channel=origin_channel,
        scope_id=scope_id,
        host_binding=host_binding,
        host_lease=host_lease,
    )
    info.containment = SCOPE  # macOS: a converged stop is best effort, never verified
    self._processes[pid] = info
    self._retained_generations[info.generation] = info
    self._own_children.add(pid)

    # Drainage and terminal-state publication are SEPARATE tasks:
    # the reader drains stdout; the watcher publishes status at
    # leader exit and reaps the group (which closes the pipe).
    try:
        info._reader_task = asyncio.create_task(self._read_output(info))
        info._exit_task = asyncio.create_task(self._watch_exit(info))
        from src.async_utils import fire_and_forget

        info._lifetime_task = fire_and_forget(
            self._enforce_lifetime(info, MAX_LIFETIME_SECONDS), name=f"process_lifetime:{pid}"
        )
        self._persist_output(info)
    except BaseException:
        # The job is already spawned and recorded, so it now OWNS the
        # lease. Tear the process down instead of leaving an untracked
        # generation reference behind (H2); an unstartable lifecycle
        # deliberately fails loud here.
        await self._terminate_bound_host_job(info)
        raise

    if (revoke_epoch != self._local_revoke_epochs.get(alias, 0)
            or alias in self._revoking_aliases
            or (host_lease is not None and host_lease.revoked)):
        # Spawn crossed the revoke snapshot. Install the complete lifecycle
        # before teardown: even an unprovable kill must not strand a
        # permanently-running record or its concurrency slot.
        gone = await self._terminate_bound_host_job(info)
        if not gone:
            info.status = "unknown"
            info.finished_at = info.finished_at or time.time()
            info.capture_error = info.capture_error or "process cleanup could not be confirmed"
            self._persist_output(info)
        return ("Error: host force-revoked; process terminated."
                if gone else "Error: host force-revoked; process outcome unknown outcome_unknown=true.")

    log.info("Started process PID %d: %s", pid, command_display(command))
    return f"Process started (PID {pid}): {safe_text(command)}"


def _with_caveat_fields(page: str) -> str:
    """The page with the scope and caveat added to its metadata; unchanged if it has none."""
    def extend(text: str) -> str | None:
        try:
            meta = json.loads(text)
        except ValueError:
            return None
        if not isinstance(meta, dict) or meta.get("kind") != "process_output":
            return None
        meta["containment"] = SCOPE
        meta["cleanup_caveat"] = CAVEAT
        return json.dumps(meta, ensure_ascii=False, separators=(",", ":"))

    marker = "\n[output retention] "
    if marker in page:
        body, _, meta = page.rpartition(marker)
        extended = extend(meta)
        return page if extended is None else body + marker + extended
    extended = extend(page)
    return page if extended is None else extended


class MacOSProcessRegistry(ProcessRegistry):
    """Odin's process registry, with local jobs under the macOS worker and their scope labelled."""

    async def _start_local_reserved(self, *args, **kwargs) -> str:
        return await start_local_reserved(self, *args, **kwargs)

    @staticmethod
    def _remote_cleanup_caveat(info) -> str:
        if not info.remote and info.containment == SCOPE:
            return _CAVEAT_TEXT
        return ProcessRegistry._remote_cleanup_caveat(info)

    @staticmethod
    def _output_page(info, data: bytes, start: int, limit: int, budget: int, *, preview: bool,
                     tail_withheld: bool = False) -> str:
        if info.remote or info.containment != SCOPE:
            return ProcessRegistry._output_page(info, data, start, limit, budget, preview=preview,
                                                tail_withheld=tail_withheld)
        page = ProcessRegistry._output_page(info, data, start, limit,
                                            max(0, budget - _META_RESERVE), preview=preview,
                                            tail_withheld=tail_withheld)
        return _with_caveat_fields(page)

    async def kill(self, pid: int, *, authorized=None) -> str:
        result = await super().kill(pid, authorized=authorized)
        info = self._processes.get(pid)
        if (info is not None and not info.remote and info.containment == SCOPE
                and result == f"Process {pid} killed."):
            return result + _CAVEAT_TEXT
        return result


# Lifted from the Linux original (ToolExecutor._ensure_process_registry), with the macOS registry.
def ensure_process_registry(self):
    """Lazy-init the ProcessRegistry ON THE EXECUTOR (RFC-004 P4).

    The attribute stays here — not on the system domain — because the
    web API (agents_loops, config_admin) and graceful shutdown read
    ``tool_executor._process_registry`` directly.
    """
    if not hasattr(self, "_process_registry"):
        # Pass the RESOLVER, not a resolved string: each background spawn
        # must re-verify the workspace's mutable filesystem invariants.
        self._process_registry = MacOSProcessRegistry(  # macOS: the session worker
            workspace=self._ensure_local_workspace,
            remote_exec=self._exec_remote_target,
            retention_dir=self._retention_root() / "process-output",
            acquire_output_lease=self._acquire_process_cleanup_lease,
            command_shell=lambda: self._command_shell_mode(),
        )
    return self._process_registry
