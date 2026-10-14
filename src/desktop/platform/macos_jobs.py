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

Two commands Odin builds for itself, read_file's raw transport and apply_patch, are written for GNU
hosts. They are recognized by their exact opening text (any host) and made portable before they
run: their ``chmod 600 -- FILES`` becomes ``chmod -- 600 FILES`` (BSD chmod reads ``--`` after the
mode as a file; both mean the same on GNU), and apply_patch's host runner is given a rename that is
renameatx_np(RENAME_EXCL) on a macOS host and Linux's own renameat2 elsewhere. Only that opening is
rewritten, never text after it (paths, scripts); every other command runs exactly as written, and
a raw command route (run_command) is never rewritten.
"""
# ruff: noqa: E501
from __future__ import annotations

import asyncio
import base64
import json
import re
import shlex
import socket
import sys
import zlib
from pathlib import Path

from src.tools import local_supervisor as _ls
from src.tools.process_manager import ProcessRegistry

SCOPE = "session_best_effort"
CAVEAT = "detached or raced descendants are unverified"
_CAVEAT_TEXT = f" containment={SCOPE}; {CAVEAT}."
_META_RESERVE = 160  # room for the two metadata fields within the page budget

# The host runner's rename: renameatx_np(RENAME_EXCL) on a macOS host, Linux's own elsewhere.
RENAME_ON_THE_HOST = (
    "_rename = _rename_noreplace\n"
    "if _sys.platform == 'darwin':\n"
    "    def _rename(source, destination, *, src_dir_fd, dst_dir_fd):\n"
    "        import ctypes, errno\n"
    "        _libc = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)\n"
    "        _call = _libc.renameatx_np\n"
    "        _call.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,\n"
    "                          ctypes.c_uint]\n"
    "        _call.restype = ctypes.c_int\n"
    "        if _call(src_dir_fd, os.fsencode(source), dst_dir_fd, os.fsencode(destination),\n"
    "                 0x4) != 0:  # RENAME_EXCL\n"
    "            code = ctypes.get_errno()\n"
    "            if code in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:\n"
    "                raise PatchError('target filesystem lacks the atomic no-replace rename '\n"
    "                                 'required by apply_patch')\n"
    "            raise OSError(code, os.strerror(code), destination)\n"
)
# The opening text of Odin's own commands (src/tools/handlers/files_docs.py), exactly.
_READ_FILE_RAW = (
    "metadata=$(mktemp) || exit 1; "
    'body=$(mktemp) || { rm -f -- "$metadata"; exit 1; }; '
    'encoded=$(mktemp) || { rm -f -- "$metadata" "$body"; exit 1; }; '
    'trap \'rm -f -- "$metadata" "$body" "$encoded"\' EXIT; '
    'chmod 600 -- "$metadata" "$body" "$encoded" || exit 1; ')
_APPLY_PATCH = (
    "runner=$(mktemp) || exit 1; "
    'plan=$(mktemp) || { rm -f -- "$runner"; exit 1; }; '
    'trap \'rm -f -- "$runner" "$plan"\' EXIT; '
    'chmod 600 -- "$runner" "$plan" || exit 1; ')
_DECODER = shlex.quote(
    "import base64,sys,zlib; "
    "sys.stdout.buffer.write(zlib.decompress(base64.b64decode(sys.stdin.buffer.read())))")
# apply_patch's next step, right after its opening: the runner, plain or compressed.
_RUNNER = re.compile(r'printf %s ([A-Za-z0-9+/=]+) \| (base64 -d|'
                     + re.escape(f"python3 -c {_DECODER}") + r') > "\$runner" \|\| exit 1; ')
_WRAPPER = "\nimport json\nimport sys as _sys\n"
_APPLY_CALL = "    _changed = apply_plan(_sys.argv[1], _plan)\n"
_APPLY_WITH_RENAME = "    _changed = apply_plan(_sys.argv[1], _plan, rename_noreplace=_rename)\n"


def _with_rename(payload: str, *, compressed: bool) -> str:
    """apply_patch's runner payload, given the host's rename; unchanged if it isn't Odin's."""
    try:
        raw = base64.b64decode(payload, validate=True)
        text = (zlib.decompress(raw) if compressed else raw).decode("utf-8")
    except (ValueError, zlib.error):
        return payload
    anchor = text.rfind(_WRAPPER)
    tail = text[anchor + len(_WRAPPER):] if anchor >= 0 else ""
    if anchor < 0 or tail.count(_APPLY_CALL) != 1:
        return payload
    patched = (text[:anchor + len(_WRAPPER)] + RENAME_ON_THE_HOST
               + tail.replace(_APPLY_CALL, _APPLY_WITH_RENAME, 1)).encode("utf-8")
    return base64.b64encode(zlib.compress(patched) if compressed else patched).decode("ascii")


def engine_command(command: str) -> str | None:
    """Which of Odin's own GNU-written commands this is, by its exact opening; else None."""
    if command.startswith(_READ_FILE_RAW):
        return "read_file"
    if command.startswith(_APPLY_PATCH) and _RUNNER.match(command, len(_APPLY_PATCH)):
        return "apply_patch"
    return None


def _bsd_order(opening: str) -> str:
    return opening.replace("chmod 600 -- ", "chmod -- 600 ", 1)


def portable_command(command: str) -> str:
    """One of Odin's own commands, written to run on GNU and BSD hosts alike (see the notes)."""
    kind = engine_command(command)
    if kind == "read_file":
        return _bsd_order(_READ_FILE_RAW) + command[len(_READ_FILE_RAW):]
    if kind == "apply_patch":
        match = _RUNNER.match(command, len(_APPLY_PATCH))
        payload = _with_rename(match.group(1), compressed=match.group(2) != "base64 -d")
        return (_bsd_order(_APPLY_PATCH) + command[len(_APPLY_PATCH):match.start(1)] + payload
                + command[match.end(1):])
    return command


PRIVACY_HINT = (
    "\n[macOS privacy] macOS may have refused this for privacy (Operation not permitted). If so, "
    "allow Odin in System Settings > Privacy & Security > Files and Folders (or Full Disk Access "
    "for other protected data), then try again.")
# Places macOS protects by privacy setting: Files and Folders (Desktop, Documents, Downloads,
# iCloud Drive, external and network volumes), and data behind Full Disk Access.
PROTECTED_PLACES = ("/Desktop", "/Documents", "/Downloads", "/Library/Mobile Documents",
                    "/Volumes/", "/Library/Mail", "/Library/Messages", "/Library/Safari",
                    "/Library/Containers/", "/Library/Group Containers/")


def with_privacy_hint(code: int, output):
    """A local failure that macOS refused (Operation not permitted) at a place it protects for
    privacy says which setting may allow it, once. EPERM has other causes too (an immutable
    flag, for one), so the hint is offered only where a protected place is named, and never
    retries anything itself."""
    from src.tools.command_shell import CommandOutput

    text = str(output)
    if (code == 0 or "Operation not permitted" not in text or PRIVACY_HINT in text
            or not any(place in text for place in PROTECTED_PLACES)):
        return output
    if isinstance(output, CommandOutput):
        return CommandOutput(text + PRIVACY_HINT, shell=output.effective_shell,
                             reason=output.termination_reason, returncode=output.raw_returncode)
    return text + PRIVACY_HINT


_internal_bin: Path | None = None


def _internal_environment(env):
    """The environment for apply_patch's runner: the engine's interpreter first as python3.

    The runner is engine code and needs a current python3. On macOS, /usr/bin/python3 is Apple's
    older interpreter, or a stub that offers to install developer tools; neither is the engine's.
    A private folder in the verified per-user temporary folder holds a python3 that runs the
    engine's interpreter isolated and without writing bytecode (-I -B): the runner's command
    passes neither, and the app ships no bytecode, so the interpreter would otherwise write it
    into the app (which the app's start check then finds changed), and read the user's Python
    settings. It goes ahead of the rest of PATH. Every other command keeps the user's own PATH,
    run_script included: its script is the model's, run by the user's interpreter.
    """
    import os
    import shlex
    import tempfile

    from .darwin import user_temp_root

    global _internal_bin
    if _internal_bin is None or not (_internal_bin / "python3").is_file():
        folder = Path(tempfile.mkdtemp(prefix="odin-desktop-bin-", dir=user_temp_root()))
        script = f"#!/bin/sh\nexec {shlex.quote(sys.executable)} -I -B \"$@\"\n"
        fd = os.open(folder / "python3", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
        with os.fdopen(fd, "w") as stream:
            stream.write(script)
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
        if internal:  # macOS: apply_patch's runner uses the engine's own python3
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

    # Odin's own GNU-written commands, made portable for whichever host runs them. A raw
    # command route (run_command) is never rewritten, whatever its text.
    kind = None if use_command_shell else engine_command(command)
    if kind is not None:
        command = portable_command(command)
    if not is_local_address(address):
        return await ToolExecutor._exec_command.linux_original(
            self, address, command, ssh_user, timeout, on_output, use_workspace, target,
            use_command_shell)
    if timeout is None:
        timeout = _current_tool_timeout_ctx.get() or self.config.command_timeout_seconds
    cwd = self._ensure_local_workspace() if use_workspace else None
    shell = self._command_shell_mode() if use_command_shell else "sh"
    internal = kind == "apply_patch"  # only its runner needs the engine's python3
    bh = self.bulkheads.get("subprocess")
    if bh:
        try:
            async with bh.acquire():
                code, output = await run_local_command(
                    command, timeout=timeout, on_output=on_output, cwd=cwd,
                    command_shell=shell, internal=internal)
        except BulkheadFullError:
            return 1, "Error: subprocess bulkhead full — too many concurrent local commands"
    else:
        code, output = await run_local_command(command, timeout=timeout, on_output=on_output,
                                               cwd=cwd, command_shell=shell, internal=internal)
    return code, with_privacy_hint(code, output)


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
    """The page with the scope, the caveat and Work's release verdict in its metadata; unchanged
    if it has none."""
    def extend(text: str) -> str | None:
        try:
            meta = json.loads(text)
        except ValueError:
            return None
        if not isinstance(meta, dict) or meta.get("kind") != "process_output":
            return None
        meta["containment"] = SCOPE
        meta["cleanup_caveat"] = CAVEAT
        if "cleanup_verified" in meta:
            # A settled stop converged on the session; it never proves it empty, so the public
            # verdict is Work's: best effort once settled, unproven otherwise, never verified.
            meta["resource_release"] = "best_effort" if meta["cleanup_verified"] else "unproven"
            meta["cleanup_verified"] = False
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
