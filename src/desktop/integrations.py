"""Desktop outbound integration management, without an HTTP or inbound server.

The retained dispatcher owns URL/event validation, delivery and statistics.
Only its desired targets are persisted here. Signing keys live exclusively in
the profile keyring; dispatcher adoption follows durable configuration writes.
"""

from __future__ import annotations

import asyncio
import uuid
from copy import deepcopy
from typing import Any
from urllib.parse import urlparse

from ..config.persistence import _load_document
from ..config.schema import OutboundWebhookTarget
from ..notifications.outbound_webhooks import OutboundWebhookDispatcher
from .management import MethodError

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


class IntegrationsService:
    METHODS = METHODS
    READ_METHODS = READ_METHODS

    def __init__(self, settings, *, dispatcher=None):
        self.settings = settings
        self.dispatcher = dispatcher
        self._lock = asyncio.Lock()

    def _owner(self):
        if self.dispatcher is not None:
            return self.dispatcher
        config = self.settings.config.outbound_webhooks
        owner = OutboundWebhookDispatcher(
            scrub_secrets=config.scrub_secrets,
            rate_limit_seconds=config.rate_limit_seconds,
        )
        for index, row in enumerate(config.targets):
            if row.secret or urlparse(row.url).username is not None:
                # Never silently adopt imported plaintext signing credentials.
                raise MethodError("unavailable", "outbound webhook secrets require keyring storage")
            try:
                secret = self.settings.secrets.get(_secret_name(_runtime_id(row, index))) or ""
                private_url = self.settings.secrets.get(_url_secret_name(_runtime_id(row, index)))
            except Exception:
                raise MethodError(
                    "unavailable", "outbound webhook keyring is unavailable",
                ) from None
            try:
                owner.register(
                    **row.model_dump(exclude={"id", "secret", "url"}),
                    url=(private_url if private_url and _public_url(private_url) == row.url
                         else row.url),
                    webhook_id=_runtime_id(row, index), secret=secret,
                )
            except ValueError:
                # As upstream boot does, retain invalid configured rows on disk
                # without claiming they were adopted by the running dispatcher.
                continue
        self.dispatcher = owner
        return owner

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
            dispatcher = self._owner()
            if method == "webhooks.outbound.list":
                return dispatcher.get_status()
            if method == "webhooks.outbound.test":
                ident = self._identifier(params)
                result = await dispatcher.send_test_event(ident)
                if result is None:
                    raise MethodError("not_found", "webhook not found")
                return result.to_dict()
            return self._mutate(dispatcher, method, params)

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
                updated = {field: getattr(target, field) for field in updated}
                # Never serialize the live signing key.
                updated["secret"] = ""
                if not row.id and _public_url(target.url) == row.url:
                    updated["id"] = ""
                updated["url"] = _public_url(target.url)
            new_id = updated["id"] or uuid.uuid5(
                uuid.NAMESPACE_URL, f"outbound-webhook:{len(rows)}:{updated['url']}"
            ).hex[:12]
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
                )} | {"secret": "", "url": _public_url(target.url)})
                remapped[target.id] = target
                moves[old_id] = target.id
        return rows, remapped, moves

    def _apply_targets(self, dispatcher, targets):
        """Owner adoption seam: persistence has already succeeded."""
        dispatcher._webhooks = targets

    def _mutate(self, dispatcher, method, params):
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
        desired_secrets = {_secret_name(key): target.secret for key, target in targets.items()}
        desired_secrets.update({
            _url_secret_name(key): target.url if urlparse(target.url).username is not None else ""
            for key, target in targets.items()
        })
        for old_id in previous_targets:
            desired_secrets.setdefault(_secret_name(old_id), "")
            desired_secrets.setdefault(_url_secret_name(old_id), "")
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
