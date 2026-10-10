"""Windows: Odin's ``resolve_workspace`` contract, without touching the pinned module.

The same guarantees as ``src/tools/workspace.py``: an absolute path, no link,
protected roots rejected before anything is created, the overlap check again on
the canonical path, the user's own folder, private to them (Linux: mode 0700)
and usable. The pinned module's pure path helpers are reused: Windows paths
compare case-insensitively, so their overlap checks hold for case aliases.

A path that isn't on a local fixed drive is refused before anything resolves or
probes it. "Usable" is the DACL's answer: the folder must open with the rights to
list, traverse, and create and delete entries (Linux: ``os.access`` R, W and X;
Windows' ``os.access`` doesn't consult the DACL).
"""
from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from . import win32
from .windows_files import (
    _create_directory,
    canonical,
    dacl_is_private,
    held,
    own_sids,
    require_local,
)

# Linux's R, W and X on a folder: list, traverse, and add or remove entries.
_USABLE = (win32.FILE_LIST_DIRECTORY | win32.FILE_TRAVERSE | win32.FILE_ADD_FILE
           | win32.FILE_ADD_SUBDIRECTORY | win32.FILE_DELETE_CHILD | win32.SYNCHRONIZE)


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def resolve_workspace(
    configured: str,
    *,
    protected_roots: Sequence[str | os.PathLike[str]] | None = None,
    require_owner: bool = True,
    owner_uid: int | None = None,
    create_if_missing: bool = True,
) -> Path:
    from ...tools.workspace import WorkspaceError, _canonical, _reject_overlap

    if not configured or not str(configured).strip():
        raise WorkspaceError("tools.local_working_dir is empty")
    raw = Path(str(configured).strip()).expanduser()
    if not raw.is_absolute():
        raise WorkspaceError(f"local_working_dir must be absolute: {configured!r}")
    try:
        require_local(raw)
    except (OSError, ValueError):
        raise WorkspaceError(
            f"local_working_dir must be on a local fixed drive: {raw}") from None
    if _is_link(raw):
        raise WorkspaceError(f"local_working_dir must not be a symlink: {raw}")
    workspace = _canonical(raw)
    _reject_overlap(workspace, protected_roots)
    if create_if_missing and not workspace.exists():
        try:
            with held(canonical(workspace.parent)):
                _create_directory(workspace)
        except OSError:
            pass  # reported below, as the pinned resolver does
    if not workspace.exists():
        raise WorkspaceError(
            f"local_working_dir does not exist and could not be created: {workspace}")
    if not workspace.is_dir() or _is_link(workspace):
        raise WorkspaceError(f"local_working_dir is not a directory: {workspace}")
    _reject_overlap(workspace, protected_roots)
    with held(canonical(workspace)) as chain:
        security = win32.object_security(chain.handle)
        usable = _usable(chain.path)
    if require_owner and security.owner not in own_sids():
        raise WorkspaceError(f"local_working_dir must be owned by the current user: {workspace}")
    if not dacl_is_private(security):
        raise WorkspaceError(f"local_working_dir must be private to its owner: {workspace}")
    if not usable:
        raise WorkspaceError(f"local_working_dir is not fully usable: {workspace}")
    return workspace


def _usable(path: Path) -> bool:
    """Whether the folder opens with the rights a working folder needs (no side effects)."""
    try:
        handle = win32.create_file(
            path, _USABLE, win32.FILE_SHARE_READ | win32.FILE_SHARE_WRITE
            | win32.FILE_SHARE_DELETE, win32.OPEN_EXISTING,
            win32.FILE_FLAG_BACKUP_SEMANTICS | win32.FILE_FLAG_OPEN_REPARSE_POINT)
    except OSError:
        return False
    win32.close(handle)
    return True
