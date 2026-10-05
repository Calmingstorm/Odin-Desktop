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
RESERVE = 20 * GIB


class LabError(RuntimeError):
    """A failed precondition, not permission to repair the host."""


class Incus:
    def __init__(self):
        # Always the local default project, even if the caller changed remotes.
        self.prefix = ["sudo", "-n", "incus", "--force-local", "--project", "default"]

    def run(self, *args, capture=False, timeout=600):
        result = subprocess.run(
            [*self.prefix, *args], check=False, text=True,
            capture_output=capture, timeout=timeout,
        )
        if result.returncode:
            raise LabError(f"Incus {' '.join(args)} failed: {result.stderr or result.returncode}")
        return result.stdout

    def query(self, path):
        # Raw queries reject --project. Qualify the API URL instead.
        separator = "&" if "?" in path else "?"
        result = subprocess.run(
            ["sudo", "-n", "incus", "--force-local", "query",
             f"{path}{separator}project=default"],
            check=False, text=True, capture_output=True, timeout=60,
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
                "type": "disk", "path": "/", "pool": "default", "size": "40GiB",
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


def preflight(api, *, creating=False, name=None):
    pool = api.query("/1.0/storage-pools/default")
    if pool.get("status") != "Created" or pool.get("driver") != "zfs":
        raise LabError(
            "default ZFS pool is unavailable. Operator must restore it externally; "
            "this tool never imports, repairs, resizes or replaces storage."
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
    resources = api.query("/1.0/storage-pools/default/resources")
    space = resources["space"]
    available = int(space["total"]) - int(space["used"])
    missing = sum(find(instances, item) is None for item in NAMES) if creating else 0
    required = missing * DISK + RESERVE
    if available < required:
        raise LabError(
            f"Storage needs {required / GIB:.1f} GiB available for {missing} remaining "
            f"40 GiB disks and a 20 GiB reserve; has {available / GIB:.1f} GiB. "
            "Stop here. No automatic resize, thin overcommit or bots cleanup."
        )
    host = api.query("/1.0/resources")
    memory = host["memory"]
    if int(memory["total"]) - int(memory["used"]) < 12 * GIB:
        raise LabError("Less than 12 GiB host memory headroom; refusing VM operation")
    return {"available_bytes": available, "required_bytes": required, "instances": instances}


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
        "--storage", "default", "--network", "incusbr0",
        "--device", "root,size=40GiB",
        "--config", "limits.cpu=4", "--config", "limits.memory=8GiB",
        "--config", "boot.autostart=false", "--config", f"user.odq.owner={MARKER}",
        "--config", f"user.odq.image={spec['fingerprint']}",
    )
    owned(find(api.instances(), name))
    # Incus defaults to sparse ZFS zvols. Reserve this lab's volume through
    # Incus, not a zfs command or a pool-wide configuration change.
    api.run("storage", "volume", "set", "default", f"virtual-machine/{name}",
            "zfs.reserve_space=true")


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
    if instance["status"] != "Stopped":
        api.run("stop", name, "--timeout", "120", timeout=150)
    require_stopped(owned(find(api.instances(), name)))


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
    api.run("file", "pull", f"{name}/var/tmp/odq-smoke.png", str(target))
    for filename in ("packages.tsv", "listeners.txt"):
        api.run("file", "pull", f"{name}/root/odq/evidence/{filename}",
                str(destination / filename))
    # A header alone is not semantic screenshot proof. Viewer inspection is required.
    data = target.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise LabError("Guest capture is not a PNG")
    proof.update({"instance": name, "image": image_spec(name),
                  "screenshot_sha256": hashlib.sha256(data).hexdigest(),
                  "source_sha": subprocess.check_output(
                      ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                  ).strip(), "visual_inspection": "required"})
    (destination / "proof.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(proof, indent=2))


@contextmanager
def mutation_lock():
    # Shared across clones, no global host service/config installation.
    # /tmp file is non-secret orchestration scratch, not a shared guest folder.
    flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/tmp/odin-desktop-qualification.lock", flags, 0o600)
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
    parser.add_argument("--label", default="configured")
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
