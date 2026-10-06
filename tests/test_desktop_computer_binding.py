"""Management uses genuine temporary-profile authority; all native edges stubbed."""
import asyncio
import os
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.computer.controller import ComputerController
from src.computer.models import (
    BackendCapabilities,
    ComputerError,
    ManagementContext,
    RequestContext,
)
from src.computer.policy import foreground
from src.computer.runtime import recovery
from src.computer.store import ComputerStore
from src.desktop.authority import OwnerAuthority
from src.desktop.computer_binding import ComputerBindingService
from src.desktop.management import MethodError
from src.desktop.paths import ProfilePaths
from src.permissions.manager import PermissionManager


@pytest.fixture
def graph(tmp_path):
    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path / "profile-home")
    authority = OwnerAuthority(paths)
    owner = authority.authenticate_local(peer_uid=os.geteuid())
    permissions = PermissionManager(authority)
    store = ComputerStore(tmp_path / "computer.sqlite3", tmp_path / "evidence")
    backend = Mock(side_effect=AssertionError("No graphics may be started"))
    controller = ComputerController(store, backend, lambda _: False, enabled=True)
    settings = SimpleNamespace(config=SimpleNamespace(computer=SimpleNamespace(enabled=True)))
    core = SimpleNamespace(authority=authority, permissions=permissions, paths=paths)
    service = ComputerBindingService(core, settings, controller=controller)
    token = permissions.set_request_owner(owner)
    yield SimpleNamespace(service=service, controller=controller, store=store, core=core,
                          authority=authority, owner=owner, permissions=permissions,
                          backend=backend)
    permissions.reset_request_owner(token)
    store.close()
    authority.release_runtime()


def stranded(g, *, owner=None, host="localhost", descriptor=False, pending_action=False):
    # A retained historical task fixture, not a management-synthesized turn.
    context = RequestContext(owner or g.owner.owner_id, "retained-conversation",
                             "retained-turn", host)
    grant = g.store.create_session(context, "drawing")
    if descriptor:
        g.store.record_runtime(grant, dict(
            version=1, session_id=grant.session_id,
            boot_id="12345678-1234-1234-1234-123456789abc", launch_pending=False,
            kind="processes", no_persistent_devices=True, input_was_enabled=False, processes=[]))
    if pending_action:
        grant = g.store.set_state(grant.session_id, "active")
        g.store.begin_action(grant, "retained-action", "retained-payload", 10)
    g.store.recover()
    return g.store.get_session(grant.session_id)


@pytest.mark.asyncio
async def test_start_readiness_and_close_are_inert_idempotent(graph):
    g = graph
    assert not g.service.published_available
    await g.service.start()
    await g.service.start()
    result = await g.service.handle("computer.status", {})
    assert result["session"] is None
    assert result["readiness"]["management_available"]
    assert result["readiness"]["input_supported"] is False
    g.backend.assert_not_called()
    await g.service.close()
    await g.service.close()
    assert not g.service.readiness()["management_available"]
    with pytest.raises(MethodError, match="closed"):
        await g.service.start()


@pytest.mark.asyncio
async def test_rejects_payload_identity_forged_owner_and_missing_auth(graph):
    g = graph
    await g.service.start()
    with pytest.raises(MethodError) as caught:
        await g.service.handle("computer.status", {"owner_id": g.owner.owner_id})
    assert caught.value.code == "invalid_params"
    for owner in (None, replace(g.owner, _seal=object()), replace(g.owner, runtime_id="other")):
        token = g.permissions.set_request_owner(owner)
        try:
            with pytest.raises(MethodError) as caught:
                await g.service.handle("computer.status", {})
            assert caught.value.code == "permission_denied"
        finally:
            g.permissions.reset_request_owner(token)
    g.backend.assert_not_called()


@pytest.mark.asyncio
async def test_context_has_no_conversation_turn_or_input_authority(graph):
    g = graph
    await g.service.start()
    original = g.controller.operator_session
    async def inspect(context, operation, **params):
        assert type(context) is ManagementContext
        assert not hasattr(context, "turn_id") and not hasattr(context, "channel_id")
        assert g.service._authorize(context)
        with pytest.raises(ComputerError, match="foreground_only"):
            foreground(context)
        with pytest.raises(ComputerError, match="foreground_only"):
            await g.controller.session(context, {"operation": "start", "app": "drawing"})
        return await original(context, operation, **params)
    g.controller.operator_session = inspect
    assert (await g.service.handle("computer.status", {}))["session"] is None
    assert not g.service._authorize(ManagementContext(g.owner.owner_id, "localhost"))
    assert not ({"computer.start", "computer.resume", "computer.act", "computer.observe"}
                & g.service.METHODS)
    g.backend.assert_not_called()


@pytest.mark.asyncio
async def test_absence_recovery_preserves_unknown_action_no_replay(graph, monkeypatch):
    g = graph
    grant = stranded(g, descriptor=True, pending_action=True)
    await g.service.start()
    async def absent(descriptor):
        assert descriptor["session_id"] == grant.session_id
        return {"status": "absence_verified", "reason": "owned_runtime_gone"}
    inspect = Mock(side_effect=absent)
    monkeypatch.setattr(recovery, "verify_absence", inspect)
    result = await g.service.handle("computer.reconcile", {
        "session_id": grant.session_id, "generation": grant.generation})
    assert result["session"]["state"] == "closed"
    assert result["session"]["recovery"]["complete"] is True
    receipt = g.store.receipt(grant.session_id, "retained-action", "retained-payload")
    assert receipt["status"] == "unknown"
    assert result["session"]["input_supported"] is False
    assert inspect.call_count == 1
    g.backend.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_release_and_legacy_ack_never_claim_clean(graph):
    g = graph
    grant = stranded(g)
    await g.service.start()
    params = {"session_id": grant.session_id, "generation": grant.generation}
    result = await g.service.handle("computer.reconcile", params)
    assert result["session"]["state"] == "quarantined"
    assert result["session"]["recovery"]["complete"] is False
    with pytest.raises(MethodError) as caught:
        await g.service.handle("computer.acknowledge_legacy_recovery", {
            **params, "acknowledgment": "cleanup happened"})
    assert caught.value.code == "explicit_acknowledgment_required"
    result = await g.service.handle("computer.acknowledge_legacy_recovery", {
        **params, "acknowledgment": f"ACKNOWLEDGE UNVERIFIED CLEANUP {grant.session_id}"})
    assert result["session"]["state"] == "closed"
    assert result["session"]["cleanup"]["complete"] is False
    assert result["session"]["recovery"]["status"] == "operator_acknowledged_unverified"
    g.backend.assert_not_called()


@pytest.mark.asyncio
async def test_exact_generation_owner_host_and_revocation_rechecks(graph, monkeypatch):
    g = graph
    grant = stranded(g, descriptor=True)
    await g.service.start()
    for generation in (True, 0, grant.generation + 1):
        with pytest.raises(MethodError):
            await g.service.handle("computer.reconcile", {"session_id": grant.session_id,
                                                         "generation": generation})
    with pytest.raises(MethodError) as caught:
        await g.service.handle("computer.stop", {"session_id": "different",
                                                  "generation": grant.generation})
    assert caught.value.code == "not_found"
    async def revoke(descriptor):
        g.authority.release_runtime()
        return {"status": "absence_verified", "reason": "owned_runtime_gone"}
    monkeypatch.setattr(recovery, "verify_absence", revoke)
    with pytest.raises(MethodError) as caught:
        await g.service.handle("computer.reconcile", {"session_id": grant.session_id,
                                                      "generation": grant.generation})
    assert caught.value.code == "not_found"
    assert g.store.get_session(grant.session_id).state == "quarantined"
    g.backend.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["owner", "host"])
async def test_foreign_session_recovery_never_reads_pixels_or_adopts_task(graph, field):
    g = graph
    grant = stranded(g, owner="foreign-owner" if field == "owner" else None,
                     host="different-host" if field == "host" else "localhost")
    await g.service.start()
    with pytest.raises(MethodError) as caught:
        await g.service.handle("computer.reconcile", {"session_id": grant.session_id,
                                                      "generation": grant.generation})
    assert caught.value.code == "not_found"
    assert g.store.get_session(grant.session_id).state == "quarantined"
    g.backend.assert_not_called()


@pytest.mark.asyncio
async def test_copied_management_context_child_cannot_issue_operations(graph):
    g = graph
    await g.service.start()
    async def intercepted(context, operation, **params):
        async def child():
            assert not g.service._authorize(context)
            with pytest.raises(ComputerError, match="not_found"):
                await g.controller._management_auth(context)
        await asyncio.create_task(child())
        return {"state": "paused", "input_supported": True}
    g.controller.operator_session = intercepted
    result = await g.service.handle("computer.status", {})
    assert result["session"]["input_supported"] is False


@pytest.mark.asyncio
async def test_activation_revokes_without_restore_replay_or_native_ready(graph):
    g = graph
    await g.service.start()
    calls = []
    original = g.controller.set_enabled
    async def enabled(value):
        calls.append(value)
        await original(value)
    g.controller.set_enabled = enabled
    candidate = SimpleNamespace(computer=SimpleNamespace(enabled=False))
    change = g.service.prepare_settings(candidate, [(('computer', 'enabled'), False)])
    await change.apply()
    assert g.controller.enabled is False
    assert g.service.published_available is False
    await change.rollback()
    assert g.controller.enabled is True
    assert calls == [False, True]
    assert not g.service.readiness()["native_qualified"]
    g.backend.assert_not_called()
    with pytest.raises(MethodError) as caught:
        g.service.prepare_settings(candidate, [(('computer', 'display'), ':99')])
    assert caught.value.code == "capability_unavailable"


@pytest.mark.asyncio
async def test_activation_management_delegates_to_transaction_owner_not_raw_payload(graph):
    g = graph
    calls = []
    async def save(method, params):
        calls.append((method, params))
        return {"revision": "saved"}
    g.service.settings.handle = save
    await g.service.start()
    params = {"expected_revision": "r1", "changes": {"computer.enabled": False}}
    assert await g.service.handle("computer.activation.set", params) == {"revision": "saved"}
    assert calls == [("computer.activation.set", params)]
    g.backend.assert_not_called()


@pytest.mark.asyncio
async def test_activation_rechecks_owner_before_apply(graph):
    g = graph
    await g.service.start()
    candidate = SimpleNamespace(computer=SimpleNamespace(enabled=False))
    change = g.service.prepare_settings(candidate, [(('computer', 'enabled'), False)])
    g.authority.release_runtime()
    with pytest.raises(MethodError) as caught:
        await change.apply()
    assert caught.value.code == "permission_denied"
    assert g.controller.enabled is True


@pytest.mark.asyncio
async def test_disabled_settings_still_allow_recovery_status_and_stop(graph):
    g = graph
    grant = stranded(g)
    g.service.settings.config.computer.enabled = False
    await g.service.start()
    assert not g.controller.enabled
    assert (await g.service.handle("computer.status", {}))["session"]["state"] == "quarantined"
    with pytest.raises(MethodError) as caught:
        await g.service.handle("computer.pause", {"session_id": grant.session_id,
                                                  "generation": grant.generation})
    assert caught.value.code == "disabled"
    result = await g.service.handle("computer.reconcile", {
        "session_id": grant.session_id, "generation": grant.generation})
    assert result["session"]["state"] == "quarantined"
    g.backend.assert_not_called()


@pytest.mark.asyncio
async def test_recovery_after_stub_absence_keeps_generation_and_consent_fences(graph, monkeypatch):
    g = graph
    grant = stranded(g, descriptor=True)
    await g.service.start()
    async def unknown(descriptor):
        return {"status": "unknown", "reason": "inspection_unavailable"}
    monkeypatch.setattr(recovery, "verify_absence", unknown)
    result = await g.service.handle("computer.reconcile", {
        "session_id": grant.session_id, "generation": grant.generation})
    assert result["session"]["state"] == "quarantined"
    assert result["session"]["generation"] == grant.generation
    assert result["session"]["consent_generation"] == grant.consent_generation
    assert not result["session"]["input_supported"]
    g.backend.assert_not_called()


@pytest.mark.asyncio
async def test_hyprland_owner_reconcile_wrong_generation_never_instantiates_backend(graph):
    g = graph
    grant = stranded(g)
    await g.service.start()
    with pytest.raises(MethodError) as caught:
        await g.service.handle("computer.reconcile_hyprland_owner", {
            "session_id": grant.session_id, "generation": grant.generation + 1})
    assert caught.value.code == "stale_generation"
    g.backend.assert_not_called()


@pytest.mark.asyncio
async def test_emergency_release_unsupported_backend_remains_quarantined(graph):
    g = graph
    grant = stranded(g)
    await g.service.start()
    with pytest.raises(MethodError) as caught:
        await g.service.handle("computer.release_owned_input", {
            "session_id": grant.session_id, "generation": grant.generation})
    assert caught.value.code == "hyprland_recovery_unavailable"
    assert g.store.get_session(grant.session_id).state == "quarantined"
    g.backend.assert_not_called()


@pytest.mark.asyncio
async def test_pause_and_stop_forward_exact_current_generation_to_retained_lifecycle(graph):
    g = graph
    grant = stranded(g)
    await g.service.start()
    calls = []
    async def pause(session_id):
        calls.append(("pause", session_id))
        return g.store.get_session(session_id).public()
    async def stop(session_id, state):
        calls.append((state, session_id))
        return g.store.get_session(session_id).public()
    g.controller._pause, g.controller._stop = pause, stop
    params = {"session_id": grant.session_id, "generation": grant.generation}
    for method in ("computer.pause", "computer.stop", "computer.cancel", "computer.close"):
        with pytest.raises(MethodError) as caught:
            await g.service.handle(method, {**params, "generation": grant.generation + 1})
        assert caught.value.code == "stale_generation"
        await g.service.handle(method, params)
    assert calls == [("pause", grant.session_id), ("cancelled", grant.session_id),
                     ("cancelled", grant.session_id), ("closed", grant.session_id)]
    g.backend.assert_not_called()


@pytest.mark.asyncio
async def test_failed_close_retains_controller_for_recovery_and_never_claims_closed(graph):
    g = graph
    await g.service.start()
    g.controller._live["retained"] = object()
    async def incomplete():
        return None
    g.controller.close = incomplete
    with pytest.raises(RuntimeError, match="cleanup incomplete"):
        await g.service.close()
    assert g.service.readiness()["management_available"]
    assert not g.service._closed
    g.controller._live.clear()
    await g.service.close()
    assert g.service._closed


@pytest.mark.asyncio
@pytest.mark.parametrize("released", [False, True])
async def test_retained_hyprland_recovery_child_rechecks_and_reports_no_receiver_proof(
    graph, monkeypatch, released,
):
    from src.computer.runtime.hyprland_recovery import HyprlandRecoveryResult

    g = graph
    grant = stranded(g)
    await g.service.start()
    assessments = []
    monkeypatch.setattr(g.store, "prepare_hyprland_reconnect",
                        lambda grant: ({"owner": {"stub": True}, "command_id": "retained"}, False))
    monkeypatch.setattr(g.store, "record_hyprland_recovery_assessment",
                        lambda grant, **value: assessments.append(value))
    async def reconcile(owner, *, command_id, query_only, persist, checkpoint, prepare_phase):
        assert owner == {"stub": True} and command_id == "retained"
        assert not query_only
        # This is the controller-owned recovery task, not an arbitrary copied
        # child context. Its checkpoints must still accept the original owner.
        await checkpoint()
        return HyprlandRecoveryResult("quarantined", None, {
            "released": released, "release_ack": released, "unknown_release": not released,
            "resources_retired": released, "receiver_release_verified": False,
        }, "stub_native_release")
    backend = SimpleNamespace(capabilities=BackendCapabilities(
        "wayland", "existing_session", backend="hyprland"),
        reconcile_durable_owner=reconcile, abort_native_recovery=Mock())
    g.controller.backend_factory = lambda app: backend
    result = await g.service.handle("computer.reconcile_hyprland_owner", {
        "session_id": grant.session_id, "generation": grant.generation})
    assert result["session"]["state"] == "quarantined"
    assert not result["session"]["input_supported"]
    assert not g.controller._live and not g.controller._recoveries
    assert assessments == [{"state": "fresh_target_required" if released
                             else "operator_release_required", "released": released,
                             "resources_retired": released}]
    backend.abort_native_recovery.assert_called_once()


@pytest.mark.asyncio
async def test_private_store_start_is_inert_with_default_integration(tmp_path, graph):
    g = graph
    config = SimpleNamespace(enabled=False, storage_dir=str(tmp_path / "private-computer"))
    settings = SimpleNamespace(config=SimpleNamespace(computer=config))
    service = ComputerBindingService(g.core, settings)
    await service.start()
    assert service._integration is not None
    assert not service.controller._live and not service.controller.enabled
    assert not service.published_available
    assert (await service.handle("computer.status", {}))["session"] is None
    await service.close()
    assert service._integration._closed
