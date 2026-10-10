"""Windows: Odin's ``resolve_workspace`` contract, without touching the pinned module.

The same guarantees as ``src/tools/workspace.py``: an absolute path, no link,
protected roots rejected before anything is created, the overlap check again on
the canonical path, the user's own folder, private to them (Linux: mode 0700)
and usable. The pinned module's pure path helpers are reused: Windows paths
compare case-insensitively, so their overlap checks hold for case aliases.
"""
from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from . import win32
from .windows_files import _create_directory, canonical, dacl_is_private, held, own_sids


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
    if require_owner and security.owner not in own_sids():
        raise WorkspaceError(f"local_working_dir must be owned by the current user: {workspace}")
    if not dacl_is_private(security):
        raise WorkspaceError(f"local_working_dir must be private to its owner: {workspace}")
    if not os.access(workspace, os.R_OK | os.W_OK | os.X_OK):
        raise WorkspaceError(f"local_working_dir is not fully usable: {workspace}")
    return workspace
