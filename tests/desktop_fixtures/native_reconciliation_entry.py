"""Test-only original Guardian/native/Controller/Store composition, not a GUI grant.

Shared X11 recovery is deliberately read-only. Real receiver release is recorded
separately; losing the sole guardian ledger never manufactures release proof.
"""
from __future__ import annotations

import asyncio
import json
import os
import select
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.computer.controller import ComputerController
from src.computer.models import ComputerError, RequestContext
from src.computer.runtime.recovery import boot_id, process_identity, verify_absence
from src.computer.runtime.x11_guardian import Guardian, GuardianFailure, InjectionHelper
from src.computer.runtime.x11_owned_device import open_input
from src.computer.runtime.x11_worker_lifecycle import parent_watch
from src.computer.store import ComputerStore
from tests.desktop_fixtures.native_lifecycle_receiver import assert_private_native

CONTEXT = RequestContext("native-qualification-owner", "native-qualification-channel",
                         "native-qualification-turn", "localhost", surface="desktop")
ACTION = "native-press-once"
PAYLOAD = "native-test-key-control-l"


def emit(value):
    print(json.dumps(value, sort_keys=True), flush=True)


def private_root(path):
    value = Path(path).resolve()
    assert value.is_relative_to(Path(os.environ["ODIN_REAL_CORE_ROOT"]).resolve())
    value.mkdir(mode=0o700, parents=True, exist_ok=True)
    return value


def original_store(root):
    return ComputerStore(root / "native.db", root / "evidence")


def guardian():
    from Xlib import X, display
    assert_private_native()
    parent_watch()
    request = json.loads(sys.stdin.readline())
    receiver_identity = request["receiver_identity"]
    connection = display.Display()
    native = open_input(os.environ["DISPLAY"], mode="shared")
    helper = InjectionHelper(os.environ["DISPLAY"], dict(os.environ), mode="shared",
                             expected_device_identity=native.identity())
    try:
        emit({"kind": "guardian-ready", "guardian": process_identity(os.getpid()),
              "helper": process_identity(helper.process.pid)})
        assert json.loads(sys.stdin.readline()) == {"go": True}
        window = connection.create_resource_object("window", request["window"])
        expected_pid = receiver_identity["pid"]

        def validate(step):
            # This is a dedicated test receiver, not a replacement app-scope
            # policy. Native focus, window PID and exact live identity are checked
            # before new input. Guardian's original overlap/lease guards remain.
            if process_identity(expected_pid) != receiver_identity:
                raise GuardianFailure("application_identity_changed")
            if Path(f"/proc/{expected_pid}").stat().st_uid != os.geteuid():
                raise GuardianFailure("application_uid_mismatch")
            prop = window.get_full_property(
                connection.intern_atom("_NET_WM_PID"), X.AnyPropertyType)
            focused = connection.get_input_focus().focus
            if prop is None or list(prop.value) != [expected_pid] or focused.id != window.id:
                raise GuardianFailure("application_scope_changed")
            window.get_attributes()
            connection.sync()

        result = Guardian(native, helper, validate, controller_fd=0).run([
            ("key", native.keycode("Control_L"), True), ("wait", 1.0),
            ("key", native.keycode("Control_L"), False)])
        Path(request["guardian_receipt"]).write_text(json.dumps(result), encoding="utf-8")
        emit({"kind": "guardian-result", "result": result})
    finally:
        helper.fence()
        native.close()
        connection.close()


def controller(root, window, receiver_pid):
    assert_private_native()
    store = original_store(root)
    original = ComputerController(store, None, lambda _: True, enabled=False)
    grant = store.create_session(CONTEXT, environment="existing_session")
    child = subprocess.Popen([sys.executable, __file__, "guardian"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr, text=True, bufsize=1)
    descriptor = {"version": 1, "session_id": grant.session_id, "boot_id": boot_id(),
                  "kind": "processes", "launch_pending": True,
                  "processes": [process_identity(os.getpid()), process_identity(child.pid)],
                  "no_persistent_devices": True, "input_was_enabled": True}
    store.record_runtime(grant, descriptor)
    child.stdin.write(json.dumps({"window": window,
                                 "receiver_identity": process_identity(receiver_pid),
                                 "guardian_receipt": str(root / "guardian-receipt.json")}) + "\n")
    child.stdin.flush()
    assert select.select([child.stdout], [], [], 3)[0], "guardian readiness timeout"
    ready = json.loads(child.stdout.readline())
    descriptor.update(launch_pending=False, processes=[*descriptor["processes"], ready["helper"]])
    store.record_runtime(grant, descriptor)
    grant = store.set_state(grant.session_id, "active")
    assert store.begin_action(grant, ACTION, PAYLOAD, 10) is None
    # Identity persisted before authorizing any native edge.
    (root / "identity.json").write_text(json.dumps({"session_id": grant.session_id,
        "controller": process_identity(os.getpid()), **ready}), encoding="utf-8")
    child.stdin.write('{"go": true}\n')
    child.stdin.flush()
    emit({"kind": "controller-ready", "session_id": grant.session_id, **ready})
    try:
        # The real Electron parent's pipe is an ownership lifetime. EOF revokes
        # the guardian, does not finish the pending action as successful.
        while child.poll() is None:
            if select.select([sys.stdin], [], [], .01)[0] and not os.read(0, 4096):
                child.stdin.close()
                child.wait(timeout=3)
                emit({"kind": "app-parent-eof", "pending_action_preserved": True})
                return
        child.wait(timeout=3)
    finally:
        store.close()
    # No restart of the action, and no fabricated clean receipt on early death.
    del original


async def recover(root):
    assert_private_native()
    store = original_store(root)
    original = ComputerController(store, None, lambda _: True, enabled=False)
    identity = json.loads((root / "identity.json").read_text())
    grant = store.get_session(identity["session_id"])
    before = store.receipt(grant.session_id, ACTION, PAYLOAD)
    controller_denial = None
    try:
        await original.reconcile_recovery(CONTEXT, grant.session_id, grant.generation)
    except ComputerError as error:
        controller_denial = str(error)
    assert controller_denial == "operator_surface_required", controller_denial
    # Main desktop intentionally removed the web operator reconciliation route.
    # Compose its ORIGINAL read-only inspector and store CAS, without changing
    # policy or pretending this is an available production controller command.
    assessment = await verify_absence(store.runtime_descriptor(grant.session_id))
    grant = store.finish_recovery(grant, assessment)
    status = {"state": grant.state, "generation": grant.generation,
              "recovery": store.recovery_status(grant.session_id)}
    # Original receipt lookup precedes active grant CAS: retry returns stored
    # unknown, even with a revoked generation. It never emits native input.
    retry = store.begin_action(grant, ACTION, PAYLOAD, 10)
    assert before == retry and before["status"] == "unknown"
    assert status["state"] == "quarantined"
    busy = None
    try:
        store.create_session(CONTEXT, environment="existing_session")
    except ComputerError as error:
        busy = str(error)
    assert busy == "session_busy", busy
    result = {"kind": "recovered", "state": status["state"], "generation": status["generation"],
              "recovery": status["recovery"], "cleanup": store.cleanup(grant.session_id),
              "receipt": before, "retry_receipt": retry, "new_session_error": busy,
              "controller_source": str(
                  Path(sys.modules[ComputerController.__module__].__file__).resolve()),
              "store_source": str(Path(sys.modules[ComputerStore.__module__].__file__).resolve()),
              "live_backends": len(original._live),
              "qualification": "test-only-original-native-composition",
              "production_controller_reconcile_denial": controller_denial,
              "recovery_composition": "original-verify_absence-and-store-CAS-test-only",
              "release_reconcile": "shared-X11-read-only-no-actuation"}
    emit(result)
    store.close()


def bind_dormant_native_owner(management, root):
    """Inject before service.start(), so the foreground seam keeps this store.

    Startup binds the management controller into the request dispatcher. Writing
    directly to the dispatcher at compose time is overwritten by that binding.
    """
    from src.computer.integration import ComputerIntegration

    service = management.computer
    assert not service._started and service.controller is None
    store = original_store(root)
    controller = ComputerController(store, None, lambda _: True, enabled=False)
    integration = ComputerIntegration(
        SimpleNamespace(config=management.settings.config), controller=controller,
        settings=management.settings.config.computer)
    service.controller = controller
    service._integration = integration
    return integration


def core_entry(root):
    """Real source core owns the ORIGINAL dormant native integration on restart."""
    import src.__main__ as entry
    from src.desktop.management import ManagementService

    original_compose = ManagementService.compose.__func__

    def compose(cls, core, **kwargs):
        management = original_compose(cls, core, **kwargs)
        integration = bind_dormant_native_owner(management, root)
        (root / "core-native-owner.json").write_text(json.dumps({
            "core_pid": os.getpid(), "integration": "original-ComputerIntegration",
            "store": "original-ComputerStore", "test_only_dormant_composition": True,
            "live_backends": len(integration.controller._live),
        }), encoding="utf-8")
        return management

    ManagementService.compose = classmethod(compose)
    entry.main()


def main():
    assert_private_native()
    mode = sys.argv[1]
    if mode == "guardian":
        guardian()
    elif mode == "controller":
        controller(private_root(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
    elif mode == "recover":
        asyncio.run(recover(private_root(sys.argv[2])))
    elif mode == "core":
        root = private_root(sys.argv[2])
        # Original desktop parser receives only the real supervisor's args.
        sys.argv = [sys.argv[0], *sys.argv[3:]]
        core_entry(root)
    else:
        raise ValueError("unknown native fixture mode")


if __name__ == "__main__":
    main()
