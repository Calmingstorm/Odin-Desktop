"""Profile settings transactions with real, injectable runtime owners."""

from __future__ import annotations

import asyncio
import copy
import inspect
import threading

from pydantic import ValidationError

from ..config.apply_registry import (
    REDACTED,
    build_meta_payload,
    config_revision,
    flatten,
    is_secret,
    schema_facts,
    spec_for,
)
from ..config.image_defaults import (
    IMAGE_MODEL_DEFAULTS,
    IMAGE_MODEL_PREFIX,
    read_image_model_metadata,
)
from ..config.persistence import (
    DELETE_CONFIG_PATH,
    _config_file_lock,
    _dump_atomic,
    _load_document,
    _patch_config_paths,
)
from ..config.schema import Config
from .management import MethodError
from .provisioning import fresh_config
from .secrets import SecretStoreError

_MISSING = object()
_PROVIDERS = frozenset(
    {
        "providers.codex.set",
        "providers.auxiliary.set",
        "providers.ollama.set",
        "providers.compat.set",
    }
)
METHODS = (
    frozenset(
        {"settings.schema", "settings.set", "secrets.set", "secrets.clear", "models.image.intent"}
    )
    | _PROVIDERS
)
READ_METHODS = frozenset({"settings.schema"})


def _get(node, path, default=_MISSING):
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def _put(node, path, value):
    for key in path[:-1]:
        if not isinstance(node.get(key), dict):
            node[key] = {}
        node = node[key]
    if value is DELETE_CONFIG_PATH:
        node.pop(path[-1], None)
    else:
        node[path[-1]] = copy.deepcopy(value)


def _handler(path):
    if path.startswith("openai_codex.auxiliary.") or path == "openai_codex.auxiliary":
        return "providers.auxiliary.set"
    for prefix, method in (
        ("openai_codex.", "providers.codex.set"),
        ("ollama.", "providers.ollama.set"),
        ("openai_compatible.", "providers.compat.set"),
        ("llm_provider.", "models.main.set"),
    ):
        if path.startswith(prefix):
            return method
    if path in {
        "agents.model",
        "agents.auto_model_allowlist",
        "agents.thinking_mode",
        "agents.model_selection_hints",
    }:
        return "models.agents.set"
    if path == "tools.disabled_tools":
        return "tools.set_enabled"
    if path in {"tools.command_timeout_seconds", "tools.tool_timeouts"} or path.startswith(
        "tools.tool_timeouts."
    ):
        return "tools.timeouts.set"
    if path in {"tools.default_host", "tools.allow_host_tofu", "tools.hosts"} or path.startswith(
        "tools.hosts."
    ):
        return "hosts.settings"
    if path == "computer.enabled":
        return "computer.activation.set"
    if path.startswith("mcp."):
        if path in {"mcp.max_published_tools_per_server", "mcp.max_published_tools_global"}:
            return "mcp.set_limits"
        return "mcp.set_global_enabled" if path == "mcp.enabled" else "mcp.save"
    if path.startswith("outbound_webhooks."):
        return "webhooks.outbound.save"
    return "settings.set"


def _error(message, code="bad_request", disposition="rejected"):
    return MethodError(code, message, disposition=disposition)


class SettingsService:
    METHODS = METHODS
    READ_METHODS = READ_METHODS

    def __init__(self, paths, secrets, *, config=None, owners=None):
        self.paths, self.secrets = paths, secrets
        self.owners = dict(owners or {})
        self._lock = threading.RLock()
        self._async_lock = asyncio.Lock()
        if config is None:
            document, _ = _load_document(paths.config_file)
            values = fresh_config(paths).model_dump(mode="json")
            self._merge(values, dict(document))
            config = Config.model_validate(values, context={"startup": True})
        self.config = config if isinstance(config, Config) else Config.model_validate(config)
        self._boot = self.config.model_dump(mode="json")
        self._applied = {}
        self._generation = 0
        self._keyring_checked = False
        self._keyring_error = None
        self._transaction_active = False

    @staticmethod
    def _merge(base, updates):
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                SettingsService._merge(base[key], value)
            else:
                base[key] = value

    def hydrate_secrets(self):
        with self._lock:
            values = self.config.model_dump(mode="json")
            try:
                for path, value in flatten(values):
                    if is_secret(path) and isinstance(value, str):
                        stored = self.secrets.get(path)
                        if stored is not None:
                            _put(values, tuple(path.split(".")), stored)
            except SecretStoreError:
                self._keyring_error = "Profile keyring is unavailable or locked"
                self._keyring_checked = True
                return False
            self.config = Config.model_validate(values, context={"startup": True})
            self._keyring_checked, self._keyring_error = True, None
            return True

    def _image_metadata(self):
        return read_image_model_metadata(self.paths.config_file, self.config)

    @property
    def revision(self):
        document, _ = _load_document(self.paths.config_file)
        return config_revision(
            {
                "config": self.config.model_dump(mode="json"),
                "saved": document,
                "image_models": self._image_metadata(),
                "generation": self._generation,
            }
        )

    def _image_revision(self, metadata=None):
        return config_revision(metadata if metadata is not None else self._image_metadata())

    def schema(self):
        with self._lock:
            if not self._keyring_checked:
                self.hydrate_secrets()
            metadata = self._image_metadata()
            payload = build_meta_payload(
                self.config.model_dump(mode="json"),
                boot_dump=self._boot,
                image_model_defaults=metadata,
            )
            payload["revision"] = self.revision
            payload["status"]["desired_revision"] = payload["revision"]
            counts = dict.fromkeys(payload["status"]["counts"], 0)
            for field in payload["fields"]:
                field["apply_handler"] = _handler(field["path"])
                if field["apply_mode"] == "live_apply":
                    field["save_effect"] = (
                        "Saving updates the profile through its runtime owner's transaction."
                    )
                    field["runtime_effect"] = (
                        f"Applied through {field['apply_handler']} when its owner succeeds."
                    )
                if field["sensitivity"] != "public":
                    field["secret_route"], field["default"] = "secrets.set", None
                    if self._keyring_error:
                        field.update(effective=None, configured=None, apply_state="unknown")
                if (
                    field["apply_mode"] == "live_apply"
                    and field["path"] in self._applied
                    and not (self._keyring_error and is_secret(field["path"]))
                ):
                    field["effective"] = self._applied[field["path"]]
                    field["apply_state"] = "applied"
                counts[field["apply_state"]] += 1
            payload["status"]["counts"] = counts
            payload["status"]["keyring_error"] = self._keyring_error
            payload["image_models"] = metadata
            payload["image_models_revision"] = self._image_revision(metadata)
            return payload

    def get_fields(self, paths=None):
        fields = self.schema()["fields"]
        if paths is None:
            return fields
        wanted = {".".join(path) if not isinstance(path, str) else path for path in paths}
        return [record for record in fields if record["path"] in wanted]

    def _check_revision(self, expected):
        if expected is not None and expected != self.revision:
            raise _error(
                "Settings changed; refresh before retrying", "stale_binding", "stale_binding"
            )

    def _normalize_changes(self, changes):
        if not isinstance(changes, list):
            raise _error("changes must be an array")
        out, seen = [], set()
        for change in changes:
            if not isinstance(change, dict) or not isinstance(change.get("path"), str):
                raise _error("Every change must name a setting path")
            if set(change) == {"path", "delete"} and change["delete"] is True:
                value = DELETE_CONFIG_PATH
            elif set(change) == {"path", "value"}:
                value = change["value"]
            else:
                raise _error(f"{change['path']}: specify value or delete: true")
            path = tuple(change["path"].split("."))
            if any(not segment for segment in path) or path in seen:
                raise _error(f"{change['path']}: invalid or duplicate setting path")
            seen.add(path)
            out.append((path, value))
        return out

    def _prepare(self, changes, method, *, secret=False):
        current = self.config.model_dump(mode="json")
        candidate = copy.deepcopy(current)
        defaults = fresh_config(self.paths).model_dump(mode="json")
        facts = schema_facts()
        for path, value in changes:
            if (
                not isinstance(path, tuple)
                or not path
                or any(not isinstance(p, str) or not p for p in path)
            ):
                raise _error("Invalid setting path")
            dotted = ".".join(path)
            present = _get(current, path)
            if present is _MISSING and dotted not in facts:
                if not any(
                    facts.get(".".join(path[:i]), {}).get("type") == "object"
                    for i in range(1, len(path))
                ):
                    raise _error(f"{dotted}: no such setting")
            leaves = flatten(present if value is DELETE_CONFIG_PATH else value, dotted) or [
                (dotted, value)
            ]
            if (
                method == "providers.codex.set"
                and len(path) >= 2
                and path[1] in {"retry", "connection_pool", "context_compression"}
            ):
                for leaf, _ in leaves:
                    if _get(current, tuple(leaf.split("."))) is _MISSING:
                        raise _error(f"{leaf}: unknown provider setting")
            if dotted.startswith("outbound_webhooks.targets") and value is not DELETE_CONFIG_PATH:
                from urllib.parse import urlsplit

                for leaf, leaf_value in leaves:
                    if (
                        leaf.endswith(".url")
                        and isinstance(leaf_value, str)
                        and urlsplit(leaf_value).username is not None
                    ):
                        raise _error(f"{leaf}: credential-bearing URLs belong in the keyring")
            for leaf, leaf_value in leaves:
                if is_secret(leaf) and not secret:
                    if not (
                        method.startswith("webhooks.outbound.")
                        and ((leaf.endswith(".secret") and leaf_value == "")
                             or (leaf == "outbound_webhooks.targets" and leaf_value == []))
                    ):
                        raise _error(f"{leaf}: a secret; use secrets.set or secrets.clear")
                right = _handler(leaf)
                allowed = method == right
                if right == "hosts.settings" and method.startswith("hosts."):
                    allowed = True
                if right.startswith("webhooks.outbound.") and method.startswith(
                    "webhooks.outbound."
                ):
                    allowed = True
                if not allowed:
                    raise _error(f"{leaf}: changed through {right}")
            if value is DELETE_CONFIG_PATH:
                default = _get(defaults, path)
                _put(candidate, path, DELETE_CONFIG_PATH if default is _MISSING else default)
            else:
                _put(candidate, path, value)
        self._validate_route_values(method, candidate, changes)
        try:
            desired = Config.model_validate(candidate)
        except ValidationError as exc:
            first = exc.errors(include_input=False, include_context=False)[0]
            path = ".".join(map(str, first["loc"])) or (
                ".".join(changes[0][0]) if changes else "config"
            )
            raise _error(f"{path}: {first['msg']}") from None
        result = desired.model_dump(mode="json")
        normalized = []
        for path, value in changes:
            resolved = _get(result, path)
            if resolved is _MISSING and value is not DELETE_CONFIG_PATH:
                raise _error(f"{'.'.join(path)}: no such setting")
            normalized.append(
                (path, DELETE_CONFIG_PATH if value is DELETE_CONFIG_PATH else resolved)
            )
        return desired, normalized

    def _validate_route_values(self, method, candidate, changes):
        paths = {".".join(path) for path, _ in changes}
        if method == "providers.ollama.set":
            from ..web.api.llm_admin import _validate_ollama_url

            if "ollama.base_url" in paths and isinstance(candidate["ollama"]["base_url"], str):
                try:
                    _validate_ollama_url(candidate["ollama"]["base_url"])
                except ValueError:
                    raise _error(
                        "ollama.base_url: must point to a local/private endpoint"
                    ) from None
            if "ollama.timeout" in paths:
                try:
                    value = int(candidate["ollama"]["timeout"])
                    if not 10 <= value <= 3600:
                        raise ValueError
                except (ValueError, TypeError):
                    raise _error("ollama.timeout: must be between 10 and 3600") from None
                candidate["ollama"]["timeout"] = value
        if method == "providers.codex.set":
            for name in ("request_timeout_seconds", "stream_stall_timeout_seconds"):
                if f"openai_codex.{name}" in paths and isinstance(
                    candidate["openai_codex"][name], bool
                ):
                    raise _error(f"openai_codex.{name}: must be an integer")
            if (
                "openai_codex.agent_reasoning_effort" in paths
                and candidate["openai_codex"]["agent_reasoning_effort"] == ""
            ):
                candidate["openai_codex"]["agent_reasoning_effort"] = None

    def _owner(self, method, changes):
        hook = self.owners.get(method)
        needs_owner = any(
            spec_for(".".join(path)).apply_mode == "live_apply" for path, _ in changes
        )
        if needs_owner and method in _PROVIDERS | {"settings.set"} and hook is None:
            raise _error(f"{method}: runtime owner is unavailable", "capability_unavailable")
        return hook

    def _snapshot(self):
        document, mode = _load_document(self.paths.config_file)
        return copy.deepcopy(document), mode, self.paths.config_file.read_text()

    def _restore(self, snapshot):
        _dump_atomic(snapshot[0], self.paths.config_file, snapshot[1], raw_text=snapshot[2])

    def _publish(self, desired, changes, applied):
        self.config = desired
        self._generation += 1
        if applied:
            values = dict(flatten(desired.model_dump(mode="json")))
            for path, _ in changes:
                dotted = ".".join(path)
                for leaf, value in values.items():
                    if (leaf == dotted or leaf.startswith(dotted + ".")) and spec_for(
                        leaf
                    ).apply_mode == "live_apply":
                        self._applied[leaf] = REDACTED if is_secret(leaf) and value else value

    def confirm_applied(self, changes):
        """A section owner calls this only after its actual adoption succeeds."""
        with self._lock:
            self._publish(self.config, changes, True)

    async def _prepare_owner(self, hook, desired, changes):
        if hook is not None and hasattr(hook, "prepare_settings"):
            token = hook.prepare_settings(desired, changes)
            return await token if inspect.isawaitable(token) else token
        return None

    async def _apply_owner(self, hook, token, desired, changes):
        if token is not None:
            result = token.apply()
        elif hook is not None:
            result = hook(desired, self.config, changes)
        else:
            return
        if inspect.isawaitable(result):
            result = await result
        self._owner_result(result)

    async def _discard_owner(self, token):
        if token is not None:
            result = token.rollback()
            if inspect.isawaitable(result):
                await result

    @staticmethod
    def _owner_result(result):
        if result is False or (
            isinstance(result, dict)
            and (result.get("committed") is False or result.get("success") is False)
        ):
            raise RuntimeError("Runtime owner rejected the candidate")

    def _result(self, changes):
        wanted = [".".join(path) for path, _ in changes]
        records = [
            field
            for field in self.get_fields()
            if any(field["path"] == path or field["path"].startswith(path + ".") for path in wanted)
        ]
        return {"revision": self.revision, "fields": records}

    def save_changes(self, changes, *, method="settings.set", expected_revision=None):
        """Synchronous persistence helper; section caller owns runtime apply."""
        if self._transaction_active:
            raise _error(
                "Settings owner transaction is in progress", "stale_binding", "stale_binding"
            )
        with self._lock, _config_file_lock(self.paths.config_file):
            self._check_revision(expected_revision)
            desired, normalized = self._prepare(changes, method)
            try:
                _patch_config_paths(normalized, path=self.paths.config_file)
            except Exception:
                raise _error("Configuration not saved", "internal_error") from None
            self._publish(desired, normalized, False)
            return self._result(normalized)

    def _rollback(self, snapshot, method):
        try:
            self._restore(snapshot)
        except Exception:
            raise _error(
                f"{method}: apply failed and saved settings could not be restored",
                "internal_error",
                "outcome_unknown",
            ) from None

    async def _save_async(self, changes, method, expected_revision):
        with self._lock, _config_file_lock(self.paths.config_file):
            self._check_revision(expected_revision)
            desired, normalized = self._prepare(changes, method)
            hook = self._owner(method, normalized)
            token = await self._prepare_owner(hook, desired, normalized)
            snapshot = self._snapshot()
            try:
                _patch_config_paths(normalized, path=self.paths.config_file)
            except Exception:
                await self._discard_owner(token)
                raise _error("Configuration not saved", "internal_error") from None
            try:
                await self._apply_owner(hook, token, desired, normalized)
            except BaseException as exc:
                try:
                    await self._discard_owner(token)
                finally:
                    self._rollback(snapshot, method)
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise _error(
                    f"{method}: configuration not applied; saved settings restored",
                    "internal_error",
                ) from None
            self._publish(desired, normalized, hook is not None)
            return self._result(normalized)

    async def _secret(self, method, params):
        if set(params) != ({"path", "value"} if method == "secrets.set" else {"path"}):
            raise _error("Secret operation accepts only path and its write-only value")
        path = params.get("path")
        if not isinstance(path, str) or not path or not is_secret(path):
            raise _error("path must name a secret setting")
        segments = tuple(path.split("."))
        if (
            _get(self.config.model_dump(mode="json"), segments) is _MISSING
            and path not in schema_facts()
        ):
            raise _error(f"{path}: no such secret setting")
        value = params.get("value", "") if method == "secrets.set" else ""
        if method == "secrets.set" and (
            not isinstance(value, str)
            or not value
            or value == REDACTED
            or len(value.encode("utf-8")) > 65536
        ):
            raise _error(f"{path}: secret must be a nonempty bounded string, not a redaction mask")
        owner = _handler(path)
        with self._lock, _config_file_lock(self.paths.config_file):
            desired, _ = self._prepare([(segments, value)], owner, secret=True)
            hook = self._owner(owner, [(segments, value)])
            token = await self._prepare_owner(hook, desired, [(segments, value)])
            snapshot = self._snapshot()
            before = _MISSING
            try:
                before = self.secrets.get(path)
                if method == "secrets.set":
                    self.secrets.set(path, value)
                else:
                    self.secrets.delete(path)
                _patch_config_paths([(segments, DELETE_CONFIG_PATH)], path=self.paths.config_file)
                await self._apply_owner(hook, token, desired, [(segments, value)])
            except BaseException as exc:
                try:
                    await self._discard_owner(token)
                    if before is not _MISSING:
                        if before is None:
                            self.secrets.delete(path)
                        else:
                            self.secrets.set(path, before)
                    self._restore(snapshot)
                except Exception:
                    raise _error(
                        "Credential transaction failed and rollback is unproven",
                        "internal_error",
                        "outcome_unknown",
                    ) from None
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise _error(
                    "Credential not applied; previous saved credential restored",
                    "capability_unavailable"
                    if isinstance(exc, SecretStoreError)
                    else "internal_error",
                ) from None
            self._keyring_checked, self._keyring_error = True, None
            self._publish(desired, [(segments, value)], hook is not None)
            return {"set": method == "secrets.set"}

    def _image_intent(self, params):
        operations = params.get("operations")
        if (
            set(params) != {"expected_revision", "operations"}
            or not isinstance(operations, dict)
            or not operations
            or not set(operations).issubset(IMAGE_MODEL_DEFAULTS)
            or any(value not in ("follow", "pin") for value in operations.values())
        ):
            raise _error("operations must map image_model and/or outer_model to follow or pin")
        with self._lock, _config_file_lock(self.paths.config_file):
            metadata = self._image_metadata()
            if params["expected_revision"] != self._image_revision(metadata):
                raise _error(
                    "Image model intent changed; refresh before retrying",
                    "stale_binding",
                    "stale_binding",
                )
            changes = [
                (
                    IMAGE_MODEL_PREFIX + (leaf,),
                    metadata[leaf]["default" if op == "follow" else "effective"],
                )
                for leaf, op in operations.items()
            ]
            desired, normalized = self._prepare(changes, "settings.set")
            try:
                _patch_config_paths(
                    normalized, path=self.paths.config_file, image_model_intent=operations
                )
            except Exception:
                raise _error("Image model intent not saved", "internal_error") from None
            self._publish(desired, normalized, False)
            metadata = self._image_metadata()
            return {
                "image_models": metadata,
                "image_models_revision": self._image_revision(metadata),
                "revision": self.revision,
            }

    async def handle(self, method, params):
        if method not in self.METHODS:
            raise _error("Unknown settings method", "method_not_found")
        if not isinstance(params, dict):
            raise _error("params must be an object")
        async with self._async_lock:
            if method == "settings.schema":
                return self.schema()
            self._transaction_active = True
            try:
                if method in {"secrets.set", "secrets.clear"}:
                    return await self._secret(method, params)
                if method == "models.image.intent":
                    return self._image_intent(params)
                if set(params) != {"expected_revision", "changes"} or not isinstance(
                    params["expected_revision"], str
                ):
                    raise _error("expected_revision and changes are required")
                return await self._save_async(
                    self._normalize_changes(params["changes"]), method, params["expected_revision"]
                )
            finally:
                self._transaction_active = False

    async def reload(self):
        """Reload saved state only through an attached atomic composite owner.

        Independent sequential owner swaps cannot honestly roll back a partly
        adopted provider graph. Composition must supply the reload owner rather
        than treat replacing the desired Config object as successful reload.
        """
        async with self._async_lock:
            with self._lock, _config_file_lock(self.paths.config_file):
                document, _ = _load_document(self.paths.config_file)
                try:
                    values = fresh_config(self.paths).model_dump(mode="json")
                    self._merge(values, dict(document))
                    desired = Config.model_validate(values, context={"startup": True})
                    values = desired.model_dump(mode="json")
                    for path, value in flatten(values):
                        if is_secret(path) and isinstance(value, str):
                            stored = self.secrets.get(path)
                            if stored is not None:
                                _put(values, tuple(path.split(".")), stored)
                    desired = Config.model_validate(values)
                except Exception:
                    raise _error(
                        "Saved configuration or keyring could not be loaded",
                        "capability_unavailable",
                    ) from None
                old = dict(flatten(self.config.model_dump(mode="json")))
                changes = [
                    (tuple(path.split(".")), value)
                    for path, value in flatten(values)
                    if old.get(path, _MISSING) != value
                ]
                hook = self.owners.get("runtime.reload")
                if changes and hook is None:
                    raise _error(
                        "Atomic configuration reload owner is unavailable", "capability_unavailable"
                    )
                self._transaction_active = True
                token = None
                try:
                    token = await self._prepare_owner(hook, desired, changes)
                    await self._apply_owner(hook, token, desired, changes)
                except BaseException:
                    await self._discard_owner(token)
                    raise
                finally:
                    self._transaction_active = False
                self._publish(desired, changes, hook is not None)
                return {"revision": self.revision, "fields": self.get_fields()}
