"""Execute emitted guest capture/config code with fake commands, not a host GUI."""

import configparser
import os
import subprocess
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1] / "scripts/qualification/lab/guest/cinnamon.sh"


@pytest.fixture
def capture(tmp_path):
    payload = subprocess.run(["bash", str(RECIPE), "--print-capture"], check=True,
                             capture_output=True, text=True).stdout
    helper = tmp_path / "capture"
    helper.write_text(payload)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    fake_id = binaries / "id"
    fake_id.write_text('#!/bin/sh\necho "${FAKE_USER:-odq}"\n')
    fake_id.chmod(0o755)
    fake_scrot = binaries / "scrot"
    fake_scrot.write_text(
        "#!/usr/bin/python3\n"
        "from PIL import Image\n"
        "import os, pathlib, sys\n"
        "if os.environ.get('FAIL_CAPTURE'): sys.exit(7)\n"
        "if os.environ.get('BAD_PNG'): pathlib.Path(sys.argv[1]).write_bytes(b'bad')\n"
        "else: Image.new('RGB',(32,24)).save(sys.argv[1],format='PNG')\n"
    )
    fake_scrot.chmod(0o755)
    env = {**os.environ, "PATH": str(binaries) + ":/usr/bin:/bin", "DISPLAY": ":guest-test",
           "XDG_SESSION_TYPE": "x11", "XDG_CURRENT_DESKTOP": "X-Cinnamon"}
    return helper, env, tmp_path


def execute_capture(capture, **environment):
    helper, env, home = capture
    return subprocess.run(["/bin/bash", str(helper), str(home / "screenshot.png")],
                          env={**env, **environment}, capture_output=True, text=True)


def test_guest_capture_outputs_valid_png(capture):
    _, _, home = capture
    assert execute_capture(capture).returncode == 0
    from PIL import Image
    with Image.open(home / "screenshot.png") as image:
        assert image.size == (32, 24)
        assert image.format == "PNG"
    assert not list(home.glob(".cinnamon-capture.*"))


@pytest.mark.parametrize("env", [
    {"XDG_SESSION_TYPE": "wayland"}, {"DISPLAY": ""}, {"FAKE_USER": "root"},
    {"XDG_CURRENT_DESKTOP": "GNOME"}, {"FAIL_CAPTURE": "1"}, {"BAD_PNG": "1"},
])
def test_capture_rejects_wrong_session_and_invalid_results(capture, env):
    _, _, home = capture
    assert execute_capture(capture, **env).returncode != 0
    assert not (home / "screenshot.png").exists()
    assert not list(home.glob(".cinnamon-capture.*"))


@pytest.mark.parametrize("symlink", [False, True])
def test_capture_never_overwrites_existing_output(capture, symlink):
    _, _, home = capture
    target = home / "screenshot.png"
    if symlink:
        target.symlink_to(home / "absent")
    else:
        target.write_text("existing evidence")
    assert execute_capture(capture).returncode == 64
    if symlink:
        assert target.is_symlink()
        assert not (home / "absent").exists()
    else:
        assert target.read_text() == "existing evidence"


def test_generated_config_sets_x11_autologin_and_no_servers(tmp_path):
    subprocess.run(["bash", "-c", 'source "$1"; cinnamon_write_config "$2"',
                    "fixture", str(RECIPE), str(tmp_path)], check=True)
    config = configparser.ConfigParser()
    config.read(tmp_path / "etc/lightdm/lightdm.conf.d/99-odq.conf")
    assert config["Seat:*"]["autologin-user"] == "odq"
    assert config["Seat:*"]["autologin-session"] == "cinnamon"
    assert not config["Seat:*"].getboolean("xserver-allow-tcp")
    assert not config["XDMCPServer"].getboolean("enabled")
    assert not config["VNCServer"].getboolean("enabled")
    script = 'source "$1"; printf "%s,%s" "$LIBGL_ALWAYS_SOFTWARE" "$GALLIUM_DRIVER"'
    rendering_config = tmp_path / "etc/X11/Xsession.d/80odq-software-rendering"
    result = subprocess.run(["bash", "-c", script,
                             "fixture", str(rendering_config)],
                            check=True, capture_output=True, text=True)
    assert result.stdout == "1,llvmpipe"
    assert os.access(tmp_path / "usr/local/lib/odq/capture", os.X_OK)


@pytest.mark.parametrize("existing", ["none", "file", "symlink"])
@pytest.mark.parametrize("failure", [False, True])
def test_package_service_policy_restored_on_success_and_failure(tmp_path, existing, failure):
    directory = tmp_path / "usr/sbin"
    directory.mkdir(parents=True)
    policy = directory / "policy-rc.d"
    original = directory / "original"
    if existing == "file":
        policy.write_text("original policy")
    if existing == "symlink":
        original.write_text("original policy")
        policy.symlink_to(original)
    command = 'source "$1"; cinnamon_with_service_policy "$2" /bin/sh "$2/usr/sbin/policy-rc.d"'
    result = subprocess.run(["bash", "-c", command, "fixture", str(RECIPE), str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == 101
    command = ('source "$1"; cinnamon_with_service_policy "$2" /bin/'
               + ("false" if failure else "true"))
    result = subprocess.run(["bash", "-c", command, "fixture", str(RECIPE), str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == (1 if failure else 0)
    if existing == "none":
        assert not policy.exists()
    else:
        assert policy.read_text() == "original policy"
        assert policy.is_symlink() == (existing == "symlink")
    assert not list(directory.glob("odq-policy-rc.d.*"))


@pytest.mark.parametrize("root,vm,message", [
    ("0", "exit 1", "Refusing provisioning outside a VM"),
    ("1000", "echo kvm", "requires root inside the guest"),
    ("0", "echo lxc", "Requires an isolated QEMU/KVM guest"),
])
def test_provision_refuses_unsafe_context_before_common(tmp_path, root, vm, message):
    for name, body in (("id", "echo " + root), ("systemd-detect-virt", vm)):
        command = tmp_path / name
        command.write_text("#!/bin/sh\n" + body + "\n")
        command.chmod(0o755)
    result = subprocess.run(["/bin/bash", str(RECIPE)], env={**os.environ, "PATH": str(tmp_path)},
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert message in result.stderr
