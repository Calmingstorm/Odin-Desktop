"""macOS storage variants.

Linux opens SQLite through /proc/self/fd/<held directory>/<name>, so a swapped parent link cannot
redirect it. macOS has no procfs: the held directory's current path comes from fcntl(F_GETPATH), and
the file found there must be the one the held directory names. The directory is private (0700), so
only this user or root could swap it between that check and SQLite's open; that same-user limit is
the one the IPC socket states too. SQLite derives its -journal, -wal and -shm names from this path.
"""

from __future__ import annotations

import fcntl
import os
import sys

if sys.platform != "darwin":
    raise ImportError("macOS storage variants are macOS-only")

_MAXPATHLEN = 1024


def anchored_database_path(directory_fd: int, name: str) -> str:
    """commands._anchored_database_path on macOS."""
    raw = fcntl.fcntl(directory_fd, fcntl.F_GETPATH, bytes(_MAXPATHLEN))
    directory = os.fsdecode(raw.split(b"\0", 1)[0])
    if not os.path.isabs(directory):
        raise OSError("the journal folder has no absolute path")
    path = os.path.join(directory, name)
    held = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    named = os.stat(path, follow_symlinks=False)
    if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
        raise OSError("the journal file changed between the held folder and its path")
    return path
