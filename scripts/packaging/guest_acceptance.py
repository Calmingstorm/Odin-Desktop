#!/usr/bin/env python3
"""Run only inside the marked P4.2 disposable Incus container as root.

The candidate core and user-managed replacement helper run as packageowner.
No command here is dispatched by an app or model. Second-install sentinels are
test data and a harmless echo service, not imported workstation configuration.
"""
from __future__ import annotations

import hashlib
import json
import os
import pwd
import secrets
import socket
import struct
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path("/p42-evidence")
INPUTS = Path("/p42-inputs")
HOME = Path("/home/packageowner")
ACCOUNT = pwd.getpwnam("packageowner")
INSTALL = Path("/opt/Odin")


def run(command, *, owner=False, expected=0, timeout=180):
    if owner:
        command = ["/usr/sbin/runuser", "-u", "packageowner", "--", "/usr/bin/env", "-i",
                   "HOME=" + str(HOME), "PATH=/usr/bin:/bin",
                   "XDG_RUNTIME_DIR=" + str(HOME / "run"),
                   *command]
    result = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
    name = str(len(list(ROOT.glob("command-*.log")))).zfill(3)
    (ROOT / ("command-" + name + ".log")).write_text(result.stdout + result.stderr)
    if (expected == "nonzero" and result.returncode == 0
            or type(expected) is int and result.returncode != expected):
        raise RuntimeError("Unexpected command outcome: " + str(command[0]) + "\n"
                           + result.stdout[-2000:] + result.stderr[-4000:])
    return result


def hashfile(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def snapshot(root):
    return {str(path.relative_to(root)): [hashfile(path), path.stat().st_mode & 0o777,
                                         path.stat().st_uid, path.stat().st_gid]
            for path in root.rglob("*") if path.is_file() and not path.is_symlink()}


def owner_dir(path):
    if HOME != path and HOME not in path.parents:
        raise RuntimeError("Refusing a directory outside the disposable owner's HOME")
    run(["/bin/mkdir", "-p", "-m", "700", str(path)], owner=True)
    return path


def owned_write(path, data):
    path.write_bytes(data)
    path.chmod(0o600)
    os.chown(path, ACCOUNT.pw_uid, ACCOUNT.pw_gid)


def executable_versions():
    return {"dpkg": run(["dpkg", "--version"]).stdout.splitlines()[0],
            "kernel": os.uname().release,
            "image": "Ubuntu noble container",
            "candidate_version": run([
                "dpkg-deb", "-f", str(INPUTS / "candidate.deb"), "Version"]).stdout.strip(),
            "previous_version": run([
                "dpkg-deb", "-f", str(INPUTS / "previous.deb"), "Version"]).stdout.strip()}


class OtherInstallation:
    """Independent data, credential-shaped sentinel, lock, endpoint and process."""
    def __init__(self):
        self.root = HOME / "independent-odin-like"
        self.process = None

    def start(self):
        owner_dir(self.root)
        for name, data in (("configuration", b"unrelated install configuration\n"),
                           ("credentials", b"disposable noncredential sentinel\n"),
                           ("history", b"unrelated retained history\n"),
                           ("lease", b"independent install lock inode\n")):
            owned_write(self.root / name, data)
        script = self.root / "receiver.py"
        owned_write(script, b"import fcntl,socket,sys\nfrom pathlib import Path\n"
                    b"r=Path(sys.argv[1])\nf=open(r/'lease','r')\n"
                    b"fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)\n"
                    b"s=socket.socket(socket.AF_UNIX)\ns.bind(str(r/'endpoint.sock'))\n"
                    b"s.listen()\n(r/'ready').write_text('ready')\nwhile True:\n"
                    b" c,_=s.accept()\n with c:\n  d=c.recv(64)\n  c.sendall(b'independent:'+d)\n"
                    b"  if d==b'exit':break\ns.close()\n(r/'endpoint.sock').unlink()\n")
        self.process = subprocess.Popen(["runuser", "-u", "packageowner", "--", "python3", "-B",
                                         str(script), str(self.root)], stdout=subprocess.DEVNULL,
                                        stderr=(ROOT / "independent.stderr").open("wb"))
        deadline = time.monotonic() + 10
        while not (self.root / "ready").exists() or not (self.root / "endpoint.sock").exists():
            if self.process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("Independent sentinel receiver did not start")
            time.sleep(0.05)
        self.before = snapshot(self.root)
        self.pid = self.process.pid
        self.lock_inode = (self.root / "lease").stat().st_ino
        self.endpoint_inode = (self.root / "endpoint.sock").stat().st_ino
        self.check()

    def check(self):
        assert self.process.poll() is None
        assert self.process.pid == self.pid
        assert snapshot(self.root) == self.before
        assert (self.root / "lease").stat().st_ino == self.lock_inode
        assert (self.root / "endpoint.sock").stat().st_ino == self.endpoint_inode
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(2)
            client.connect(str(self.root / "endpoint.sock"))
            client.sendall(b"sentinel")
            assert client.recv(64) == b"independent:sentinel"

    def close(self):
        if self.process and self.process.poll() is None:
            with socket.socket(socket.AF_UNIX) as client:
                client.connect(str(self.root / "endpoint.sock"))
                client.sendall(b"exit")
                assert client.recv(64) == b"independent:exit"
            assert self.process.wait(timeout=5) == 0


class Core:
    def __init__(self, resources=INSTALL / "resources", profile="acceptance"):
        self.resources, self.profile = resources, profile
        self.config = HOME / ".config/odin-desktop" / profile
        self.data = HOME / ".local/share/odin-desktop" / profile
        self.runtime = HOME / "run/odin-desktop" / profile
        self.child = None
        self.socket = None
        self.events = []

    def start(self):
        for path in (self.config, self.data, self.runtime):
            owner_dir(path)
        self.token = secrets.token_hex(32)
        owned_write(self.config / "ipc.token", self.token.encode())
        python = self.resources / "runtime/python/bin/python3"
        environment = ["/usr/bin/env", "-i", "HOME=" + str(HOME), "PATH=/usr/bin:/bin",
                       "XDG_RUNTIME_DIR=" + str(HOME / "run"),
                       "ODIN_DESKTOP_BUNDLE_ROOT=" + str(self.resources / "runtime")]
        self.child = subprocess.Popen(["runuser", "-u", "packageowner", "--", *environment,
                                      str(python), "-I", "-B", "-m", "src", "--socket",
                                      str(self.runtime / "core.sock"), "--token-file",
                                      str(self.config / "ipc.token"), "--profile", self.profile,
                                      "--data-dir", str(self.data)], stdin=subprocess.PIPE,
                                     stdout=subprocess.DEVNULL,
                                     stderr=(ROOT / (self.profile + ".stderr")).open("wb"))
        deadline = time.monotonic() + 45
        while not (self.runtime / "core.sock").exists():
            if self.child.poll() is not None:
                raise RuntimeError("Core failed before handshake: "
                                   + (ROOT / (self.profile + ".stderr")).read_text()[-3000:])
            if time.monotonic() > deadline:
                raise RuntimeError("Core startup deadline")
            time.sleep(0.05)
        # SO_PEERCRED binds credentials at connect. Root orchestrates dpkg, but
        # the IPC client must genuinely connect as the same ordinary owner.
        os.setegid(ACCOUNT.pw_gid)
        os.seteuid(ACCOUNT.pw_uid)
        try:
            self.socket = socket.socket(socket.AF_UNIX)
            self.socket.settimeout(15)
            self.socket.connect(str(self.runtime / "core.sock"))
        finally:
            os.seteuid(0)
            os.setegid(0)
        self.send({"t": "hello", "protocol": {"major": 0, "minor": 3},
                   "client": {"name": "p42-package-acceptance", "version": "1"},
                   "profile_id": self.profile, "token": self.token, "features": []})
        self.welcome = self.receive()
        assert self.welcome["t"] == "welcome", self.welcome
        assert self.request("status.get")["phase"] == "ready"
        return self

    def send(self, value):
        data = json.dumps(value).encode()
        self.socket.sendall(struct.pack("!I", len(data)) + data)

    def exact(self, size):
        value = b""
        while len(value) < size:
            chunk = self.socket.recv(size - len(value))
            if not chunk:
                raise RuntimeError("Unexpected core IPC EOF")
            value += chunk
        return value

    def receive(self):
        size = struct.unpack("!I", self.exact(4))[0]
        assert 0 < size <= 4 * 1024 * 1024
        return json.loads(self.exact(size))

    def request(self, method, params=None):
        identity = str(uuid.uuid4())
        self.send({"t": "req", "id": identity, "method": method, "params": params or {}})
        while True:
            response = self.receive()
            if response["t"] == "evt":
                self.events.append(response)
                continue
            assert response["t"] == "res" and response["id"] == identity
            assert response["ok"], response
            return response["result"]

    def close(self):
        if self.socket:
            self.request("runtime.shutdown", {"reason": "p42-disposable-acceptance"})
            self.socket.close()
            self.socket = None
        if self.child and self.child.poll() is None:
            self.child.stdin.close()
            assert self.child.wait(timeout=35) == 0
        assert not (self.runtime / "core.sock").exists()


def main():
    assert os.geteuid() == 0 and str(ROOT) == "/p42-evidence"
    ROOT.mkdir(exist_ok=True)
    assert not Path("/opt/odin").exists()
    owner_dir(HOME / "run")
    other = OtherInstallation()
    report = {"schema": 1, "gate": "fail", "cases": {}, "versions": executable_versions()}
    try:
        other.start()
        run(["apt-get", "install", "-y", "--no-install-recommends",
             str(INPUTS / "previous.deb")], timeout=300)
        assert run(["dpkg-query", "-W", "-f=${Status}", "odin-desktop"]).stdout == (
            "install ok installed")
        before_exe = hashfile(INSTALL / "odin-desktop")
        old = Core().start()
        conversation = old.request("conversations.create", {"command_id": str(uuid.uuid4()),
                                  "title": "Preserved P4.1 conversation"})
        old.close()
        report["cases"]["previous_nonroot_core"] = {"handshake": True, "conversation": conversation}
        other.check()
        report["cases"]["alongside_before_upgrade"] = "pass"
        # Legacy P4.1 has no lifetime barrier. A root process scan alone cannot
        # close its launch race, so a direct upgrade is intentionally refused.
        run(["dpkg", "-i", str(INPUTS / "candidate.deb")], expected="nonzero", timeout=300)
        assert hashfile(INSTALL / "odin-desktop") == before_exe
        other.check()
        report["cases"]["unguarded_direct_upgrade"] = "refused unchanged; not supported"

        # In this disposable guest only, externally fence ALL package execution:
        # chmod the exact application root while no app/core remains. The user
        # cannot traverse it, including old Python or raw Electron entrypoints.
        # No process is stopped or signalled by a package script.
        run(["chmod", "700", str(INSTALL)])
        run([str(INSTALL / "odin-desktop"), "--version"], owner=True, expected="nonzero")
        data_before = snapshot(old.data)
        key_before = hashfile(old.data / "secrets/id_ed25519")
        run(["dpkg", "--remove", "odin-desktop"], timeout=300)
        run(["dpkg", "--install", str(INPUTS / "candidate.deb")], timeout=300)
        assert (INSTALL / "resources/ownership.py").is_file()
        assert snapshot(old.data) == data_before
        assert hashfile(old.data / "secrets/id_ed25519") == key_before
        other.check()
        report["cases"]["legacy_offline_transition"] = (
            "externally fenced remove/install; user state unchanged")

        upgraded = Core().start()
        assert upgraded.request("conversations.list")["items"][0]["title"] == (
            "Preserved P4.1 conversation")
        upgraded.close()
        marker = json.loads((upgraded.data / "package-state.json").read_text())
        assert marker["state"] == "committed"
        backup = upgraded.data / "package-backups" / marker["backup"]
        assert (backup / "data/transport.sqlite3").is_file()
        report["cases"]["ordinary_owner_migration"] = {
            "state": "committed", "backup": marker["backup"]}
        other.check()
        # A live actual packaged core owns its own lease, independent of any
        # app launcher. dpkg must refuse both replacement and removal.
        running = Core().start()
        installed_before = hashfile(INSTALL / "resources/app.asar")
        run(["dpkg", "--install", str(INPUTS / "candidate.deb")], expected="nonzero", timeout=300)
        assert hashfile(INSTALL / "resources/app.asar") == installed_before
        run(["dpkg", "--remove", "odin-desktop"], expected="nonzero", timeout=300)
        assert running.request("status.get")["phase"] == "ready"
        running.close()
        other.check()
        report["cases"]["surviving_core_busy_install_remove"] = (
            "both refused without signals; core remained ready")
        # Same product version is deliberate: these are unreleased candidates,
        # not a fabricated release bump. dpkg still executes the real hooks.
        run(["dpkg", "--install", str(INPUTS / "candidate.deb")], timeout=300)
        assert hashfile(upgraded.data / "secrets/id_ed25519") == key_before
        other.check()
        report["cases"]["guarded_candidate_replacement"] = (
            "real dpkg reinstall after clean core Exit")
        # Actual package-manager interruption boundary, not manually invented
        # state: unpack completes while configure has not run. The persistent
        # marker fences even a new owner launch until dpkg configuration.
        run(["dpkg", "--unpack", str(INPUTS / "candidate.deb")], timeout=300)
        assert Path("/var/lib/odin-desktop/package-ownership/transaction.json").is_file()
        state_before = snapshot(upgraded.data)
        run([str(INSTALL / "odin-desktop"), "--version"], owner=True, expected="nonzero")
        assert snapshot(upgraded.data) == state_before
        run(["dpkg", "--configure", "odin-desktop"], timeout=300)
        assert not Path("/var/lib/odin-desktop/package-ownership/transaction.json").exists()
        other.check()
        report["cases"]["dpkg_unpack_configure_interruption"] = (
            "real unpack fences launch without writes; configure restores eligibility")

        # Run the candidate's actual no-write compatibility entrypoint against
        # future state. Refusal must not alter the profile or publish a dirty
        # process lifetime, so a compatible replacement remains possible.
        state_file = upgraded.data / "package-state.json"
        original_marker = state_file.read_bytes()
        future = json.loads(original_marker)
        future["compatibility"]["storage"] += 1
        owned_write(state_file, json.dumps(future).encode())
        future_before = snapshot(upgraded.data)
        run([str(INSTALL / "resources/runtime/python/bin/python3"), "-I", "-B", "-m",
             "src.desktop.package_state", "--profile", upgraded.profile, "--token-file",
             str(upgraded.config / "ipc.token"), "--data-dir", str(upgraded.data)],
            owner=True, expected="nonzero")
        assert snapshot(upgraded.data) == future_before
        owned_write(state_file, original_marker)
        report["cases"]["future_state_rollback_refusal"] = "actual candidate refuses before writes"

        # Manual AppImage path, owned by the ordinary user. The helper is an
        # explicitly invoked local file, never an app-dispatched apply path.
        applications = owner_dir(HOME / "Applications with spaces")
        current_image = applications / "Odin current.AppImage"
        next_image = applications / "Odin new.AppImage"
        helper = applications / "replace-appimage.py"
        run(["cp", str(INPUTS / "candidate.AppImage"), str(current_image)], owner=True)
        run(["cp", str(INPUTS / "candidate.AppImage"), str(next_image)], owner=True)
        run(["cp", str(INPUTS / "replace-appimage.py"), str(helper)], owner=True)
        run(["cp", str(INSTALL / "resources/ownership.py"),
             str(applications / "ownership.py")], owner=True)
        run(["chmod", "755", str(current_image), str(next_image)], owner=True)
        image_digest = hashfile(next_image)
        command = ["python3", "-B", str(helper), "--source", str(next_image),
                   "--destination", str(current_image), "--sha256", image_digest]
        run(command, owner=True)
        assert hashfile(current_image) == image_digest
        other.check()
        report["cases"]["real_appimage_same_path_manual_replacement"] = "pass"
        # A filesystem refusal leaves a durable transaction fence. Restore only
        # the exact user's directory mode, then explicitly rerun the same helper.
        run(["chmod", "555", str(applications)], owner=True)
        run(command, owner=True, expected="nonzero")
        assert hashfile(current_image) == image_digest
        ownership_state = HOME / ".local/state/odin-desktop/install-ownership/appimage"
        assert (ownership_state / "appimage-replacement.json").exists()
        run(["chmod", "700", str(applications)], owner=True)
        run(command, owner=True)
        assert not (ownership_state / "appimage-replacement.json").exists()
        other.check()
        report["cases"]["real_appimage_nonwritable_destination_recovery"] = "pass"

        run(["dpkg", "--remove", "odin-desktop"], timeout=300)
        assert upgraded.data.is_dir() and (upgraded.data / "transport.sqlite3").is_file()
        assert hashfile(upgraded.data / "secrets/id_ed25519") == key_before
        assert not (INSTALL / "resources/app.asar").exists()
        other.check()
        report["cases"]["removal_preserves_user_state_and_alongside"] = "pass"
        # Export lane can later mount this exact real dpkg-installed tree in
        # private graphics without installing anything on the workstation.
        run(["dpkg", "--install", str(INPUTS / "candidate.deb")], timeout=300)
        other.check()
        report["cases"]["final_export_install"] = (
            "actual installed candidate ready for isolated GUI proof")
        report["gate"] = "pass"
    finally:
        other.close()
        (ROOT / "guest-result.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))


if __name__ == "__main__":
    main()
