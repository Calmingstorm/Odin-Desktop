"""Parent-linked lifetime for a supervised core, without a blocking stdin worker."""
from __future__ import annotations

import asyncio
import os
import signal
import socket
import stat


class CoreLifetime:
    """One explicit shutdown edge, shared by parent loss and protocol shutdown."""

    def __init__(self) -> None:
        self.stopping = asyncio.Event()
        self.reason: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stdin_fd: int | None = None
        self._signals: list[signal.Signals] = []

    def watch_signals(self) -> None:
        loop = asyncio.get_running_loop()
        self._loop = loop
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.request_stop, sig.name.lower())
            self._signals.append(sig)

    @property
    def admitting(self) -> bool:
        return not self.stopping.is_set()

    def request_stop(self, reason: str) -> None:
        if not self.stopping.is_set():
            self.reason = reason
            self.stopping.set()

    def watch_parent(self, stdin_fd: int) -> None:
        """Watch a pipe or Node-style stream socket, never a blocking worker."""
        if self._stdin_fd is not None:
            raise RuntimeError("parent link is already watched")
        mode = os.fstat(stdin_fd).st_mode
        if stat.S_ISSOCK(mode):
            # Node's child_process.spawn(stdio=['pipe', ...]) uses socketpairs
            # on Linux. Inspect a duplicate without taking ownership of stdin.
            with socket.socket(fileno=os.dup(stdin_fd)) as parent:
                stream = parent.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) == socket.SOCK_STREAM
            if not stream:
                raise ValueError("core parent link must be a supervised stream")
        elif not stat.S_ISFIFO(mode):
            raise ValueError("core parent link must be a supervised stdin pipe or stream socket")
        loop = asyncio.get_running_loop()
        loop.add_reader(stdin_fd, self._parent_readable)
        self._loop = loop
        self._stdin_fd = stdin_fd

    def _parent_readable(self) -> None:
        try:
            data = os.read(self._stdin_fd, 4096)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            data = b""
        if not data:
            self.close()
            self.request_stop("parent_eof")

    async def wait(self) -> None:
        await self.stopping.wait()

    def close(self) -> None:
        if self._stdin_fd is not None:
            self._loop.remove_reader(self._stdin_fd)
            self._stdin_fd = None
        if self._loop is not None:
            for sig in self._signals:
                self._loop.remove_signal_handler(sig)
            self._signals.clear()
        self._loop = None
