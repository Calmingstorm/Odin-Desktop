"""Profile memory/list management over the tool executor's actual stores."""
from __future__ import annotations

from ..async_utils import to_thread_settled
from ..json_store import StoreCorruptError
from ..storage_redaction import _deep_scrub_strings
from .management import MethodError

METHODS = frozenset({
    "memory.list", "memory.get", "memory.set", "memory.delete", "memory.bulk_delete",
    "lists.list", "lists.get", "lists.delete",
})
READ_METHODS = frozenset({"memory.list", "memory.get", "lists.list", "lists.get"})


def _string(params: dict, name: str) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value:
        raise MethodError("bad_request", f"{name} is required")
    return value


class StateService:
    METHODS = METHODS
    READ_METHODS = READ_METHODS

    def __init__(self, paths, owner_id, *, memory=None, lists=None):
        if not isinstance(owner_id, str) or not owner_id:
            raise ValueError("owner identity is required")
        self.paths = paths
        self.owner_id = owner_id
        self._memory = memory
        self._lists = lists

    @property
    def memory(self):
        if self._memory is None:
            from ..tools.executor import ToolExecutor

            self._memory = ToolExecutor(
                memory_path=str(self.paths.data_dir / "memory.json"),
                profile_paths=self.paths,
            )
        return self._memory

    @property
    def lists(self):
        if self._lists is None:
            self._lists = self.memory.state_tools
        return getattr(self._lists, "state_tools", self._lists)

    def _scope(self, params: dict) -> str:
        # Transport admits the single profile owner. Pinned Odin's admin
        # handlers permit every retained scope, including imported user scopes.
        return _string(params, "scope")

    async def handle(self, method: str, params: dict):
        if method not in METHODS:
            raise MethodError("method_not_found", "unknown state method")
        if not isinstance(params, dict):
            raise MethodError("bad_request", "params must be an object")
        try:
            result = (await self._handle_memory(method, params)
                      if method.startswith("memory.")
                      else await self._handle_lists(method, params))
            return _deep_scrub_strings(result)
        except MethodError:
            raise
        except StoreCorruptError:
            code = "unavailable" if method in READ_METHODS else "conflict"
            if method.startswith("memory."):
                message = ("memory store unavailable (corrupt)" if method in READ_METHODS
                           else "memory store is corrupt; refusing to modify "
                           "(a backup was preserved)")
                raise MethodError(code, message) from None
            raise MethodError(code, "state store is corrupt; refusing unsafe access") from None
        except Exception:
            raise MethodError("internal_error", "state operation failed",
                              disposition="rejected" if method in READ_METHODS
                              else "outcome_unknown") from None

    async def _handle_memory(self, method: str, params: dict):
        entries = None
        scope = key = None
        if method == "memory.bulk_delete":
            entries = params.get("entries")
            if not isinstance(entries, list) or not entries:
                raise MethodError("bad_request", "entries must be a non-empty list of {scope, key}")
            # Validate the whole batch before touching retained state.
            entries = [(entry["scope"], entry["key"])
                       if isinstance(entry, dict)
                       and isinstance(entry.get("scope"), str) and entry["scope"]
                       and isinstance(entry.get("key"), str) and entry["key"]
                       else self._invalid_entry()
                       for entry in entries]
        elif method != "memory.list":
            scope = self._scope(params)
            if method != "memory.get" or params.get("key") is not None:
                key = _string(params, "key")
            if method == "memory.set" and params.get("value") is None:
                raise MethodError("bad_request", "value is required")

        backend = self.memory
        async with backend._memory_lock:
            data = await to_thread_settled(backend._load_all_memory)
            if method == "memory.list":
                return {name: {"keys": list(entries), "count": len(entries)}
                        for name, entries in data.items()}
            if method == "memory.get":
                if key is None:
                    if scope not in data:
                        raise MethodError("not_found", "scope not found")
                    return {"scope": scope, "entries": data[scope]}
                if key not in data.get(scope, {}):
                    raise MethodError("not_found", "key not found")
                return {"scope": scope, "key": key, "value": data[scope][key]}
            if method == "memory.bulk_delete":
                assert entries is not None  # fully validated before acquiring the lock
                count = 0
                for section, name in entries:
                    if name in data.get(section, {}):
                        del data[section][name]
                        count += 1
                if count:
                    await to_thread_settled(backend._save_all_memory, data)
                return {"status": "deleted", "count": count}
            if method == "memory.set":
                # Odin's web route stringifies values without the tool-only cap.
                data.setdefault(scope, {})[key] = str(params["value"])
                status = "saved"
            else:
                if key not in data.get(scope, {}):
                    raise MethodError("not_found", "key not found")
                del data[scope][key]
                status = "deleted"
            await to_thread_settled(backend._save_all_memory, data)
            return {"status": status, "scope": scope, "key": key}

    @staticmethod
    def _invalid_entry():
        raise MethodError("bad_request", "each entry must contain a scope and key")

    async def _handle_lists(self, method: str, params: dict):
        # Normalize identically to manage_list, not the fixture's parallel map.
        name = None if method == "lists.list" else _string(params, "name").strip().lower()
        if name == "":
            raise MethodError("bad_request", "name is required")
        backend = self.lists
        async with backend._lists_lock:
            # A corrupt corpus must not masquerade as an empty list of names.
            data = await to_thread_settled(backend._load_lists_for_write)
            if method == "lists.list":
                return {"items": [{
                    "name": key, "count": len(value.get("items", [])),
                    "updated_at": value.get("updated_at") or max(
                        (item.get("added_at", "") for item in value.get("items", [])),
                        default=""),
                } for key, value in sorted(data.items())]}
            if name not in data:
                raise MethodError("not_found", "list not found")
            if method == "lists.get":
                return {"name": name, "items": data[name].get("items", [])}
            del data[name]
            await to_thread_settled(backend._save_lists, data)
            return {"status": "deleted", "name": name}
