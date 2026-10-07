"""Exercise the real orchestration with a simulated Incus, never the host daemon."""

from __future__ import annotations

import copy
import fcntl
import hashlib
import importlib.util
import json
import os
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
REAL_STORAGE_USAGE = lab.storage_usage
REAL_GUEST_USAGE = lab.guest_usage


def instance(name="odq-gnome", status="Stopped"):
    return {
        "name": name, "status": status, "type": "virtual-machine", "profiles": [],
        "config": {"user.odq.owner": lab.MARKER},
        "expanded_config": {"limits.cpu": "4", "limits.memory": "8GiB",
                            "boot.autostart": "false"},
        "expanded_devices": {
            "root": {"type": "disk", "path": "/", "pool": lab.POOL, "size": "40GiB"},
            "eth0": {"type": "nic", "network": "incusbr0", "name": "eth0"},
        },
    }


class FakeIncus:
    def __init__(self):
        self.items = []
        self.calls = []
        self.pool = {"status": "Created", "driver": "dir",
                     "config": {"source": str(lab.POOL_SOURCE)}}
        self.network = {"type": "bridge", "managed": True,
                        "config": {"ipv4.nat": "true"}}
        self.available = 250 * lab.GIB
        self.memory = 30 * lab.GIB

    def query(self, path, **kwargs):
        self.calls.append(("query", path))
        if path.startswith("/1.0/instances/"):
            return copy.deepcopy(lab.find(self.items, path.rsplit("/", 1)[1]))
        return {
            "/1.0/storage-pools/odq-lab": self.pool,
            "/1.0/networks/incusbr0": self.network,
            "/1.0/storage-pools/odq-lab/resources": {
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
            lab.find(self.items, args[1])["status"] = "Running"
        elif args == ("exec", "odq-gnome", "--", "systemctl", "poweroff", "--no-block"):
            self.items[0]["status"] = "Stopped"
        return ""


def writes(api):
    return [call for call in api.calls if call[0] != "query"]


@pytest.fixture(autouse=True)
def simulated_host_storage(monkeypatch, tmp_path):
    # Never inspect real storage during orchestration tests. Dedicated tests
    # exercise the measurement helper with subprocess and statvfs stubs.
    monkeypatch.setattr(lab, "storage_usage", lambda: (20 * lab.GIB, 200 * lab.GIB))
    # An empty guest reserves its whole 40 GiB growth plus the 10 GiB reserve.
    monkeypatch.setattr(lab, "guest_usage", lambda name: 0)
    # The PID namespace does not isolate /tmp. Tests must not contend with a
    # real provisioning operation or with another independent test checkout.
    monkeypatch.setattr(lab, "LOCK_PATH", str(tmp_path / "lab.lock"))


def test_unavailable_pool_stops_before_any_host_mutation():
    api = FakeIncus()
    api.pool["status"] = "Unavailable"
    with pytest.raises(lab.LabError, match="never imports"):
        lab.preflight(api, creating=True)
    assert not writes(api)
    assert api.calls == [("query", "/1.0/storage-pools/odq-lab")]


def test_55_gib_pool_allows_one_disk_not_four_and_preserves_bots():
    api = FakeIncus()
    api.available = 55 * lab.GIB
    api.items = [{"name": "bots", "type": "container", "status": "Stopped"}]
    check = lab.preflight(api, creating=True)
    assert check["required_bytes"] == 50 * lab.GIB
    assert not writes(api)
    assert api.items == [{"name": "bots", "type": "container", "status": "Stopped"}]


@pytest.mark.parametrize("used", [0, 20, 100])
def test_budget_and_floor_exact_boundaries_allow_thin_disks(monkeypatch, used):
    api = FakeIncus()
    api.available = 50 * lab.GIB  # dir resources are the shared filesystem
    api.items = [instance(name) for name in lab.NAMES]
    monkeypatch.setattr(lab, "storage_usage", lambda: (used * lab.GIB, 100 * lab.GIB))
    check = lab.preflight(api, creating=True)
    assert check["allocated_bytes"] == used * lab.GIB
    assert check["required_bytes"] == 50 * lab.GIB
    assert check["reserved_bytes"] == {"new": 50 * lab.GIB}
    assert check["filesystem_required_bytes"] == 100 * lab.GIB
    assert check["budget_bytes"] == 150 * lab.GIB
    assert check["max_running_vms"] == 2
    assert all("/storage-pools/default" not in str(call) for call in api.calls)


@pytest.mark.parametrize("operation", ["create", "start", "provision", "smoke", "snapshot"])
@pytest.mark.parametrize("failure", ["budget", "floor", "pool-headroom"])
def test_all_storage_consuming_operations_gate_before_writes(
    tmp_path, monkeypatch, operation, failure,
):
    api = FakeIncus()
    api.items = ([] if operation == "create" else
                 [instance(status="Running" if operation in ("provision", "smoke")
                           else "Stopped")])
    if failure == "budget":
        monkeypatch.setattr(lab, "storage_usage", lambda: (100 * lab.GIB + 1, 200 * lab.GIB))
        message = "150 GiB aggregate budget"
    elif failure == "floor":
        # One byte short of the floor after this guest's 40 GiB growth + reserve.
        monkeypatch.setattr(lab, "storage_usage", lambda: (20 * lab.GIB, 100 * lab.GIB - 1))
        message = "50 GiB filesystem floor"
    else:
        api.available = 50 * lab.GIB - 1
        message = "guest growth"
    target = tmp_path / "evidence"
    with pytest.raises(lab.LabError, match=message):
        if operation == "snapshot":
            lab.snapshot(api, "odq-gnome", "configured")
        elif operation == "smoke":
            lab.smoke(api, "odq-gnome", target)
        else:
            getattr(lab, operation)(api, "odq-gnome")
    assert not writes(api)
    assert not target.exists()


@pytest.mark.parametrize("change", ["driver", "source", "status", "config"])
def test_only_exact_created_lab_dir_pool_is_accepted(change):
    api = FakeIncus()
    if change == "config":
        del api.pool["config"]
    elif change == "source":
        api.pool["config"]["source"] = "/mnt/storage/incus"
    else:
        api.pool[change] = "zfs" if change == "driver" else "Unavailable"
    with pytest.raises(lab.LabError, match="create it externally"):
        lab.preflight(api)
    assert api.calls == [("query", "/1.0/storage-pools/odq-lab")]


def test_old_pool_root_is_not_owned_even_with_lab_marker():
    api = FakeIncus()
    item = instance()
    item["expanded_devices"]["root"]["pool"] = "default"
    api.items = [item]
    with pytest.raises(lab.LabError, match="caps/devices/isolation"):
        lab.remove(api, "odq-gnome")
    assert not writes(api)


def test_storage_measurement_counts_allocated_pool_bytes_and_available_filesystem(
    tmp_path, monkeypatch,
):
    pool = tmp_path / "odq-lab"
    pool.mkdir()
    monkeypatch.setattr(lab, "POOL_SOURCE", pool)
    monkeypatch.setattr(lab, "STORAGE_PATH", tmp_path)
    calls = []
    def execute(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=f"123456\t{pool}\n", stderr="")
    monkeypatch.setattr(lab.subprocess, "run", execute)
    monkeypatch.setattr(lab.os, "statvfs", lambda _: SimpleNamespace(
        f_bavail=1000, f_bfree=2000, f_frsize=4096,
    ))
    assert REAL_STORAGE_USAGE() == (123456, 1000 * 4096)
    assert calls[0][0] == ["sudo", "-n", "du", "-s", "-B1", "--", str(pool)]
    assert calls[0][1]["stdin"] == subprocess.DEVNULL
    assert calls[0][1]["timeout"] == 60


@pytest.mark.parametrize("output,returncode", [("", 0), ("invalid", 0), ("-1", 0),
                                               ("12345", 1)])
def test_failed_partial_or_invalid_du_is_not_zero_usage(tmp_path, monkeypatch, output, returncode):
    pool = tmp_path / "odq-lab"
    pool.mkdir()
    monkeypatch.setattr(lab, "POOL_SOURCE", pool)
    monkeypatch.setattr(lab, "STORAGE_PATH", tmp_path)
    monkeypatch.setattr(lab.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=returncode, stdout=output, stderr="partial traversal denied",
    ))
    with pytest.raises(lab.LabError):
        REAL_STORAGE_USAGE()


def test_storage_source_symlink_refuses_measurement(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    pool = tmp_path / "odq-lab"
    pool.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(lab, "POOL_SOURCE", pool)
    monkeypatch.setattr(lab, "STORAGE_PATH", tmp_path)
    monkeypatch.setattr(lab.subprocess, "run", lambda *a, **k: pytest.fail("no du on symlink"))
    with pytest.raises(lab.LabError, match="real directory"):
        REAL_STORAGE_USAGE()


def test_guest_measurement_counts_only_the_owned_guest_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(lab, "POOL_SOURCE", tmp_path / "odq-lab")
    calls = []
    def execute(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=f"4096\t{argv[-1]}\n", stderr="")
    monkeypatch.setattr(lab.subprocess, "run", execute)
    assert REAL_GUEST_USAGE("odq-kde") == 4096
    assert calls[0][0] == ["sudo", "-n", "du", "-s", "-B1", "--",
                           str(tmp_path / "odq-lab/virtual-machines/odq-kde")]
    assert calls[0][1]["stdin"] == subprocess.DEVNULL
    assert calls[0][1]["timeout"] == 60


@pytest.mark.parametrize("name", ["bots", "../odq-kde", "odq-kde/../../etc", ""])
def test_guest_measurement_refuses_names_outside_the_lab(monkeypatch, name):
    monkeypatch.setattr(lab.subprocess, "run", lambda *a, **k: pytest.fail("no du"))
    with pytest.raises(lab.LabError, match="Unknown lab VM name"):
        REAL_GUEST_USAGE(name)


@pytest.mark.parametrize("output,returncode", [("", 0), ("invalid", 0), ("-1", 0),
                                               ("12345", 1)])
def test_failed_or_invalid_guest_du_is_not_zero_usage(monkeypatch, output, returncode):
    monkeypatch.setattr(lab.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=returncode, stdout=output, stderr="cannot access",
    ))
    with pytest.raises(lab.LabError):
        REAL_GUEST_USAGE("odq-kde")


def test_snapshots_require_explicit_cli_opt_in():
    with pytest.raises(SystemExit):
        lab.main(["snapshot", "odq-gnome"])


@pytest.mark.parametrize("action", ["create", "start", "stop", "provision", "snapshot",
                                    "remove", "smoke"])
def test_cli_dispatches_only_explicit_owned_action(action, monkeypatch, tmp_path):
    api = FakeIncus()
    monkeypatch.setattr(lab, "Incus", lambda: api)
    calls = []
    monkeypatch.setattr(lab, action, lambda *args: calls.append(args))
    argv = [action, "odq-gnome"]
    if action == "snapshot":
        argv.extend(["--label", "configured"])
    if action == "smoke":
        argv.extend(["--evidence", str(tmp_path / "proof")])
    assert lab.main(argv) == 0
    assert calls[0][:2] == (api, "odq-gnome")
    assert len(calls) == 1
    if action == "snapshot":
        assert calls[0][2] == "configured"


def test_cli_preflight_reports_storage_policy_without_writes(monkeypatch, capsys):
    api = FakeIncus()
    monkeypatch.setattr(lab, "Incus", lambda: api)
    assert lab.main(["preflight"]) == 0
    check = json.loads(capsys.readouterr().out)
    assert check["pool"] == "odq-lab"
    assert check["budget_bytes"] == 150 * lab.GIB
    assert check["filesystem_floor_bytes"] == 50 * lab.GIB
    assert not writes(api)


@pytest.mark.parametrize("status", ["Running", "Starting", "Frozen", "Error"])
def test_one_other_nonstopped_vm_allows_a_second_boot(status):
    api = FakeIncus()
    api.items = [instance(), instance("odq-kde", status)]
    lab.start(api, "odq-gnome")
    assert writes(api) == [("start", "odq-gnome"), ("exec", "odq-gnome", "--", "/bin/true")]
    assert lab.find(api.items, "odq-kde")["status"] == status


@pytest.mark.parametrize("status", ["Running", "Starting", "Frozen", "Error"])
def test_two_other_nonstopped_vms_prevent_a_third_boot(status):
    api = FakeIncus()
    api.items = [instance(), instance("odq-kde", status), instance("odq-cinnamon", "Running")]
    with pytest.raises(lab.LabError, match="2 other VMs are not stopped"):
        lab.start(api, "odq-gnome")
    assert not writes(api)


@pytest.mark.parametrize("operation", ["create", "snapshot", "provision", "smoke"])
def test_two_running_vms_also_block_other_storage_operations(tmp_path, operation):
    api = FakeIncus()
    target = "odq-hyprland"
    api.items = [instance("odq-kde", "Running"), instance("odq-cinnamon", "Running")]
    if operation != "create":
        status = "Running" if operation in ("provision", "smoke") else "Stopped"
        api.items.append(instance(target, status))
    with pytest.raises(lab.LabError, match="other VMs are not stopped"):
        if operation == "snapshot":
            lab.snapshot(api, target, "configured")
        elif operation == "smoke":
            lab.smoke(api, target, tmp_path / "evidence")
        else:
            getattr(lab, operation)(api, target)
    assert not writes(api)


@pytest.mark.parametrize("operation", ["create", "start", "snapshot"])
def test_running_vm_outside_the_lab_blocks_lab_operations(operation):
    api = FakeIncus()
    api.items = [instance(), {"name": "other", "type": "virtual-machine", "status": "Running"}]
    with pytest.raises(lab.LabError, match="VM outside the lab is not stopped: other"):
        if operation == "snapshot":
            lab.snapshot(api, "odq-gnome", "configured")
        else:
            getattr(lab, operation)(api, "odq-kde" if operation == "create" else "odq-gnome")
    assert not writes(api)


def test_running_container_in_the_lab_pool_blocks_lab_operations():
    api = FakeIncus()
    container = {"name": "odq-p42-packages", "type": "container", "status": "Running",
                 "expanded_devices": {"root": {"type": "disk", "path": "/", "pool": lab.POOL}}}
    api.items = [instance(), container]
    with pytest.raises(lab.LabError, match="Container odq-p42-packages in the lab pool"):
        lab.start(api, "odq-gnome")
    assert not writes(api)
    # A container on another pool does not draw on the lab pool or its floor.
    container["expanded_devices"]["root"]["pool"] = "default"
    lab.start(api, "odq-gnome")
    assert ("start", "odq-gnome") in writes(api)


def test_running_guests_reserve_their_remaining_growth(monkeypatch):
    api = FakeIncus()
    api.items = [instance(), instance("odq-kde", "Running")]
    usage = {"odq-gnome": 12 * lab.GIB, "odq-kde": 15 * lab.GIB}
    monkeypatch.setattr(lab, "guest_usage", usage.__getitem__)
    check = lab.preflight(api, name="odq-gnome")
    # Each guest can still grow to its 40 GiB cap, plus the 10 GiB reserve.
    assert check["reserved_bytes"] == {"odq-kde": 35 * lab.GIB, "odq-gnome": 38 * lab.GIB}
    assert check["required_bytes"] == 73 * lab.GIB
    assert check["filesystem_required_bytes"] == 123 * lab.GIB


def test_guest_at_its_cap_reserves_only_the_overhead(monkeypatch):
    api = FakeIncus()
    api.items = [instance()]
    monkeypatch.setattr(lab, "guest_usage", lambda name: 41 * lab.GIB)
    assert lab.preflight(api, name="odq-gnome")["required_bytes"] == 10 * lab.GIB


@pytest.mark.parametrize("failure", ["budget", "floor"])
def test_second_guest_is_refused_when_both_guests_growth_does_not_fit(monkeypatch, failure):
    api = FakeIncus()
    api.items = [instance(), instance("odq-kde")]
    monkeypatch.setattr(lab, "guest_usage", lambda name: 15 * lab.GIB)
    # Alone, odq-gnome needs 35 GiB; with odq-kde running, both need 70 GiB.
    if failure == "budget":
        storage, message = (80 * lab.GIB + 1, 200 * lab.GIB), "aggregate budget"
    else:
        storage, message = (20 * lab.GIB, 120 * lab.GIB - 1), "filesystem floor"
    monkeypatch.setattr(lab, "storage_usage", lambda: storage)
    assert lab.preflight(api, name="odq-gnome")["required_bytes"] == 35 * lab.GIB
    lab.find(api.items, "odq-kde")["status"] = "Running"
    with pytest.raises(lab.LabError, match=message):
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


def test_create_uses_exact_image_no_profiles_and_thin_disk(monkeypatch):
    api = FakeIncus()
    monkeypatch.setattr(lab, "image_spec", lambda _: {"fingerprint": "a" * 64})
    lab.create(api, "odq-gnome")
    [init] = writes(api)
    assert init[:4] == ("init", f"images:{'a' * 64}", "odq-gnome", "--vm")
    assert "--no-profiles" in init
    assert "limits.cpu=4" in init and "limits.memory=8GiB" in init
    assert "root,size=40GiB" in init and "boot.autostart=false" in init
    assert init[init.index("--storage") + 1] == lab.POOL
    assert "reserve_space" not in str(api.calls)
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
    assert writes(api) == [("start", "odq-gnome"),
                           ("exec", "odq-gnome", "--", "systemctl", "poweroff", "--no-block")]
    assert api.items[0]["status"] == "Stopped"


def test_stop_uses_agent_poweroff_not_acpi_suspend():
    api = FakeIncus()
    api.items = [instance("odq-cinnamon", status="Running")]
    def execute(*args, **kwargs):
        api.calls.append(args)
        if args[0] == "stop":
            api.items[0]["status"] = "Frozen"  # observed ACPI suspend failure
            pytest.fail("ACPI power-key stop can suspend Cinnamon and lose the agent")
        assert args == ("exec", "odq-cinnamon", "--", "systemctl", "poweroff", "--no-block")
        assert kwargs == {"capture": True, "timeout": 10}
        api.items[0]["status"] = "Stopped"
        return ""
    api.run = execute
    lab.stop(api, "odq-cinnamon")
    assert len(writes(api)) == 1


def test_stop_does_not_force_after_timeout():
    api = FakeIncus()
    api.items = [instance(status="Running")]
    def fail(*args, **kwargs):
        api.calls.append(args)
        raise lab.LabError("timeout")
    api.run = fail
    with pytest.raises(lab.LabError, match="timeout"):
        lab.stop(api, "odq-gnome")
    assert writes(api) == [("exec", "odq-gnome", "--", "systemctl", "poweroff", "--no-block")]


@pytest.mark.parametrize("failure", [lab.LabError("agent unavailable"),
                                    subprocess.TimeoutExpired("incus exec", 10)])
def test_stop_unavailable_agent_is_explicit_without_replay(failure):
    api = FakeIncus()
    api.items = [instance(status="Running")]
    def fail(*args, **kwargs):
        api.calls.append(args)
        raise failure
    api.run = fail
    message = "Guest agent poweroff failed or outcome unknown.*no forced stop/replay"
    with pytest.raises(lab.LabError, match=message):
        lab.stop(api, "odq-gnome")
    assert writes(api) == [("exec", "odq-gnome", "--", "systemctl", "poweroff", "--no-block")]


@pytest.mark.parametrize("stopped", [False, True])
def test_stop_polls_bounded_status_without_replaying_request(monkeypatch, stopped):
    api = FakeIncus()
    api.items = [instance(status="Running")]
    elapsed = [0]
    polls = []
    monkeypatch.setattr(lab.time, "monotonic", lambda: elapsed[0])
    def sleep(seconds):
        elapsed[0] += seconds
    monkeypatch.setattr(lab.time, "sleep", sleep)
    def query(path, **kwargs):
        assert path == "/1.0/instances/odq-gnome"
        polls.append(kwargs["timeout"])
        if stopped and len(polls) == 3:
            api.items[0]["status"] = "Stopped"
        return copy.deepcopy(api.items[0])
    api.query = query
    api.run = lambda *args, **kwargs: api.calls.append(args)
    if stopped:
        lab.stop(api, "odq-gnome")
        assert len(polls) == 3
    else:
        with pytest.raises(lab.LabError, match="Stopped after 180s; no forced stop/replay"):
            lab.stop(api, "odq-gnome")
        assert elapsed[0] == 180
    assert all(0 < timeout <= 10 for timeout in polls)
    assert writes(api) == [("exec", "odq-gnome", "--", "systemctl", "poweroff", "--no-block")]


@pytest.mark.parametrize("change", ["owner", "caps", "devices"])
def test_stop_refuses_changed_ownership_or_isolation_before_poweroff(change):
    api = FakeIncus()
    api.items = [instance(status="Running")]
    if change == "owner":
        api.items[0]["config"].clear()
    elif change == "caps":
        api.items[0]["expanded_config"]["limits.cpu"] = "8"
    else:
        api.items[0]["expanded_devices"]["share"] = {"type": "disk"}
    with pytest.raises(lab.LabError):
        lab.stop(api, "odq-gnome")
    assert not writes(api)


@pytest.mark.parametrize("failure", [lab.LabError("metadata unavailable"),
                                    subprocess.TimeoutExpired("incus query", 10),
                                    "ownership"])
def test_stop_status_failure_or_ownership_change_cannot_replay(failure):
    api = FakeIncus()
    api.items = [instance(status="Running")]
    def query(path, **kwargs):
        if failure == "ownership":
            api.items[0]["config"].clear()
            return copy.deepcopy(api.items[0])
        raise failure
    api.query = query
    api.run = lambda *args, **kwargs: api.calls.append(args)
    message = "Cannot confirm guest poweroff.*no forced stop/replay"
    with pytest.raises(lab.LabError, match=message):
        lab.stop(api, "odq-gnome")
    assert writes(api) == [("exec", "odq-gnome", "--", "systemctl", "poweroff", "--no-block")]


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
    assert changes[6] == ("exec", "odq-gnome", "--", "systemctl", "poweroff", "--no-block")


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
    assert all(kwargs["stdin"] == subprocess.DEVNULL for _, kwargs in calls)


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


def test_incus_capture_failure_preserves_guest_stdout_error(monkeypatch):
    error = '{"passed": false, "error": "native capture denied"}\n'
    monkeypatch.setattr(lab.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout=error, stderr="",
    ))
    with pytest.raises(lab.LabError, match="native capture denied"):
        lab.Incus().run("exec", "odq-gnome", "--", "python3",
                        "/root/odq/smoke.py", "gnome", capture=True)


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
            if args[3] == "sha256sum":
                return guest_hash_output(args[5:])
            return json.dumps({"passed": True, "session": {"Type": "wayland"}})
        if args[:2] == ("file", "pull"):
            local = Path(args[3])
            assert local.is_file()
            assert local.stat().st_uid == lab.os.getuid()
            assert local.stat().st_mode & 0o777 == 0o600
            Path(args[3]).write_bytes(b"\x89PNG\r\n\x1a\nfixture")
        return ""
    api.run = execute
    monkeypatch.setattr(lab, "image_spec", lambda _: {"fingerprint": "a" * 64})
    monkeypatch.setattr(lab.subprocess, "check_output", lambda *a, **k: "fixture-sha\n")
    target = tmp_path / "evidence"
    lab.smoke(api, "odq-gnome", target)
    saved = json.loads((target / "proof.json").read_text())
    assert saved["source_sha"] == "fixture-sha"
    assert saved["source_dirty"] is True
    assert saved["source_matches"] is True
    assert saved["image"] == {"fingerprint": "a" * 64}
    assert saved["host_files_sha256"][
        "scripts/qualification/lab/images/gnome.json"
    ] == hashlib.sha256((lab.HERE / "images/gnome.json").read_bytes()).hexdigest()
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


def guest_hash_output(paths, *, stale=None):
    """Simulate sha256sum, including a separately generated capture artifact."""
    lines = []
    for path in paths:
        data = (b"generated guest capture\n" if path == "/usr/local/lib/odq/capture"
                else (lab.HERE / "guest" / Path(path).name).read_bytes())
        if path == stale:
            data += b"stale guest recipe\n"
        lines.append(f"{hashlib.sha256(data).hexdigest()}  {path}\n")
    return "".join(lines)


@pytest.mark.parametrize("name", lab.NAMES)
@pytest.mark.parametrize("dirty", [False, True])
def test_smoke_provenance_exact_host_guest_image_fixture(tmp_path, monkeypatch, name, dirty):
    root = tmp_path / "checkout"
    here = root / "scripts/qualification/lab"
    (here / "guest").mkdir(parents=True)
    (here / "images").mkdir()
    desktop = name[4:]
    files = {"lab.py": b"fixture orchestration\n", "guest/common.sh": b"common\n",
             "guest/smoke.py": b"smoke\n", f"guest/{desktop}.sh": desktop.encode(),
             f"images/{desktop}.json": b'{"fingerprint":"fixture image"}\n'}
    for relative, data in files.items():
        (here / relative).write_bytes(data)
    monkeypatch.setattr(lab, "ROOT", root)
    monkeypatch.setattr(lab, "HERE", here)
    git_calls = []
    def git(argv, **kwargs):
        git_calls.append((argv, kwargs))
        return "base-commit\n" if argv[1] == "rev-parse" else (" M lab.py\n" if dirty else "")
    monkeypatch.setattr(lab.subprocess, "check_output", git)
    api = FakeIncus()
    def execute(*args, **kwargs):
        api.calls.append(args)
        assert kwargs == {"capture": True, "timeout": 30}
        return guest_hash_output(args[5:])
    api.run = execute
    proof = lab.smoke_provenance(api, name)
    host = {f"scripts/qualification/lab/{path}": hashlib.sha256(data).hexdigest()
            for path, data in files.items()}
    uploaded = {f"/root/odq/{Path(path).name}": f"scripts/qualification/lab/{path}"
                for path in files if path.startswith("guest/")}
    capture = "/usr/local/lib/odq/capture"
    assert proof == {
        "source_sha": "base-commit", "source_dirty": dirty,
        "host_files_sha256": host,
        "guest_files_sha256": {
            **{path: host[source] for path, source in uploaded.items()},
            capture: hashlib.sha256(b"generated guest capture\n").hexdigest(),
        },
        "source_comparison": {
            **{path: {"host_path": source, "matches": True}
               for path, source in uploaded.items()},
            capture: {"host_path": None, "matches": None,
                      "reason": "Generated guest artifact; no host byte-equivalent comparison"},
        },
        "source_matches": True,
    }
    assert api.calls == [("exec", name, "--", "sha256sum", "--", *uploaded, capture)]
    assert git_calls == [
        (["git", "rev-parse", "HEAD"], {"cwd": root, "text": True}),
        (["git", "status", "--porcelain", "--untracked-files=all"],
         {"cwd": root, "text": True}),
    ]


@pytest.mark.parametrize("stale", ["common.sh", "smoke.py", "gnome.sh"])
def test_smoke_stale_uploaded_script_records_truthful_failure(tmp_path, monkeypatch, stale):
    api = FakeIncus()
    api.items = [instance(status="Running")]
    stale_path = f"/root/odq/{stale}"
    def execute(*args, **kwargs):
        api.calls.append(args)
        if args[0] == "exec":
            if args[3] == "sha256sum":
                return guest_hash_output(args[5:], stale=stale_path)
            return '{"passed": true}'
        Path(args[3]).write_bytes(b"\x89PNG\r\n\x1a\nfixture")
        return ""
    api.run = execute
    monkeypatch.setattr(lab.subprocess, "check_output", lambda *a, **k: "base-commit\n")
    target = tmp_path / "stale"
    with pytest.raises(lab.LabError, match="reprovision required"):
        lab.smoke(api, "odq-gnome", target)
    proof = json.loads((target / "proof.json").read_text())
    assert proof["passed"] is False
    assert proof["source_matches"] is False
    assert proof["source_comparison"][stale_path]["matches"] is False
    host_path = proof["source_comparison"][stale_path]["host_path"]
    assert proof["host_files_sha256"][host_path] != proof["guest_files_sha256"][stale_path]
    assert proof["image"] == lab.image_spec("odq-gnome")
    assert (target / "guest.png").is_file()
    assert all(call[0] in ("query", "exec", "file") for call in api.calls)


@pytest.mark.parametrize("failure", ["missing", "duplicate", "invalid", "unexpected"])
def test_guest_hash_output_cannot_forge_provenance(failure):
    api = FakeIncus()
    def execute(*args, **kwargs):
        lines = guest_hash_output(args[5:]).splitlines()
        if failure == "missing":
            lines.pop()
        elif failure == "duplicate":
            lines.append(lines[0])
        elif failure == "invalid":
            lines[0] = "not a sha256sum digest"
        else:
            lines[0] = "a" * 64 + "  /unexpected"
        return "\n".join(lines)
    api.run = execute
    with pytest.raises(lab.LabError, match="guest sha256sum provenance output"):
        lab.smoke_provenance(api, "odq-gnome")


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
    monkeypatch.setattr(lab, "LOCK_WAIT_SECONDS", 0)
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


def test_lock_waits_for_the_other_command_then_runs(tmp_path, monkeypatch):
    holder = os.open(lab.LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(holder, fcntl.LOCK_EX)
    sleeps = []
    def sleep(seconds):
        sleeps.append(seconds)
        os.close(holder)  # the other lane's command finishes
    monkeypatch.setattr(lab, "time", SimpleNamespace(monotonic=lambda: 0, sleep=sleep))
    ran = []
    with lab.mutation_lock():
        ran.append(True)
    assert ran == [True]
    assert sleeps == [2]


def test_lock_wait_is_bounded(tmp_path, monkeypatch):
    holder = os.open(lab.LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(holder, fcntl.LOCK_EX)
    times = iter((0, 0, 600, 900))
    sleeps = []
    monkeypatch.setattr(lab, "time", SimpleNamespace(monotonic=lambda: next(times),
                                                     sleep=sleeps.append))
    try:
        with pytest.raises(lab.LabError, match="Another lab command is active after 900s"):
            with lab.mutation_lock():
                pytest.fail("the lock is still held")
    finally:
        os.close(holder)
    assert sleeps == [2, 2]


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
