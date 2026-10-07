#!/usr/bin/env python3
"""P3.5 candidate-native qualification, exclusively inside owned Incus guests.

Host orchestration never imports a controller or accesses graphics. The guest
probe imports the INSTALLED candidate controller/adapters, never checkout src.
An unavailable backend is a blocker, not a passing input case. Receipts and
receiver measurements are separate evidence. No auto-consent or guard bypass.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import pwd
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUESTS = {"x11": "odq-cinnamon", "gnome": "odq-gnome",
          "kde": "odq-kde", "hyprland": "odq-hyprland"}
RESOURCES = Path("/opt/Odin/resources")
PYTHON = RESOURCES / "runtime/python/bin/python3"
CASES = {
    "grounding": ["tests/test_computer_freshness_r1.py",
                  "tests/test_computer_geometry_r1.py"],
    "focus_geometry_modal": ["tests/test_computer_native_gui_r5.py",
                             "tests/test_desktop_computer_binding.py"],
    "actions": ["tests/test_computer_actions_r4.py"],
    "loss_recovery": ["tests/test_desktop_computer_binding.py",
                      "tests/test_computer_class1_receipt_recovery.py"],
    "foreground": ["tests/test_desktop_computer_binding.py"],
    "packaged_abi": ["tests/test_computer_hyprland_packaging_r32.py",
                     "tests/test_hyprland_plugin_campaign.py"],
}
# These are retained reference corpora, not automatically executed on a different
# environment. Their fixed container paths/UIDs cannot safely be repointed at a VM.
CORPORA = {
    "x11": ["scripts/computer-feasibility/controller-gui.py",
            "scripts/computer-feasibility/x11-owned-guardian-corpus.py",
            "scripts/computer-feasibility/x11-owned-evidence-check.py"],
    "gnome": ["scripts/computer-feasibility/wayland-portal.py",
              "scripts/computer-feasibility/wayland-r8-evidence.py"],
    "kde": ["scripts/computer-feasibility/wayland-r8-evidence.py"],
    "hyprland": ["scripts/computer-feasibility/hyprland-live-qualification.py",
                 "scripts/computer-feasibility/hyprland-recovery-qualification.py",
                 "scripts/computer-feasibility/hyprland-wire-receiver.c"],
}


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def validate_lab(instances, backend, owner):
    """Pure admission check; lab.py additionally verifies exact VM devices/caps."""
    if backend not in GUESTS or not owner.startswith("p35 "):
        raise ValueError("p35_lab_lock_required")
    target = GUESTS[backend]
    running = [row for row in instances if row["status"].lower() != "stopped"]
    if len(running) != 1 or running[0]["name"] != target:
        raise ValueError("exclusive_running_guest_required")
    if (running[0].get("type") != "virtual-machine"
            or running[0].get("config", {}).get("user.odq.owner")
            != "odin-desktop-qualification-v1"):
        raise ValueError("owned_guest_required")
    return target


def classify(cases, blockers):
    """No empty corpus, receipts-only proof or unknown release can qualify D11."""
    required = {"target_capture", "text", "key", "stroke", "stale_observation",
                "stale_generation", "focus_geometry_modal", "pause", "cancel",
                "exit", "controller_loss", "guardian_loss", "retirement_recovery",
                "restart_quarantine", "helper_discovery", "abi_refusal"}
    measured = {r["case"] for r in cases if r.get("passed") is True
                and r.get("evidence_kind") == "receiver_platform"}
    if blockers:
        return "limited" if measured else "blocked"
    return "proven" if required <= measured else "limited" if measured else "blocked"


def receiver_effect(rows, case):
    """Measure receiver effects without interpreting controller success as delivery."""
    if case == "text":
        return any(row.get("event") == "text" and row.get("text") == "P35safe"
                   for row in rows)
    if case == "key":
        return any(row.get("event") == "text" and row.get("text") == "P35saf"
                   for row in rows)
    if case == "stroke":
        stroke = [i for i, row in enumerate(rows) if row.get("event") == "stroke"]
        return bool(stroke) and any(row.get("event") == "button_up"
            and row.get("buttons") == 0 for row in rows[stroke[-1] + 1:])
    raise ValueError("unknown_receiver_case")


def run_host(args):
    if args.output.resolve() == ROOT or ROOT in args.output.resolve().parents:
        raise ValueError("external_evidence_required")
    candidate = args.candidate.resolve(strict=True)
    if candidate.suffix != ".deb":
        raise ValueError("deb_candidate_required")
    owner = Path("/run/odq-lab.lock/owner").read_text()
    spec = importlib.util.spec_from_file_location(
        "p35_lab", ROOT / "scripts/qualification/lab/lab.py")
    lab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab)
    incus = lab.Incus()
    instances = incus.instances()
    vm = validate_lab(instances, args.backend, owner)
    lab.owned(lab.find(instances, vm))
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    started = time.time()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    deb_sha = digest(candidate)
    guest_dir = "/root/odq/p35-" + uuid.uuid4().hex
    incus.run("exec", vm, "--", "mkdir", "-m", "755", guest_dir)
    incus.run("file", "push", str(candidate), vm + guest_dir + "/candidate.deb")
    incus.run("file", "push", str(Path(__file__).resolve()), vm + guest_dir + "/computer.py")
    incus.run("file", "push", str(ROOT / "scripts/qualification/lab/guest/smoke.py"),
              vm + guest_dir + "/session_environment.py")
    if args.backend == "x11":
        incus.run("file", "push", str(ROOT / "scripts/qualification/native_receiver.c"),
                  vm + guest_dir + "/receiver.c")
        incus.run("exec", vm, "--", "sh", "-c",
                  "cc -Wall -Wextra -Werror -O2 " + guest_dir + "/receiver.c "
                  "$(pkg-config --cflags --libs gtk+-3.0) -o /usr/local/lib/odq/p35-receiver")
    # Fence is the shipped package fence; do not force it or delete an install lease.
    incus.run("exec", vm, "--", "/usr/bin/python3", guest_dir + "/computer.py",
              "--guest-exit", "--backend", args.backend, "--output", guest_dir)
    incus.run("exec", vm, "--", "dpkg", "-i", guest_dir + "/candidate.deb")
    incus.run("exec", vm, "--", "install", "-m", "755", guest_dir + "/computer.py",
              "/usr/local/lib/odq/p35-computer.py")
    incus.run("exec", vm, "--", "install", "-m", "644",
              guest_dir + "/session_environment.py", "/usr/local/lib/odq/session_environment.py")
    guest_out = "/home/odq/p35-" + uuid.uuid4().hex
    command = [*incus.prefix, "exec", vm, "--", "/usr/bin/python3",
               "/usr/local/lib/odq/p35-computer.py", "--guest-launch", "--backend", args.backend,
               "--output", guest_out]
    with (args.output / "guest.log").open("w") as log:
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True)
        for line in child.stdout:
            print(line, end="", flush=True)
            log.write(line)
        code = child.wait(timeout=600)
    incus.run("file", "pull", "--recursive", vm + guest_out, str(args.output / "guest"))
    proof = json.loads((args.output / "guest" / "result.json").read_text())
    record = {"schema": 1, "source_sha": sha, "source_dirty": dirty,
              "candidate_sha256": deb_sha, "backend": args.backend, "vm": vm,
              "candidate_source_sha": proof["candidate_source_sha"],
              "vm_configuration": lab.find(instances, vm), "command": command,
              "start_unix": started, "finish_unix": time.time(), "guest_exit_code": code,
              "cases": proof["cases"], "blockers": proof["blockers"],
              "verdict": classify(proof["cases"], proof["blockers"]),
              "reference_corpora": {p: digest(ROOT / p) for p in CORPORA[args.backend]},
              "guest_harness_sha256": digest(Path(__file__)),
              "receiver_source_sha256": digest(ROOT / "scripts/qualification/native_receiver.c"),
              "headless_regressions": CASES,
              "cleanup": "guest probe owns its receiver and controller; caller must stop its VM"}
    record["artifacts"] = {str(p.relative_to(args.output)): digest(p)
                           for p in sorted(args.output.rglob("*")) if p.is_file()}
    (args.output / "qualification.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"backend": args.backend, "verdict": record["verdict"],
                      "blockers": record["blockers"]}), flush=True)
    return 0 if record["verdict"] == "proven" else 2


def guest_launch(args):
    if (os.getuid() != 0 or socket.gethostname() != GUESTS[args.backend]
            or Path("/etc/odin-desktop-qualification").read_text().strip()
            != "odin-desktop-qualification-v1"):
        raise ValueError("owned_vm_root_launcher_required")
    # Reuse the retained lab environment discovery with a credential allowlist.
    source = Path(__file__).with_name("session_environment.py")
    spec = importlib.util.spec_from_file_location("guest_environment", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    account = pwd.getpwnam("odq")
    environment = module.session_environment(account.pw_uid,
        "x11" if args.backend == "x11" else "wayland")
    if args.guest_exit:
        command = ["/usr/bin/odin-desktop", "--exit"]
    else:
        command = [str(PYTHON), "-I", "-B", str(Path(__file__).resolve()), "--guest",
                   "--backend", args.backend, "--output", str(args.output)]
    return subprocess.call(["runuser", "-u", "odq", "--", "env", "-i",
                            *(f"{key}={value}" for key, value in environment.items()), *command])


def guest_guard(backend):
    # This guard is never a substitute for host-side Incus ownership validation.
    if (socket.gethostname() != GUESTS[backend] or os.getuid() == 0
            or Path("/opt/odin").exists() or not PYTHON.is_file()
            or Path("/etc/odin-desktop-qualification").read_text().strip()
            != "odin-desktop-qualification-v1"):
        raise ValueError("owned_vm_candidate_required")


async def guest_probe(args):
    guest_guard(args.backend)
    from src.computer.controller import ComputerController
    from src.computer.models import RequestContext
    from src.computer.store import ComputerStore

    out = args.output
    out.mkdir(mode=0o700, parents=False, exist_ok=False)
    cases, blockers = [], []
    versions = subprocess.run(
        ["dpkg-query", "-W", "-f=${Package}\t${Version}\n", "odin-desktop",
         "gnome-shell", "mutter", "kwin-wayland", "hyprland", "cinnamon",
         "xserver-xorg-core"], text=True, capture_output=True).stdout
    (out / "versions.tsv").write_text(versions)
    metadata = json.loads((RESOURCES / "runtime/helpers/metadata.json").read_text())
    installed = {"python": sys.executable,
                 "controller": sys.modules[ComputerController.__module__].__file__,
                 "helper_metadata": metadata, "session_type": os.environ.get("XDG_SESSION_TYPE")}
    if not installed["controller"].startswith(str(RESOURCES)):
        raise ValueError("candidate_import_required")
    from src.computer.runtime.assets.wayland_probe_private import device_equal
    from src.computer.runtime.wayland_probe import _ASSETS
    installed["asset_discovery"] = str(_ASSETS)
    installed["private_probe_loaded"] = callable(device_equal)
    installed["helper_usage_refusals"] = {}
    for name in ("odin-computer-wayland-input", "odin-hyprland-input", "odin-hyprland-capture"):
        binary = RESOURCES / "runtime/helpers/bin" / name
        probe = subprocess.run([str(binary)], stdin=subprocess.DEVNULL, capture_output=True,
            timeout=5, env={"PATH": "/usr/bin:/bin", "HOME": str(out), "LANG": "C.UTF-8"})
        installed["helper_usage_refusals"][name] = {
            "sha256": digest(binary), "exit_code": probe.returncode,
            "stdout": probe.stdout.decode(errors="replace"),
            "stderr": probe.stderr.decode(errors="replace")}
        if probe.returncode == 0:
            blockers.append("native_helper_did_not_refuse_missing_configuration:" + name)
    cases.append({"case": "helper_discovery", "passed": str(_ASSETS).startswith(str(RESOURCES)),
                  "evidence_kind": "candidate_discovery"})
    (out / "installed.json").write_text(json.dumps(installed, indent=2))
    if args.backend != "x11":
        if args.backend == "hyprland":
            plugin = list((RESOURCES / "runtime").rglob("odin-hyprland-scope-*.so"))
            blockers.append("candidate_has_no_exact_abi_hyprland_scope_plugin" if not plugin
                            else "hyprland_same_boot_receiver_release_unqualified")
            # Exercise the installed ABI fence with a measured guest executable,
            # not a guessed version, stub IPC, loaded experiment or edited guard.
            from src.computer.runtime.hyprland_identity import (
                ExecutableTrust,
                HyprlandIdentity,
                measure_process,
            )
            from src.computer.runtime.hyprland_plugin import (
                HyprlandPluginError,
                ManagedHyprlandPlugin,
                PluginApproval,
            )
            version = json.loads(subprocess.check_output(["hyprctl", "-j", "version"], text=True))
            pids = subprocess.check_output(["pgrep", "-u", str(os.getuid()), "-x", "Hyprland"],
                                           text=True).split()
            if len(pids) != 1:
                raise ValueError("unique_guest_compositor_required")
            executable = os.readlink("/proc/" + pids[0] + "/exe")
            trust = ExecutableTrust(executable, digest(executable),
                version["version"].lstrip("v"), version["commit"])
            pin = measure_process(int(pids[0]), os.getuid(), trust, time.monotonic() + 5)
            incompatible = PluginApproval("/usr/local/lib/odin/odin-hyprland-scope-"
                + "a" * 64 + ".so", "a" * 64, "0.0.0-incompatible", "b" * 40, "c" * 64, True)
            try:
                ManagedHyprlandPlugin(approval=incompatible,
                    identity=HyprlandIdentity(pin, trust), ipc=None)
            except HyprlandPluginError as error:
                cases.append({"case": "abi_refusal",
                    "passed": str(error) == "hyprland_plugin_compositor_pin_mismatch",
                    "evidence_kind": "candidate_abi_refusal",
                    "version": version, "refusal": str(error)})
            else:
                blockers.append("incompatible_compositor_abi_was_not_rejected")
        elif args.backend == "kde":
            plugin = list((RESOURCES / "runtime").rglob("*odinscope*.so"))
            blockers.append("candidate_has_no_exact_abi_kwin_scope_plugin" if not plugin
                            else "kde_portal_input_unqualified")
            from src.computer.runtime.kwin_scope import KWinWaylandScopeProvider
            provider = KWinWaylandScopeProvider(
                bus_address=os.environ["DBUS_SESSION_BUS_ADDRESS"], expected_uid=os.getuid())
            try:
                identity = await provider.identity()
                (out / "scope-identity.json").write_text(
                    json.dumps(identity, default=str, indent=2))
            except Exception as error:
                blockers.append(str(error))
            finally:
                await provider.close()
        else:
            from src.computer.runtime.wayland_scope import GNOMEWaylandScopeProvider
            provider = GNOMEWaylandScopeProvider(
                bus_address=os.environ["DBUS_SESSION_BUS_ADDRESS"], expected_uid=os.getuid())
            try:
                identity = await provider.identity()
                (out / "scope-identity.json").write_text(
                    json.dumps(identity, default=str, indent=2))
            except Exception as error:
                blockers.append(str(error))
            finally:
                await provider.close()
        # Do not make a portal consent request when the shipping input/scope path
        # cannot qualify. A different capture utility cannot count as this adapter.
        blockers.append("native_input_cases_not_executed_no_qualified_candidate_path")
    else:
        from src.computer.runtime.x11_attached import X11AttachedBackend
        receiver_log = (out / "receiver.jsonl").open("w")
        receiver = subprocess.Popen(["/usr/local/lib/odq/p35-receiver"],
            stdin=subprocess.PIPE, stdout=receiver_log, stderr=subprocess.STDOUT)
        await asyncio.sleep(2)
        monitors = subprocess.check_output(["/usr/bin/xrandr", "--listmonitors"], text=True)
        names = [line.split()[-1] for line in monitors.splitlines()[1:]]
        backend = X11AttachedBackend(enabled=True, display_name=os.environ["DISPLAY"],
            xauthority=os.environ.get("XAUTHORITY", ""), monitor_names=names,
            input_enabled=True, runtime_sudo=False)
        store = ComputerStore(out / "state.sqlite3", out / "evidence")
        context = RequestContext("p35-lab", "owned-receiver", "native-case", "localhost")
        controller = ComputerController(
            store, lambda _: backend, lambda c: c == context, enabled=True)
        try:
            grant = await controller.session(context, {"operation": "start"})
            (out / "start.json").write_text(json.dumps(grant, indent=2))
            try:
                async def observe(name):
                    from src.computer.vision import observation_image
                    current = store.get_session(grant["session_id"])
                    view = await controller.observe(context, {"session_id": current.session_id,
                                                             "generation": current.generation})
                    obs = controller._live[current.session_id].observations[view["observation_id"]]
                    observation_image(view["image_bytes"], obs.frame_metadata)
                    await controller.validate_observation_delivery(
                        context, obs.frame_metadata, obs.image_sha256)
                    (out / (name + ".png")).write_bytes(view.pop("image_bytes"))
                    (out / (name + ".json")).write_text(json.dumps(view, default=str, indent=2))
                    return obs

                def payload(obs, operation, **fields):
                    return {"session_id": obs.session_id, "generation": obs.generation,
                            "consent_generation": obs.source.consent_generation,
                            "source_id": obs.source.source_id,
                            "source_revision": obs.source.source_revision,
                            "observation_id": obs.observation_id, "action_id": uuid.uuid4().hex,
                            "operation": operation, "expect": {"type": "visual_change"}, **fields}

                async def act(name, operation, **fields):
                    obs = await observe(name + "-before")
                    result = await controller.act(context, payload(obs, operation, **fields))
                    (out / (name + "-receipt.json")).write_text(
                        json.dumps(result, default=str, indent=2))
                    if result.get("execution", {}).get("released") is not True:
                        raise RuntimeError("unknown_release_stop_all_input")
                    await asyncio.sleep(.15)
                    return result

                def receiver_rows():
                    receiver_log.flush()
                    lines = (out / "receiver.jsonl").read_text().splitlines()
                    return [json.loads(line) for line in lines
                            if line.startswith("{")]

                def measured(name, passed, detail):
                    cases.append({"case": name, "passed": bool(passed),
                                  "evidence_kind": "receiver_platform", "detail": detail})

                obs = await observe("initial")
                scope = backend._scope
                if (not scope or scope["process"]["pid"] != receiver.pid
                        or not obs.focused or obs.modal is not None):
                    raise RuntimeError("owned_safe_receiver_not_grounded")
                measured("target_capture", True, {"scope": scope,
                    "receiver_pid": receiver.pid, "capture_sha256": obs.image_sha256})
                # Replaced delivery and generation are rejected before any native write.
                old = payload(obs, "type", text="Stale")
                await observe("replacement")
                for name, request in [("stale_observation", old),
                                      ("stale_generation", {**old, "generation": 0})]:
                    before = receiver_rows()
                    try:
                        await controller.act(context, request)
                    except Exception as error:
                        measured(name, receiver_rows() == before, str(error))
                    else:
                        raise RuntimeError(name + "_accepted")
                await act("text", "type", text="P35safe")
                rows = receiver_rows()
                measured("text", receiver_effect(rows, "text"), rows[-8:])
                await act("key", "key", key="BackSpace")
                rows = receiver_rows()
                measured("key", receiver_effect(rows, "key"), rows[-8:])
                # Every point is translated from fresh captured source geometry.
                obs = await observe("stroke-grounding")
                scope = backend._scope
                x, y, width, height = scope["window_rect"]
                origin = scope["source_origin"]
                sx, sy = obs.width / obs.source.pixel_width, obs.height / obs.source.pixel_height
                points = [[int((x - origin[0] + dx) * sx),
                           int((y - origin[1] + height // 2 + dy) * sy)]
                          for dx, dy in [(100, 0), (180, 20), (260, 0), (340, 20)]]
                result = await controller.act(context, payload(obs, "polyline", points=points,
                                                               duration=.6))
                (out / "stroke-receipt.json").write_text(json.dumps(result, default=str, indent=2))
                if result.get("execution", {}).get("released") is not True:
                    raise RuntimeError("unknown_release_stop_all_input")
                await asyncio.sleep(.2)
                rows = receiver_rows()
                measured("stroke", receiver_effect(rows, "stroke"), rows[-12:])
                obs = await observe("geometry-before")
                before_scope = backend._scope.copy()
                stale = payload(obs, "type", text="NoReplay")
                receiver.stdin.write(b"G")
                receiver.stdin.flush()
                await asyncio.sleep(.5)
                try:
                    result = await controller.act(context, stale)
                    if result.get("execution", {}).get("injected") is not False:
                        raise RuntimeError("geometry_change_did_not_fence_old_binding")
                except ValueError:
                    pass
                obs = await observe("geometry-after")
                geometry_ok = (backend._scope["window_rect"] != before_scope["window_rect"]
                    and backend._scope["process"] == before_scope["process"])
                scope = backend._scope
                x, y, width, height = scope["window_rect"]
                origin = scope["source_origin"]
                sx, sy = obs.width / obs.source.pixel_width, obs.height / obs.source.pixel_height
                click = payload(obs, "click", x=int((x - origin[0] + width // 2) * sx),
                    y=int((y - origin[1] + height - 18) * sy))
                result = await controller.act(context, click)
                (out / "modal-open-receipt.json").write_text(
                    json.dumps(result, default=str, indent=2))
                if result.get("execution", {}).get("released") is not True:
                    raise RuntimeError("unknown_release_stop_all_input")
                obs = await observe("modal-after")
                modal_ok = bool(obs.modal) and obs.modal_kind == "safe_application"
                if modal_ok:
                    result = await controller.act(context, payload(obs, "key", key="Return",
                        expected_modal=obs.modal))
                    (out / "modal-close-receipt.json").write_text(
                        json.dumps(result, default=str, indent=2))
                    if result.get("execution", {}).get("released") is not True:
                        raise RuntimeError("unknown_release_stop_all_input")
                    await asyncio.sleep(.15)
                rows = receiver_rows()
                measured("focus_geometry_modal", geometry_ok and modal_ok
                    and any(r.get("event") == "modal_opened" for r in rows)
                    and any(r.get("event") == "modal_closed" for r in rows), rows[-12:])
                current = store.get_session(grant["session_id"])
                paused = await controller.session(context, {"operation": "pause",
                    "session_id": current.session_id, "generation": current.generation})
                (out / "pause.json").write_text(json.dumps(paused, default=str, indent=2))
                measured("pause", receiver.poll() is None and not backend._children,
                         {"receiver_alive": receiver.poll() is None,
                          "worker_count": len(backend._children)})
                current = store.get_session(grant["session_id"])
                cancelled = await controller.session(context, {"operation": "cancel",
                    "session_id": current.session_id, "generation": current.generation})
                (out / "cancel.json").write_text(json.dumps(cancelled, default=str, indent=2))
                measured("cancel", receiver.poll() is None and not backend._children,
                         {"receiver_alive": receiver.poll() is None,
                          "worker_count": len(backend._children)})
                # New explicit guest consent after clean cancellation. Deliberate
                # sole-guardian loss is confined to this owned receiver/guest.
                await controller.close()
                backend = X11AttachedBackend(enabled=True, display_name=os.environ["DISPLAY"],
                    xauthority=os.environ.get("XAUTHORITY", ""), monitor_names=names,
                    input_enabled=True, runtime_sudo=False)
                controller = ComputerController(
                    store, lambda _: backend, lambda c: c == context, enabled=True)
                grant = await controller.session(context, {"operation": "start"})
                obs = await observe("loss-before")
                scope = backend._scope
                x, y, width, height = scope["window_rect"]
                origin = scope["source_origin"]
                sx, sy = obs.width / obs.source.pixel_width, obs.height / obs.source.pixel_height
                points = [[int((x - origin[0] + dx) * sx),
                           int((y - origin[1] + height // 2 + dy) * sy)]
                          for dx, dy in [(100, 0), (180, 20), (260, 0), (340, 20)]]
                baseline = sum(r.get("event") == "button_down" for r in receiver_rows())
                request = payload(obs, "polyline", points=points, duration=1)
                task = asyncio.create_task(controller.act(context, request))
                until = time.monotonic() + 4
                killed = None
                while not task.done() and time.monotonic() < until:
                    if (sum(r.get("event") == "button_down" for r in receiver_rows()) > baseline
                            and len(backend._guardians) == 1):
                        guardian = next(iter(backend._guardians))
                        # Popen handle is exact child ownership. Never pgrep kill.
                        killed = guardian.pid
                        guardian.send_signal(signal.SIGKILL)
                        break
                    await asyncio.sleep(.005)
                try:
                    loss = await task
                except Exception as error:
                    loss = {"exception": type(error).__name__, "reason": str(error)}
                (out / "guardian-loss.json").write_text(json.dumps({
                    "owned_guardian_pid": killed, "receipt": loss,
                    "receiver": receiver_rows()[-20:]}, default=str, indent=2))
                current = store.get_session(grant["session_id"])
                measured("guardian_loss", killed is not None and current.state == "quarantined",
                         {"state": current.state, "killed_owned_child": killed,
                          "release_is_unknown": True})
                if killed is None or current.state != "quarantined":
                    raise RuntimeError("guardian_loss_corpus_not_established_stop_input")
                # Unknown release means no further input or replacement. Close,
                # reopen the durable store and assert the fence and no replay.
                sid = current.session_id
                await controller.close()
                store.close()
                store = ComputerStore(out / "state.sqlite3", out / "evidence")
                controller = ComputerController(store, lambda _: backend,
                    lambda c: c == context, enabled=True)
                before = receiver_rows()
                refused = []
                for operation in ("replay", "replacement"):
                    if store.get_session(sid).state != "quarantined":
                        raise RuntimeError("durable_quarantine_missing_stop_input")
                    try:
                        if operation == "replay":
                            await controller.act(context, request)
                        else:
                            await controller.session(context, {"operation": "start"})
                    except Exception as error:
                        refused.append({"operation": operation, "refusal": str(error)})
                persisted = store.get_session(sid)
                measured("restart_quarantine", len(refused) == 2
                    and persisted.state == "quarantined" and receiver_rows() == before,
                    {"state": persisted.state, "refusals": refused,
                     "scope": "controller/store reconstruction, not Electron/core process"})
                blockers.extend(["native_controller_loss_and_app_exit_not_yet_measured",
                    "app_core_process_restart_quarantine_not_measured",
                    "shared_x11_abrupt_sole_guardian_loss_has_no_universal_release_guarantee"])
            except Exception as error:
                blockers.append(str(error))
        except Exception as error:
            blockers.append(type(error).__name__ + ":" + str(error))
        finally:
            await controller.close()
            store.close()
            receiver.stdin.close()
            receiver.wait(timeout=5)
            receiver_log.close()
    proof = {"cases": cases, "blockers": blockers, "verdict": classify(cases, blockers),
             "candidate_source_sha": metadata["desktop_source_commit"],
             "cleanup": "controller close completed; no replacement or replay attempted"}
    (out / "result.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(proof), flush=True)
    return 2 if blockers else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=GUESTS, required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--guest", action="store_true")
    parser.add_argument("--guest-launch", action="store_true")
    parser.add_argument("--guest-exit", action="store_true")
    args = parser.parse_args()
    if args.guest:
        return asyncio.run(guest_probe(args))
    if args.guest_launch or args.guest_exit:
        return guest_launch(args)
    if args.candidate is None:
        parser.error("--candidate is required for host execution")
    return run_host(args)


if __name__ == "__main__":
    raise SystemExit(main())
