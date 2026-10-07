"""Behavior of the disposable container controller, never a live Incus daemon."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts/packaging/acceptance.py"
SPEC = importlib.util.spec_from_file_location("p42_acceptance", PATH)
acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)


def instance():
    return {
        "name": acceptance.NAME, "type": "container", "profiles": [], "status": "Running",
        "expanded_devices": copy.deepcopy(acceptance.DEVICES),
        "expanded_config": {"user.odq.owner": acceptance.MARKER,
                            "boot.autostart": "false", "limits.cpu": "2",
                            "limits.memory": "4GiB", "security.privileged": "false"},
    }


class FakeIncus:
    def __init__(self):
        self.item = instance()
        self.calls = []

    def instances(self):
        return [] if self.item is None else [self.item]

    def query(self, path):
        if path.endswith("storage-pools/odq-lab"):
            return {"driver": "dir", "status": "Created",
                    "config": {"source": "/mnt/storage/odq-lab"}}
        if path.endswith("networks/incusbr0"):
            return {"managed": True, "config": {"ipv4.nat": "true"}}
        if path.endswith("resources"):
            return {"memory": {"total": 64 * acceptance.GIB, "used": 20 * acceptance.GIB}}
        raise AssertionError(path)

    def run(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if args[0] == "stop":
            self.item["status"] = "Stopped"
        if args[0] == "delete":
            self.item = None
        return "captured"


@pytest.mark.parametrize("field,value", [
    ("type", "virtual-machine"), ("name", "bots"), ("profiles", ["default"]),
    ("expanded_devices", {"root": acceptance.DEVICES["root"],
                          "host": {"type": "disk", "source": "/", "path": "/host"}}),
])
def test_refuses_foreign_or_exposed_targets(field, value):
    api = FakeIncus()
    api.item[field] = value
    with pytest.raises(acceptance.AcceptanceError):
        acceptance.Container(api).exec("/bin/true")
    assert not api.calls


@pytest.mark.parametrize("key,value", [
    ("user.odq.owner", "foreign"), ("security.privileged", "true"),
    ("raw.lxc", "arbitrary"), ("limits.memory", "8GiB"),
    ("security.nesting", "true"),
])
def test_security_identity_is_rechecked_for_every_operation(key, value):
    api = FakeIncus()
    api.item["expanded_config"][key] = value
    with pytest.raises(acceptance.AcceptanceError):
        acceptance.Container(api).push(PATH, "/p42-inputs/controller.py")
    assert not api.calls


def test_push_cannot_target_other_paths():
    api = FakeIncus()
    with pytest.raises(acceptance.AcceptanceError):
        acceptance.Container(api).push(PATH, "/etc/controller.py")
    assert not api.calls


def test_exec_rechecks_identity_and_stays_inside_container():
    api = FakeIncus()
    assert acceptance.Container(api).exec("/usr/bin/id", capture=True) == "captured"
    args, kwargs = api.calls[0]
    assert args == ("exec", acceptance.NAME, "--env", "DEBIAN_FRONTEND=noninteractive",
                    "--", "/usr/bin/id")
    assert kwargs["capture"] is True


def test_cleanup_gracefully_stops_and_removes_exact_owned_container_only():
    api = FakeIncus()
    result = acceptance.Container(api).cleanup()
    assert result == {"container_removed": True, "host_services_touched": False}
    assert [call[0] for call in api.calls] == [
        ("stop", acceptance.NAME, "--timeout", "30"), ("delete", acceptance.NAME)]


def test_storage_budget_failure_never_creates_guest():
    api = FakeIncus()
    used = acceptance.lab.POOL_BUDGET - 14 * acceptance.GIB + 1
    with patch.object(acceptance.lab, "storage_usage",
                      return_value=(used, 200 * acceptance.GIB)):
        with pytest.raises(acceptance.AcceptanceError, match="storage budget"):
            acceptance.Container(api).prepare()
    assert not api.calls


def lab_vm(name="odq-kde", status="Running", size="40GiB"):
    return {"name": name, "status": status, "type": "virtual-machine", "profiles": [],
            "config": {"user.odq.owner": acceptance.lab.MARKER},
            "expanded_config": {"limits.cpu": "4", "limits.memory": "8GiB",
                                "boot.autostart": "false"},
            "expanded_devices": {
                "root": {"type": "disk", "path": "/", "pool": "odq-lab", "size": size},
                "eth0": {"type": "nic", "network": "incusbr0", "name": "eth0"}}}


@pytest.mark.parametrize("failure", ["budget", "floor"])
def test_running_lab_vm_growth_counts_against_the_container(failure):
    api = FakeIncus()
    vm = lab_vm()
    api.instances = lambda: [api.item, vm]
    gib = acceptance.GIB
    # The container alone needs 14 GiB; the running VM at 15 GiB adds 25 + 10 GiB.
    if failure == "budget":
        storage = (acceptance.lab.POOL_BUDGET - 49 * gib + 1, 200 * gib)
        message = "storage budget"
    else:
        storage = (20 * gib, acceptance.lab.FILESYSTEM_FLOOR + 49 * gib - 1)
        message = "filesystem floor"
    with patch.object(acceptance.lab, "storage_usage", return_value=storage), \
            patch.object(acceptance.lab, "guest_usage", return_value=15 * gib):
        with pytest.raises(acceptance.AcceptanceError, match=message):
            acceptance.Container(api).prepare()
    assert not api.calls


def test_vm_growth_is_measured_before_the_pool():
    api = FakeIncus()
    api.instances = lambda: [api.item, lab_vm()]
    order = []
    def guest(name):
        order.append("guest")
        return 15 * acceptance.GIB
    def pool():
        order.append("pool")
        return 20 * acceptance.GIB, 200 * acceptance.GIB
    with patch.object(acceptance.lab, "storage_usage", pool), \
            patch.object(acceptance.lab, "guest_usage", guest):
        acceptance.Container(api).prepare()
    # A guest growing between the two reads is then over-reserved, never under.
    assert order == ["guest", "pool"]


@pytest.mark.parametrize("change", ["cap", "outside"])
def test_unbounded_running_vm_fails_closed_before_growth_math(change):
    api = FakeIncus()
    vm = (lab_vm(size="80GiB") if change == "cap"
          else {"name": "other", "type": "virtual-machine", "status": "Running"})
    api.instances = lambda: [api.item, vm]
    with patch.object(acceptance.lab, "storage_usage", side_effect=AssertionError("pool read")), \
            patch.object(acceptance.lab, "guest_usage", side_effect=AssertionError("du")):
        with pytest.raises(acceptance.lab.LabError,
                           match="caps/devices" if change == "cap" else "outside the lab"):
            acceptance.Container(api).prepare()
    assert not api.calls


def test_reuse_preserves_running_vm_and_only_uses_owned_light_container():
    api = FakeIncus()
    with patch.object(acceptance.lab, "storage_usage",
                      return_value=(20 * acceptance.GIB, 200 * acceptance.GIB)):
        result = acceptance.Container(api).prepare()
    assert result["reused"] is True
    assert not api.calls


def test_refuses_stopped_leftover_instead_of_silently_reusing_it():
    api = FakeIncus()
    api.item["status"] = "Stopped"
    with patch.object(acceptance.lab, "storage_usage",
                      return_value=(20 * acceptance.GIB, 200 * acceptance.GIB)):
        with pytest.raises(acceptance.AcceptanceError, match="explicit cleanup"):
            acceptance.Container(api).prepare()
    assert not api.calls
