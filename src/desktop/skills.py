"""Owner-managed retained skills, with no foreground/request delivery shim.

Startup imports trusted profile code as Odin does. Source, metadata and config
are never identity: the real permission context gates mutations and execution.
The retained manager is the catalog's schema owner and dispatch boundary.
"""
from __future__ import annotations

import asyncio
import hashlib
import json

from ..async_utils import to_thread_settled
from ..llm.secret_scrubber import scrub_output_secrets
from ..storage_redaction import _deep_scrub_strings
from ..tools.runtime_delivery import execution_delivery_scope
from ..tools.skill_manager import MAX_SKILL_OUTPUT_CHARS, SKILL_NAME_PATTERN, SkillManager
from .management import MethodError

METHODS = frozenset({
    "skills.list", "skills.get", "skills.save", "skills.validate", "skills.test",
    "skills.set_enabled", "skills.delete", "skills.config.get", "skills.config.set",
})
READ_METHODS = frozenset({"skills.list", "skills.get", "skills.config.get"})


class _ConfigStore:
    """One profile-keyring blob per skill, never plaintext credential fallback."""

    def __init__(self, secrets, directory):
        self.secrets = secrets
        self.directory = directory

    @staticmethod
    def key(name):
        return "skill_config_" + hashlib.sha256(name.encode()).hexdigest()

    def load(self, name):
        marker = self.directory / f"{name}.json"
        if not marker.exists():
            return {}
        if json.loads(marker.read_text()) != {"storage": "profile-keyring"}:
            # No silent adoption/migration of an imported plaintext config.
            raise ValueError("skill configuration requires keyring storage")
        value = self.secrets.get(self.key(name))
        if value is None:
            raise ValueError("skill configuration is unavailable")
        result = json.loads(value)
        if not isinstance(result, dict):
            raise ValueError("invalid skill configuration")
        return result

    def save(self, name, values):
        from ..permissions.persistence import write_private_atomic

        self.secrets.set(self.key(name), json.dumps(values, allow_nan=False))
        if not write_private_atomic(self.directory / f"{name}.json",
                                    json.dumps({"storage": "profile-keyring"})):
            raise OSError("skill config persistence failed")

    def delete(self, name):
        if (self.directory / f"{name}.json").exists():
            self.secrets.delete(self.key(name))


class SkillsService:
    METHODS = METHODS
    READ_METHODS = READ_METHODS

    def __init__(self, settings, *, executor, owner_id, permissions=None,
                 manager=None, invalidate=None):
        self.settings = settings
        self.paths = settings.paths
        self.executor = executor
        self.owner_id = owner_id
        self.permissions = (permissions if permissions is not None
                            else getattr(executor, "_permission_manager", None))
        self.skill_manager = manager
        self._invalidate = invalidate
        self._lock = asyncio.Lock()
        self._started = False
        self._closed = False

    def _changed(self):
        if self._invalidate is not None:
            self._invalidate()

    def set_on_catalog_changed(self, callback):
        self._invalidate = callback

    def update_runtime_config(self, tools):
        """Adopt only an effective ToolsConfig supplied by graph composition.

        Not a protocol method: saved restart-only values must not be passed as
        effective configuration. Existing invocations retain their own limits.
        """
        if self.skill_manager is not None:
            self.skill_manager._tool_timeouts = dict(tools.tool_timeouts)
            self.skill_manager._allowed_urls = tuple(
                url.rstrip("/") for url in tools.skill_allowed_urls
            )

    async def start(self):
        """Compose once off-loop; advertise no definitions before qualification."""
        async with self._lock:
            if self._closed:
                raise MethodError("unavailable", "skills service is closed")
            if self._started:
                return
            if self.skill_manager is None:
                def construct():
                    # Assign while settled worker owns the lock: cancellation
                    # must not orphan imported modules outside lifecycle cleanup.
                    self.skill_manager = SkillManager(
                        str(self.paths.data_dir / "skills"), self.executor,
                        memory_path=str(self.paths.data_dir / "memory.json"),
                        tool_timeouts=dict(self.executor.config.tool_timeouts),
                        allowed_urls=tuple(self.executor.config.skill_allowed_urls),
                        config_store=_ConfigStore(self.settings.secrets,
                                                 self.paths.data_dir / "skills" / "config"),
                    )
                await to_thread_settled(construct)
            self._started = True
            self._changed()

    def get_tool_definitions(self):
        if not self._started or self._closed or self.skill_manager is None:
            return []
        return self.skill_manager.get_tool_definitions()

    def list_skills(self):
        """Prompt/catalog read seam; not an execution or authority shortcut."""
        if not self._started or self._closed or self.skill_manager is None:
            return []
        return self.skill_manager.list_skills()

    async def reload(self):
        async with self._lock:
            self._ready()
            # Adopt effective executor config, not a saved pending-restart map.
            self.update_runtime_config(self.executor.config)
            try:
                await to_thread_settled(self.skill_manager.reload)
            finally:
                self._changed()

    async def close(self):
        async with self._lock:
            self._closed = True
            if self.skill_manager is not None:
                self.skill_manager.close()
            self._changed()

    def _ready(self):
        if not self._started or self._closed or self.skill_manager is None:
            raise MethodError("unavailable", "skills service is not started")

    def _owner(self):
        # An ID string, code declaration or saved credential cannot substitute
        # for the sealed transport context. No owner context is manufactured.
        if self.permissions is None or not self.permissions.is_owner(self.owner_id):
            raise MethodError("permission_denied", "authenticated owner context required")

    @staticmethod
    def _name(params):
        name = params.get("name")
        if not isinstance(name, str) or not SKILL_NAME_PATTERN.fullmatch(name):
            raise MethodError("bad_request", "valid skill name is required")
        return name

    @staticmethod
    def _code(params):
        code = params.get("code")
        if not isinstance(code, str) or not code.strip() or len(code) > 50_000:
            raise MethodError("bad_request", "code must be a nonempty bounded string")
        return code

    async def handle(self, method, params):
        if method not in METHODS:
            raise MethodError("not_found", "unknown skills method")
        if type(params) is not dict:
            raise MethodError("bad_request", "params must be an object")
        async with self._lock:
            self._ready()
            if method not in READ_METHODS:
                self._owner()
            try:
                return await self._handle(method, params)
            except MethodError:
                raise
            except Exception:
                raise MethodError("unavailable", "skill operation failed",
                                  "rejected" if method in READ_METHODS
                                  else "outcome_unknown") from None

    @staticmethod
    def _test_output(result):
        # Strip delivery subclasses: their scrubber bypass is only valid for
        # already-authorized retained envelopes, not arbitrary skill returns.
        text = scrub_output_secrets(str(result))
        if len(text) > MAX_SKILL_OUTPUT_CHARS:
            marker = f"\n... [truncated at {MAX_SKILL_OUTPUT_CHARS} chars]"
            text = text[:MAX_SKILL_OUTPUT_CHARS - len(marker)] + marker
        return text

    async def _test(self, manager, name):
        if not manager.has_skill(name):
            raise MethodError("not_found", "skill not found")
        try:
            # Authentication is inherited from transport, never reconstructed
            # from an ID or params. Like chat, capture task-local execution;
            # retain the caller's tool/live resolver constraints and the real
            # owner's live HostAccessManager. A management test has no chat
            # destination, so do not fabricate conversation delivery authority.
            with execution_delivery_scope(self.owner_id, ""):
                result = await manager.execute(name, {}, requester_id=self.owner_id)
            is_error = result.startswith("Skill error:") or result.startswith("Skill '")
            return {"result": self._test_output(result), "is_error": is_error}
        except Exception as error:
            return {"result": self._test_output(error), "is_error": True}

    async def _handle(self, method, params):
        manager = self.skill_manager
        if method == "skills.list":
            return _deep_scrub_strings(manager.list_skills())
        if method == "skills.validate":
            return _deep_scrub_strings(manager.validate_skill_code(self._code(params)))
        name = self._name(params)
        if method == "skills.test":
            return await self._test(manager, name)
        if method == "skills.save":
            code = self._code(params)
            existing = manager.has_skill(name)
            # create: true never replaces an existing skill (checked under the service lock).
            if params.get("create") is True and existing:
                raise MethodError("conflict", "a skill with this name already exists")
            operation = manager.edit_skill if existing else manager.create_skill
            try:
                result = await to_thread_settled(operation, name, code)
            finally:
                self._changed()
            if not manager.has_skill(name) or manager.get_skill_info(name)["code"] != code:
                raise MethodError(
                    "bad_request", "skill could not be loaded; previous version retained",
                )
            return {"result": _deep_scrub_strings(result)}
        if method == "skills.delete":
            if not manager.has_skill(name) and not any(
                row["name"] == name for row in manager.list_skills()
            ):
                raise MethodError("not_found", "skill not found")
            operation = (manager.delete_skill if manager.has_skill(name)
                         else manager.delete_failed_skill)
            try:
                result = await to_thread_settled(operation, name)
            finally:
                self._changed()
            return {"result": _deep_scrub_strings(result)}
        if not manager.has_skill(name):
            raise MethodError("not_found", "skill not found")
        if method == "skills.get":
            return _deep_scrub_strings(manager.get_skill_info(name))
        if method == "skills.set_enabled":
            enabled = params.get("enabled")
            if type(enabled) is not bool:
                raise MethodError("bad_request", "enabled must be a boolean")
            try:
                result = await to_thread_settled(
                    manager.enable_skill if enabled else manager.disable_skill, name,
                )
            finally:
                self._changed()
            return {"result": result}
        if method == "skills.config.get":
            info = manager.get_skill_info(name)
            return {"config": _deep_scrub_strings(manager.get_skill_config(name)),
                    "schema": _deep_scrub_strings(info["metadata"]["config_schema"])}
        values = params.get("config", {})
        if not isinstance(values, dict):
            raise MethodError("bad_request", "config must be an object")
        # Schema validation belongs to the retained manager. Exceptions and
        # value-bearing diagnostics are not reflected into durable receipts.
        errors = await to_thread_settled(manager.set_skill_config, name, values)
        if errors:
            raise MethodError("bad_request", "invalid skill configuration")
        return {"config": _deep_scrub_strings(manager.get_skill_config(name))}
