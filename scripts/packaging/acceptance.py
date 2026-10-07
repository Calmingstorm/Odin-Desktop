#!/usr/bin/env python3
"""P4.2 disposable Incus container controller. Never starts a VM or host service.

The existing lab's Incus transport is reused, but its VM-only operations are not.
Every operation rechecks the exact container identity and isolation settings.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "scripts/qualification/lab/lab.py"
spec = importlib.util.spec_from_file_location("p42_lab", LAB)
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)

NAME = "odq-p42-packages"
MARKER = "odin-desktop-p42-disposable-v1"
IMAGE = "40d78ed6219c01d85dc98192647f0be335b1fbb3e7d0de509e5efc792624f441"
GIB = 1024**3
DEVICES = {
    "root": {"type": "disk", "path": "/", "pool": "odq-lab", "size": "12GiB"},
    "eth0": {"type": "nic", "network": "incusbr0", "name": "eth0"},
}


class AcceptanceError(RuntimeError):
    pass


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def owned(item):
    if (not item or item.get("name") != NAME or item.get("type") != "container"
            or item.get("profiles") or item.get("expanded_devices") != DEVICES):
        raise AcceptanceError("Refusing an unowned or nonisolated package container")
    config = item.get("expanded_config", {})
    required = {
        "user.odq.owner": MARKER, "boot.autostart": "false",
        "limits.cpu": "2", "limits.memory": "4GiB", "security.privileged": "false",
    }
    if any(config.get(key) != value for key, value in required.items()):
        raise AcceptanceError("Package container identity/caps changed")
    if any(key.startswith("raw.") or key.startswith("security.")
           and key != "security.privileged" for key in config):
        raise AcceptanceError("Unexpected container security configuration")
    return item


class Container:
    def __init__(self, api=None):
        self.api = api or lab.Incus()

    def find(self):
        return next((item for item in self.api.instances() if item["name"] == NAME), None)

    def check(self):
        return owned(self.find())

    def preflight(self):
        pool = self.api.query("/1.0/storage-pools/odq-lab")
        if (pool.get("driver") != "dir" or pool.get("status") != "Created"
                or pool.get("config", {}).get("source") != "/mnt/storage/odq-lab"):
            raise AcceptanceError("Existing odq-lab pool required; never repair another pool")
        network = self.api.query("/1.0/networks/incusbr0")
        if not network.get("managed") or network.get("config", {}).get("ipv4.nat") != "true":
            raise AcceptanceError("Existing managed incusbr0 NAT network required")
        # Same policy as lab VMs: reserve this container's growth plus the remaining
        # growth of every running lab VM (caps validated), measured before the pool.
        growth = 14 * GIB + sum(lab.running_reserve(self.api.instances(), skip=(NAME,)).values())
        used, free = lab.storage_usage()
        if used + growth > lab.POOL_BUDGET:
            raise AcceptanceError("Container growth would exceed existing lab storage budget")
        if free < lab.FILESYSTEM_FLOOR + growth:
            raise AcceptanceError("Container growth would violate existing filesystem floor")
        memory = self.api.query("/1.0/resources")["memory"]
        if int(memory["total"]) - int(memory["used"]) < 8 * GIB:
            raise AcceptanceError("Insufficient host memory headroom for light container")
        return {"pool_allocated_bytes": used, "filesystem_free_bytes": free}

    def prepare(self):
        resources = self.preflight()
        existing = self.find()
        if existing:
            self.check()
            if existing["status"] != "Running":
                raise AcceptanceError(
                    "Existing stopped container requires explicit cleanup, not reuse")
            return {"reused": True, **resources}
        self.api.run("init", "images:" + IMAGE, NAME, "--no-profiles", "--storage", "odq-lab",
                     "-c", "user.odq.owner=" + MARKER, "-c", "boot.autostart=false",
                     "-c", "limits.cpu=2", "-c", "limits.memory=4GiB",
                     "-c", "security.privileged=false")
        # The default profile is deliberately absent. Add only the existing NAT NIC.
        self.api.run("config", "device", "set", NAME, "root", "size=12GiB")
        self.api.run("config", "device", "add", NAME, "eth0", "nic",
                     "network=incusbr0", "name=eth0")
        self.check()
        self.api.run("start", NAME)
        self.check()
        self.exec("/bin/sh", "-ec",
                  "until getent hosts archive.ubuntu.com >/dev/null; do sleep 1; done", timeout=120)
        self.exec("/usr/bin/apt-get", "update", timeout=600)
        self.exec("/usr/bin/apt-get", "install", "-y", "--no-install-recommends",
                  "python3", "util-linux", "procps", "openssh-client", "xvfb", "dbus-x11",
                  "libgtk-3-0", "libnss3", "libxss1", "libxtst6", "libatspi2.0-0",
                  "libuuid1", "libsecret-1-0", "libgbm1", "libasound2t64", "libxshmfence1",
                  "libx11-xcb1", timeout=900)
        self.exec("/usr/sbin/useradd", "--create-home", "--shell", "/bin/bash", "packageowner")
        self.exec("/bin/mkdir", "-p", "/p42-evidence", "/p42-inputs")
        return {"reused": False, "image_fingerprint": IMAGE, **resources}

    def exec(self, *command, timeout=300, capture=False):
        self.check()
        return self.api.run("exec", NAME, "--env", "DEBIAN_FRONTEND=noninteractive",
                            "--", *command, capture=capture, timeout=timeout)

    def push(self, source, destination):
        self.check()
        if not str(destination).startswith(("/p42-inputs/", "/p42-evidence/")):
            raise AcceptanceError("Only disposable input/evidence destinations are accepted")
        self.api.run("file", "push", str(Path(source).resolve()), NAME + destination)

    def cleanup(self):
        item = self.check()
        if item["status"] == "Running":
            self.api.run("stop", NAME, "--timeout", "30")
        self.check()
        self.api.run("delete", NAME)
        if self.find() is not None:
            raise AcceptanceError("Container cleanup not confirmed")
        return {"container_removed": True, "host_services_touched": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "export", "cleanup", "status"))
    parser.add_argument("--deb", type=Path)
    parser.add_argument("--previous-deb", type=Path)
    parser.add_argument("--appimage", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    api = Container()
    report = {"schema": 1, "started": time.time(), "action": args.action,
              "container": NAME, "native_graphics": "not qualified by container ownership proofs"}
    try:
        if args.action == "prepare":
            report["preparation"] = api.prepare()
        elif args.action == "status":
            report["state"] = api.check()["status"]
        elif args.action == "cleanup":
            report["cleanup"] = api.cleanup()
        elif args.action == "export":
            status = api.exec("dpkg-query", "-W", "-f=${Status}", "odin-desktop", capture=True)
            if status != "install ok installed":
                raise AcceptanceError("Export requires actual installed candidate")
            api.exec("tar", "-C", "/", "-cf", "/p42-evidence/installed-root.tar",
                     "opt/Odin", "var/lib/dpkg/status", timeout=300)
            api.api.run("file", "pull", NAME + "/p42-evidence/installed-root.tar",
                        str(args.output / "installed-root.tar"))
            report["export"] = {"dpkg_status": status,
                                "archive_sha256": digest(args.output / "installed-root.tar")}
        else:
            if not args.deb or not args.previous_deb or not args.appimage:
                parser.error("run requires --deb, --previous-deb and --appimage")
            report["artifacts"] = {}
            for name, source in (("candidate.deb", args.deb), ("previous.deb", args.previous_deb),
                                 ("candidate.AppImage", args.appimage)):
                if not source.is_file():
                    raise AcceptanceError("Missing candidate input: " + str(source))
                report["artifacts"][name] = {
                    "bytes": source.stat().st_size, "sha256": digest(source)}
                api.push(source, "/p42-inputs/" + name)
            guest = ROOT / "scripts/packaging/guest_acceptance.py"
            api.push(guest, "/p42-inputs/guest_acceptance.py")
            api.push(ROOT / "app/packaging/replace-appimage.py", "/p42-inputs/replace-appimage.py")
            output = api.exec("/usr/bin/python3", "-B", "/p42-inputs/guest_acceptance.py",
                              capture=True, timeout=900)
            (args.output / "guest.log").write_text(output)
            report["guest"] = json.loads(output.strip().splitlines()[-1])
            if report["guest"].get("gate") != "pass":
                raise AcceptanceError("Guest acceptance did not pass")
        report["gate"] = "pass"
    except Exception as exc:
        report["gate"] = "fail"
        report["error"] = str(exc)
        raise
    finally:
        report["finished"] = time.time()
        (args.output / (args.action + ".json")).write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))


if __name__ == "__main__":
    main()
