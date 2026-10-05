#!/usr/bin/env python3
"""Manage only the four owned Incus VMs. No pool repair or host configuration."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
NAMES = ("odq-cinnamon", "odq-gnome", "odq-kde", "odq-hyprland")
MARKER = "odin-desktop-qualification-v1"
GIB = 1024**3
DISK = 40 * GIB
RESERVE = 10 * GIB
POOL = "odq-lab"
POOL_SOURCE = Path("/mnt/storage/odq-lab")
STORAGE_PATH = Path("/mnt/storage")
POOL_BUDGET = 100 * GIB
FILESYSTEM_FLOOR = 50 * GIB
LOCK_PATH = "/tmp/odin-desktop-qualification.lock"


class LabError(RuntimeError):
    """A failed precondition, not permission to repair the host."""


class Incus:
    def __init__(self):
        # Always the local default project, even if the caller changed remotes.
        self.prefix = ["sudo", "-n", "incus", "--force-local", "--project", "default"]

    def run(self, *args, capture=False, timeout=600):
        result = subprocess.run(
            [*self.prefix, *args], check=False, text=True,
            capture_output=capture, timeout=timeout, stdin=subprocess.DEVNULL,
        )
        if result.returncode:
            detail = result.stderr or result.stdout or result.returncode
            raise LabError(f"Incus {' '.join(args)} failed: {detail}")
        return result.stdout

    def query(self, path, *, timeout=60):
        # Raw queries reject --project. Qualify the API URL instead.
        separator = "&" if "?" in path else "?"
        result = subprocess.run(
            ["sudo", "-n", "incus", "--force-local", "query",
             f"{path}{separator}project=default"],
            check=False, text=True, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
        )
        if result.returncode:
            raise LabError(f"Incus query {path} failed: {result.stderr}")
        return json.loads(result.stdout)

    def instances(self):
        return json.loads(self.run("list", "--format=json", capture=True))


def image_spec(name):
    data = json.loads((HERE / "images" / f"{name[4:]}.json").read_text())
    if (not re.fullmatch(r"[0-9a-f]{64}", data.get("fingerprint", ""))
            or data.get("type") != "virtual-machine"
            or data.get("architecture") not in ("amd64", "x86_64")
            or data.get("remote") != "images"):
        raise LabError(f"Invalid pinned VM image for {name}")
    return data


def owned(instance):
    if (not instance or instance.get("name") not in NAMES
            or instance.get("type") != "virtual-machine"
            or instance.get("config", {}).get("user.odq.owner") != MARKER):
        raise LabError("Refusing a non-lab or unmarked instance")
    devices = instance.get("expanded_devices", {})
    config = instance.get("expanded_config", {})
    if (instance.get("profiles") or set(devices) != {"root", "eth0"}
            or devices["root"] != {
                "type": "disk", "path": "/", "pool": POOL, "size": "40GiB",
            }
            or devices["eth0"] != {
                "type": "nic", "network": "incusbr0", "name": "eth0",
            }
            or config.get("limits.cpu") != "4"
            or config.get("limits.memory") != "8GiB"
            or config.get("boot.autostart") != "false"
            or any(key.startswith(("raw.", "security.")) for key in config)):
        raise LabError("Lab caps/devices/isolation have changed; refusing operation")
    return instance


def find(instances, name):
    return next((item for item in instances if item["name"] == name), None)


def storage_usage():
    """Measure allocated pool bytes including images/snapshots, not logical caps.

    Dir resources report the backing filesystem, not the lab budget. Failed or
    partial du is a failed preflight, never zero usage. Thin disks need backing
    space even though they have no reservation.
    """
    if (POOL_SOURCE.resolve() != POOL_SOURCE or not POOL_SOURCE.is_dir()
            or POOL_SOURCE.stat().st_dev != STORAGE_PATH.stat().st_dev):
        raise LabError("Lab dir pool must be a real directory on /mnt/storage")
    result = subprocess.run(
        ["sudo", "-n", "du", "-s", "-B1", "--", str(POOL_SOURCE)],
        check=False, text=True, capture_output=True, timeout=60, stdin=subprocess.DEVNULL,
    )
    if result.returncode:
        raise LabError(f"Cannot measure allocated lab pool usage: {result.stderr}")
    try:
        used = int(result.stdout.split()[0])
    except (IndexError, ValueError) as exc:
        raise LabError("Invalid allocated lab pool usage from du") from exc
    filesystem = os.statvfs(STORAGE_PATH)
    free = filesystem.f_bavail * filesystem.f_frsize
    if used < 0 or free < 0:
        raise LabError("Invalid negative storage accounting")
    return used, free


def preflight(api, *, creating=False, name=None):
    # Retain creating for caller compatibility. Thin policy reserves one guest
    # growth budget for every consuming operation, regardless of missing VMs.
    pool = api.query(f"/1.0/storage-pools/{POOL}")
    if (pool.get("status") != "Created" or pool.get("driver") != "dir"
            or pool.get("config", {}).get("source") != str(POOL_SOURCE)):
        raise LabError(
            "odq-lab dir pool at /mnt/storage/odq-lab is required. Operator must "
            "create it externally; this tool never imports, repairs, resizes or "
            "replaces storage, and never accesses the old default pool."
        )
    network = api.query("/1.0/networks/incusbr0")
    network_config = network.get("config", {})
    if (network.get("type") != "bridge" or not network.get("managed")
            or network_config.get("ipv4.nat") != "true"):
        raise LabError("Existing incusbr0 managed NAT bridge is required")
    instances = api.instances()
    for item in instances:
        if item["name"] in NAMES:
            owned(item)
        # Treat Starting, Frozen and Error as occupied, not only Running.
        if item.get("type") == "virtual-machine" and item.get("status") != "Stopped":
            if item["name"] != name:
                raise LabError(f"Another VM is not stopped: {item['name']}")
    resources = api.query(f"/1.0/storage-pools/{POOL}/resources")
    space = resources["space"]
    available = int(space["total"]) - int(space["used"])
    # One heavy guest: reserve one full disk's growth plus image/metadata/COW
    # overhead, not four logical caps. Optional snapshots get no exemption.
    required = DISK + RESERVE
    if available < required:
        raise LabError(
            f"Lab pool needs {required / GIB:.1f} GiB available for one thin "
            f"40 GiB disk plus 10 GiB reserve; has {available / GIB:.1f} GiB."
        )
    used, filesystem_free = storage_usage()
    if used + required > POOL_BUDGET:
        raise LabError(
            f"Lab pool allocated usage {used / GIB:.1f} GiB plus 50 GiB growth/"
            "reserve exceeds the 100 GiB aggregate budget. Rebuild/remove owned "
            "guests instead of retaining optional snapshots."
        )
    # Preserve the floor even if ALL remaining budget is allocated, not merely
    # if this particular guest stays within its logical cap.
    filesystem_required = FILESYSTEM_FLOOR + POOL_BUDGET - used
    if filesystem_free < filesystem_required:
        raise LabError(
            f"/mnt/storage has {filesystem_free / GIB:.1f} GiB free; needs "
            f"{filesystem_required / GIB:.1f} GiB to preserve the 50 GiB filesystem "
            "floor after all remaining pool growth."
        )
    host = api.query("/1.0/resources")
    memory = host["memory"]
    # Incus reports host usable headroom (cache excluded in used), not raw
    # MemFree. Keep the original 12 GiB safety gate for a single 8 GiB guest.
    if int(memory["total"]) - int(memory["used"]) < 12 * GIB:
        raise LabError("Less than 12 GiB host memory headroom; refusing VM operation")
    return {"pool": POOL, "available_bytes": available, "required_bytes": required,
            "allocated_bytes": used, "budget_bytes": POOL_BUDGET,
            "filesystem_free_bytes": filesystem_free,
            "filesystem_required_bytes": filesystem_required,
            "filesystem_floor_bytes": FILESYSTEM_FLOOR, "instances": instances}


def require_stopped(instance):
    if instance["status"] != "Stopped":
        raise LabError("Stop the owned guest gracefully before this operation")


def wait_agent(api, name, timeout=300):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            api.run("exec", name, "--", "/bin/true", capture=True, timeout=10)
            return
        except (LabError, subprocess.TimeoutExpired):
            time.sleep(3)
    raise LabError(f"Guest agent unavailable after {timeout}s; no forced stop/replay")


def create(api, name):
    if name not in NAMES:
        raise LabError("Unknown lab VM name")
    check = preflight(api, creating=True)
    if find(check["instances"], name):
        raise LabError("Instance already exists; no replacement or implicit reprovision")
    spec = image_spec(name)
    api.run(
        "init", f"images:{spec['fingerprint']}", name, "--vm", "--no-profiles",
        "--storage", POOL, "--network", "incusbr0",
        "--device", "root,size=40GiB",
        "--config", "limits.cpu=4", "--config", "limits.memory=8GiB",
        "--config", "boot.autostart=false", "--config", f"user.odq.owner={MARKER}",
        "--config", f"user.odq.image={spec['fingerprint']}",
    )
    owned(find(api.instances(), name))


def start(api, name):
    check = preflight(api, name=name)
    instance = find(check["instances"], name)
    if not instance:
        raise LabError("Create the guest first")
    require_stopped(owned(instance))
    api.run("start", name)
    wait_agent(api, name)


def stop(api, name):
    instance = find(api.instances(), name)
    if not instance:
        raise LabError("Guest does not exist")
    owned(instance)
    if instance["status"] == "Stopped":
        return
    # Incus stop sends an ACPI power key, which Cinnamon can turn into suspend.
    # Request poweroff once through the agent. A lost acknowledgement is not
    # permission to replay the request or fall back to ACPI/forced shutdown.
    try:
        api.run("exec", name, "--", "systemctl", "poweroff", "--no-block",
                capture=True, timeout=10)
    except (LabError, subprocess.TimeoutExpired) as exc:
        raise LabError(
            f"Guest agent poweroff failed or outcome unknown: {exc}; "
            "no forced stop/replay"
        ) from exc
    deadline = time.monotonic() + 180
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            # Static instance metadata includes status and ownership/caps. Avoid
            # recursive list/state collection against a shutting-down agent.
            instance = owned(api.query(f"/1.0/instances/{name}", timeout=min(10, remaining)))
        except (LabError, subprocess.TimeoutExpired) as exc:
            raise LabError(
                f"Cannot confirm guest poweroff: {exc}; no forced stop/replay"
            ) from exc
        if instance["status"] == "Stopped":
            return
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    raise LabError("Guest did not reach Stopped after 180s; no forced stop/replay")


def provision(api, name):
    check = preflight(api, name=name)
    instance = find(check["instances"], name)
    if not instance or owned(instance)["status"] != "Running":
        raise LabError("Start the guest before provisioning")
    wait_agent(api, name)
    api.run("exec", name, "--", "hostnamectl", "set-hostname", name)
    for source in (HERE / "guest/common.sh", HERE / "guest/smoke.py",
                   HERE / f"guest/{name[4:]}.sh"):
        api.run("file", "push", str(source), f"{name}/root/odq/{source.name}",
                "--create-dirs", "--mode", "0700")
    api.run("exec", name, "--", "bash", f"/root/odq/{name[4:]}.sh", timeout=3600)
    api.run("exec", name, "--", "bash", "-c",
            "source /root/odq/common.sh; odq_finalize", timeout=120)
    # Stop instead of a reboot, so a changed guest never silently retains input.
    stop(api, name)


def snapshot(api, name, label):
    require_stopped(owned(find(api.instances(), name)))
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", label):
        raise LabError("Snapshot label must be a simple local label")
    preflight(api)
    api.run("snapshot", "create", name, label)


def remove(api, name):
    require_stopped(owned(find(api.instances(), name)))
    api.run("delete", name)  # Never --force, --all or a user-supplied instance name.


def smoke_provenance(api, name):
    """Identify working-tree bytes and actual uploaded/generated guest bytes.

    HEAD is only the base commit. Dirty trees are supported, but an uploaded
    recipe differing from the inspected host bytes cannot be passing proof.
    Capture is generated, so its digest is evidence, not a host equality claim.
    """
    sources = [HERE / "lab.py", HERE / "guest/common.sh", HERE / "guest/smoke.py",
               HERE / f"guest/{name[4:]}.sh", HERE / f"images/{name[4:]}.json"]
    host = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sources}
    uploaded = {f"/root/odq/{path.name}": str(path.relative_to(ROOT))
                for path in sources[1:4]}
    capture = "/usr/local/lib/odq/capture"
    paths = [*uploaded, capture]
    output = api.run("exec", name, "--", "sha256sum", "--", *paths,
                     capture=True, timeout=30)
    guest = {}
    for line in output.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64}) [ *](/.+)", line)
        if not match or match[2] not in paths or match[2] in guest:
            raise LabError("Invalid guest sha256sum provenance output")
        guest[match[2]] = match[1]
    if set(guest) != set(paths):
        raise LabError("Incomplete guest sha256sum provenance output")
    comparison = {
        path: {"host_path": source, "matches": guest[path] == host[source]}
        for path, source in uploaded.items()
    }
    comparison[capture] = {
        "host_path": None, "matches": None,
        "reason": "Generated guest artifact; no host byte-equivalent comparison",
    }
    return {
        "source_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        ).strip(),
        "source_dirty": bool(subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=ROOT, text=True,
        ).strip()),
        "host_files_sha256": host, "guest_files_sha256": guest,
        "source_comparison": comparison,
        "source_matches": all(item["matches"] for path, item in comparison.items()
                              if path != capture),
    }


def smoke(api, name, destination):
    check = preflight(api, name=name)
    instance = find(check["instances"], name)
    if not instance or owned(instance)["status"] != "Running":
        raise LabError("Smoke requires the running owned VM")
    destination = Path(destination).resolve()
    if destination.exists():
        raise LabError("Use a new evidence directory; preserve previous proof")
    destination.mkdir(parents=True, mode=0o700)
    # Receiver/session/capture checks execute only inside the named guest.
    output = api.run("exec", name, "--", "python3", "/root/odq/smoke.py",
                     name[4:], capture=True, timeout=180)
    proof = json.loads(output)
    if proof.get("passed") is not True:
        raise LabError(f"Guest smoke did not pass: {output}")
    target = destination / "guest.png"
    # Precreate operator-owned files. The privileged Incus client otherwise
    # copies guest mode 0600 as root, making grim's proof unreadable to us.
    # This directory is new/private, and exclusive creation preserves proof.
    target.touch(mode=0o600, exist_ok=False)
    api.run("file", "pull", f"{name}/var/tmp/odq-smoke.png", str(target))
    for filename in ("packages.tsv", "listeners.txt"):
        (destination / filename).touch(mode=0o600, exist_ok=False)
        api.run("file", "pull", f"{name}/root/odq/evidence/{filename}",
                str(destination / filename))
    # A header alone is not semantic screenshot proof. Viewer inspection is required.
    data = target.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise LabError("Guest capture is not a PNG")
    proof.update({"instance": name, "image": image_spec(name),
                  "screenshot_sha256": hashlib.sha256(data).hexdigest(),
                  "visual_inspection": "required"})
    proof.update(smoke_provenance(api, name))
    if not proof["source_matches"]:
        proof["passed"] = False
        proof["error"] = "Uploaded guest scripts differ from host sources; reprovision required"
    (destination / "proof.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(proof, indent=2))
    if not proof["source_matches"]:
        raise LabError(proof["error"])


@contextmanager
def mutation_lock():
    # Shared across clones, no global host service/config installation.
    # /tmp file is non-secret orchestration scratch, not a shared guest folder.
    flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(LOCK_PATH, flags, 0o600)
    try:
        if os.fstat(fd).st_uid != os.getuid():
            raise LabError("Lab lock is not owned by this operator")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except BlockingIOError as exc:
        raise LabError("Another lab command is active") from exc
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=(
        "preflight", "create", "start", "stop", "provision", "snapshot", "remove", "smoke",
    ))
    parser.add_argument("name", nargs="?", choices=NAMES)
    parser.add_argument("--label", help="explicit optional snapshot label; rebuild by default")
    parser.add_argument("--evidence")
    args = parser.parse_args(argv)
    api = Incus()
    try:
        if args.action == "preflight":
            print(json.dumps(preflight(api, creating=True), indent=2))
            return 0
        if not args.name:
            parser.error("this action requires a VM name")
        if args.action == "smoke" and not args.evidence:
            parser.error("smoke requires --evidence with a new output directory")
        if args.action == "snapshot" and not args.label:
            parser.error("snapshots are optional; snapshot requires an explicit --label")
        with mutation_lock():
            match args.action:
                case "snapshot":
                    snapshot(api, args.name, args.label)
                case "smoke":
                    smoke(api, args.name, args.evidence)
                case _:
                    {"create": create, "start": start, "stop": stop,
                     "provision": provision, "remove": remove}[args.action](api, args.name)
        return 0
    except (LabError, subprocess.TimeoutExpired, OSError, ValueError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
