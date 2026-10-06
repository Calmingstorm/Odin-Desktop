"""Execute the guest recipe's rendering and capture paths in temp directories.

No Incus or desktop access; CLI substitutes model success/denial. Generated PNGs
are decoded using guest-equivalent Pillow, not word assertions.
"""

from __future__ import annotations

import configparser
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

RECIPE = Path(__file__).resolve().parents[1] / "scripts/qualification/lab/guest/gnome.sh"


def render(root: Path) -> None:
    subprocess.run(
        ["bash", "-c", f"source {shlex.quote(str(RECIPE))}; gnome_write_config \"$1\"",
         "_", str(root)],
        check=True,
        env={"PATH": "/usr/bin:/bin"},
    )


def configuration(path: Path) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config.optionxform = str
    config.read(path)
    return config


def test_generated_wayland_session_and_autologin(tmp_path):
    render(tmp_path)
    gdm = configuration(tmp_path / "etc/gdm3/custom.conf")
    account = configuration(tmp_path / "var/lib/AccountsService/users/odq")
    session_path = tmp_path / "usr/share/wayland-sessions/odq-gnome.desktop"
    desktop = configuration(session_path)["Desktop Entry"]
    assert gdm["daemon"].getboolean("WaylandEnable")
    assert gdm["daemon"].getboolean("AutomaticLoginEnable")
    assert gdm["daemon"]["AutomaticLogin"] == "odq"
    assert gdm["daemon"]["DefaultSession"] == session_path.name
    assert account["User"]["SessionType"] == "wayland"
    assert account["User"]["Session"] == session_path.stem
    assert desktop["DesktopNames"] == "GNOME"
    assert not gdm["xdmcp"].getboolean("Enable")
    assert gdm["security"].getboolean("DisallowTCP")


def test_generated_extension_lock_and_accessibility(tmp_path):
    render(tmp_path)
    config = configuration(tmp_path / "etc/dconf/db/odq.d/00-gnome")
    assert config["org/gnome/shell"]["enabled-extensions"] == "@as []"
    assert config["org/gnome/shell"].getboolean("disable-user-extensions")
    assert config["org/gnome/desktop/a11y/applications"].getboolean("screen-reader-enabled")
    assert config["org/gnome/desktop/interface"].getboolean("toolkit-accessibility")
    locks = (tmp_path / "etc/dconf/db/odq.d/locks/gnome").read_text().splitlines()
    assert set(locks) == {
        "/org/gnome/shell/enabled-extensions",
        "/org/gnome/shell/disable-user-extensions",
    }


def test_native_drm_llvmpipe_environment_has_no_egl_software_force(tmp_path):
    render(tmp_path)
    gdm = configuration(tmp_path / "etc/systemd/system/gdm.service.d/odq-software.conf")
    assert gdm["Service"]["Environment"] == "GALLIUM_DRIVER=llvmpipe"
    assert gdm["Service"]["UnsetEnvironment"] == "LIBGL_ALWAYS_SOFTWARE"
    environment = (tmp_path / "etc/environment.d/60-odq-software.conf").read_text()
    assert environment.splitlines() == ["GALLIUM_DRIVER=llvmpipe"]


@pytest.mark.parametrize("inherited_force", [None, "1"])
def test_session_wrapper_clears_inherited_force_and_uses_standard_gnome(tmp_path, inherited_force):
    render(tmp_path)
    wrapper = (tmp_path / "usr/local/lib/odq/gnome-session").read_text()
    invocation = "exec /usr/bin/gnome-session --session=gnome"
    assert wrapper.count(invocation) == 1
    session = tmp_path / "stub-session"
    session.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "print(json.dumps({'argv': sys.argv[1:], 'env': dict(os.environ)}))\n"
    )
    session.chmod(0o755)
    # Substitute ONLY the executable, leaving shell environment setup and
    # arguments intact. Never launch a real desktop or connect to a host bus.
    env = {"PATH": "/usr/bin:/bin", "ODQ_TEST_SESSION": str(session)}
    if inherited_force is not None:
        env["LIBGL_ALWAYS_SOFTWARE"] = inherited_force
    result = subprocess.run(
        ["sh", "-c", wrapper.replace(invocation, 'exec "$ODQ_TEST_SESSION" --session=gnome')],
        env=env, capture_output=True, text=True, check=True,
    )
    observed = json.loads(result.stdout)
    assert observed["argv"] == ["--session=gnome"]
    assert observed["env"]["GALLIUM_DRIVER"] == "llvmpipe"
    assert observed["env"]["GNOME_SHELL_SESSION_MODE"] == "gnome"
    assert "LIBGL_ALWAYS_SOFTWARE" not in observed["env"]


def test_generated_dconf_keyfile_compiles_with_installed_dconf(tmp_path):
    render(tmp_path)
    keyfile_dir = tmp_path / "etc/dconf/db/odq.d"
    database = tmp_path / "compiled-dconf"
    # Compile directly from the isolated generated keyfile directory. This
    # exercises the installed dconf parser without reading/writing host DBs.
    result = subprocess.run(
        ["dconf", "compile", str(database), str(keyfile_dir)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert database.is_file() and database.stat().st_size > 0


@pytest.fixture
def capture(tmp_path):
    render(tmp_path)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    # The guest receives python3-pil from common.sh; tests use the repo's Python
    # dependencies instead of requiring host system GI/desktop packages.
    (bindir / "python3").symlink_to(sys.executable)
    png = tmp_path / "source.png"
    Image.new("RGB", (16, 12), (24, 42, 64)).save(png)
    env = {
        "PATH": f"{bindir}:/usr/bin:/bin",
        "XDG_SESSION_TYPE": "wayland",
        "XDG_RUNTIME_DIR": str(tmp_path),
        # Stubbed commands never connect to this, nor to a host session bus.
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent-odq-test-bus",
        "SOURCE_PNG": str(png),
        "CALLS": str(tmp_path / "calls"),
    }
    for tool in ("gnome-screenshot", "gdbus"):
        script = bindir / tool
        script.write_text(
            "#!/bin/bash\n"
            "echo \"${0##*/}\" >> \"$CALLS\"\n"
            "tool=${0##*/}\n"
            "if [[ $tool == gnome-screenshot ]]; then\n"
            "  result=${SCREENSHOT_RESULT:-deny}; out=${1#--file=}\n"
            "else\n"
            "  result=${DBUS_RESULT:-deny}; out=${!#}\n"
            "fi\n"
            "case $result in\n"
            '  success) cp "$SOURCE_PNG" "$out";;\n'
            '  corrupt) printf not-a-png > "$out";;\n'
            '  deny) echo "AccessDenied" >&2; exit 1;;\n'
            "esac\n"
        )
        script.chmod(0o755)
    return tmp_path / "usr/local/lib/odq/capture", env, tmp_path / "output.png"


def execute_capture(fixture, **overrides):
    helper, env, output = fixture
    return subprocess.run(
        [str(helper), str(output)], env=env | overrides, capture_output=True, text=True
    )


def test_capture_decodes_png_and_does_not_use_fallback(capture):
    result = execute_capture(capture, SCREENSHOT_RESULT="success")
    assert result.returncode == 0, result.stderr
    with Image.open(capture[2]) as image:
        image.load()
        assert image.size == (16, 12)
    assert Path(capture[1]["CALLS"]).read_text().splitlines() == ["gnome-screenshot"]


def test_capture_fallback_after_invalid_first_image(capture):
    result = execute_capture(capture, SCREENSHOT_RESULT="corrupt", DBUS_RESULT="success")
    assert result.returncode == 0, result.stderr
    with Image.open(capture[2]) as image:
        image.verify()
    assert Path(capture[1]["CALLS"]).read_text().splitlines() == ["gnome-screenshot", "gdbus"]


@pytest.mark.parametrize("first,second", [("deny", "deny"), ("corrupt", "corrupt")])
def test_denied_or_corrupt_capture_cannot_produce_false_proof(capture, first, second):
    result = execute_capture(capture, SCREENSHOT_RESULT=first, DBUS_RESULT=second)
    assert result.returncode == 78
    assert not capture[2].exists()
    assert not list(capture[2].parent.glob(".gnome-capture.*"))


def test_capture_rejects_x11_and_preserves_existing_evidence(capture):
    result = execute_capture(capture, XDG_SESSION_TYPE="x11", SCREENSHOT_RESULT="success")
    assert result.returncode == 78
    assert not Path(capture[1]["CALLS"]).exists()
    capture[2].write_bytes(b"original evidence")
    result = execute_capture(capture, SCREENSHOT_RESULT="success")
    assert result.returncode == 64
    assert capture[2].read_bytes() == b"original evidence"
    assert not Path(capture[1]["CALLS"]).exists()


def test_guard_refuses_non_vm_before_provisioning():
    # Root runner exercises VM refusal. A nonroot runner is refused even sooner.
    result = subprocess.run(
        ["bash", "-c", f"source {shlex.quote(str(RECIPE))}; "
         "systemd-detect-virt() { return 1; }; gnome_guard"],
        env={"PATH": "/usr/bin:/bin"},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 1
    assert "non-VM" in result.stderr if os.geteuid() == 0 else "guest root" in result.stderr


@pytest.mark.parametrize("status", [0, 1])
@pytest.mark.parametrize("existing", ["absent", "regular", "symlink"])
def test_package_policy_restored_even_on_failure(tmp_path, status, existing):
    directory = tmp_path / "usr/sbin"
    directory.mkdir(parents=True)
    policy = directory / "policy-rc.d"
    original = directory / "original-policy"
    original.write_text("#!/bin/sh\nexit 42\n")
    if existing == "regular":
        policy.write_bytes(original.read_bytes())
        policy.chmod(0o751)
    elif existing == "symlink":
        policy.symlink_to(original)
    result = subprocess.run(
        ["bash", "-c", f"source {shlex.quote(str(RECIPE))}; "
         'check_policy() { "$1/usr/sbin/policy-rc.d"; }; '
         'probe() { set +e; check_policy "$1"; actual=$?; set -e; '
         '[[ $actual == 101 ]] || exit 99; exit "$2"; }; '
         'gnome_with_service_policy "$1" probe "$1" "$2"',
         "_", str(tmp_path), str(status)],
        env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True,
    )
    assert result.returncode == status, result.stderr
    if existing == "absent":
        assert not policy.exists()
    else:
        assert policy.read_bytes() == original.read_bytes()
        assert policy.is_symlink() == (existing == "symlink")
        if existing == "regular":
            assert policy.stat().st_mode & 0o777 == 0o751
    assert not list(directory.glob("odq-policy-rc.d.*"))
