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
                             "tests/test_computer_r23_wayland_native_scope.py",
                             "tests/test_computer_hyprland_dialog_scope_r35.py"],
    "actions": ["tests/test_computer_actions_r4.py",
                "tests/test_computer_native_keyboard_focus_class.py"],
    "loss_recovery": ["tests/test_computer_cleanup_r7.py",
                      "tests/test_computer_hyprland_durable_fence_r42.py"],
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
    if args.backend == "x11":
        incus.run("file", "push", str(ROOT / "scripts/qualification/native_receiver.c"),
                  vm + guest_dir + "/receiver.c")
        incus.run("exec", vm, "--", "sh", "-c",
                  "cc -Wall -Wextra -Werror -O2 " + guest_dir + "/receiver.c "
                  "$(pkg-config --cflags --libs gtk+-3.0) -o /usr/local/lib/odq/p35-receiver")
    # Fence is the shipped package fence; do not force it or delete an install lease.
    incus.run("exec", vm, "--", "/root/odq/sessrun", "/usr/bin/odin-desktop", "--exit")
    incus.run("exec", vm, "--", "dpkg", "-i", guest_dir + "/candidate.deb")
    incus.run("exec", vm, "--", "install", "-m", "755", guest_dir + "/computer.py",
              "/usr/local/lib/odq/p35-computer.py")
    guest_out = "/home/odq/p35-" + uuid.uuid4().hex
    command = [*incus.prefix, "exec", vm, "--", "/root/odq/sessrun", str(PYTHON), "-I", "-B",
               "/usr/local/lib/odq/p35-computer.py", "--guest", "--backend", args.backend,
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
              "vm_configuration": lab.find(instances, vm), "command": command,
              "start_unix": started, "finish_unix": time.time(), "guest_exit_code": code,
              "cases": proof["cases"], "blockers": proof["blockers"],
              "verdict": classify(proof["cases"], proof["blockers"]),
              "reference_corpora": {p: digest(ROOT / p) for p in CORPORA[args.backend]},
              "headless_regressions": CASES,
              "cleanup": "guest probe owns its receiver and controller; caller must stop its VM"}
    record["artifacts"] = {str(p.relative_to(args.output)): digest(p)
                           for p in sorted(args.output.rglob("*")) if p.is_file()}
    (args.output / "qualification.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"backend": args.backend, "verdict": record["verdict"],
                      "blockers": record["blockers"]}), flush=True)
    return 0 if record["verdict"] == "proven" else 2


def guest_guard(backend):
    # This guard is never a substitute for host-side Incus ownership validation.
    if (socket.gethostname() != GUESTS[backend] or os.getuid() == 0
            or Path("/opt/odin").exists() or not PYTHON.is_file()
            or not Path("/dev/disk/by-id/virtio-incus_root").exists()):
        raise ValueError("owned_vm_candidate_required")


async def guest_probe(args):
    guest_guard(args.backend)
    from src.computer.controller import ComputerController
    from src.computer.models import RequestContext
    from src.computer.store import ComputerStore

    out = args.output
    out.mkdir(mode=0o700, parents=False, exist_ok=False)
    cases, blockers = [], []
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
    cases.append({"case": "helper_discovery", "passed": str(_ASSETS).startswith(str(RESOURCES)),
                  "evidence_kind": "candidate_discovery"})
    (out / "installed.json").write_text(json.dumps(installed, indent=2))
    if args.backend != "x11":
        if args.backend == "hyprland":
            plugin = list((RESOURCES / "runtime").rglob("odin-hyprland-scope-*.so"))
            blockers.append("candidate_has_no_exact_abi_hyprland_scope_plugin" if not plugin
                            else "hyprland_same_boot_receiver_release_unqualified")
        elif args.backend == "kde":
            plugin = list((RESOURCES / "runtime").rglob("*odinscope*.so"))
            blockers.append("candidate_has_no_exact_abi_kwin_scope_plugin" if not plugin
                            else "kde_portal_input_unqualified")
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
            blockers.append("safe_receiver_action_corpus_pending")
            try:
                view = await controller.observe(context, {"session_id": grant["session_id"],
                                                         "generation": grant["generation"]})
                (out / "capture.png").write_bytes(view["image_bytes"])
                view.pop("image_bytes")
                (out / "observation.json").write_text(json.dumps(view, default=str, indent=2))
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
    args = parser.parse_args()
    if args.guest:
        return asyncio.run(guest_probe(args))
    if args.candidate is None:
        parser.error("--candidate is required for host execution")
    return run_host(args)


if __name__ == "__main__":
    raise SystemExit(main())
