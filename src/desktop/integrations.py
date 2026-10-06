"""Desktop outbound integration management, without an HTTP or inbound server.

The retained dispatcher owns URL/event validation, delivery and statistics.
Only its desired targets are persisted here. Signing keys live exclusively in
the profile keyring; dispatcher adoption follows durable configuration writes.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from contextlib import nullcontext
from copy import deepcopy
from typing import Any
from urllib.parse import urlparse

from ..config.persistence import _load_document
from ..config.schema import OutboundWebhookTarget
from ..notifications.outbound_webhooks import OutboundWebhookDispatcher
from .management import MethodError
from .secrets import secret_call

METHODS = frozenset({
    "webhooks.outbound.list", "webhooks.outbound.save", "webhooks.outbound.delete",
    "webhooks.outbound.test", "integrations.email.get",
})
READ_METHODS = frozenset({"webhooks.outbound.list", "integrations.email.get"})
_FIELDS = ("name", "url", "secret", "events", "enabled", "scrub_secrets", "verify_ssl")
_TARGET_PATH = ("outbound_webhooks", "targets")


def _runtime_id(row: Any, index: int) -> str:
    return row.id or uuid.uuid5(
        uuid.NAMESPACE_URL, f"outbound-webhook:{index}:{row.url}"
    ).hex[:12]


def _secret_name(ident: str) -> str:
    # Configured IDs need not fit the vault's bounded identifier grammar.
    return "outbound_webhook_" + uuid.uuid5(uuid.NAMESPACE_URL, ident).hex


def _url_secret_name(ident: str) -> str:
    return "outbound_webhook_url_" + uuid.uuid5(uuid.NAMESPACE_URL, ident).hex


def _public_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(netloc=parsed.netloc.rsplit("@", 1)[-1]).geturl()


class ProfileOutboundWebhookDispatcher(OutboundWebhookDispatcher):
    """Retained delivery with live profile targets and one shutdown owner.

    Construction is inert: no keyring read, transport, background task or ingress.
    Target qualification is atomic. Credentialed and legacy-unmarked rows are
    requalified so locking or unlocking the vault never requires a config edit.
    """

    def __init__(self, get_config, *, secrets=None):
        super().__init__()
        self._get_config = get_config
        self._secrets = secrets
        self._adopted_rows = None
        self._skipped_targets = []
        # Shared by qualification and management transactions, never acquired
        # on an async delivery path. Workers may not publish stale signing keys
        # across a concurrent save/rollback on this same retained owner.
        self._target_lock = threading.RLock()
        self._closed = False
        self._deliveries = set()

    def _sync(self):
        with self._target_lock:
            while True:
                config = self._sync_locked()
                if config is not None:
                    return config

    def _sync_locked(self):
        if self._closed:
            raise MethodError("unavailable", "outbound webhook owner is closed")
        config = deepcopy(self._get_config().outbound_webhooks)
        rows = [row.model_dump() for row in config.targets]
        if rows != self._adopted_rows or any(
            row.signing_key_stored is not False or row.private_url_stored is not False
            for row in config.targets
        ):
            candidate = OutboundWebhookDispatcher()
            skipped = []
            for index, row in enumerate(config.targets):
                if row.secret or urlparse(row.url).username is not None:
                    raise MethodError(
                        "unavailable", "outbound webhook secrets require keyring storage")
                ident = _runtime_id(row, index)
                secret = ""
                private_url = None
                try:
                    if self._secrets is None and (
                        row.signing_key_stored is not False or row.private_url_stored is not False
                    ):
                        raise ValueError("profile keyring is unavailable")
                    if row.signing_key_stored is not False:
                        secret = self._secrets.get(_secret_name(ident)) if self._secrets else None
                        if row.signing_key_stored and not secret:
                            raise ValueError("stored signing key is missing")
                    if row.private_url_stored is not False:
                        private_url = (self._secrets.get(_url_secret_name(ident))
                                       if self._secrets else None)
                        if row.private_url_stored and not private_url:
                            raise ValueError("stored private URL is missing")
                        if private_url and _public_url(private_url) != row.url:
                            raise ValueError("stored private URL is missing or stale")
                    secret = secret or ""
                except Exception:
                    # Do not expose backend exception text or downgrade a signed
                    # or authenticated target to an unsigned/public delivery.
                    skipped.append({"id": ident, "name": row.name, "url": row.url,
                                    "reason": "outbound webhook keyring credentials "
                                              "are unavailable"})
                    continue
                try:
                    candidate.register(**row.model_dump(exclude={
                        "id", "secret", "url", "signing_key_stored", "private_url_stored"}),
                        url=private_url or row.url, webhook_id=ident, secret=secret)
                except ValueError:
                    continue
            # Config replacement/in-place edits can occur while the vault is
            # answering. Qualify a fresh snapshot instead of publishing old rows.
            if self._get_config().outbound_webhooks != config:
                return None
            if self._closed:
                raise MethodError("unavailable", "outbound webhook owner is closed")
            self._webhooks = {
                ident: self._webhooks[ident] if self._webhooks.get(ident) == target else target
                for ident, target in candidate._webhooks.items()
            }
            self._adopted_rows = deepcopy(rows)
            self._skipped_targets = skipped
        self._scrub = config.scrub_secrets
        self._rate_limit_seconds = max(0.0, config.rate_limit_seconds)
        return config

    def get_status(self):
        self._sync()
        status = super().get_status()
        if self._skipped_targets:
            status["skipped_webhooks"] = deepcopy(self._skipped_targets)
        return status

    async def dispatch(self, event_type, data, **kwargs):
        if self._closed:
            return []
        task = asyncio.current_task()
        self._deliveries.add(task)
        try:
            config = await secret_call(self._sync)
            if self._closed or not config.enabled:
                return []
            return await super().dispatch(event_type, data, **kwargs)
        finally:
            self._deliveries.discard(task)

    async def send_test_event(self, webhook_id):
        task = asyncio.current_task()
        self._deliveries.add(task)
        try:
            await secret_call(self._sync)
            if self._closed:
                raise MethodError("unavailable", "outbound webhook owner is closed")
            skipped = next((row for row in self._skipped_targets
                            if row["id"] == webhook_id), None)
            if skipped:
                raise MethodError("unavailable", skipped["reason"])
            return await super().send_test_event(webhook_id)
        finally:
            self._deliveries.discard(task)

    async def close(self):
        if self._closed:
            return
        self._closed = True
        tasks = [task for task in self._deliveries if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await super().close()


class IntegrationsService:
    METHODS = METHODS
    READ_METHODS = READ_METHODS

    def __init__(self, settings, *, dispatcher=None, owns_dispatcher=None):
        self.settings = settings
        self.dispatcher = dispatcher
        self._owns_dispatcher = (dispatcher is None if owns_dispatcher is None else owns_dispatcher)
        self._closed = False
        self._lock = asyncio.Lock()

    def _owner(self):
        if self._closed:
            raise MethodError("unavailable", "outbound integration service is closed")
        if self.dispatcher is not None:
            sync = getattr(self.dispatcher, "_sync", None)
            if callable(sync):
                sync()
            return self.dispatcher
        owner = ProfileOutboundWebhookDispatcher(
            lambda: self.settings.config, secrets=self.settings.secrets)
        owner._sync()
        self.dispatcher = owner
        return owner

    async def close(self):
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._owns_dispatcher and self.dispatcher is not None:
                await self.dispatcher.close()

    async def handle(self, method: str, params: dict) -> dict:
        if method not in METHODS:
            raise MethodError("not_found", "unknown integration method")
        if not isinstance(params, dict):
            raise MethodError("bad_request", "params must be an object")
        if method == "integrations.email.get":
            email = self.settings.config.email
            return {
                "enabled": email.enabled, "tls_verify": email.tls_verify,
                "smtp": {key: value for key, value in email.smtp.model_dump().items()
                         if key != "password"},
                "imap": {key: value for key, value in email.imap.model_dump().items()
                         if key != "password"},
            }
        async with self._lock:
            dispatcher = await secret_call(self._owner)
            if method == "webhooks.outbound.list":
                return await secret_call(dispatcher.get_status)
            if method == "webhooks.outbound.test":
                ident = self._identifier(params)
                result = await dispatcher.send_test_event(ident)
                if result is None:
                    raise MethodError("not_found", "webhook not found")
                return result.to_dict()
            # Keep keyring writes, config persistence, adoption and rollback in
            # one settled worker transaction. Cancellation cannot release the
            # service gate with an unfinished signing-key write behind it.
            return await secret_call(self._mutate, dispatcher, method, params)

    @staticmethod
    def _identifier(params):
        ident = params.get("id")
        if not isinstance(ident, str) or not ident:
            raise MethodError("bad_request", "id is required")
        return ident

    @staticmethod
    def _validate(params, *, updating):
        for field in ("enabled", "scrub_secrets", "verify_ssl"):
            if field in params and not (updating and params[field] is None):
                if type(params[field]) is not bool:
                    raise MethodError("bad_request", f"{field} must be a boolean")
        for field in ("name", "url", "secret"):
            if field in params and not (updating and params[field] is None):
                if not isinstance(params[field], str):
                    raise MethodError("bad_request", f"{field} must be a string")
        # Preserve POST route's stricter name limit, while PUT uses the owner.
        if not updating:
            if len(params.get("name", "")) > 100:
                raise MethodError("bad_request", "name exceeds maximum length of 100")
        if isinstance(params.get("url"), str) and len(params["url"]) > 2048:
            raise MethodError("bad_request", "url exceeds maximum length (2048 chars)")

    def _saved_rows(self):
        """Read desired state, not rejected/stale boot state, before whole-list edits.

        Revision checks and SettingsService's commit check fence concurrent saves.
        Never adopt a saved rejected row here; it remains desired state only.
        """
        if not hasattr(self.settings, "paths"):
            # In-memory settings owners have no separate durable document.
            return deepcopy(self.settings.config.outbound_webhooks.targets)
        try:
            document, _ = _load_document(self.settings.paths.config_file)
            section = document.get("outbound_webhooks", {})
            if not isinstance(section, dict):
                raise ValueError("invalid outbound webhook section")
            if "targets" not in section:
                return deepcopy(self.settings.config.outbound_webhooks.targets)
            values = section["targets"]
            if not isinstance(values, list):
                raise ValueError("invalid outbound webhook targets")
            rows = [OutboundWebhookTarget.model_validate(value) for value in values]
            if any(row.secret or urlparse(row.url).username is not None for row in rows):
                raise ValueError("saved credentials require keyring storage")
            return rows
        except Exception:
            raise MethodError("unavailable", "could not read outbound webhook targets") from None

    def _desired_rows(self, original, candidate, *, ident, deleted):
        """Preserve rejected rows and upstream id-less index/URL identities."""
        rows = []
        remapped = {}
        moves = {}
        configured_ids = set()
        for index, row in enumerate(original):
            old_id = _runtime_id(row, index)
            configured_ids.add(old_id)
            if deleted and old_id == ident:
                continue
            target = candidate.get(old_id)
            updated = row.model_dump()
            if target is not None:
                updated = {field: getattr(target, field) for field in updated
                           if field not in {"signing_key_stored", "private_url_stored"}}
                # Never serialize the live signing key.
                updated["secret"] = ""
                updated["signing_key_stored"] = bool(target.secret)
                updated["private_url_stored"] = urlparse(target.url).username is not None
                if not row.id and _public_url(target.url) == row.url:
                    updated["id"] = ""
                updated["url"] = _public_url(target.url)
            new_id = updated["id"] or uuid.uuid5(
                uuid.NAMESPACE_URL, f"outbound-webhook:{len(rows)}:{updated['url']}"
            ).hex[:12]
            if target is None and new_id != old_id and (
                row.signing_key_stored is not False or row.private_url_stored is not False
            ):
                # A skipped target still owns vault entries under its old ID.
                # Preserve that binding when another id-less row is removed.
                updated["id"] = new_id = old_id
            if target is not None:
                target.id = new_id
                remapped[new_id] = target
                moves[old_id] = new_id
            # Invalid rows are retained, never silently rewritten with keys.
            if updated.get("secret"):
                raise MethodError("unavailable", "outbound webhook secrets require keyring storage")
            if urlparse(updated["url"]).username is not None:
                raise MethodError(
                    "unavailable", "outbound webhook credentials require keyring storage",
                )
            rows.append(updated)
        for old_id, target in candidate._webhooks.items():
            if old_id not in configured_ids:
                rows.append({field: getattr(target, field) for field in (
                    "id", "created_at", *_FIELDS,
                )} | {"secret": "", "url": _public_url(target.url),
                      "signing_key_stored": bool(target.secret),
                      "private_url_stored": urlparse(target.url).username is not None})
                remapped[target.id] = target
                moves[old_id] = target.id
        return rows, remapped, moves

    def _apply_targets(self, dispatcher, targets):
        """Owner adoption seam: persistence has already succeeded."""
        dispatcher._webhooks = targets

    def _mutate(self, dispatcher, method, params):
        with getattr(dispatcher, "_target_lock", nullcontext()):
            sync = getattr(dispatcher, "_sync", None)
            if callable(sync):
                sync()
            return self._mutate_locked(dispatcher, method, params)

    def _mutate_locked(self, dispatcher, method, params):
        try:
            revision = self.settings.revision
        except Exception:
            raise MethodError("unavailable", "could not read outbound webhook targets") from None
        expected = params.get("expected_revision", revision)
        if expected is not None and expected != revision:
            raise MethodError("stale_binding", "settings revision changed", "stale_binding")
        deleting = method == "webhooks.outbound.delete"
        updating = "id" in params
        ident = self._identifier(params) if deleting or updating else None
        if not deleting:
            self._validate(params, updating=updating)
        candidate = OutboundWebhookDispatcher()
        candidate._webhooks = deepcopy(dispatcher._webhooks)
        try:
            if deleting:
                result = candidate.unregister(ident)
            elif updating:
                result = candidate.update(ident, **{key: params.get(key) for key in _FIELDS})
            else:
                name = params.get("name", "")
                url = params.get("url", "")
                result = candidate.register(
                    name=name or _public_url(url), url=url,
                    secret=params.get("secret", ""), events=params.get("events"),
                    enabled=params.get("enabled", True),
                    scrub_secrets=params.get("scrub_secrets", True),
                    verify_ssl=params.get("verify_ssl", True),
                )
                ident = result.id
        except (ValueError, TypeError):
            raise MethodError("bad_request", "invalid webhook configuration") from None
        if result is None or result is False:
            raise MethodError("not_found", "webhook not found")
        original_rows = self._saved_rows()
        rows, targets, moves = self._desired_rows(
            original_rows, candidate, ident=ident, deleted=deleting,
        )
        previous_targets = deepcopy(dispatcher._webhooks)
        stored_keys = set()
        for index, row in enumerate(original_rows):
            old_id = _runtime_id(row, index)
            if row.signing_key_stored is not False:
                stored_keys.add(_secret_name(old_id))
            if row.private_url_stored is not False:
                stored_keys.add(_url_secret_name(old_id))
        desired_secrets = {}
        for key, target in targets.items():
            for vault_key, value in (
                (_secret_name(key), target.secret),
                (_url_secret_name(key),
                 target.url if urlparse(target.url).username is not None else ""),
            ):
                if value or vault_key in stored_keys:
                    desired_secrets[vault_key] = value
        for old_id in previous_targets:
            for vault_key in (_secret_name(old_id), _url_secret_name(old_id)):
                if vault_key in stored_keys:
                    desired_secrets.setdefault(vault_key, "")
        previous_secrets = {}
        changed_secrets = []
        persisted = False
        try:
            for key, value in desired_secrets.items():
                before = self.settings.secrets.get(key)
                previous_secrets[key] = before
                if (before or "") == value:
                    continue
                # Include the key before writing: a backend can fail after effect.
                changed_secrets.append(key)
                if value:
                    outcome = self.settings.secrets.set(key, value)
                else:
                    outcome = self.settings.secrets.clear(key)
                if outcome is False:
                    raise RuntimeError("keyring write failed")
            self.settings.save_changes(
                [(_TARGET_PATH, rows)], method=method,
                expected_revision=expected,
            )
            persisted = True
            if self._apply_targets(dispatcher, targets) is False:
                raise RuntimeError("owner rejected adoption")
        except Exception as exc:
            rollback_failed = False
            if persisted:
                try:
                    self.settings.save_changes(
                        [(_TARGET_PATH, [row.model_dump() for row in original_rows])],
                        method=method, expected_revision=self.settings.revision,
                    )
                except Exception:
                    rollback_failed = True
                dispatcher._webhooks = previous_targets
            for key in reversed(changed_secrets):
                try:
                    if previous_secrets[key] is None:
                        outcome = self.settings.secrets.clear(key)
                    else:
                        outcome = self.settings.secrets.set(key, previous_secrets[key])
                    if outcome is False:
                        raise RuntimeError("keyring rollback failed")
                except Exception:
                    rollback_failed = True
            if rollback_failed:
                raise MethodError(
                    "unavailable", "outbound webhook rollback failed", "outcome_unknown",
                ) from None
            if isinstance(exc, MethodError):
                raise
            raise MethodError("unavailable", "could not save outbound webhook targets") from None
        if deleting:
            return {"status": "deleted", "webhook_id": ident}
        return targets[moves[ident]].to_dict()
