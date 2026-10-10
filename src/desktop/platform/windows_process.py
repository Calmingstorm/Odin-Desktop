"""Windows: the engine's process ownership and lifetime (phase 2 plan B3).

* **Containment.** The engine joins a kill-on-close Job Object as the first act of
  ``main``. Every child it starts is in the job, with no breakaway. When the
  engine's handle to the job closes (normal exit, crash or termination), Windows
  ends them all. The handle is never inheritable, so no child keeps the job alive.
* **Drain.** Windows has no zombies. The final drain is verified when, after a
  bounded wait, the job holds only the engine and its armed finalize watchdog.
  Anything else takes the emergency path. It ends survivors by handle and waits
  for them, reading the job's membership again after each pass, until only the
  engine is left or its bound runs out. Out of time, it says so on stderr and
  leaves the rest to kill-on-close as the engine exits: that ending is the
  kernel's and isn't verified before the profile lock is released.
* **Watchdog.** A helper process holds an inherited handle to this exact process
  (never a PID) and an event. Unless the event is set by the deadline, it calls
  ``TerminateProcess``. It holds no job handle.
* **Lifetime.** SIGINT and SIGBREAK reach the loop through ``signal.signal``. The
  parent link is the raw stdin pipe, polled by a native thread with
  ``PeekNamedPipe`` (never a waiting read, which would block every other call on
  that pipe). Only the thread's completion event proves it stopped.
"""
from __future__ import annotations

import asyncio
import ctypes
import importlib
import msvcrt
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import NoReturn

from . import win32

# The engine's only handle to its job, kept for the life of the process: closing
# it would end every child at once.
_JOB = None
_WATCHDOG_PID: int | None = None
# Parent-link readers still blocked after their stop bound: unproven owners.
_UNSETTLED_READERS: list[object] = []
_DRAIN_SECONDS = 2.0
_SURVIVOR_WAIT_SECONDS = 2.0
_PARENT_POLL_SECONDS = 0.1
_LIST_CAPACITY = 64
_ERROR_MORE_DATA = 234


def _entry_module():
    """The running ``src.__main__``: under ``python -m src`` it is ``__main__``."""
    running = sys.modules.get("__main__")
    spec = getattr(running, "__spec__", None)
    if spec is not None and spec.name == "src.__main__":
        return running
    return importlib.import_module("src.__main__")


def create_job():
    """A new kill-on-close job; its handle is not inheritable."""
    job = win32.CreateJobObjectW(None, None)
    if not job:
        raise win32.error()
    limits = win32.JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    limits.BasicLimitInformation.LimitFlags = win32.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not win32.SetInformationJobObject(job, win32.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                                         ctypes.byref(limits), ctypes.sizeof(limits)):
        code = ctypes.get_last_error()
        win32.close(job)
        raise win32.error(code)
    return job


def join_job() -> None:
    """Put this process in a new kill-on-close job, once."""
    global _JOB
    if _JOB is not None:
        return
    job = create_job()
    if not win32.AssignProcessToJobObject(job, win32.GetCurrentProcess()):
        code = ctypes.get_last_error()
        win32.close(job)
        raise win32.error(code)
    _JOB = job


def job_process_ids(job=None) -> list[int]:
    """Every process now in the job (the engine included)."""
    job = _JOB if job is None else job
    pointer = ctypes.sizeof(ctypes.c_size_t)
    capacity = _LIST_CAPACITY
    while True:
        buffer = ctypes.create_string_buffer(8 + pointer * capacity)
        if win32.QueryInformationJobObject(job, win32.JOB_OBJECT_BASIC_PROCESS_ID_LIST_CLASS,
                                           buffer, ctypes.sizeof(buffer), None):
            assigned = int.from_bytes(buffer.raw[0:4], "little")
            listed = int.from_bytes(buffer.raw[4:8], "little")
            if listed >= assigned:
                ids = (ctypes.c_size_t * listed).from_buffer_copy(buffer.raw, 8)
                return [int(pid) for pid in ids]
        elif ctypes.get_last_error() != _ERROR_MORE_DATA:
            raise win32.error()
        if capacity >= 1 << 16:
            raise OSError("the job's process list does not fit")
        capacity *= 4


# --- Routed variants of src/__main__.py ------------------------------------------------------


def core_main() -> None:
    """``main`` on Windows: join the job first, before any child or worker can start."""
    try:
        join_job()
    except OSError as exc:
        sys.stderr.write("Odin Desktop: could not join the engine's kill-on-close job "
                         f"(WinError {exc.winerror}); refusing to start\n")
        raise SystemExit(1) from None
    _entry_module().main.linux_original()


def enable_process_containment(log) -> bool:
    """``_enable_process_containment`` on Windows: provenance, and the job joined by ``main``."""
    import secrets

    from ...tools.process_manager import DEFAULT_JOB_TOKEN, JOB_TOKEN_ENV, PROC_TOKEN_ENV

    os.environ.setdefault(PROC_TOKEN_ENV, secrets.token_hex(8))
    os.environ.setdefault(JOB_TOKEN_ENV, DEFAULT_JOB_TOKEN)
    if _JOB is None:
        log.error("The engine is not in its kill-on-close job; descendants would be "
                  "unattributable, so it refuses to start")
        return False
    log.debug("Job Object containment active")
    return True


class JobDrain:
    """The final drain on Windows, in the reaper's place (``process_manager`` is pinned)."""

    def drain_at_teardown(self) -> tuple[int, bool]:
        return drain_at_teardown(self)


def finalize_and_exit(loop, zombie_reaper, log, exit_code: int) -> None:
    """``_finalize_and_exit`` on Windows: Linux's barrier, with the job as the process table.

    Windows leaves no zombies, so the reaper's sweep never starts here; its final
    drain becomes the job's survivor check.
    """
    _entry_module()._finalize_and_exit.linux_original(loop, JobDrain(), log, exit_code)


def drain_at_teardown(self) -> tuple[int, bool]:
    """The job's final drain: nothing to reap, survivors counted.

    Verified only when, within the bound, the job holds just the engine and its
    armed watchdog, and no parent-link reader is still blocked.
    """
    if _JOB is None or _UNSETTLED_READERS:
        return 0, False
    allowed = {os.getpid()} | ({_WATCHDOG_PID} if _WATCHDOG_PID else set())
    deadline = time.monotonic() + _DRAIN_SECONDS
    while set(job_process_ids()) - allowed:
        if time.monotonic() >= deadline:
            return 0, False
        time.sleep(0.05)
    return 0, True


def terminate_survivors(timeout: float = _SURVIVOR_WAIT_SECONDS) -> bool:
    """End every other process in the job by its handle and wait for it, within one bound.

    Membership is read again after every pass, so a process started while others
    were ending is found too. True: the job held only the engine within the bound.
    False: what's left ends by kill-on-close when the engine exits, unverified.
    """
    if _JOB is None:
        return True
    own = os.getpid()
    deadline = time.monotonic() + timeout
    handles: dict[int, int] = {}  # held to the end, so no PID is reused meanwhile
    try:
        while True:
            others = [pid for pid in job_process_ids() if pid != own]
            if not others:
                return True
            if time.monotonic() >= deadline:
                return False
            for pid in others:
                if pid not in handles:
                    handle = _open_member(pid)
                    if handle:
                        win32.TerminateProcess(handle, 1)
                        handles[pid] = handle
            for pid in others:
                if pid in handles:
                    remaining = max(0, int((deadline - time.monotonic()) * 1000))
                    win32.WaitForSingleObject(handles[pid], remaining)
            time.sleep(0.01)  # an ended process can stay listed for a moment
    except OSError:
        return False
    finally:
        for handle in handles.values():
            win32.close(handle)


def _open_member(pid: int) -> int:
    """A handle that can end ``pid``, or 0 when it's gone or no longer in our job."""
    handle = win32.OpenProcess(win32.PROCESS_TERMINATE | win32.SYNCHRONIZE
                               | win32.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return 0
    member = win32.BOOL()
    # The PID was read before the open: act only if this process is still in our job.
    if win32.IsProcessInJob(handle, _JOB, ctypes.byref(member)) and member.value:
        return handle
    win32.close(handle)
    return 0


_UNVERIFIED_CLEANUP = (b"odin-desktop: processes remained in the engine's job at exit; "
                       b"kill-on-close ends them, unverified\n")


def _captured_hard_exit() -> Callable[[int], NoReturn]:
    """The emergency exit, its primitives captured before teardown can replace them."""
    terminate = terminate_survivors
    write = os.write
    exit_now = os._exit

    def hard_exit(code: int) -> NoReturn:
        try:
            if not terminate():
                write(2, _UNVERIFIED_CLEANUP)
        finally:
            exit_now(code)

    return hard_exit


_WATCHDOG_PROGRAM = r"""
import ctypes, os, sys
kernel32 = ctypes.WinDLL("kernel32")
kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
kernel32.WaitForSingleObject.restype = ctypes.c_uint32
kernel32.SetEvent.argtypes = [ctypes.c_void_p]
kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
disarm, engine, ready = (int(value) for value in sys.argv[1:4])
deadline_ms, code = int(float(sys.argv[4]) * 1000), int(sys.argv[5])
try:
    kernel32.SetEvent(ready)
    if kernel32.WaitForSingleObject(disarm, deadline_ms) != 0:
        kernel32.TerminateProcess(engine, code)
finally:
    os._exit(0)
"""


@dataclass(frozen=True, slots=True)
class WindowsWatchdog:
    """The armed helper and the primitives captured to disarm it.

    ``process`` is only held, never called: teardown uses the captured primitives.
    """

    process: subprocess.Popen
    helper: int
    pid: int
    disarm: int
    handles: tuple[int, ...]
    hard_exit: Callable[[int], NoReturn]
    set_event: Callable[[int], int]
    wait: Callable[[int, int], int]
    exit_code_of: Callable[[int, object], int]
    close: Callable[[int], None]


def _inheritable_event() -> int:
    attributes = win32.SECURITY_ATTRIBUTES(ctypes.sizeof(win32.SECURITY_ATTRIBUTES), None, True)
    event = win32.CreateEventW(ctypes.byref(attributes), True, False, None)
    if not event:
        raise win32.error()
    return event


def arm_finalize_watchdog(exit_code: int) -> WindowsWatchdog:
    """``_arm_finalize_watchdog`` on Windows. Failing to arm exits at once, as on Linux."""
    global _WATCHDOG_PID
    code = exit_code or 1
    hard_exit = _captured_hard_exit()
    handles: list[int] = []
    try:
        timeout = _entry_module()._FINALIZE_WATCHDOG_TIMEOUT
        disarm = _inheritable_event()
        handles.append(disarm)
        ready = _inheritable_event()
        handles.append(ready)
        engine = win32.OpenProcess(win32.PROCESS_TERMINATE | win32.SYNCHRONIZE, True,
                                   win32.GetCurrentProcessId())
        if not engine:
            raise win32.error()
        handles.append(engine)
        info = subprocess.STARTUPINFO()
        info.lpAttributeList = {"handle_list": [disarm, engine, ready]}
        # The base interpreter, never a virtual environment's launcher: a launcher adds
        # a second process to the job, which the drain would count as a survivor.
        python = getattr(sys, "_base_executable", "") or sys.executable
        process = subprocess.Popen(
            [python, "-I", "-S", "-c", _WATCHDOG_PROGRAM, str(disarm), str(engine),
             str(ready), str(timeout), str(code)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            # No console at all: a hidden one (CREATE_NO_WINDOW) still starts a console
            # host process in the job, which the drain would count as a survivor.
            close_fds=True, startupinfo=info, creationflags=subprocess.DETACHED_PROCESS)
        # Popen's own handle keeps this PID from being reused while we open ours.
        helper = win32.OpenProcess(win32.SYNCHRONIZE | win32.PROCESS_QUERY_LIMITED_INFORMATION,
                                   False, process.pid)
        if not helper:
            raise win32.error()
        handles.append(helper)
        for handle in (disarm, engine, ready):
            os.set_handle_inheritable(handle, False)  # later children inherit none of them
        if win32.WaitForSingleObject(ready, 2000) != win32.WAIT_OBJECT_0:
            hard_exit(code)
            raise AssertionError("os._exit returned")  # test doubles only
        _WATCHDOG_PID = process.pid
        return WindowsWatchdog(
            process=process, helper=helper, pid=process.pid, disarm=disarm, handles=tuple(handles),
            hard_exit=hard_exit, set_event=win32.SetEvent, wait=win32.WaitForSingleObject,
            exit_code_of=win32.GetExitCodeProcess, close=win32.close)
    except BaseException:  # noqa: BLE001 - no unguarded finalize is allowed
        for handle in handles:
            try:
                win32.close(handle)
            except BaseException:  # noqa: BLE001
                pass
        hard_exit(code)
        raise AssertionError("os._exit returned")  # test doubles only


def disarm_finalize_watchdog(watchdog: WindowsWatchdog, exit_code: int) -> None:
    """``_disarm_finalize_watchdog`` on Windows: set the event, then see the helper exit 0."""
    global _WATCHDOG_PID
    try:
        if not watchdog.set_event(watchdog.disarm):
            watchdog.hard_exit(exit_code or 1)
        if watchdog.wait(watchdog.helper, 5000) != win32.WAIT_OBJECT_0:
            watchdog.hard_exit(exit_code or 1)
        status = win32.DWORD()
        if not watchdog.exit_code_of(watchdog.helper, ctypes.byref(status)) or status.value != 0:
            watchdog.hard_exit(exit_code or 1)
        _WATCHDOG_PID = None
        for handle in watchdog.handles:
            watchdog.close(handle)
    except BaseException:  # noqa: BLE001 - clean completion is now unprovable
        watchdog.hard_exit(exit_code or 1)


# --- Lifetime ----------------------------------------------------------------------------------


class _StdinReader(threading.Thread):
    """Watches the parent's stdin pipe by polling it, never with a read left waiting.

    A synchronous ``ReadFile`` waiting on a pipe holds its file object's lock, and
    every other synchronous call on that object queues behind it. That includes the
    C runtime start-up of any DLL loaded meanwhile, which asks ``GetFileType`` about
    the standard handles: the engine hung importing numpy. ``PeekNamedPipe`` returns
    at once. Data is read (it is there, so the read can't wait) and discarded, as on
    Linux; a closed write end (``ERROR_BROKEN_PIPE``) is the parent's EOF.
    """

    def __init__(self, handle: int, on_end: Callable[[], None]):
        super().__init__(name="core-parent-link", daemon=True)
        self._handle = handle
        self._on_end = on_end
        self._stopping = threading.Event()
        self.done = threading.Event()

    def run(self) -> None:
        try:
            buffer = ctypes.create_string_buffer(4096)
            while not self._stopping.is_set():
                available = win32.DWORD()
                if not win32.PeekNamedPipe(self._handle, None, 0, None,
                                           ctypes.byref(available), None):
                    break  # the write end closed (or the link failed): the parent is gone
                if available.value:
                    count = win32.DWORD()
                    if not win32.ReadFile(self._handle, buffer, min(available.value, 4096),
                                          ctypes.byref(count), None) or not count.value:
                        break
                    continue
                self._stopping.wait(_PARENT_POLL_SECONDS)
            else:
                return  # stopped: not a parent EOF
            self._on_end()
        finally:
            self.done.set()

    def stop(self, timeout: float = 1.0) -> bool:
        """Ask the poll to end; True once it has (within one poll interval)."""
        self._stopping.set()
        return self.done.wait(timeout)


class WindowsCoreLifetime:
    """``CoreLifetime`` on Windows: the same stop edges, grace and admission rule."""

    def __init__(self) -> None:
        self.stopping = asyncio.Event()
        self.reason: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._reader: _StdinReader | None = None
        self._previous: dict[signal.Signals, object] = {}

    def watch_signals(self) -> None:
        loop = asyncio.get_running_loop()
        self._loop = loop

        def handler(signum, frame) -> None:
            try:
                loop.call_soon_threadsafe(self._signalled, signal.Signals(signum).name.lower())
            except RuntimeError:
                pass  # the loop already closed

        for sig in (signal.SIGINT, signal.SIGBREAK):
            self._previous[sig] = signal.signal(sig, handler)

    @property
    def admitting(self) -> bool:
        return not self.stopping.is_set()

    def _signalled(self, reason: str) -> None:
        from ..lifecycle import PARENT_EXIT_GRACE_SECONDS

        # As on Linux: with a live parent link, its shutdown request or EOF comes first.
        if self._reader is None:
            self.request_stop(reason)
        else:
            self._loop.call_later(PARENT_EXIT_GRACE_SECONDS, self.request_stop, reason)

    def request_stop(self, reason: str) -> None:
        if not self.stopping.is_set():
            self.reason = reason
            self.stopping.set()

    def watch_parent(self, stdin_fd: int) -> None:
        """Watch the parent's stdin pipe from a native reader thread."""
        if self._reader is not None:
            raise RuntimeError("parent link is already watched")
        handle = msvcrt.get_osfhandle(stdin_fd)
        if win32.GetFileType(handle) != win32.FILE_TYPE_PIPE:
            raise ValueError("core parent link must be a supervised stdin pipe or stream socket")
        loop = asyncio.get_running_loop()

        def ended() -> None:
            try:
                loop.call_soon_threadsafe(self._parent_eof)
            except RuntimeError:
                pass

        reader = _StdinReader(handle, ended)
        reader.start()
        self._loop = loop
        self._reader = reader

    def _parent_eof(self) -> None:
        self.close()
        self.request_stop("parent_eof")

    async def wait(self) -> None:
        await self.stopping.wait()

    def close(self) -> None:
        reader, self._reader = self._reader, None
        if reader is not None and not reader.stop():
            # Still blocked after the bound: finalization can't call this clean.
            _UNSETTLED_READERS.append(reader)
        for sig, previous in self._previous.items():
            signal.signal(sig, previous)
        self._previous.clear()
        self._loop = None
