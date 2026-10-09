"""Single-owner, read-only trajectory methods over the retained saver.

The saver owns bounded JSONL scanning and filtering before selection. This
boundary carries the pinned selected-file route guards, without a web server
or a writer constructor during a read.
"""
from __future__ import annotations

from pathlib import Path

from ..observability.diagnostics import scrub_diagnostic
from ..trajectories.saver import TrajectorySaver
from .management import MethodError

METHODS = frozenset({
    "trajectories.list", "trajectories.read", "trajectories.search",
    "trajectories.message",
})
READ_METHODS = METHODS


class _TrajectoryReader(TrajectorySaver):
    """Retained reader algorithms without mkdir or writer initialization."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self._count = 0


def _limit(params, default):
    try:
        return min(max(int(params.get("limit", default)), 1), 500)
    except (ValueError, TypeError, OverflowError):
        return default


def _text(params, name, default=None):
    value = params.get(name, default)
    if value is not None and not isinstance(value, str):
        raise MethodError("bad_request", f"{name} must be a string")
    return value


class TrajectoriesService:
    METHODS = METHODS
    READ_METHODS = READ_METHODS

    def __init__(self, paths=None, *, saver=None, get_directory=None, saver_getter=None):
        self.paths = paths
        self._saver = saver
        self._get_directory = get_directory
        self._saver_getter = saver_getter
        self._reader = None
        self._binding = None

    @property
    def saver(self):
        if self._saver is not None:
            return self._saver
        directory = (self._get_directory() if self._get_directory is not None else
                     self.paths.data_dir / "trajectories" if self.paths is not None else None)
        if directory is None:
            return None
        binding = Path(directory)
        runtime = self._saver_getter() if self._saver_getter is not None else None
        if runtime is not None and Path(runtime.directory) == binding:
            return runtime
        if binding != self._binding:
            self._reader = _TrajectoryReader(binding)
            self._binding = binding
        return self._reader

    async def handle(self, method, params):
        if method not in METHODS:
            raise MethodError("method_not_found", "Unknown trajectories method")
        if not isinstance(params, dict):
            raise MethodError("bad_request", "params must be an object")
        try:
            # Scrub full trace text, never truncate context or model wording.
            return scrub_diagnostic(await self._handle(method, params))
        except MethodError:
            raise
        except Exception:
            raise MethodError("unavailable", "Trajectory read is unavailable") from None

    async def _handle(self, method, params):
        saver = self.saver
        if saver is None:
            raise MethodError("capability_unavailable", "trajectory saving not available")
        if method == "trajectories.list":
            # The reader never writes, so the writer's counter would always say 0.
            files = await saver.list_files()
            return {"files": files, "count": len(files)}
        if method == "trajectories.message":
            message_id = _text(params, "message_id", "")
            entry = await saver.find_by_message_id(message_id)
            if entry is None:
                raise MethodError("not_found", "trajectory not found")
            return {"entry": entry}
        filters = {key: _text(params, key) for key in ("channel_id", "user_id", "tool_name")}
        errors = str(params.get("errors_only", "")).lower() in ("1", "true")
        if method == "trajectories.search":
            results = await saver.search(**filters, errors_only=errors, limit=_limit(params, 50))
            return {"results": results, "count": len(results)}
        filename = _text(params, "filename", "")
        if (not filename.endswith(".jsonl") or "/" in filename
                or "\\" in filename or ".." in filename):
            raise MethodError("bad_request", "invalid filename")
        safe_path = (saver.directory / filename).resolve()
        if not safe_path.is_relative_to(saver.directory.resolve()):
            raise MethodError("bad_request", "invalid filename")
        filters = {key: value for key, value in filters.items() if value}
        if errors:
            filters["errors_only"] = True
        entries = await saver.read_file(filename, limit=_limit(params, 100), **filters)
        return {"entries": entries, "count": len(entries)}
