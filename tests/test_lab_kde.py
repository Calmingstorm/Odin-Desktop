"""Execute KDE capture behaviour without a VM, desktop or host mutation."""
import configparser
import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "scripts/qualification/lab/guest/kde.sh"


@pytest.fixture
def capture(tmp_path):
    exported = subprocess.run(
        ["bash", str(RECIPE), "--print-capture"], check=True, capture_output=True
    ).stdout
    helper = tmp_path / "capture"
    helper.write_bytes(exported)
    helper.chmod(0o755)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in {
        "id": '#!/bin/sh\nif [ "$1" = -un ]; then echo "${TEST_USER:-odq}"; else echo 1000; fi\n',
        "pgrep": '#!/bin/sh\nexit "${TEST_KWIN_STATUS:-0}"\n',
        "spectacle": (
            '#!/bin/sh\nprintf "%s\\n" "$QT_QPA_PLATFORM" "$@" >"$CALL_LOG"\n'
            'while [ "$#" -gt 0 ]; do\n'
            ' if [ "$1" = --output ]; then shift; cp "$PNG_SOURCE" "$1"; fi\n'
            ' shift\ndone\nexit "${TEST_CAPTURE_STATUS:-0}"\n'
        ),
    }.items():
        p = bindir / name
        p.write_text(body)
        p.chmod(0o755)
    source = tmp_path / "source.png"
    Image.new("RGB", (800, 600), "black").save(source)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               XDG_SESSION_TYPE="wayland", XDG_CURRENT_DESKTOP="KDE",
               WAYLAND_DISPLAY="wayland-0", DBUS_SESSION_BUS_ADDRESS="unix:path=/fake",
               PNG_SOURCE=str(source), CALL_LOG=str(tmp_path / "calls"))
    return helper, env, tmp_path


def run_capture(capture, **overrides):
    helper, env, tmp_path = capture
    return subprocess.run([str(helper), str(tmp_path / "out.png")],
                          env=dict(env, **overrides), capture_output=True, text=True)


def test_capture_success_executes_spectacle_and_publishes_new_image(capture):
    assert run_capture(capture).returncode == 0
    _, _, path = capture
    assert (path / "out.png").read_bytes() == (path / "source.png").read_bytes()
    args = (path / "calls").read_text().splitlines()
    assert args[:5] == ["wayland", "--background", "--nonotify", "--fullscreen", "--output"]
    assert not list(path.glob(".odq-kde-capture.*"))


@pytest.mark.parametrize("overrides", [
    {"TEST_USER": "root"}, {"XDG_SESSION_TYPE": "x11"},
    {"XDG_CURRENT_DESKTOP": "GNOME"}, {"WAYLAND_DISPLAY": ""},
    {"DBUS_SESSION_BUS_ADDRESS": ""}, {"TEST_KWIN_STATUS": "1"},
])
def test_invalid_session_never_invokes_screenshot(capture, overrides):
    result = run_capture(capture, **overrides)
    assert result.returncode != 0
    assert "refused" in result.stderr
    assert not (capture[2] / "calls").exists()


def test_capture_denial_is_not_published(capture):
    result = run_capture(capture, TEST_CAPTURE_STATUS="1")
    assert result.returncode != 0
    assert "Spectacle/KWin capture failed" in result.stderr
    path = capture[2]
    assert not (path / "out.png").exists()
    assert not list(path.glob(".odq-kde-capture.*"))


def test_existing_evidence_is_never_overwritten(capture):
    path = capture[2]
    (path / "out.png").write_bytes(b"old evidence")
    result = run_capture(capture)
    assert result.returncode != 0
    assert "output already exists" in result.stderr
    assert (path / "out.png").read_bytes() == b"old evidence"
    assert not (path / "calls").exists()
    assert not list(path.glob(".odq-kde-capture.*"))


def test_invalid_capture_output_is_not_published(capture):
    (capture[2] / "source.png").write_bytes(b"not an image")
    result = run_capture(capture)
    assert result.returncode != 0
    assert "did not produce a PNG" in result.stderr
    assert not (capture[2] / "out.png").exists()


def test_truncated_png_is_not_published(capture):
    # A plausible signature/IHDR is not a screenshot. Require the complete
    # image stream to decode before publishing evidence.
    (capture[2] / "source.png").write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + bytes.fromhex("0000000d4948445200000320000002580802000000") + bytes(5)
    )
    result = run_capture(capture)
    assert result.returncode != 0
    assert "invalid PNG" in result.stderr
    assert not (capture[2] / "out.png").exists()
    assert not list(capture[2].glob(".odq-kde-capture.*"))


def test_recipe_rejects_unknown_mode_without_guest_mutation():
    result = subprocess.run(["bash", str(RECIPE), "--unknown"], capture_output=True)
    assert result.returncode == 2


def test_provision_refuses_non_vm_before_any_package_action(tmp_path):
    # If run as root in CI, the VM guard rejects. Non-root rejects sooner.
    guard = tmp_path / "systemd-detect-virt"
    guard.write_text("#!/bin/sh\nexit 1\n")
    guard.chmod(0o755)
    result = subprocess.run(["bash", str(RECIPE)], capture_output=True, text=True,
                            env=dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}"))
    assert result.returncode != 0
    assert ("provisioning requires guest root" in result.stderr
            or "refusing non-VM provisioning" in result.stderr)


def test_image_plan_records_vm_not_container_artifact():
    # Machine-readable input to parent tooling, not document wording.
    image = json.loads((ROOT / "scripts/qualification/lab/images/kde.json").read_text())
    assert image["type"] == "virtual-machine"
    assert image["rootfs"]["path"].endswith("/disk.qcow2")
    assert len(bytes.fromhex(image["fingerprint"])) == 32
    assert len(bytes.fromhex(image["rootfs"]["sha256"])) == 32


def test_recipe_declares_runtime_packages_and_unlocks_sddm_pam_account():
    recipe = RECIPE.read_text()
    for package in ("plasma-workspace-wayland", "kde-spectacle", "libpam-systemd",
                    "speech-dispatcher-espeak-ng", "espeak-ng"):
        assert package in recipe
    assert "chpasswd" in recipe
    assert "openssl rand -base64 48" in recipe


@pytest.fixture(params=["fresh", "root-owned-retry"])
def user_config(tmp_path, request):
    # Real root-owned fixture directories reproduce install -d's intermediate
    # ownership bug. This runs only inside the test launcher's PID namespace;
    # no guest, host account, service, or desktop configuration is touched.
    home = tmp_path / "home"
    home.mkdir()
    uid, gid = os.getuid(), os.getgid()
    assert uid != 0, "Run through the repository PID launcher as the repo user"
    command = [
        "sudo", "-n", "env", "-i", "PATH=/usr/bin:/bin", "bash", "-c",
        f"source {shlex.quote(str(RECIPE))}; "
        'kde_write_user_config "$1" "$2" "$3"',
        "_", str(home), str(uid), str(gid),
    ]
    if request.param == "root-owned-retry":
        # Generate an earlier root-owned configuration, then repair it using
        # exactly the same emitter that provisioning calls for odq.
        result = subprocess.run(command[:-2] + ["0", "0"], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert (home / ".config").stat().st_uid == 0
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return home, uid, gid


def test_emitted_user_config_owns_every_intermediate_and_allows_kde_writes(user_config):
    home, uid, gid = user_config
    for relative in (".config", ".config/plasma-workspace", ".config/plasma-workspace/env",
                     ".config/plasma-workspace/env/odq-software.sh"):
        path = home / relative
        assert (path.stat().st_uid, path.stat().st_gid) == (uid, gid)
        assert path.stat().st_mode & 0o777 == 0o755
    # This is an actual unprivileged write, not an ownership command-string test.
    for name in ("kwinrc", "kdeglobals"):
        (home / ".config" / name).write_text("[General]\n")
    assert sorted(path.name for path in home.iterdir()) == [".config"]


@pytest.mark.parametrize("inherited", [None, "1"])
def test_emitted_environment_selects_llvmpipe_without_forced_egl(user_config, inherited):
    home, _, _ = user_config
    env = {"PATH": "/usr/bin:/bin"}
    if inherited is not None:
        env["LIBGL_ALWAYS_SOFTWARE"] = inherited
    result = subprocess.run(
        ["sh", "-c", '. "$1"; exec env', "_",
         str(home / ".config/plasma-workspace/env/odq-software.sh")],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    emitted = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert "LIBGL_ALWAYS_SOFTWARE" not in emitted
    assert emitted["GALLIUM_DRIVER"] == "llvmpipe"
    assert emitted["QT_ACCESSIBILITY"] == "1"
    assert emitted["QT_LINUX_ACCESSIBILITY_ALWAYS_ON"] == "1"


def test_emitted_kaccess_config_enables_native_screen_reader(user_config):
    # Parse the actual provisioned fixture, not shell source: kaccess reads
    # kaccessrc ScreenReader/Enabled and mirrors false to GNOME when unset.
    home, uid, gid = user_config
    path = home / ".config/kaccessrc"
    config = configparser.ConfigParser()
    config.optionxform = str
    assert config.read(path) == [str(path)]
    assert config.sections() == ["ScreenReader"]
    assert dict(config["ScreenReader"]) == {"Enabled": "true"}
    assert config.getboolean("ScreenReader", "Enabled") is True
    assert (path.stat().st_uid, path.stat().st_gid) == (uid, gid)
    assert path.stat().st_mode & 0o777 == 0o644
    # The KDE emitter must not create its own Orca wrapper/autostart launch.
    assert sorted(p.relative_to(home).as_posix() for p in home.rglob("*") if p.is_file()) == [
        ".config/kaccessrc", ".config/plasma-workspace/env/odq-software.sh",
    ]
