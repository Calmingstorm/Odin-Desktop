"""Rootless containment behavior. No real cgroups, desktop or guest controls."""

import importlib.util
import signal
import types
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts/qualification/lab/guest/owned_processes.py"
spec = importlib.util.spec_from_file_location("odq_owned_test", PATH)
owned = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owned)


@pytest.fixture
def group(tmp_path, monkeypatch):
    obj = owned.OwnedProcesses.__new__(owned.OwnedProcesses)
    obj.path = tmp_path / ("odq-orca-" + "a" * 32)
    obj.path.mkdir()
    monkeypatch.setattr(
        obj, "identities", lambda: [{"pid": 111, "starttime": 9, "uid": 1000, "state": "S"}]
    )
    return obj


def test_dead_leader_does_not_shortcircuit_descendant_cleanup(group, monkeypatch):
    calls = []
    child = types.SimpleNamespace(
        returncode=0, wait=lambda timeout: calls.append(("wait", timeout))
    )
    monkeypatch.setattr(group, "signal_members", lambda: calls.append("pidfd-term-descendants"))
    monkeypatch.setattr(
        group, "wait_empty", lambda timeout: calls.append(("empty", timeout)) or True
    )
    monkeypatch.setattr(group, "populated", lambda: False)
    result = group.cleanup([child])
    assert calls[0] == "pidfd-term-descendants"
    assert result["descendants_exited"] and result["owned_children_exited"]
    assert not group.path.exists()


def test_concurrent_fork_and_detached_children_get_atomic_cgroup_kill(group, monkeypatch):
    calls = []
    waits = iter([False, True])
    monkeypatch.setattr(group, "signal_members", lambda: calls.append("term"))
    monkeypatch.setattr(group, "wait_empty", lambda timeout: calls.append(timeout) or next(waits))
    monkeypatch.setattr(group, "kill", lambda: calls.append("atomic-kill-descendants"))
    monkeypatch.setattr(group, "populated", lambda: False)
    result = group.cleanup([])
    assert calls == ["term", 15, "atomic-kill-descendants", 5]
    assert result["escalated"] and result["descendants_exited"]


def test_unconfirmed_drain_keeps_group_and_failure(group, monkeypatch):
    monkeypatch.setattr(group, "signal_members", lambda: None)
    monkeypatch.setattr(group, "wait_empty", lambda timeout: False)
    monkeypatch.setattr(group, "kill", lambda: None)
    result = group.cleanup([])
    assert not result["descendants_exited"] and not result["owned_children_exited"]
    assert group.path.exists()
    assert "still populated" in result["error"]


def test_proc_error_fails_closed_no_global_signal(group, monkeypatch):
    def fail():
        raise PermissionError("proc unavailable")

    monkeypatch.setattr(group, "signal_members", fail)
    monkeypatch.setattr(group, "kill", lambda: pytest.fail("unknown ownership cannot kill"))
    result = group.cleanup([])
    assert not result["descendants_exited"]
    assert group.path.exists()


def test_pidfd_membership_checked_before_signal(group, monkeypatch):
    calls = []
    monkeypatch.setattr(group, "members", lambda: [111])
    monkeypatch.setattr(owned.os, "pidfd_open", lambda pid: calls.append(("open", pid)) or 40)
    monkeypatch.setattr(owned.os, "close", lambda fd: calls.append(("close", fd)))
    monkeypatch.setattr(Path, "read_text", lambda *a, **kw: "0::/" + group.path.name + "\n")
    monkeypatch.setattr(
        owned.signal, "pidfd_send_signal", lambda fd, sig: calls.append(("signal", fd, sig))
    )
    group.signal_members()
    assert calls == [("open", 111), ("signal", 40, signal.SIGTERM), ("close", 40)]


def test_pid_reuse_or_foreign_group_never_signalled(group, monkeypatch):
    monkeypatch.setattr(group, "members", lambda: [111])
    monkeypatch.setattr(owned.os, "pidfd_open", lambda pid: 40)
    monkeypatch.setattr(owned.os, "close", lambda fd: None)
    monkeypatch.setattr(Path, "read_text", lambda *a, **kw: "0::/foreign-session\n")
    monkeypatch.setattr(owned.signal, "pidfd_send_signal", lambda *a: pytest.fail("foreign signal"))
    with pytest.raises(RuntimeError, match="left owned"):
        group.signal_members()


@pytest.mark.parametrize("name", ["odq-orca-old", "../session", "user.slice", ""])
def test_only_fresh_fixed_labels(name, tmp_path):
    with pytest.raises(RuntimeError, match="label"):
        owned.OwnedProcesses(name, tmp_path)


def test_launch_joins_before_drop_credentials_no_pam(group, monkeypatch):
    calls = []
    monkeypatch.setattr(group, "join", lambda: calls.append("join-root-owned-cgroup"))
    monkeypatch.setattr(owned.os, "setgroups", lambda groups: calls.append(("groups", groups)))
    monkeypatch.setattr(owned.os, "setgid", lambda gid: calls.append(("gid", gid)))
    monkeypatch.setattr(owned.os, "setuid", lambda uid: calls.append(("uid", uid)))

    def launch(argv, **kwargs):
        assert kwargs["start_new_session"] is True
        assert "runuser" not in argv
        kwargs["preexec_fn"]()
        calls.append(("exec", argv))

    monkeypatch.setattr(owned.subprocess, "Popen", launch)
    group.spawn(["env", "-i", "fixed-task"], uid=1000, gid=1000)
    assert calls == [
        "join-root-owned-cgroup",
        ("groups", []),
        ("gid", 1000),
        ("uid", 1000),
        ("exec", ["env", "-i", "fixed-task"]),
    ]


def test_identity_evidence_retained_even_on_failed_drain(group, monkeypatch):
    monkeypatch.setattr(group, "signal_members", lambda: None)
    monkeypatch.setattr(group, "wait_empty", lambda timeout: False)
    monkeypatch.setattr(group, "kill", lambda: None)
    proof = group.cleanup([])
    assert proof["members_before_cleanup"] == [
        {"pid": 111, "starttime": 9, "uid": 1000, "state": "S"}
    ]
    assert not proof["descendants_exited"]
