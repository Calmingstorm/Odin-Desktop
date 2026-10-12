"""App-supervised Desktop entry point with retained containment barriers."""

from __future__ import annotations

import asyncio
import os
import select
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import NoReturn

from src import restart
from src.desktop.platform.variants import windows_variant
from src.runtime_paths import runtime_install_root
from src.tools.process_manager import AdoptedZombieReaper


@windows_variant("src.desktop.platform.windows_process:enable_process_containment")
def _enable_process_containment(log) -> bool:
    """Become a child subreaper so escaped descendants stay ours.

    Process-wide state, so it is set ONCE here at the application
    boundary rather than by any library constructor. Without it, a
    background descendant that double-forks and calls ``setsid()``
    reparents to PID 1 and becomes unattributable — and the process
    manager then refuses to claim its cleanup is complete (PR #244).
    """
    import secrets

    from .tools.process_manager import (
        DEFAULT_JOB_TOKEN,
        JOB_TOKEN_ENV,
        PROC_TOKEN_ENV,
        set_child_subreaper,
    )

    # Process-wide provenance: stamped into os.environ BEFORE any
    # subprocess is spawned, so every child Odin creates inherits it and
    # background-job cleanup can tell another subsystem's child (decided
    # not-ours) from one that discarded its environment (ambiguous, fails
    # closed).
    os.environ.setdefault(PROC_TOKEN_ENV, secrets.token_hex(8))
    # Every child inherits a job token; background jobs override it with
    # their own. A child that has the process marker but NO job token
    # deleted it, which is tampering — not foreign ownership.
    os.environ.setdefault(JOB_TOKEN_ENV, DEFAULT_JOB_TOKEN)

    if set_child_subreaper(True):
        log.debug("Child-subreaper containment active")
        return True
    else:
        log.error(
            "Could not become a child subreaper — escaped background "
            "descendants would be unattributable; cleanup will refuse to "
            "report success and in-place restarts will be blocked"
        )
    return False


# Cooperative per-step ceiling for the ordinary finalize barrier. It keeps
# well-behaved async work bounded, but it is NOT a hard wall-clock guarantee:
# cancellation may enter synchronous user code and prevent the loop from ever
# servicing asyncio.wait()'s timeout (round-23 #2).
_FINALIZE_STEP_TIMEOUT = 3.0

# Hard process-level ceiling, armed in an isolated helper process BEFORE
# finalization begins. The ordinary barrier has at most three cooperative 3s
# phases (task drain, async generators, default executor); the remaining margin
# covers the final zombie proof and clean close. If the main process blocks
# anywhere — including with the GIL retained in cancellation/finalization or in
# loop.close() — the helper SIGKILLs that exact incarnation via pidfd. This is
# deliberately out-of-process: once teardown starts, no code in Odin's process
# is trusted to make progress.
_FINALIZE_WATCHDOG_TIMEOUT = 12.0


# Objects caught on the emergency path are parked here FOREVER — the
# process exits moments later. CPython clears an `except ... as exc`
# binding when the handler ends; if that drops the final reference, a
# user-defined __del__ runs synchronously on the main thread BEFORE
# os._exit is reached (round-22, reproduced on all three failure
# paths). Parking keeps the reference alive so no finalizer can ever
# run on this path. Never cleared, never capped: eviction would drop
# references, which is exactly the hazard.
_PARKED_FOR_EXIT: list[object] = []


def _safe_repr(exc: BaseException) -> str:
    """Identity of ``exc`` without executing ANY of its code (round-21).

    ``repr()``/``str()``/f-string interpolation all re-enter
    user-controlled methods: a blocking ``__repr__`` hung the main
    thread on the emergency path, and a repr returning a ``str``
    SUBCLASS smuggled a hostile ``__format__`` into the f-string that
    consumed it. ``object.__repr__`` is C-level — it never calls back
    into the exception, reads the type's name from the type dict
    without the descriptor protocol, and returns an EXACT ``str`` that
    concatenates and formats inertly. The message (``args``) is
    deliberately dropped: it is user-controlled data of user-controlled
    type.
    """
    try:
        return object.__repr__(exc)
    except BaseException:
        return "unrepresentable exception"


def _finalize_loop(loop, zombie_reaper: AdoptedZombieReaper, log) -> str | None:
    """Teardown tail in the exact round-15 §3.3 order.

    Drain before close: cancel stragglers, then run the loop's async
    generator and default-executor shutdown hooks — closing without this
    destroys still-pending work mid-await, and an in-place restart would
    exec over half-finished writes. Only AFTER that barrier has every
    subprocess owner provably stopped, so only then may the final
    no-grace zombie drain run (a drain any earlier could consume an exit
    status a still-running owner legitimately awaits — round-15
    blocker #1).

    Cooperative steps use bounded ``asyncio.wait`` calls. They are backed by
    the process-level watchdog armed by :func:`_finalize_and_exit`, because no
    event-loop timeout can fire while cancellation/finalization is executing
    blocking synchronous code (round-23). Failure anywhere on this path VETOES
    the in-place re-exec
    (``restart.block_reexec``): exec'ing over an unverified process
    table hands invisible survivors to the new image, while exiting
    lets the supervisor start clean and PID 1 reap whatever remains.

    Returns None when the owner barrier completed (tasks, async
    generators and the default executor all provably stopped), else the
    failure reason. An unproven verdict means owners MAY include
    blocked non-daemon threads — the caller must then leave via the
    emergency path, never via ordinary interpreter shutdown (round-17)
    — and the unproven return path itself performs NO synchronous I/O,
    not even logging or the veto record (round-19).
    """
    owners_stopped = False
    failure = ""
    pending: list = []
    done: set = set()
    refused: set = set()
    try:
        pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            done, refused = loop.run_until_complete(
                asyncio.wait(pending, timeout=_FINALIZE_STEP_TIMEOUT)
            )
            for settled in done:
                if not settled.cancelled():
                    settled.exception()  # retrieve; parity with gather()
        if refused:
            failure = f"{len(refused)} task(s) survived cancellation"
        else:
            for label, factory in (
                ("async-generator", loop.shutdown_asyncgens),
                ("default-executor", loop.shutdown_default_executor),
            ):
                hook = loop.create_task(factory())
                _done, hung = loop.run_until_complete(
                    asyncio.wait({hook}, timeout=_FINALIZE_STEP_TIMEOUT)
                )
                if hung:
                    _PARKED_FOR_EXIT.append(hook)
                    failure = f"{label} shutdown did not finish"
                    break
                if hook.exception() is not None:
                    # A hook that RAISED is as unproven as one that hung
                    # — asyncio.wait reports it done, but done-with-error
                    # is not a completed barrier. Park the task: its
                    # exception (and coroutine frame) must not be freed
                    # on this path (round-22).
                    _PARKED_FOR_EXIT.append(hook)
                    failure = f"{label} shutdown failed"
                    break
            else:
                owners_stopped = True
    except Exception as exc:
        _PARKED_FOR_EXIT.append(exc)  # a dropped ref could run __del__
        failure = "exception during loop drain: " + _safe_repr(exc)
    if not owners_stopped:
        # UNPROVEN verdict. From here to os._exit there must be NO
        # synchronous I/O: a blocking logging handler would hang the
        # main thread before the emergency exit is ever reachable, and
        # a raising one would unwind into ordinary interpreter shutdown
        # — the exact round-17 hang again (round-19). No log line, no
        # veto record (restart.block_reexec logs), not even
        # loop.close() (pending-task warnings go through logging): the
        # caller's emergency path says all of it from a bounded scribe.
        # The task collections are parked too — releasing them at frame
        # exit would free coroutine frames whose locals can carry
        # user-defined finalizers (round-22).
        _PARKED_FOR_EXIT.extend((pending, done, refused))
        return failure or "owner barrier unproven"
    try:
        drained, verified = zombie_reaper.drain_at_teardown()
    except Exception as exc:
        # A failing drain is a FAILURE VERDICT like any other: no
        # synchronous logging, no veto record here — a blocking handler
        # would hang the main thread before the emergency exit is
        # reachable (round-20 #1). The reason travels to the scribe;
        # the exception is parked so no __del__ fires here (round-22).
        _PARKED_FOR_EXIT.append(exc)
        return "final zombie drain failed: " + _safe_repr(exc)
    if not verified:
        return "final zombie drain could not verify a clean process table"
    if drained:
        log.info("Reaped %d adopted zombie(s) at teardown", drained)
    loop.close()
    log.info("Odin stopped")
    return None


_FINALIZE_WATCHDOG_PROGRAM = r"""
import os
import select
import signal
import sys

control_fd = int(sys.argv[1])
ready_fd = int(sys.argv[2])
parent_pidfd = int(sys.argv[3])
deadline = float(sys.argv[4])
try:
    os.write(ready_fd, b"R")
    os.close(ready_fd)
    readable, _, _ = select.select([control_fd], [], [], deadline)
    if not readable:
        signal.pidfd_send_signal(parent_pidfd, signal.SIGKILL)
finally:
    os._exit(0)
"""


@dataclass(frozen=True, slots=True)
class _FinalizeWatchdog:
    """Kernel-backed finalization deadline and captured disarm primitives."""

    control_fd: int
    pid: int
    hard_exit: Callable[[int], NoReturn]
    write: Callable[[int, bytes], int]
    close: Callable[[int], None]
    waitpid: Callable[[int, int], tuple[int, int]]


@windows_variant("src.desktop.platform.windows_process:arm_finalize_watchdog")
def _arm_finalize_watchdog(exit_code: int) -> _FinalizeWatchdog:
    """Arm an out-of-process, GIL-independent finalization deadline.

    A Python thread cannot be a hard wall-clock boundary: synchronous teardown
    can retain the GIL forever. The isolated helper process owns a pidfd for
    this exact parent incarnation and sends SIGKILL if the control pipe is not
    disarmed before the deadline. The helper acknowledges startup before this
    function returns, so finalize never begins without an active guard.

    The helper does no logging or cleanup at expiry. Its signal is deliberately
    uncatchable and pidfd-targeted, so user callbacks cannot intercept it and
    PID reuse cannot redirect it. Arm failure exits immediately rather than
    attempting unguarded finalization.
    """
    code = exit_code or 1
    # Capture every primitive before teardown can run arbitrary callbacks.
    hard_exit = os._exit
    pipe = os.pipe
    close = os.close
    read = os.read
    write = os.write
    waitpid = os.waitpid
    set_inheritable = os.set_inheritable
    pidfd_open = os.pidfd_open
    spawn = os.posix_spawn
    select_ready = select.select
    control_r = control_w = ready_r = ready_w = parent_pidfd = -1
    try:
        control_r, control_w = pipe()
        ready_r, ready_w = pipe()
        parent_pidfd = pidfd_open(os.getpid())
        for fd in (control_r, ready_w, parent_pidfd):
            set_inheritable(fd, True)
        argv = (
            sys.executable,
            "-I",
            "-S",
            "-c",
            _FINALIZE_WATCHDOG_PROGRAM,
            str(control_r),
            str(ready_w),
            str(parent_pidfd),
            str(_FINALIZE_WATCHDOG_TIMEOUT),
        )
        pid = spawn(sys.executable, argv, os.environ)
        for fd in (control_r, ready_w, parent_pidfd):
            close(fd)
        control_r = ready_w = parent_pidfd = -1

        readable, _, _ = select_ready([ready_r], [], [], 2.0)
        if not readable or read(ready_r, 1) != b"R":
            hard_exit(code)
            raise AssertionError("os._exit returned")  # test doubles only
        close(ready_r)
        ready_r = -1
        return _FinalizeWatchdog(
            control_fd=control_w,
            pid=pid,
            hard_exit=hard_exit,
            write=write,
            close=close,
            waitpid=waitpid,
        )
    except BaseException:  # noqa: BLE001 — no unguarded finalize is allowed
        for fd in (control_r, control_w, ready_r, ready_w, parent_pidfd):
            if fd >= 0:
                try:
                    close(fd)
                except BaseException:
                    pass
        hard_exit(code)
        raise AssertionError("os._exit returned")  # test doubles only


@windows_variant("src.desktop.platform.windows_process:disarm_finalize_watchdog")
def _disarm_finalize_watchdog(
    watchdog: _FinalizeWatchdog, exit_code: int
) -> None:
    """Disarm and reap the helper after fully clean finalization.

    Only captured C-backed primitives run here. Any failure is unsafe: a live
    helper or uncertain child status must not be carried into ordinary exit or
    in-place exec, so the already-captured hard exit is used.
    """
    try:
        if watchdog.write(watchdog.control_fd, b"D") != 1:
            watchdog.hard_exit(exit_code or 1)
        watchdog.close(watchdog.control_fd)
        waited, status = watchdog.waitpid(watchdog.pid, 0)
        if waited != watchdog.pid or status != 0:
            watchdog.hard_exit(exit_code or 1)
    except BaseException:  # noqa: BLE001 — clean completion is now unprovable
        watchdog.hard_exit(exit_code or 1)


@windows_variant("src.desktop.platform.windows_process:finalize_and_exit")
def _finalize_and_exit(
    loop, zombie_reaper: AdoptedZombieReaper, log, exit_code: int
) -> None:
    """Run the finalize barrier under a pre-armed hard deadline.

    A genuinely blocked default-executor worker is a NON-DAEMON thread:
    ordinary interpreter shutdown joins it forever. More generally, arbitrary
    finalizers may run while cancellation frames, completed task frames, or
    loop callback handles are released. Those callbacks can block before the
    cooperative barrier returns (round-23). The external watchdog is therefore
    armed *before* any finalize work and remains armed until the entire clean
    barrier has returned. It does not depend on event-loop progress.

    Returns normally only when the complete barrier finished cleanly; the
    caller then owns the ordinary restart/exit tail.
    """
    watchdog = _arm_finalize_watchdog(exit_code)
    try:
        failure = _finalize_loop(loop, zombie_reaper, log)
    except BaseException as exc:  # noqa: BLE001 — nothing may escape this path
        # Whatever leaked out of finalize, the process state is at best
        # unproven — resurfacing the exception would resurrect ordinary
        # interpreter shutdown and the round-17 hang with it. The repr
        # is guarded too: a broken __repr__ raising HERE would escape
        # this very handler (round-20 #2), and the exception is parked
        # so clearing this binding cannot run a __del__ (round-22).
        _PARKED_FOR_EXIT.append(exc)
        failure = "finalize crashed: " + _safe_repr(exc)
    if failure is None:
        _disarm_finalize_watchdog(watchdog, exit_code)
        return
    _emergency_exit(log, exit_code, failure, hard_exit=watchdog.hard_exit)
    # os._exit never returns in production. Test doubles do; disarm there so a
    # unit test cannot inherit a live watchdog that fires in a later test.
    _disarm_finalize_watchdog(watchdog, exit_code)


def _emergency_exit(
    log,
    exit_code: int,
    reason: str,
    *,
    hard_exit: Callable[[int], NoReturn] | None = None,
) -> None:
    """Leave NOW, depending on no ordinary I/O whatsoever (round-18/19).

    Behind an unproven barrier even the last words are best-effort: a
    logging HANDLER or stream flush can itself RAISE — or BLOCK forever
    on a wedged pipe — and either kept ``os._exit`` from ever running
    (round-18: a raising ``stdout.flush``; round-19: a blocking
    ``log.error`` before the verdict even returned). ALL remaining
    output — the veto record included, since ``restart.block_reexec``
    logs — therefore happens in a daemon thread with a bounded join:
    whatever it cannot say within the bound is abandoned with it at
    exit, and the exit itself depends on nothing.
    """
    import logging
    import threading

    # Direct unit callers use the current function so their test double still
    # works. _finalize_and_exit passes the pre-finalize captured C function,
    # which hostile teardown callbacks cannot replace.
    exit_now = hard_exit if hard_exit is not None else os._exit

    def _last_words() -> None:
        try:
            restart.block_reexec(
                "teardown could not prove a clean process state — "
                f"in-place re-exec unsafe ({reason})"
            )
        except Exception:
            pass
        try:
            log.error(
                "Teardown unproven (%s) — exiting without interpreter "
                "shutdown: state may include blocked non-daemon threads "
                "or unreaped children",
                reason,
            )
        except Exception:
            pass
        try:
            flushes = [h.flush for h in logging.getLogger().handlers]
            flushes += [sys.stdout.flush, sys.stderr.flush]
        except Exception:
            return
        for flush in flushes:
            try:
                flush()
            except Exception:
                pass

    try:
        scribe = threading.Thread(
            target=_last_words, name="emergency-exit-flush", daemon=True
        )
        scribe.start()
        scribe.join(timeout=1.0)
    except BaseException as exc:  # noqa: BLE001 — os._exit is unconditional
        _PARKED_FOR_EXIT.append(exc)
    exit_now(exit_code or 1)


def _startup_diagnostic(exc: BaseException, fallback_path: str, token_path: str) -> str:
    """Bounded, inert failure metadata, never exception repr/str or credentials.

    Only exact built-in exception types and fixed refusal reasons are emitted.
    The finalizer's existing stop log writes it with its watchdog already armed.
    """
    from src.desktop.commands import JournalStorageError

    kinds = (
        (PermissionError, "PermissionError"), (FileNotFoundError, "FileNotFoundError"),
        (FileExistsError, "FileExistsError"), (BlockingIOError, "BlockingIOError"),
        (OSError, "OSError"), (ValueError, "ValueError"), (RuntimeError, "RuntimeError"),
        (JournalStorageError, "JournalStorageError"),
    )
    # Identity comparisons avoid even a hostile subclass metaclass's __hash__.
    kind = next((name for cls, name in kinds if type(exc) is cls), "startup_failure")
    path = fallback_path
    reason = "core startup failed"
    if kind != "startup_failure":
        args = exc.args
        allowed = {
            "foreign profile ancestor", "profile ancestor writable by others",
            "profile directory must be owner-private (0700)",
            "foreign IPC ancestor", "IPC ancestor writable by others",
            "IPC parent must be owner-private (0700)", "unsafe IPC credential file",
            "invalid IPC credential", "unsafe profile identity record",
            "unsafe profile identity lock", "unsafe app bootstrap file",
            "existing state has no identity; explicit recovery required",
            "core parent link must be a supervised stdin pipe or stream socket",
            "core parent link must be a supervised stream",
        }
        message = args[1] if len(args) > 1 and type(args[0]) is int else args[0] if args else None
        if type(message) is str and message in allowed:
            reason = message
        if reason in {"unsafe IPC credential file", "invalid IPC credential"}:
            path = token_path
        if any(type(exc) is cls for cls in (PermissionError, FileNotFoundError, FileExistsError,
                                           BlockingIOError, OSError)) and type(exc.filename) is str:
            path = exc.filename
    # A pathname can carry control characters or be arbitrarily long. The line
    # is inert, bounded and log-injection-safe even for malformed local paths.
    path = "".join(c if c.isprintable() else "?" for c in path[:1024])
    return f"Odin stopped: {kind}: {reason}: {path}"


@windows_variant("src.desktop.platform.windows_process:core_main")
def main() -> None:
    """Run one profile core, then prove the retained finalization barrier."""
    if "--version" in sys.argv or "-V" in sys.argv:
        from src.version import get_version
        print(f"Odin Desktop {get_version()}")
        return
    import logging

    from src.cli import parse_core_args
    from src.desktop.core import CoreService
    from src.desktop.package_ownership import acquire_core_lease

    options = parse_core_args()
    # Independent kernel-held lease, not an inherited app process or env flag.
    # Retained through the complete finalization/containment barrier below.
    package_lease = acquire_core_lease(options.paths)
    if package_lease is not None:
        try:
            from src.desktop.package_state import inspect_profile
            from src.version import get_version

            inspect_profile(options.paths, package_version=get_version())
            package_lease.begin()
        except BaseException:
            # The provisional kernel lease acquired no writable profile or
            # execution resource. A compatible successor must remain possible.
            package_lease.close()
            raise
    # Select paths before service construction. Values are paths, not credentials.
    os.environ["ODIN_DESKTOP_PROFILE"] = options.paths.profile_id
    os.environ["ODIN_DESKTOP_TOKEN_FILE"] = str(options.token_file)
    os.environ["ODIN_DESKTOP_DATA_DIR"] = str(options.paths.data_dir)
    log = logging.getLogger("odin.desktop")
    # App captures stderr; no second file handler or live logging configuration.
    # One root handler gives every line local time, level and logger name (Python's
    # bare last-resort handler printed other loggers' warnings without either).
    # odin.desktop reports INFO; every other logger keeps the default WARNING floor.
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s",
                                           "%Y-%m-%d %H:%M:%S%z"))
    stop_diagnostic = None

    def final_stop_record(record) -> bool:
        if stop_diagnostic is not None and record.msg == "Odin stopped":
            record.msg = stop_diagnostic
            record.args = ()
        return True

    handler.addFilter(final_stop_record)
    logging.getLogger().addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        if not _enable_process_containment(log):
            raise SystemExit(1)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        reaper = AdoptedZombieReaper()
        exit_code = 0
        service = CoreService(
            options.paths, options.socket, options.token_file, release_runtime_on_close=False
        )
    except BaseException:
        # The run's own cleanup below never starts; don't leave the root handler.
        logging.getLogger().removeHandler(handler)
        handler.close()
        raise

    async def supervised() -> int:
        reaper.start()
        try:
            return await service.run()
        finally:
            await reaper.stop()

    try:
        exit_code = loop.run_until_complete(supervised())
    except KeyboardInterrupt:
        exit_code = 130
    except Exception as exc:
        # No synchronous I/O before the finalization watchdog is armed.
        # Even scrubbed logging can block on a supervisor's full stderr pipe.
        _PARKED_FOR_EXIT.append(exc)
        stop_diagnostic = _startup_diagnostic(
            exc, str(options.paths.data_dir), str(options.token_file),
        )
        exit_code = 1
    finally:
        _finalize_and_exit(loop, reaper, log, exit_code)
        if package_lease is not None:
            try:
                package_lease.finish()
            except Exception:
                # No clean attestation when authoritative release is missing.
                # Preserve dirty receipt but still finish profile teardown.
                exit_code = 1
            finally:
                package_lease.close()
        # A successor cannot acquire this profile while async finalizers or
        # contained descendants might still own it. Emergency exit releases
        # the kernel lock only by ending this incarnation, never early here.
        service.release_runtime()
        asyncio.set_event_loop(None)
        logging.getLogger().removeHandler(handler)
        handler.close()
    if exit_code:
        raise SystemExit(exit_code)


def _command_protected_roots(config) -> list[str]:
    from src.tools.workspace import command_protected_roots

    return command_protected_roots(runtime_install_root(), config)


def _provision_command_workspace(config, log):
    """Fail-closed workspace preflight for Phase 2 composition.

    The executor independently validates these roots on every use. Neither
    import nor the Phase 1 entry point provisions anything.
    """
    from src.tools.workspace import (
        WorkspaceError,
        provision_startup_workspace,
        provisioning_hint,
    )

    def _warn_fallback(path, configured, reason) -> None:
        log.warning(
            "Local command workspace fell back to %s — the configured "
            "default could not be provisioned (%s). Local commands work, "
            "but this indicates a packaging or permissions problem. %s",
            path,
            reason,
            provisioning_hint(configured),
        )

    try:
        workspace = provision_startup_workspace(
            config.tools,
            protected_roots=_command_protected_roots(config),
            on_fallback=_warn_fallback,
        )
        log.info("Local command workspace ready: %s", workspace)
        return workspace
    except WorkspaceError as exc:
        log.error(
            "Local command workspace unusable — local commands will refuse to run: %s. %s",
            exc,
            provisioning_hint(config.tools.local_working_dir),
        )
    except Exception as exc:
        log.error("Local command workspace provisioning failed unexpectedly: %s", exc)
    return None


if __name__ == "__main__":
    main()
