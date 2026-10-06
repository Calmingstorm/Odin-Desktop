"""Offline behavioral tests. None boot Incus, install packages or touch a desktop."""

import configparser
import json
import os
import runpy
import shlex
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
RECIPE = REPO / "scripts/qualification/lab/guest/hyprland.sh"


@pytest.fixture
def generated(tmp_path):
    subprocess.run(
        ["bash", "-c", 'source "$1"; odq_hyprland_files "$2"', "fixture",
         str(RECIPE), str(tmp_path)], check=True,
    )
    return tmp_path


def test_generated_autologin_selects_native_session(generated):
    config = configparser.ConfigParser()
    config.read(generated / "etc/sddm.conf.d/90-odq.conf")
    session = config["Autologin"]["Session"]
    assert config["Autologin"]["User"] == "odq"
    assert not config["Autologin"].getboolean("Relogin")
    desktop = configparser.ConfigParser()
    desktop.read(generated / "usr/share/wayland-sessions" / session)
    launcher = generated / desktop["Desktop Entry"]["Exec"].lstrip("/")
    assert os.access(launcher, os.X_OK)
    assert desktop["Desktop Entry"]["DesktopNames"] == "Hyprland"


def test_session_launch_passes_native_software_environment(generated, tmp_path):
    stub = tmp_path / "stubs"
    stub.mkdir()
    (stub / "id").write_text("#!/bin/sh\necho odq\n")
    (stub / "dbus-run-session").write_text(
        f"#!{sys.executable}\nimport os,json,sys\n"
        "print(json.dumps({'args':sys.argv[1:],'env':dict(os.environ)}))\n"
    )
    for item in stub.iterdir():
        item.chmod(0o755)
    result = subprocess.run(
        ["bash", str(generated / "usr/local/lib/odq/hyprland-session")], check=True,
        env={"PATH": f"{stub}:/usr/bin:/bin", "XDG_RUNTIME_DIR": str(tmp_path)},
        text=True, capture_output=True,
    )
    launched = json.loads(result.stdout)
    assert launched["args"] == ["--", "Hyprland", "--config",
                                "/home/odq/.config/hypr/hyprland.conf"]
    env = launched["env"]
    assert env["XDG_SESSION_TYPE"] == "wayland"
    assert env["LIBGL_ALWAYS_SOFTWARE"] == "1"
    assert env["GALLIUM_DRIVER"] == "llvmpipe"
    assert env["AQ_NO_MODIFIERS"] == "1"
    assert env["GTK_A11Y"] == "atspi"
    assert env["NO_AT_BRIDGE"] == "0"


def test_session_launcher_refuses_other_user(generated, tmp_path):
    stub = tmp_path / "guard-stubs"
    stub.mkdir()
    (stub / "id").write_text("#!/bin/sh\necho unrelated-user\n")
    (stub / "id").chmod(0o755)
    result = subprocess.run(
        ["bash", str(generated / "usr/local/lib/odq/hyprland-session")],
        env={"PATH": f"{stub}:/usr/bin:/bin"}, capture_output=True,
    )
    assert result.returncode == 77


def test_ready_uses_nested_bus_without_systemd_and_reaches_orca(generated, tmp_path):
    """A nested dbus-run-session has no org.freedesktop.systemd1 service."""
    stubs = tmp_path / "ready-stubs"
    stubs.mkdir()
    log = tmp_path / "ready.jsonl"
    runtime = tmp_path / "ready-runtime"
    runtime.mkdir()
    session = {
        "WAYLAND_DISPLAY": "wayland-7", "XDG_RUNTIME_DIR": str(runtime),
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/fixture/nested-session-bus",
        "HYPRLAND_INSTANCE_SIGNATURE": "ready-fixture", "XDG_SESSION_TYPE": "wayland",
        "XDG_CURRENT_DESKTOP": "Hyprland",
    }
    for command in ("dbus-update-activation-environment", "gsettings", "gdbus", "orca"):
        stub = stubs / command
        stub.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\nfrom pathlib import Path\n"
            "name = Path(sys.argv[0]).name\n"
            "with open(os.environ['ODQ_TEST_LOG'], 'a') as stream:\n"
            "    stream.write(json.dumps({'command': name, 'args': sys.argv[1:], "
            "'bus': os.environ['DBUS_SESSION_BUS_ADDRESS']}) + '\\n')\n"
            "if name == 'dbus-update-activation-environment' and '--systemd' in sys.argv:\n"
            "    sys.exit(42)\n"
            "if name == 'orca':\n"
            "    assert (Path(os.environ['XDG_RUNTIME_DIR']) / "
            "'odq-hyprland-session.json').is_file()\n"
        )
        stub.chmod(0o755)
    subprocess.run(
        ["bash", str(generated / "usr/local/lib/odq/hyprland-ready")], check=True,
        env={"PATH": f"{stubs}:/usr/bin:/bin", "ODQ_TEST_LOG": str(log), **session},
        capture_output=True, text=True,
    )
    calls = [json.loads(row) for row in log.read_text().splitlines()]
    assert [call["command"] for call in calls] == [
        "dbus-update-activation-environment", "gsettings", "gsettings", "gdbus", "orca",
    ]
    assert calls[0]["args"] == [
        "WAYLAND_DISPLAY", "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE",
        "HYPRLAND_INSTANCE_SIGNATURE",
    ]
    assert calls[1]["args"] == [
        "set", "org.gnome.desktop.interface", "toolkit-accessibility", "true",
    ]
    assert calls[2]["args"] == [
        "set", "org.gnome.desktop.a11y.applications", "screen-reader-enabled", "true",
    ]
    assert calls[3]["args"] == [
        "call", "--session", "--dest", "org.a11y.Bus", "--object-path", "/org/a11y/bus",
        "--method", "org.a11y.Bus.GetAddress",
    ]
    assert calls[4]["args"] == ["--replace"]
    assert all(call["bus"] == session["DBUS_SESSION_BUS_ADDRESS"] for call in calls)
    record = runtime / "odq-hyprland-session.json"
    assert json.loads(record.read_text()) == session
    assert record.stat().st_mode & 0o777 == 0o600


def test_generated_config_disables_xwayland(generated):
    config = (generated / "home/odq/.config/hypr/hyprland.conf").read_text()
    assert "xwayland {\n    enabled = false\n}" in config


@pytest.mark.parametrize("distro,release,architecture,expected", [
    ("ubuntu", "resolute", "x86_64", 0),
    ("ubuntu", "noble", "x86_64", 77),
    ("debian", "trixie", "x86_64", 77),
    ("ubuntu", "resolute", "aarch64", 77),
])
def test_platform_guard(tmp_path, distro, release, architecture, expected):
    release_file = tmp_path / "os-release"
    release_file.write_text(f"ID={distro}\nVERSION_CODENAME={release}\n")
    (tmp_path / "uname").write_text(f"#!/bin/sh\necho {architecture}\n")
    (tmp_path / "uname").chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; odq_hyprland_platform "$2"', "guard",
         str(RECIPE), str(release_file)],
        env={"PATH": f"{tmp_path}:/usr/bin:/bin"}, capture_output=True,
    )
    assert result.returncode == expected


@pytest.mark.parametrize("virtualization", ["none", "lxc", "docker", "vmware"])
def test_install_refuses_non_lab_virtualization(tmp_path, virtualization):
    (tmp_path / "id").write_text("#!/bin/sh\necho 0\n")
    (tmp_path / "systemd-detect-virt").write_text(
        f"#!/bin/sh\necho {virtualization}\n"
    )
    for item in tmp_path.iterdir():
        item.chmod(0o755)
    result = subprocess.run(
        ["bash", str(RECIPE)], env={"PATH": f"{tmp_path}:/usr/bin:/bin"},
        capture_output=True, text=True,
    )
    assert result.returncode == 77
    assert "Refusing non-QEMU/KVM" in result.stderr


def test_install_refuses_non_root_before_guest_operations(tmp_path):
    (tmp_path / "id").write_text("#!/bin/sh\necho 1000\n")
    (tmp_path / "id").chmod(0o755)
    result = subprocess.run(
        ["bash", str(RECIPE)], env={"PATH": f"{tmp_path}:/usr/bin:/bin"},
        capture_output=True, text=True,
    )
    assert result.returncode == 77
    assert "Guest root required" in result.stderr


def test_install_explicitly_supplies_pam_and_orca_speech_module(tmp_path):
    """No guest commands run: each provisioning side effect is a shell stub."""
    log = tmp_path / "provision.log"
    subprocess.run(
        ["bash", "-c", '''
source "$1"
id() { echo 0; }
systemd-detect-virt() { echo kvm; }
hostname() { echo odq-hyprland; }
odq_hyprland_platform() { :; }
source() {
    [[ "$1" == /root/odq/common.sh ]] || return 1
    odq_common() { :; }
    odq_finalize() { :; }
}
apt-get() { printf '%s\\n' "$*" >> "$ODQ_TEST_LOG"; }
odq_hyprland_files() { [[ "$1" == / ]]; }
chown() { printf 'chown %s\\n' "$*" >> "$ODQ_TEST_LOG"; }
systemctl() { :; }
odq_hyprland_install
''', "provision-fixture", str(RECIPE)],
        env={"PATH": "/usr/bin:/bin", "ODQ_TEST_LOG": str(log)}, check=True,
    )
    install = next(shlex.split(row) for row in log.read_text().splitlines()
                   if row.startswith("install "))
    assert "--no-install-recommends" in install
    assert "hyprland=0.53.3+ds-4" in install
    assert "libpam-systemd" in install  # SDDM only recommends runtime/logind PAM.
    assert "speech-dispatcher-espeak-ng" in install  # espeak-ng is not the module.
    # Owners of non-base commands/imports in emitted launcher, ready and capture.
    helper_packages = {
        "hyprland=0.53.3+ds-4",  # Hyprland, hyprctl
        "dbus-daemon",  # dbus-run-session, dbus-update-activation-environment
        "libglib2.0-bin",  # gsettings, gdbus (schemas alone do not supply commands)
        "orca", "procps", "grim", "foot",  # orca, pgrep, grim, terminal
        "python3-gi", "gir1.2-gdkpixbuf-2.0",  # capture's fresh PNG decoder
        "gsettings-desktop-schemas", "at-spi2-core",  # schemas and a11y bus service
    }
    assert helper_packages <= set(install)
    ownership = [shlex.split(row) for row in log.read_text().splitlines()
                 if row.startswith("chown ")]
    assert ["chown", "odq:odq", "/home/odq/.config"] in ownership
    assert ["chown", "-R", "odq:odq", "/home/odq/.config/hypr"] in ownership


@pytest.fixture
def capture_lab(generated, monkeypatch):
    capture_file = generated / "usr/local/lib/odq/capture"
    namespace = runpy.run_path(str(capture_file), run_name="capture_fixture")
    capture = namespace["capture"]
    uid = os.getuid()
    runtime_base = generated / "runtime"
    runtime = runtime_base / str(uid)
    runtime.mkdir(parents=True)
    record = runtime / "odq-hyprland-session.json"
    session = {
        "WAYLAND_DISPLAY": "wayland-1", "XDG_RUNTIME_DIR": str(runtime),
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/isolated/bus",
        "HYPRLAND_INSTANCE_SIGNATURE": "fixture", "XDG_SESSION_TYPE": "wayland",
        "XDG_CURRENT_DESKTOP": "Hyprland",
    }
    record.write_text(json.dumps(session))
    record.chmod(0o600)
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(runtime / "wayland-1"))
    listener.listen(8)
    monkeypatch.setitem(capture.__globals__, "Path",
                        lambda value: runtime_base if value == "/run/user" else Path(value))
    monkeypatch.setattr(namespace["pwd"], "getpwuid", lambda _: SimpleNamespace(pw_name="odq"))
    monitors = [{"name": "Virtual-1", "width": 1280, "height": 720}]
    calls = []

    def check_output(args, **kwargs):
        calls.append((args, kwargs))
        assert "DISPLAY" not in kwargs["env"]
        assert kwargs["env"]["DBUS_SESSION_BUS_ADDRESS"] == session["DBUS_SESSION_BUS_ADDRESS"]
        return json.dumps(monitors) if args[0] == "hyprctl" else "('unix:path=/a11y',)"

    def run(args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "grim":
            Image.new("RGB", (16, 12), "blue").save(args[-1])
        return subprocess.CompletedProcess(args, 0)

    class Pixbuf:
        @staticmethod
        def new_from_file(filename):
            with Image.open(filename) as image:
                image.load()
                width, height = image.size
            return SimpleNamespace(get_width=lambda: width, get_height=lambda: height)

    monkeypatch.setattr(namespace["subprocess"], "check_output", check_output)
    monkeypatch.setattr(namespace["subprocess"], "run", run)
    monkeypatch.setitem(sys.modules, "gi", SimpleNamespace(require_version=lambda *_: None))
    monkeypatch.setitem(sys.modules, "gi.repository", SimpleNamespace(
        GdkPixbuf=SimpleNamespace(Pixbuf=Pixbuf)))
    yield SimpleNamespace(capture=capture, runtime=runtime, record=record, session=session,
                          monitors=monitors, calls=calls, output=generated / "output.png",
                          subprocess=namespace["subprocess"], run=run)
    listener.close()


def test_capture_uses_recorded_session_and_fresh_png(capture_lab, capsys):
    capture_lab.output.write_bytes(b"stale")
    capture_lab.capture(capture_lab.output)
    with Image.open(capture_lab.output) as image:
        assert image.size == (16, 12)
    result = json.loads(capsys.readouterr().out)
    assert result["accessibility_bus"] == "responding"
    assert result["session_type"] == "wayland"
    grim_call = next(c for c in capture_lab.calls if c[0][0] == "grim")
    assert grim_call[0][-1] != str(capture_lab.output)
    assert grim_call[1]["env"]["WAYLAND_DISPLAY"] == "wayland-1"
    assert not list(capture_lab.output.parent.glob(".odq-grim-*"))


@pytest.mark.parametrize("bad_session", ["x11", "unspecified"])
def test_capture_rejects_non_native_session(capture_lab, bad_session):
    capture_lab.session["XDG_SESSION_TYPE"] = bad_session
    capture_lab.record.write_text(json.dumps(capture_lab.session))
    with pytest.raises(RuntimeError, match="native odq Wayland"):
        capture_lab.capture(capture_lab.output)
    assert capture_lab.calls == []


def test_capture_rejects_headless_substitute(capture_lab):
    capture_lab.monitors[0]["name"] = "HEADLESS-1"
    with pytest.raises(RuntimeError, match="headless is not lab proof"):
        capture_lab.capture(capture_lab.output)
    assert not capture_lab.output.exists()


def test_capture_rejects_world_readable_environment(capture_lab):
    capture_lab.record.chmod(0o644)
    with pytest.raises(RuntimeError, match="untrusted compositor"):
        capture_lab.capture(capture_lab.output)
    assert capture_lab.calls == []


@pytest.mark.parametrize("display", ["/tmp/wayland-1", "../wayland-1", "folder/wayland-1"])
def test_capture_rejects_external_display_socket(capture_lab, display):
    capture_lab.session["WAYLAND_DISPLAY"] = display
    capture_lab.record.write_text(json.dumps(capture_lab.session))
    with pytest.raises(RuntimeError, match="local socket basename"):
        capture_lab.capture(capture_lab.output)
    assert capture_lab.calls == []


def test_capture_rejects_undecodable_png(capture_lab, monkeypatch):
    def corrupt_grim(args, **kwargs):
        if args[0] == "grim":
            Path(args[-1]).write_bytes(b"not an image")
            return subprocess.CompletedProcess(args, 0)
        return capture_lab.run(args, **kwargs)

    monkeypatch.setattr(capture_lab.subprocess, "run", corrupt_grim)
    with pytest.raises(OSError):
        capture_lab.capture(capture_lab.output)
    assert not capture_lab.output.exists()
    assert not list(capture_lab.output.parent.glob(".odq-grim-*"))


def test_capture_failure_preserves_existing_output_and_cleans_temp(capture_lab, monkeypatch):
    capture_lab.output.write_bytes(b"previous evidence")

    def fail_grim(args, **kwargs):
        if args[0] == "grim":
            raise subprocess.CalledProcessError(1, args)
        return capture_lab.run(args, **kwargs)

    monkeypatch.setattr(capture_lab.subprocess, "run", fail_grim)
    with pytest.raises(subprocess.CalledProcessError):
        capture_lab.capture(capture_lab.output)
    assert capture_lab.output.read_bytes() == b"previous evidence"
    assert not list(capture_lab.output.parent.glob(".odq-grim-*"))
