"""Exercise the real orchestration with a simulated Incus, never the host daemon."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "qualification_lab", ROOT / "scripts/qualification/lab/lab.py",
)
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


def instance(name="odq-gnome", status="Stopped"):
    return {
        "name": name, "status": status, "type": "virtual-machine", "profiles": [],
        "config": {"user.odq.owner": lab.MARKER},
        "expanded_config": {"limits.cpu": "4", "limits.memory": "8GiB",
                            "boot.autostart": "false"},
        "expanded_devices": {
            "root": {"type": "disk", "path": "/", "pool": "default", "size": "40GiB"},
            "eth0": {"type": "nic", "network": "incusbr0", "name": "eth0"},
        },
    }


class FakeIncus:
    def __init__(self):
        self.items = []
        self.calls = []
        self.pool = {"status": "Created", "driver": "zfs"}
        self.network = {"type": "bridge", "managed": True,
                        "config": {"ipv4.nat": "true"}}
        self.available = 250 * lab.GIB
        self.memory = 30 * lab.GIB

    def query(self, path):
        self.calls.append(("query", path))
        return {
            "/1.0/storage-pools/default": self.pool,
            "/1.0/networks/incusbr0": self.network,
            "/1.0/storage-pools/default/resources": {
                "space": {"total": self.available, "used": 0},
            },
            "/1.0/resources": {"memory": {"total": self.memory, "used": 0}},
        }[path]

    def instances(self):
        return copy.deepcopy(self.items)

    def run(self, *args, **kwargs):
        self.calls.append(args)
        if args[0] == "init":
            self.items.append(instance(args[2]))
        elif args[0] == "start":
            self.items[0]["status"] = "Running"
        elif args[0] == "stop":
            self.items[0]["status"] = "Stopped"
        return ""


def writes(api):
    return [call for call in api.calls if call[0] != "query"]


def test_unavailable_pool_stops_before_any_host_mutation():
    api = FakeIncus()
    api.pool["status"] = "Unavailable"
    with pytest.raises(lab.LabError, match="never imports"):
        lab.preflight(api, creating=True)
    assert not writes(api)
    assert api.calls == [("query", "/1.0/storage-pools/default")]


def test_55_gib_pool_refuses_four_disks_and_preserves_bots():
    api = FakeIncus()
    api.available = 55 * lab.GIB
    api.items = [{"name": "bots", "type": "container", "status": "Stopped"}]
    with pytest.raises(lab.LabError, match="180.0 GiB"):
        lab.create(api, "odq-gnome")
    assert not writes(api)
    assert api.items == [{"name": "bots", "type": "container", "status": "Stopped"}]


@pytest.mark.parametrize("status", ["Running", "Starting", "Frozen", "Error"])
def test_any_other_nonstopped_vm_prevents_boot(status):
    api = FakeIncus()
    api.items = [instance(), instance("odq-kde", status)]
    with pytest.raises(lab.LabError, match="Another VM"):
        lab.start(api, "odq-gnome")
    assert not writes(api)


def test_external_vm_also_blocks_boot():
    api = FakeIncus()
    api.items = [instance(), {"name": "other", "type": "virtual-machine", "status": "Running"}]
    with pytest.raises(lab.LabError, match="Another VM"):
        lab.start(api, "odq-gnome")
    assert not writes(api)


@pytest.mark.parametrize("change", ["unmarked", "container", "gpu", "share", "proxy",
                                   "profile", "raw", "memory", "autostart"])
def test_changed_isolation_refuses_destructive_operation(change):
    api = FakeIncus()
    item = instance()
    if change == "unmarked":
        item["config"].clear()
    elif change == "container":
        item["type"] = "container"
    elif change in ("gpu", "share", "proxy"):
        item["expanded_devices"][change] = {"type": change}
    elif change == "profile":
        item["profiles"] = ["default"]
    elif change == "raw":
        item["expanded_config"]["raw.qemu"] = "unsafe"
    elif change == "memory":
        item["expanded_config"]["limits.memory"] = "32GiB"
    else:
        item["expanded_config"]["boot.autostart"] = "true"
    api.items = [item]
    with pytest.raises(lab.LabError):
        lab.remove(api, "odq-gnome")
    assert not writes(api)


def test_missing_guest_is_a_clear_error():
    with pytest.raises(lab.LabError, match="non-lab"):
        lab.remove(FakeIncus(), "odq-gnome")


def test_insufficient_memory_or_non_nat_network_blocks():
    api = FakeIncus()
    api.memory = 11 * lab.GIB
    with pytest.raises(lab.LabError, match="memory headroom"):
        lab.preflight(api)
    api.memory = 30 * lab.GIB
    api.network["config"]["ipv4.nat"] = "false"
    with pytest.raises(lab.LabError, match="NAT bridge"):
        lab.preflight(api)
    assert not writes(api)


def test_create_uses_exact_image_no_profiles_and_reserved_disk(monkeypatch):
    api = FakeIncus()
    monkeypatch.setattr(lab, "image_spec", lambda _: {"fingerprint": "a" * 64})
    lab.create(api, "odq-gnome")
    init, reservation = writes(api)
    assert init[:4] == ("init", f"images:{'a' * 64}", "odq-gnome", "--vm")
    assert "--no-profiles" in init
    assert "limits.cpu=4" in init and "limits.memory=8GiB" in init
    assert "root,size=40GiB" in init and "boot.autostart=false" in init
    assert reservation == ("storage", "volume", "set", "default",
                           "virtual-machine/odq-gnome", "zfs.reserve_space=true")
    assert len(api.items) == 1


def test_create_does_not_replace_existing_guest():
    api = FakeIncus()
    api.items = [instance()]
    with pytest.raises(lab.LabError, match="already exists"):
        lab.create(api, "odq-gnome")
    assert not writes(api)


def test_start_then_graceful_stop(monkeypatch):
    api = FakeIncus()
    api.items = [instance()]
    monkeypatch.setattr(lab, "wait_agent", lambda *_: None)
    lab.start(api, "odq-gnome")
    assert api.items[0]["status"] == "Running"
    lab.stop(api, "odq-gnome")
    assert writes(api) == [("start", "odq-gnome"), ("stop", "odq-gnome", "--timeout", "120")]
    assert api.items[0]["status"] == "Stopped"


def test_stop_does_not_force_after_timeout():
    api = FakeIncus()
    api.items = [instance(status="Running")]
    def fail(*args, **kwargs):
        api.calls.append(args)
        raise lab.LabError("timeout")
    api.run = fail
    with pytest.raises(lab.LabError, match="timeout"):
        lab.stop(api, "odq-gnome")
    assert writes(api) == [("stop", "odq-gnome", "--timeout", "120")]


@pytest.mark.parametrize("operation", ["snapshot", "remove"])
def test_snapshot_and_remove_require_stopped(operation):
    api = FakeIncus()
    api.items = [instance(status="Running")]
    with pytest.raises(lab.LabError, match="gracefully"):
        if operation == "snapshot":
            lab.snapshot(api, "odq-gnome", "configured")
        else:
            lab.remove(api, "odq-gnome")
    assert not writes(api)


def test_snapshot_labels_cannot_inject_other_instance_path():
    api = FakeIncus()
    api.items = [instance()]
    with pytest.raises(lab.LabError, match="label"):
        lab.snapshot(api, "odq-gnome", "../bots")
    assert not writes(api)


def test_snapshot_and_remove_affect_only_owned_vm():
    api = FakeIncus()
    api.items = [instance()]
    lab.snapshot(api, "odq-gnome", "configured")
    lab.remove(api, "odq-gnome")
    assert writes(api) == [("snapshot", "create", "odq-gnome", "configured"),
                           ("delete", "odq-gnome")]


def test_invalid_image_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(lab, "HERE", tmp_path)
    (tmp_path / "images").mkdir()
    (tmp_path / "images/gnome.json").write_text(json.dumps({"fingerprint": "latest"}))
    with pytest.raises(lab.LabError, match="pinned"):
        lab.image_spec("odq-gnome")


def test_provision_uploads_only_guest_recipes_then_stops(monkeypatch):
    api = FakeIncus()
    api.items = [instance(status="Running")]
    monkeypatch.setattr(lab, "wait_agent", lambda *_: None)
    lab.provision(api, "odq-gnome")
    changes = writes(api)
    assert changes[0] == ("exec", "odq-gnome", "--", "hostnamectl", "set-hostname", "odq-gnome")
    assert all(call[0:2] == ("file", "push") for call in changes[1:4])
    assert all("odq-gnome/root/odq/" in call[3] for call in changes[1:4])
    assert changes[4] == ("exec", "odq-gnome", "--", "bash", "/root/odq/gnome.sh")
    assert changes[5] == ("exec", "odq-gnome", "--", "bash", "-c",
                          "source /root/odq/common.sh; odq_finalize")
    assert changes[6] == ("stop", "odq-gnome", "--timeout", "120")


def test_cli_never_accepts_bots_as_mutation_target():
    with pytest.raises(SystemExit):
        lab.main(["remove", "bots"])


def test_cli_preflight_reports_blocked_without_mutation(monkeypatch, capsys):
    api = FakeIncus()
    api.pool["status"] = "Unavailable"
    monkeypatch.setattr(lab, "Incus", lambda: api)
    assert lab.main(["preflight"]) == 1
    assert "BLOCKED" in capsys.readouterr().err
    assert not writes(api)


def test_incus_commands_are_local_default_project_without_shell(monkeypatch):
    calls = []
    def execute(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout='[]', stderr='')
    monkeypatch.setattr(lab.subprocess, "run", execute)
    api = lab.Incus()
    assert api.instances() == []
    assert api.query("/1.0/instances?recursion=1") == []
    assert calls[0][0] == ["sudo", "-n", "incus", "--force-local", "--project",
                           "default", "list", "--format=json"]
    assert calls[1][0] == ["sudo", "-n", "incus", "--force-local", "query",
                           "/1.0/instances?recursion=1&project=default"]
    assert all("shell" not in kwargs for _, kwargs in calls)


@pytest.mark.parametrize("query", [False, True])
def test_cli_errors_do_not_become_silent_success(monkeypatch, query):
    monkeypatch.setattr(lab.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout="", stderr="permission denied",
    ))
    api = lab.Incus()
    with pytest.raises(lab.LabError, match="permission denied"):
        if query:
            api.query("/1.0/resources")
        else:
            api.run("list")


def test_pinned_image_uses_full_vm_digest(tmp_path, monkeypatch):
    monkeypatch.setattr(lab, "HERE", tmp_path)
    (tmp_path / "images").mkdir()
    data = {"fingerprint": "a" * 64, "type": "virtual-machine",
            "architecture": "amd64", "remote": "images"}
    (tmp_path / "images/gnome.json").write_text(json.dumps(data))
    assert lab.image_spec("odq-gnome") == data


def test_agent_wait_is_bounded_and_does_not_restart(monkeypatch):
    api = FakeIncus()
    attempts = []
    def unavailable(*args, **kwargs):
        attempts.append(args)
        raise lab.LabError("agent unavailable")
    api.run = unavailable
    times = iter((0, 0, 10))
    monkeypatch.setattr(lab.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(lab.time, "sleep", lambda _: None)
    with pytest.raises(lab.LabError, match="no forced stop"):
        lab.wait_agent(api, "odq-gnome", timeout=5)
    assert attempts == [("exec", "odq-gnome", "--", "/bin/true")]


def test_agent_wait_success():
    api = FakeIncus()
    lab.wait_agent(api, "odq-gnome", timeout=5)
    assert writes(api) == [("exec", "odq-gnome", "--", "/bin/true")]


def test_smoke_saves_fresh_guest_evidence_without_claiming_visual_success(
    tmp_path, monkeypatch,
):
    api = FakeIncus()
    api.items = [instance(status="Running")]
    def execute(*args, **kwargs):
        api.calls.append(args)
        if args[0] == "exec":
            return json.dumps({"passed": True, "session": {"Type": "wayland"}})
        if args[:2] == ("file", "pull"):
            Path(args[3]).write_bytes(b"\x89PNG\r\n\x1a\nfixture")
        return ""
    api.run = execute
    monkeypatch.setattr(lab, "image_spec", lambda _: {"fingerprint": "a" * 64})
    monkeypatch.setattr(lab.subprocess, "check_output", lambda *a, **k: "fixture-sha\n")
    target = tmp_path / "evidence"
    lab.smoke(api, "odq-gnome", target)
    saved = json.loads((target / "proof.json").read_text())
    assert saved["source_sha"] == "fixture-sha"
    assert saved["visual_inspection"] == "required"
    assert len(saved["screenshot_sha256"]) == 64
    assert (target / "packages.tsv").is_file()
    assert all("odq-gnome" in str(call) for call in writes(api))
    with pytest.raises(lab.LabError, match="preserve previous proof"):
        lab.smoke(api, "odq-gnome", target)


def test_smoke_guest_failure_cannot_produce_pass_record(tmp_path):
    api = FakeIncus()
    api.items = [instance(status="Running")]
    api.run = lambda *a, **k: json.dumps({"passed": False, "error": "Wayland denied"})
    target = tmp_path / "failed"
    with pytest.raises(lab.LabError, match="did not pass"):
        lab.smoke(api, "odq-gnome", target)
    assert not (target / "proof.json").exists()


def test_smoke_bad_png_cannot_produce_pass_record(tmp_path):
    api = FakeIncus()
    api.items = [instance(status="Running")]
    def execute(*args, **kwargs):
        if args[0] == "exec":
            return '{"passed": true}'
        Path(args[3]).write_bytes(b"not png")
        return ""
    api.run = execute
    target = tmp_path / "failed"
    with pytest.raises(lab.LabError, match="not a PNG"):
        lab.smoke(api, "odq-gnome", target)
    assert not (target / "proof.json").exists()


def test_creation_and_smoke_require_owned_names_and_running_state(tmp_path):
    api = FakeIncus()
    with pytest.raises(lab.LabError, match="Unknown"):
        lab.create(api, "bots")
    with pytest.raises(lab.LabError, match="Create the guest"):
        lab.start(api, "odq-gnome")
    with pytest.raises(lab.LabError, match="Start the guest"):
        lab.provision(api, "odq-gnome")
    with pytest.raises(lab.LabError, match="running owned"):
        lab.smoke(api, "odq-gnome", tmp_path / "evidence")
    assert not writes(api)


def test_lock_rejects_symlink_and_concurrent_command(tmp_path, monkeypatch):
    original_open = lab.os.open
    lock = tmp_path / "lab.lock"
    monkeypatch.setattr(lab.os, "open", lambda _, flags, mode: original_open(lock, flags, mode))
    with lab.mutation_lock():
        with pytest.raises(lab.LabError, match="Another lab command"):
            with lab.mutation_lock():
                pytest.fail("a second lock should not execute")
    lock.unlink()
    lock.symlink_to(tmp_path / "other")
    with pytest.raises(OSError):
        with lab.mutation_lock():
            pytest.fail("a symlink lock should not execute")


def test_stop_already_stopped_guest_is_read_only():
    api = FakeIncus()
    api.items = [instance()]
    lab.stop(api, "odq-gnome")
    assert not writes(api)


def test_timeouts_surface_as_blocked(monkeypatch, capsys):
    api = FakeIncus()
    api.query = lambda _: (_ for _ in ()).throw(subprocess.TimeoutExpired("incus", 60))
    monkeypatch.setattr(lab, "Incus", lambda: api)
    assert lab.main(["preflight"]) == 1
    assert "BLOCKED" in capsys.readouterr().err
