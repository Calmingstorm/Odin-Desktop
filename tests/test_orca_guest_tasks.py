"""Rootless unit tests for the task suite's guest/input identity boundary."""

import importlib.util
import json
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).parents[1] / "app/test/e2e/orca-guest.py"
spec = importlib.util.spec_from_file_location("orca_guest_tasks", SOURCE)
guest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guest)


def test_host_refusal_precedes_account_display_or_input(monkeypatch):
    monkeypatch.setattr(guest, "command", lambda *args: "none")
    monkeypatch.setattr(
        guest.pwd, "getpwnam", lambda _: pytest.fail("Account probing before VM guard")
    )
    with pytest.raises(RuntimeError, match="Actual odq VM"):
        guest.guard()


def test_suite_launch_uses_measured_native_focus_not_dom_input():
    source = SOURCE.with_name("orca.spec.ts").read_text()
    launch = source.split("async function launch(", 1)[1].split("async function hear(", 1)[0]
    assert launch.index("'key', 'Escape'") < launch.index("electron.launch(")
    assert "window.show()" in launch and "window.focus()" in launch
    assert "NO_AT_BRIDGE: '0'" in launch and "GTK_A11Y: 'always'" in launch
    assert ".click(" not in launch and ".fill(" not in launch
    assert "minimized: false" in launch
    assert "node.states?.includes('ACTIVE')" in launch
    assert "'snapshot'" in launch and "expect.poll" in launch


def test_real_vm_requires_lab_hostname(monkeypatch):
    monkeypatch.setattr(guest, "command", lambda *args: "kvm")
    monkeypatch.setattr(guest.socket, "gethostname", lambda: "workstation")
    with pytest.raises(RuntimeError, match="Actual odq VM"):
        guest.guard()


def test_vm_root_is_not_the_owned_session_user(monkeypatch):
    monkeypatch.setattr(guest, "command", lambda *args: "qemu")
    monkeypatch.setattr(guest.socket, "gethostname", lambda: "odq-cinnamon")
    monkeypatch.setattr(guest.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=1001))
    monkeypatch.setattr(guest.os, "geteuid", lambda: 0)
    monkeypatch.setenv("ODIN_ORCA_ROOT", "/var/tmp/odq-orca-unit")
    with pytest.raises(RuntimeError, match="Owned odq user"):
        guest.guard()


@pytest.mark.parametrize(("title", "action"), [("terminal", "cancel"), ("Attach files", "shell")])
def test_unapproved_target_or_operation_rejected_before_input(monkeypatch, title, action):
    monkeypatch.setattr(guest, "active_dialog", lambda _: pytest.fail("Target lookup"))
    with pytest.raises(ValueError, match="Only the task suite"):
        guest.native(title, action)


def test_no_active_dialog_never_imports_evdev(monkeypatch):
    def missing(_):
        raise RuntimeError("No owned active AT-SPI dialog")

    monkeypatch.setattr(guest, "active_dialog", missing)
    monkeypatch.setitem(sys.modules, "evdev", None)
    with pytest.raises(RuntimeError, match="No owned active"):
        guest.native("Attach files", "cancel")


def test_cli_host_fails_closed_without_display():
    result = subprocess.run(
        [sys.executable, "-B", str(SOURCE), "guard"],
        env={"PATH": "/usr/bin:/bin"},
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["passed"] is False


@pytest.fixture
def virtual_keyboard(monkeypatch, tmp_path):
    # Unit-only fake device: no /dev/uinput open, no desktop state or VM operation.
    events = []

    class Codes:
        values = {}

        def __getattr__(self, name):
            return self.values.setdefault(name, len(self.values) + 1)

    codes = Codes()

    class Device:
        def __init__(self, *args, **kwargs):
            events.append(("open", kwargs["name"]))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            events.append(("close",))

        def write(self, *args):
            events.append(args)

        def syn(self):
            pass

    monkeypatch.setitem(sys.modules, "evdev", SimpleNamespace(UInput=Device, ecodes=codes))
    monkeypatch.setattr(
        guest, "active_dialog", lambda _: SimpleNamespace(revalidate=lambda _: object())
    )
    # These cases model keyboard ordering only. Real modal text/state readback
    # and refusal before Enter are covered separately in test_orca_native_input.
    monkeypatch.setattr(
        guest, "verify_native_text", lambda binding, title, expected: binding.revalidate(title)
    )
    monkeypatch.setattr(guest.time, "sleep", lambda _: None)
    monkeypatch.setenv("ODIN_ORCA_ROOT", str(tmp_path))
    monkeypatch.setenv("ODIN_ORCA_DESKTOP", "cinnamon")
    return codes, events


def test_native_cancel_has_matched_press_release(virtual_keyboard):
    codes, events = virtual_keyboard
    guest.native("Attach files", "cancel")
    assert (codes.EV_KEY, codes.KEY_ESC, 1) in events
    assert (codes.EV_KEY, codes.KEY_ESC, 0) in events
    assert events[-1] == ("close",)


def test_describe_only_observes_modal_without_input_or_fake_speech(virtual_keyboard):
    _, events = virtual_keyboard
    guest.native("Save file", "describe")
    assert events == []


def test_file_path_outside_disposable_root_refused_before_device(virtual_keyboard):
    _, events = virtual_keyboard
    with pytest.raises(ValueError, match="suite-owned"):
        guest.native("Save file", "file", "/etc/passwd")
    assert not events


def test_native_typing_releases_modifiers_and_all_keys(virtual_keyboard, tmp_path):
    codes, events = virtual_keyboard
    target = str(tmp_path / "unit_keyboard-1.txt")
    guest.native("Attach files", "file", target)
    keys = [event for event in events if len(event) == 3]
    presses = [key for kind, key, state in keys if state == 1]
    releases = [key for kind, key, state in keys if state == 0]
    assert sorted(presses) == sorted(releases)
    assert codes.KEY_LEFTCTRL in presses
    assert codes.KEY_LEFTSHIFT in presses
    assert events[-1] == ("close",)


def test_native_save_rechecks_owned_dialog_before_filename(virtual_keyboard, tmp_path, monkeypatch):
    codes, events = virtual_keyboard
    titles = []
    monkeypatch.setattr(
        guest,
        "active_dialog",
        lambda title: SimpleNamespace(revalidate=lambda title: titles.append(title)),
    )
    guest.native("Save file", "file", str(tmp_path / "saved.txt"))
    assert len(titles) > 2 and set(titles) == {"Save file"}
    assert (codes.EV_KEY, codes.KEY_LEFTALT, 1) in events
    assert (codes.EV_KEY, codes.KEY_N, 1) in events


@pytest.fixture
def guarded_session(monkeypatch):
    """A pure filesystem/session model, never a real session or host bus."""
    uid = 1001
    root = "/var/tmp/odq-orca-unit"
    env = {
        "ODIN_ORCA_ROOT": root,
        "HOME": root + "/profile",
        "XDG_SESSION_ID": "c2",
        "ODIN_ORCA_DESKTOP": "cinnamon",
        "XDG_RUNTIME_DIR": "/run/user/1001",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1001/bus",
        "DISPLAY": ":0",
        "ODIN_ORCA_PID": "123",
        "ODIN_ORCA_LOG": root + "/evidence/orca.log",
        "ODIN_ORCA_EVIDENCE": root + "/evidence",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    state = {
        "session": "User=1001\nName=odq\nActive=yes\nType=x11",
        "bound": True,
        "orca_uid": uid,
        "orca_argv": b"orca\0\0",
        "log_symlink": False,
    }

    class ModelPath:
        def __init__(self, value):
            self.value = str(value)

        def __str__(self):
            return self.value

        def __eq__(self, other):
            return self.value == str(other)

        def __truediv__(self, other):
            return ModelPath(self.value + "/" + str(other))

        @property
        def name(self):
            return self.value.rsplit("/", 1)[-1]

        @property
        def parent(self):
            return ModelPath(self.value.rsplit("/", 1)[0])

        def resolve(self, strict=False):
            if self.value.endswith("/fd/8") and state["bound"]:
                return ModelPath(env["ODIN_ORCA_LOG"])
            return self

        def is_relative_to(self, other):
            return self.value.startswith(str(other) + "/")

        def is_symlink(self):
            return state["log_symlink"] if self.value.endswith("/orca.log") else False

        def is_file(self):
            return True

        def stat(self):
            return SimpleNamespace(
                st_uid=state["orca_uid"] if self.value == "/proc/123" else uid,
                st_mode=stat.S_IFSOCK if self.value.startswith("/run/user/1001/") else stat.S_IFREG,
            )

        def joinpath(self, name):
            return self / name

        def read_bytes(self):
            return state["orca_argv"]

        def iterdir(self):
            return iter([self / "8"])

    monkeypatch.setattr(guest, "Path", ModelPath)
    monkeypatch.setattr(guest.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=uid))
    monkeypatch.setattr(guest.os, "geteuid", lambda: uid)
    monkeypatch.setattr(guest.socket, "gethostname", lambda: "odq-cinnamon")
    monkeypatch.setattr(
        guest,
        "command",
        lambda *args: "kvm" if args[0] == "systemd-detect-virt" else state["session"],
    )
    return state, env


def test_owned_vm_session_open_log_binding_accepts_erased_orca_argv(guarded_session):
    assert guest.guard()["orca_pid"] == 123


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("session", "User=1001\nName=odq\nActive=no\nType=x11", "active odq"),
        ("bound", False, "Log not bound"),
        ("orca_uid", 0, "Owned live Orca"),
        ("orca_argv", b"python3\0fake-speech.py\0", "Owned live Orca"),
        ("log_symlink", True, "Fresh owned evidence"),
    ],
)
def test_session_and_process_identity_fail_closed(guarded_session, field, value, reason):
    state, _ = guarded_session
    state[field] = value
    with pytest.raises(RuntimeError, match=reason):
        guest.guard()


@pytest.mark.parametrize(
    ("key", "value", "reason"),
    [
        ("HOME", "/home/odq", "Disposable guest home"),
        ("XDG_SESSION_ID", "../host", "Explicit graphical"),
        ("XDG_RUNTIME_DIR", "/tmp/host-runtime", "Owned guest runtime"),
        ("DBUS_SESSION_BUS_ADDRESS", "unix:path=/tmp/host-bus", "Owned guest user bus"),
        ("DISPLAY", "remote:0", "Local guest X11"),
    ],
)
def test_rejects_host_identity_environment(guarded_session, monkeypatch, key, value, reason):
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match=reason):
        guest.guard()


def test_owned_wayland_socket_required_not_host_path(guarded_session, monkeypatch):
    state, _ = guarded_session
    state["session"] = "User=1001\nName=odq\nActive=yes\nType=wayland"
    monkeypatch.setenv("ODIN_ORCA_DESKTOP", "gnome")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert guest.guard()["session"]["Type"] == "wayland"
    monkeypatch.setenv("WAYLAND_DISPLAY", "/tmp/wayland-0")
    with pytest.raises(RuntimeError, match="Guest compositor socket"):
        guest.guard()


def test_changed_source_after_device_settle_stops_before_any_input(virtual_keyboard, monkeypatch):
    _, events = virtual_keyboard

    def stale(_):
        raise RuntimeError("Stale native source process binding")

    monkeypatch.setattr(guest, "active_dialog", lambda _: SimpleNamespace(revalidate=stale))
    with pytest.raises(RuntimeError, match="no replay"):
        guest.native("Attach files", "cancel")
    assert events == [("open", "odq-orca-file-dialog"), ("close",)]


def test_unused_general_frame_input_removed():
    assert not hasattr(guest, "active_odin_frame")
    assert not hasattr(guest, "web_key")


def test_lost_target_mid_typing_does_not_repeat_partly_executed_input(
    virtual_keyboard, monkeypatch, tmp_path
):
    codes, events = virtual_keyboard
    calls = []

    def revalidate(title):
        calls.append(title)
        if len(calls) == 4:
            raise RuntimeError("No owned active AT-SPI dialog")

    monkeypatch.setattr(guest, "active_dialog", lambda _: SimpleNamespace(revalidate=revalidate))
    with pytest.raises(RuntimeError, match="no replay") as error:
        guest.native("Attach files", "file", str(tmp_path / "file.txt"))
    assert "No owned active AT-SPI dialog" not in str(error.value)
    keys = [event for event in events if len(event) == 3]
    presses = [key for kind, key, state in keys if state == 1]
    releases = [key for kind, key, state in keys if state == 0]
    assert sorted(presses) == sorted(releases)
    assert codes.KEY_ENTER not in presses
    assert len(calls) == 4 and events[-1] == ("close",)
