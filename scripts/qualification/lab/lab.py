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
POOL_BUDGET = 150 * GIB
FILESYSTEM_FLOOR = 50 * GIB
# Decision H: at most two lab VMs run at once. A running VM outside the lab
# still blocks every lab operation.
MAX_RUNNING_VMS = 2
LOCK_PATH = "/tmp/odin-desktop-qualification.lock"
# With two VMs, lab commands from two lanes overlap; wait for the other command
# instead of failing, but never longer than this.
LOCK_WAIT_SECONDS = 900


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


def _allocated(path):
    """Allocated bytes under one lab path. Failed or partial du is a failed
    preflight, never zero usage."""
    result = subprocess.run(
        ["sudo", "-n", "du", "-s", "-B1", "--", str(path)],
        check=False, text=True, capture_output=True, timeout=60, stdin=subprocess.DEVNULL,
    )
    if result.returncode:
        raise LabError(f"Cannot measure allocated lab pool usage: {result.stderr}")
    try:
        used = int(result.stdout.split()[0])
    except (IndexError, ValueError) as exc:
        raise LabError("Invalid allocated lab pool usage from du") from exc
    if used < 0:
        raise LabError("Invalid negative storage accounting")
    return used


def storage_usage():
    """Measure allocated pool bytes including images/snapshots, not logical caps.

    Dir resources report the backing filesystem, not the lab budget. Thin disks
    need backing space even though they have no reservation.
    """
    if (POOL_SOURCE.resolve() != POOL_SOURCE or not POOL_SOURCE.is_dir()
            or POOL_SOURCE.stat().st_dev != STORAGE_PATH.stat().st_dev):
        raise LabError("Lab dir pool must be a real directory on /mnt/storage")
    used = _allocated(POOL_SOURCE)
    filesystem = os.statvfs(STORAGE_PATH)
    free = filesystem.f_bavail * filesystem.f_frsize
    if free < 0:
        raise LabError("Invalid negative storage accounting")
    return used, free


def guest_usage(name):
    """Allocated bytes of one owned guest's directory in the lab pool.

    The name is an owned lab name, never caller text. A missing or unreadable
    directory fails the preflight. du does not follow a symlinked argument, so a
    replaced directory can only read low, which reserves more growth, not less.
    """
    if name not in NAMES:
        raise LabError("Unknown lab VM name")
    return _allocated(POOL_SOURCE / "virtual-machines" / name)


def growth_reserve(name):
    """Room one guest can still take: up to its 40 GiB cap, plus overhead."""
    return max(0, DISK - guest_usage(name)) + RESERVE


def running_reserve(instances, skip=()):
    """Reserve the remaining growth of every running lab VM.

    Fail closed on any other running storage consumer whose growth has no known
    cap: a VM outside the lab, or a container whose root is in the lab pool.
    Callers measure this before the pool and filesystem, so a guest growing in
    between is over-reserved, never under-reserved.
    """
    reserved = {}
    for item in instances:
        if item.get("status") == "Stopped" or item["name"] in skip:
            continue
        if item.get("type") == "virtual-machine":
            if item["name"] not in NAMES:
                raise LabError(f"A VM outside the lab is not stopped: {item['name']}")
            owned(item)  # the 40 GiB cap is validated, never assumed
            reserved[item["name"]] = growth_reserve(item["name"])
        elif item.get("expanded_devices", {}).get("root", {}).get("pool") == POOL:
            raise LabError(
                f"Container {item['name']} in the lab pool is not stopped; "
                "its growth has no reservation"
            )
    return reserved


def preflight(api, *, creating=False, name=None):
    # Retain creating for caller compatibility. Without a running guest name,
    # an operation reserves one full guest growth budget (create, snapshot copy).
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
    others = [item["name"] for item in instances
              if item.get("type") == "virtual-machine" and item.get("status") != "Stopped"
              and item["name"] != name]
    if len(others) >= MAX_RUNNING_VMS:
        raise LabError(
            f"{len(others)} other VMs are not stopped ({', '.join(others)}); "
            f"at most {MAX_RUNNING_VMS} VMs run at once"
        )
    # Reserve growth for every lab guest that may run during this operation:
    # the other running guests and this one, each up to its 40 GiB cap plus
    # overhead. Their current allocation is already in the measured pool usage.
    # Stopped guests cannot grow, and every operation that adds data runs this
    # preflight first. Optional snapshots get no exemption.
    reserved = running_reserve(instances, skip=(name,))
    if name is not None and find(instances, name):
        reserved[name] = growth_reserve(name)
    else:
        reserved["new"] = DISK + RESERVE
    required = sum(reserved.values())
    resources = api.query(f"/1.0/storage-pools/{POOL}/resources")
    space = resources["space"]
    available = int(space["total"]) - int(space["used"])
    if available < required:
        raise LabError(
            f"Lab pool needs {required / GIB:.1f} GiB available for guest growth "
            f"(each thin 40 GiB disk to its cap plus 10 GiB reserve: "
            f"{', '.join(reserved)}); has {available / GIB:.1f} GiB."
        )
    used, filesystem_free = storage_usage()
    if used + required > POOL_BUDGET:
        raise LabError(
            f"Lab pool allocated usage {used / GIB:.1f} GiB plus {required / GIB:.1f} GiB "
            f"growth/reserve exceeds the {POOL_BUDGET // GIB} GiB aggregate budget. "
            "Rebuild/remove owned guests instead of retaining optional snapshots."
        )
    # Keep the floor after the reserved growth of the guests that may run.
    filesystem_required = FILESYSTEM_FLOOR + required
    if filesystem_free < filesystem_required:
        raise LabError(
            f"/mnt/storage has {filesystem_free / GIB:.1f} GiB free; needs "
            f"{filesystem_required / GIB:.1f} GiB to preserve the 50 GiB filesystem "
            "floor after the running guests' growth."
        )
    host = api.query("/1.0/resources")
    memory = host["memory"]
    # Incus reports host usable headroom (cache excluded in used), not raw
    # MemFree. Keep the 12 GiB gate for one 8 GiB guest before every operation,
    # including a second guest's start.
    if int(memory["total"]) - int(memory["used"]) < 12 * GIB:
        raise LabError("Less than 12 GiB host memory headroom; refusing VM operation")
    return {"pool": POOL, "available_bytes": available, "required_bytes": required,
            "reserved_bytes": reserved, "allocated_bytes": used, "budget_bytes": POOL_BUDGET,
            "filesystem_free_bytes": filesystem_free,
            "filesystem_required_bytes": filesystem_required,
            "filesystem_floor_bytes": FILESYSTEM_FLOOR,
            "max_running_vms": MAX_RUNNING_VMS, "instances": instances}


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
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise LabError(
                        f"Another lab command is active after {LOCK_WAIT_SECONDS}s"
                    ) from exc
                time.sleep(2)
        yield
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
