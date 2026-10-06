"""Guest bootstrap unit tests with fake session discovery, never a host session."""

import hashlib
import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/qualification/lab/guest/orca_run.py"


def test_debug_customization_flushes_actual_idle_emission_without_rewriting(
    guest, monkeypatch, tmp_path
):
    path = tmp_path / "actual-debug.log"
    with path.open("w") as sink:
        fake_orca = types.ModuleType("orca")
        fake_orca.debug = types.SimpleNamespace(debugFile=sink)
        monkeypatch.setitem(sys.modules, "orca", fake_orca)
        exec(guest.debug_buffering_customization(), {})
        emission = "01:02:03.123456 - SPEECH OUTPUT: 'Native button.' {'established': False}\n"
        sink.write(emission)
        assert path.read_text() == emission
        assert sink.line_buffering is True
        assert sink.write_through is True


def collector_receipt(guest, tmp_path, *, pid=42, ready=True, console_ready=True):
    events, console = tmp_path / "events.jsonl", tmp_path / "collector.log"
    receipt = {
        "type": "ready" if ready else "source",
        "run": "fresh",
        "address": "unix:path=guest-a11y",
        "collector_peer": ":1.2",
        "started_ns": 100,
        "collector": {"pid": pid, "uid": events.parent.stat().st_uid},
    }
    events.write_text(json.dumps(receipt) + "\n")
    events.chmod(0o600)
    console.write_text(
        json.dumps({"native_event_collector": "ready", "path": str(events)}) + "\n"
        if console_ready
        else ""
    )
    return events, console, receipt


def test_native_collector_requires_flushed_header_console_and_live_child(guest, tmp_path):
    events, console, ready = collector_receipt(guest, tmp_path)
    child = types.SimpleNamespace(pid=42, poll=lambda: None)
    assert guest.wait_native_collector(child, events, console, tmp_path.stat().st_uid) == ready


@pytest.mark.parametrize(
    "failure", ["dead", "wrong_pid", "wrong_type", "public", "symlink", "no_console", "no_file"]
)
def test_native_collector_failed_readiness_blocks_app(guest, tmp_path, failure):
    events, console, _ = collector_receipt(
        guest,
        tmp_path,
        pid=43 if failure == "wrong_pid" else 42,
        ready=failure != "wrong_type",
        console_ready=failure != "no_console",
    )
    if failure == "public":
        events.chmod(0o644)
    elif failure == "symlink":
        moved = tmp_path / "actual"
        events.rename(moved)
        events.symlink_to(moved)
    elif failure == "no_file":
        events.unlink()
    child = types.SimpleNamespace(pid=42, poll=lambda: 1 if failure == "dead" else None)
    with pytest.raises(RuntimeError, match="Native dialog collector"):
        guest.wait_native_collector(child, events, console, tmp_path.stat().st_uid, timeout=0)


def test_collector_spawn_is_contained_and_cleanup_registered_before_wait(
    guest, tmp_path, monkeypatch
):
    account = types.SimpleNamespace(pw_uid=1000, pw_gid=1000)
    child = object()
    env = {"ODIN_ORCA_PID": "15"}
    children, calls = [], []

    def spawn(argv, **kwargs):
        calls.append((argv, kwargs))
        return child

    def refuse(*args):
        assert children == [child]
        raise RuntimeError("readiness failed")

    monkeypatch.setattr(guest, "wait_native_collector", refuse)
    with pytest.raises(RuntimeError, match="readiness failed"):
        guest.start_native_collector(
            types.SimpleNamespace(spawn=spawn), children, env, account, tmp_path, "log-stream"
        )
    assert env["ODIN_ORCA_DIALOG_EVENTS"] == str(tmp_path / "evidence/native-dialog-events.jsonl")
    assert "ODIN_ORCA_PID=15" in calls[0][0]
    assert calls[0][0][-3:] == [
        "/usr/bin/python3",
        "-B",
        str(tmp_path / "scripts/qualification/lab/guest/native_dialog_events.py"),
    ]
    assert calls[0][1]["uid"] == 1000


@pytest.fixture
def guest(monkeypatch):
    # No real smoke/session imports or DBus/environment probing.
    smoke = types.ModuleType("smoke")
    smoke.session_info = lambda: {"Type": "x11"}
    smoke.session_environment = lambda uid, kind: {
        "XDG_CURRENT_DESKTOP": "X-Cinnamon",
        "DISPLAY": ":1",
    }
    monkeypatch.setitem(sys.modules, "smoke", smoke)
    original_path = sys.path[:]
    spec = importlib.util.spec_from_file_location("orca_guest_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.path[:] = original_path
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        module.pwd, "getpwnam", lambda name: types.SimpleNamespace(pw_uid=1000, pw_gid=1000)
    )

    def command(argv, **kwargs):
        if argv[:2] == ["loginctl", "list-sessions"]:
            return "2 1000 odq seat0 tty2\n"
        if argv[:2] == ["loginctl", "show-session"]:
            return "Type=x11\nActive=yes\n"
        return {"systemd-detect-virt": "kvm\n", "hostname": "odq-cinnamon\n"}[argv[0]]

    monkeypatch.setattr(module.subprocess, "check_output", command)
    return module


def test_guest_context_validates_live_named_vm(guest):
    account, info, env = guest.guest_context("cinnamon")
    assert account.pw_uid == 1000
    assert info == {"Type": "x11"}
    assert env["XDG_CURRENT_DESKTOP"] == "X-Cinnamon"


@pytest.mark.parametrize("desktop", ["hyprland", "host", "cinnamon;reboot", ""])
def test_guest_context_no_unapproved_desktop(guest, desktop):
    with pytest.raises(RuntimeError, match="Unsupported"):
        guest.guest_context(desktop)


def test_guest_context_requires_guest_root(guest, monkeypatch):
    monkeypatch.setattr(guest.os, "geteuid", lambda: 1000)
    with pytest.raises(RuntimeError, match="guest root"):
        guest.guest_context("cinnamon")


@pytest.mark.parametrize("virt", ["none", "lxc", "docker", "wsl"])
def test_guest_context_rejects_host_and_containers(guest, monkeypatch, virt):
    monkeypatch.setattr(guest.subprocess, "check_output", lambda argv, **kwargs: virt)
    with pytest.raises(RuntimeError, match="actual VM"):
        guest.guest_context("cinnamon")


def test_guest_context_wrong_hostname(guest, monkeypatch):
    monkeypatch.setattr(
        guest.subprocess,
        "check_output",
        lambda argv, **kwargs: "kvm" if argv[0] == "systemd-detect-virt" else "aarons-desktop",
    )
    with pytest.raises(RuntimeError, match="Wrong qualification guest"):
        guest.guest_context("cinnamon")


def test_guest_context_wrong_session_type(guest, monkeypatch):
    monkeypatch.setattr(guest, "session_info", lambda: {"Type": "wayland"})
    with pytest.raises(RuntimeError, match="session type"):
        guest.guest_context("cinnamon")


def test_guest_context_wrong_live_desktop(guest, monkeypatch):
    monkeypatch.setattr(
        guest, "session_environment", lambda *args: {"XDG_CURRENT_DESKTOP": "GNOME"}
    )
    with pytest.raises(RuntimeError, match="desktop identity"):
        guest.guest_context("cinnamon")


def test_guest_context_no_active_guest_session(guest, monkeypatch):
    previous = guest.subprocess.check_output
    monkeypatch.setattr(
        guest.subprocess,
        "check_output",
        lambda argv, **kwargs: "" if argv[0] == "loginctl" else previous(argv, **kwargs),
    )
    with pytest.raises(RuntimeError, match="explicit active"):
        guest.guest_context("cinnamon")


def test_user_command_clears_environment_no_shell(guest):
    command = guest.user_command(
        {"DISPLAY": ":1", "ODIN_ORCA_LOG": "/tmp/a b"}, ["node", "fixed-script.js"]
    )
    assert command == [
        "env",
        "-i",
        "DISPLAY=:1",
        "ODIN_ORCA_LOG=/tmp/a b",
        "node",
        "fixed-script.js",
    ]
    assert "-c" not in command


@pytest.mark.parametrize(
    "root", ["/", "relative", "/home/odin/odq-orca-fake", "/var/tmp/wrong-name"]
)
def test_artifact_root_invalid_before_writes(guest, root):
    with pytest.raises(RuntimeError, match="private /var/tmp"):
        guest.run("cinnamon", root)


def test_manifest_digest_is_exact_uploaded_bytes(guest, tmp_path):
    data = b'{"source_dirty":true}\n'
    (tmp_path / "artifact-manifest.json").write_bytes(data)
    assert guest.artifact_provenance(tmp_path) == hashlib.sha256(data).hexdigest()


def test_manifest_required_never_made_up(guest, tmp_path):
    with pytest.raises(FileNotFoundError):
        guest.artifact_provenance(tmp_path)


@pytest.mark.parametrize("tampered", ["chrome-sandbox", "electron"])
def test_native_sandbox_rejects_changed_runtime_before_install(guest, tmp_path, tampered):
    runtime = tmp_path / "app/node_modules/electron/dist"
    runtime.mkdir(parents=True)
    files = {}
    for name in ("chrome-sandbox", "electron"):
        path = runtime / name
        path.write_bytes(b"exact-runtime")
        files[str(path.relative_to(tmp_path))] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()
        }
    (tmp_path / "artifact-manifest.json").write_text(json.dumps({"files": files}))
    (runtime / tampered).write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="digest mismatch"):
        guest.prepare_native_sandbox(tmp_path)


def test_native_sandbox_rejects_symlink_before_install(guest, tmp_path):
    runtime = tmp_path / "app/node_modules/electron/dist"
    runtime.mkdir(parents=True)
    (runtime / "chrome-sandbox").symlink_to(tmp_path / "outside")
    (tmp_path / "artifact-manifest.json").write_text("{}")
    with pytest.raises(RuntimeError, match="regular archived file"):
        guest.prepare_native_sandbox(tmp_path)


def test_no_engine_explicit_fixture_only(guest, tmp_path):
    assert guest.real_core_environment(tmp_path) == {}


def test_optional_engine_presence_requires_complete_lane(guest, tmp_path):
    (tmp_path / "engine").mkdir()
    with pytest.raises(RuntimeError, match="Incomplete"):
        guest.real_core_environment(tmp_path)


def test_bundled_engine_sets_command_and_required_no_silent_skip(guest, tmp_path):
    (tmp_path / "engine/src").mkdir(parents=True)
    (tmp_path / "engine/src/__main__.py").write_text("source")
    (tmp_path / "engine/site-packages").mkdir()
    wrapper = tmp_path / "scripts/qualification/lab/guest/real_core.py"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("wrapper")
    env = guest.real_core_environment(tmp_path)
    assert env["ODIN_ORCA_REAL_CORE_REQUIRED"] == "1"
    assert json.loads(env["ODIN_ORCA_REAL_CORE_CMD"]) == [
        "/usr/bin/python3",
        "-B",
        "-P",
        str(wrapper),
    ]


@pytest.fixture
def real_wrapper(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "real_core_guest_test", SCRIPT.parent / "real_core.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(
        module.subprocess,
        "check_output",
        lambda argv, **kwargs: "kvm" if argv[0] == "systemd-detect-virt" else "odq-cinnamon",
    )
    monkeypatch.setattr(
        module.sys,
        "path",
        [
            "/unsafe/app/src",
            "/unsafe/site-packages",
            "/usr/lib/python3.12",
            "/usr/lib/python3.12/lib-dynload",
        ],
    )
    monkeypatch.setattr(module.os, "chdir", lambda path: None)
    with tempfile.TemporaryDirectory(prefix="odq-orca-test-", dir="/var/tmp") as directory:
        root = Path(directory)
        (root / "engine/src").mkdir(parents=True)
        (root / "engine/src/__main__.py").write_text("source")
        (root / "engine/site-packages").mkdir()
        home = root / "task-unit"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        for key, leaf in (
            ("XDG_CONFIG_HOME", "config"),
            ("XDG_DATA_HOME", "data"),
            ("XDG_CACHE_HOME", "cache"),
        ):
            monkeypatch.setenv(key, str(home / leaf))
        yield module, root


def test_real_wrapper_removes_app_shadow_and_ambient_dependencies(real_wrapper, monkeypatch):
    module, root = real_wrapper
    monkeypatch.setenv("PYTHONPATH", "/unsafe/host/source")
    assert module.prepare(root) == root / "engine"
    assert module.sys.path == [
        str(root / "engine"),
        str(root / "engine/site-packages"),
        "/usr/lib/python3.12",
        "/usr/lib/python3.12/lib-dynload",
    ]
    assert "PYTHONPATH" not in module.os.environ


def test_real_wrapper_rejects_root(real_wrapper, monkeypatch):
    module, root = real_wrapper
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    with pytest.raises(RuntimeError, match="unprivileged"):
        module.prepare(root)


def test_real_wrapper_rejects_nonprivate_home(real_wrapper, monkeypatch):
    module, root = real_wrapper
    monkeypatch.setenv("HOME", "/home/odq")
    with pytest.raises(RuntimeError, match="per-task HOME"):
        module.prepare(root)


def test_real_wrapper_rejects_existing_host_config(real_wrapper, monkeypatch):
    module, root = real_wrapper
    monkeypatch.setenv("XDG_CONFIG_HOME", "/home/odq/.config")
    with pytest.raises(RuntimeError, match="private XDG"):
        module.prepare(root)
