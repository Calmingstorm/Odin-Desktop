"""Bounded, read-only observations of the executor's actual local workspace.

The composition owner supplies an executor provider, never a request path or
command. ``await snapshot()`` is the health/status seam; this is not a protocol
service or an execution route. Git observations use local refs only, so they
cannot establish remote freshness. No fetching, pruning or governor changes.
"""
from __future__ import annotations

import asyncio
import os
import selectors
import shutil
import stat
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from .platform.variants import windows_variant

COLLECTION_SECONDS = 3.0
SNAPSHOT_SECONDS = 3.5
WALK_SECONDS = 0.3
MAX_ENTRIES = 4096
MAX_DEPTH = 32
GIT_OUTPUT_BYTES = 4096
GIT_SECONDS = 0.7

# Neither refs nor branch names are ever interpolated into commands.
_GIT_OPERATIONS = {
    "repository": ("rev-parse", "--is-inside-work-tree"),
    "head": ("rev-parse", "--verify", "HEAD"),
    "branch": ("symbolic-ref", "--quiet", "--short", "HEAD"),
    "upstream": ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"),
    "counts": ("rev-list", "--left-right", "--count", "HEAD...@{upstream}", "--"),
}


class WorkspaceDiagnostics:
    """Single-flight asynchronous collector with no caller-selectable inputs.

    A slow filesystem syscall cannot be interrupted by Python. The async wait
    is bounded, and a timed-out worker remains the *only* worker until it exits.
    Walk deadlines are cooperative between syscalls, not OS filesystem fences.
    Provider/validation failures are scrubbed, never exposed as exception text.
    """

    def __init__(self, executor_provider: Callable[[], object]) -> None:
        self._executor_provider = executor_provider
        self._pending: asyncio.Task | None = None

    async def snapshot(self) -> dict:
        if self._pending is None or self._pending.done():
            self._pending = asyncio.create_task(asyncio.to_thread(self._collect))
        try:
            return await asyncio.wait_for(asyncio.shield(self._pending), SNAPSHOT_SECONDS)
        except TimeoutError:
            return {"status": "timeout", "reason": "collection_pending",
                    "local_only": True}

    @windows_variant("src.desktop.platform.windows_desktop:workspace_collect")
    def _collect(self) -> dict:
        started = time.monotonic()
        deadline = started + COLLECTION_SECONDS
        try:
            # The executor already derives profile-protected roots and validates
            # on every call. Do not reimplement that contract or create a path.
            executor = self._executor_provider()
            root = Path(executor._ensure_local_workspace())
        except Exception:
            return {"status": "unavailable", "reason": "workspace_unusable",
                    "local_only": True}
        try:
            usage = _usage(root, min(deadline, time.monotonic() + WALK_SECONDS))
            disk = {}
            if time.monotonic() < deadline:
                try:
                    disk["free_bytes"] = shutil.disk_usage(root).free
                    disk["free_inodes"] = os.statvfs(root).f_favail
                except OSError:
                    pass
            git = _git_snapshot(root, deadline)
            return {"status": "ok" if usage["complete"] else "partial",
                    "local_only": True, "usage": usage, "disk": disk, "git": git,
                    "duration_ms": round((time.monotonic() - started) * 1000, 1)}
        except Exception:
            return {"status": "unavailable", "reason": "collection_failed",
                    "local_only": True}


@windows_variant("src.desktop.platform.windows_desktop:workspace_usage")
def _usage(root: Path, deadline: float) -> dict:
    result = {"bytes": 0, "files": 0, "entries": 0, "symlinks_skipped": 0,
              "complete": True, "reason": None}
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK

    def incomplete(reason):
        result["complete"] = False
        result["reason"] = result["reason"] or reason

    def walk(fd, depth, device):
        with os.scandir(fd) as entries:
            for entry in entries:
                if result["entries"] >= MAX_ENTRIES or time.monotonic() >= deadline:
                    incomplete("walk_limit")
                    return
                result["entries"] += 1
                try:
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        result["symlinks_skipped"] += 1
                    elif stat.S_ISREG(info.st_mode):
                        result["bytes"] += info.st_size
                        result["files"] += 1
                    elif stat.S_ISDIR(info.st_mode):
                        if depth >= MAX_DEPTH or info.st_dev != device:
                            incomplete("walk_boundary")
                            continue
                        child = os.open(entry.name, flags, dir_fd=fd)
                        try:
                            opened = os.fstat(child)
                            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                                incomplete("directory_changed")
                            else:
                                walk(child, depth + 1, device)
                        finally:
                            os.close(child)
                    else:
                        incomplete("special_file_skipped")
                except OSError:
                    incomplete("entry_unavailable")
                if result["reason"] == "walk_limit":
                    return

    fd = os.open(root, flags)
    try:
        walk(fd, 0, os.fstat(fd).st_dev)
    finally:
        os.close(fd)
    return result


def _git(root: Path, operation: str, deadline: float) -> tuple[str, str]:
    """Private literal-operation reader; output and wall time are bounded."""
    remaining = min(GIT_SECONDS, deadline - time.monotonic())
    if remaining <= 0:
        return "timeout", ""
    argv = ("/usr/bin/git", "--no-pager", "--no-optional-locks",
            "-c", "protocol.allow=never", "-c", "core.fsmonitor=false",
            "-c", "core.hooksPath=/dev/null", *_GIT_OPERATIONS[operation])
    env = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_SYSTEM": os.devnull, "GIT_TERMINAL_PROMPT": "0",
           # Unlike protocol.allow's fallback, this also overrides repository
           # protocol-specific allow settings. Empty means no allowed transports.
           "GIT_ALLOW_PROTOCOL": "", "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1",
           "GIT_NO_REPLACE_OBJECTS": "1", "GIT_CEILING_DIRECTORIES": str(root.parent)}
    try:
        process = subprocess.Popen(argv, cwd=root, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return "unavailable", ""
    output = bytearray()
    end = time.monotonic() + remaining
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                wait = end - time.monotonic()
                if wait <= 0:
                    return "timeout", ""
                if not selector.select(wait):
                    return "timeout", ""
                chunk = os.read(process.stdout.fileno(),
                                min(1024, GIT_OUTPUT_BYTES + 1 - len(output)))
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > GIT_OUTPUT_BYTES:
                    return "output_limit", ""
        try:
            code = process.wait(timeout=max(0.001, end - time.monotonic()))
        except subprocess.TimeoutExpired:
            return "timeout", ""
        return ("ok" if code == 0 else "failed", output.decode("utf-8", errors="replace").strip())
    finally:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            pass
        process.stdout.close()


def _git_snapshot(root: Path, deadline: float) -> dict:
    base = {"remote_freshness": "not_checked", "network_used": False}
    try:
        metadata = (root / ".git").lstat()
    except FileNotFoundError:
        return {**base, "status": "not_repository"}
    except OSError:
        return {**base, "status": "unavailable"}
    # Do not discover a parent repository or follow worktree metadata elsewhere.
    if not stat.S_ISDIR(metadata.st_mode):
        return {**base, "status": "external_metadata_unsupported"}
    state, inside = _git(root, "repository", deadline)
    if state != "ok" or inside != "true":
        return {**base, "status": "unavailable", "reason": state}
    state, _ = _git(root, "head", deadline)
    if state != "ok":
        return {**base, "status": "unavailable", "reason": "head_" + state}
    state, branch = _git(root, "branch", deadline)
    if state == "failed":
        return {**base, "status": "detached_head"}
    if state != "ok":
        return {**base, "status": "unavailable", "reason": state}
    # Names are display-only, bounded, and never reused as arguments.
    branch = "".join(c for c in branch if c.isprintable())[:256]
    state, upstream = _git(root, "upstream", deadline)
    if state == "failed":
        return {**base, "status": "no_upstream", "branch": branch}
    if state != "ok":
        return {**base, "status": "unavailable", "reason": state}
    state, counts = _git(root, "counts", deadline)
    parts = counts.split()
    if (state != "ok" or len(parts) != 2
            or not all(p.isascii() and p.isdigit() and len(p) <= 12 for p in parts)):
        return {**base, "status": "unavailable",
                "reason": state if state != "ok" else "invalid_counts"}
    return {**base, "status": "local_tracking", "branch": branch,
            "upstream": "".join(c for c in upstream if c.isprintable())[:256],
            "ahead": int(parts[0]), "behind": int(parts[1])}
