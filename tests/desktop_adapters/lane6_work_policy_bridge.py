"""Frozen agent policy setup using genuine model and profile settings owners.

Only the constructor's removed Discord input, the frozen mock import target
and socket-free transport are bridged. Storage faults gate the canonical
transaction; successful writes use its validators, lock and atomic persistence.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from src.config.schema import Config as CanonicalConfig
from src.desktop.authority import OwnerAuthority
from src.desktop.management import MethodError
from src.desktop.model_settings import ModelSettingsService
from src.desktop.paths import ProfilePaths
from src.desktop.settings import SettingsService
from src.desktop.work_policy import WorkPolicyService
from src.permissions.persistence import write_private_atomic

PERSIST_PATCH_TARGET = __name__ + ".persist_config_paths_locked"
POLICY_CASES = frozenset({
    "TestAgents.test_agent_model_policy_reports_validation_errors",
    "TestAgents.test_agent_model_policy_get_and_put",
    "TestAgents.test_agent_model_policy_rejects_invalid_and_surfaces_save_failure",
    "TestAgents.test_agent_model_policy_propagates_cancelled_persistence",
})
EVIDENCE = []


def Config(*args, **kwargs):  # noqa: N802 - frozen constructor import identity
    """Remove only the frozen transport credential argument, not config fields."""
    kwargs.pop("discord", None)
    return CanonicalConfig(*args, **kwargs)


async def persist_config_paths_locked(*args, **kwargs):
    """Default storage gate. Canonical settings remains the only real writer."""
    return None, False


class PolicyRuntime:
    def __init__(self, paths, authority, permissions, bot):
        self.paths, self.authority, self.permissions, self.bot = paths, authority, permissions, bot
        self.owner = authority.authenticate_local(peer_uid=authority.owner_uid)
        # Bootstrapping a blank isolated document must not re-run a validator
        # patched by the test before the actual method under test is entered.
        if not paths.config_file.exists():
            if not write_private_atomic(paths.config_file, "{}\n"):
                raise OSError("Fixture profile bootstrap durability is unproven")
        secrets = SimpleNamespace(get=lambda path: None)
        self.settings = SettingsService(paths, secrets, config=bot.config)
        self.models = ModelSettingsService(self.settings)

        async def gate():
            return await persist_config_paths_locked()

        self.service = WorkPolicyService(self.settings, authority=authority,
                                         model_settings=self.models, persistence_gate=gate)

    async def _request(self, method, params):
        try:
            value = await self.service.invoke(method, params, owner=self.owner)
            self.bot.config = self.settings.config
            EVIDENCE.append((method, self.owner.owner_id, str(self.paths.config_file)))
            return value, 200
        except MethodError as exc:
            return {"error": str(exc)}, 400 if exc.code == "bad_request" else 500

    async def get(self):
        return await self._request("models.agents.get", {})

    async def put(self, params):
        return await self._request("models.agents.set", params)

    def close(self):
        """No owned shared resources: parent owns authority/profile lifetime."""


def install(app, bot):
    """Expose a route-shaped direct invocation seam, never a web registrar.

    Parent's socket-free app can either return the two records from its existing
    router.routes(), or use the compatibility method installed here. Normal
    get/put traffic uses PolicyRuntime on the parent's already-isolated profile.
    The frozen direct cancellation handler owns its independent temporary one.
    """
    async def dispatch(method, request):
        with TemporaryDirectory(prefix="lane6_work_policy_direct_") as directory:
            paths = ProfilePaths.from_xdg("policy-fixture", home=Path(directory), environ={})
            authority = OwnerAuthority(paths)
            try:
                runtime = PolicyRuntime(paths, authority, None, bot)
                if method == "PUT":
                    return await runtime.put(await request.json())
                return await runtime.get()
            finally:
                authority.release_runtime()

    async def get_handler(request):
        return await dispatch("GET", request)

    async def put_handler(request):
        return await dispatch("PUT", request)

    resource = SimpleNamespace(canonical="/api/agents/model")
    records = (
        SimpleNamespace(method="GET", resource=resource, handler=get_handler),
        SimpleNamespace(method="PUT", resource=resource, handler=put_handler),
    )
    app._policy_routes = records
    if app.router is app and not callable(getattr(app.router, "routes", None)):
        # Parent Application currently stores registrar fixtures in app.routes.
        # Keep that list intact; supply the separate native route view on router.
        app.router = SimpleNamespace(routes=lambda: app._policy_routes)
    return records
