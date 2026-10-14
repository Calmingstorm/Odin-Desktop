"""macOS Desktop helpers: SSH control-socket paths (the 103-byte bound and the /private/tmp
fallback), and this Mac as a new profile's local host, which the Hosts panel checks as macos."""
from __future__ import annotations

import base64
import os
import shutil
import stat
import tempfile
import uuid
from pathlib import Path

import pytest

from src.desktop import ssh_sockets
from src.desktop.platform import macos_desktop
from src.desktop.platform.macos import macos_profile_paths


@pytest.fixture
def profile(tmp_path):
    name = f"t{uuid.uuid4().hex[:10]}"
    yield macos_profile_paths(name, home=tmp_path)
    shutil.rmtree(macos_desktop._fallback_root() / name, ignore_errors=True)


def test_the_routes_reach_the_macos_variants():
    target = "src.desktop.platform.macos_desktop:"
    assert ssh_sockets.check_socket_path.darwin_target == target + "check_socket_path"
    assert ssh_sockets.socket_directory.darwin_target == target + "socket_directory"
    assert ssh_sockets.prepare_socket_directory.darwin_target == target + "prepare_socket_directory"


def test_the_bound_keeps_room_for_the_openssh_suffix():
    base = "/private/tmp/" + "x" * (103 - 17 - len("/private/tmp/"))
    ssh_sockets.check_socket_path(base)  # exactly at the bound
    with pytest.raises(ValueError, match="maximum 103"):
        ssh_sockets.check_socket_path(base + "x")
    with pytest.raises(ValueError):
        ssh_sockets.check_socket_path("/private/tmp/a\0b")


def test_the_default_falls_back_to_private_tmp_and_is_created_private(profile, monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    provisioned = str(profile.cache_dir / "ssh-sockets")
    assert not ssh_sockets._fits(provisioned)  # Library/Caches is too long for a socket
    chosen = ssh_sockets.effective_socket_directory(provisioned, profile)
    expected = macos_desktop._fallback_root() / profile.profile_id / "ssh"
    assert chosen == str(expected)
    ssh_sockets.prepare_socket_directory(chosen)
    for path in (expected, expected.parent, expected.parent.parent):
        info = os.lstat(path)
        assert info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700
    ssh_sockets.prepare_socket_directory(chosen)  # idempotent


def test_a_long_profile_uses_the_compact_namespace(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    paths = macos_profile_paths("p" * 60, home=tmp_path)
    chosen = Path(macos_desktop.socket_directory(paths))
    assert chosen.parent.name.startswith("p-") and len(chosen.parent.name) == 14


def test_a_private_xdg_runtime_root_is_preferred(tmp_path, monkeypatch):
    # Short names: the runtime root's socket path must fit the 103-byte bound itself.
    runtime = Path(tempfile.mkdtemp(prefix="o", dir="/private/tmp"))  # mode 0700
    profile = macos_profile_paths("x" + uuid.uuid4().hex[:3], home=tmp_path)
    try:
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
        chosen = macos_desktop.socket_directory(profile)
        assert chosen == str(runtime / "odin-desktop" / profile.profile_id / "ssh")
        macos_desktop.prepare_socket_directory(chosen)
        assert stat.S_IMODE(os.lstat(chosen).st_mode) == 0o700
        runtime.chmod(0o755)  # no longer private: refused, never repaired
        with pytest.raises(PermissionError, match="Unsafe Desktop SSH XDG runtime root"):
            macos_desktop.prepare_socket_directory(chosen)
    finally:
        runtime.chmod(0o700)
        shutil.rmtree(runtime, ignore_errors=True)


def test_a_planted_fallback_namespace_is_refused(profile, monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    root = macos_desktop._fallback_root()
    root.mkdir(mode=0o700, exist_ok=True)
    planted = root / profile.profile_id
    planted.mkdir(mode=0o755)  # not this user's exact 0700
    with pytest.raises(PermissionError, match="Unsafe Desktop SSH runtime directory"):
        macos_desktop.prepare_socket_directory(str(planted / "ssh"))
    assert stat.S_IMODE(os.lstat(planted).st_mode) == 0o755  # never chmodded


def test_a_custom_directory_keeps_pool_policy(tmp_path):
    custom = tmp_path / "custom" / "ssh"
    macos_desktop.prepare_socket_directory(str(custom))
    assert not custom.exists()  # neither managed root: nothing created here


def test_no_bounded_directory_is_an_error(profile, monkeypatch):
    monkeypatch.setattr(ssh_sockets, "_fits", lambda candidate: False)
    with pytest.raises(ValueError, match="No bounded Desktop SSH runtime directory"):
        macos_desktop.socket_directory(profile)


def test_a_new_profile_names_this_mac_macos_and_puts_the_workspace_beside_the_profiles(profile):
    from src.desktop import provisioning
    from src.tools.hosts.control import HostEnrollmentManager

    target = "src.desktop.platform.macos_desktop:"
    assert provisioning.fresh_config_document.darwin_target == target + "fresh_config_document"
    assert HostEnrollmentManager._test.darwin_target == target + "host_test"
    config = provisioning.ensure_profile(profile)
    assert config.tools.hosts["localhost"].os == "macos"
    workspace = profile.data_dir.parents[1] / ".odin-desktop-workspaces" / profile.profile_id
    assert workspace.parent.parent.name == "odin-desktop"  # beside the profiles, not inside one
    assert config.tools.local_working_dir == str(workspace)
    assert stat.S_IMODE(os.lstat(workspace).st_mode) == 0o700
    # Everything else is Linux's provisioned document.
    expected = provisioning.fresh_config_document.linux_original(profile)
    expected["tools"]["hosts"]["localhost"]["os"] = "macos"
    expected["tools"]["local_working_dir"] = str(workspace)
    assert provisioning.fresh_config_document(profile) == expected


def _manager(tmp_path, hosts=None):
    from src.tools.hosts.control import HostEnrollmentManager
    from src.tools.hosts.registry import HostRegistry

    registry = HostRegistry(hosts or {}, key_path="/nonexistent/id_ed25519", trust_dir=tmp_path)
    return registry, HostEnrollmentManager(registry)


@pytest.mark.parametrize("selected, ok, detail", [
    ("macos", True, "authentication and platform verified"),
    ("linux", False, "platform mismatch: observed macos; selected linux"),
])
async def test_the_hosts_panel_checks_this_mac_as_a_macos_host(tmp_path, selected, ok, detail):
    _registry, manager = _manager(tmp_path)
    candidate = await manager.prepare(
        "localhost", {"address": "127.0.0.1", "os": selected, "confirm_local": True},
        allow_tofu=False)
    tested = await manager.test(candidate.token)
    assert tested.tested is ok
    assert tested.test_result["platform"] == "macos"
    assert tested.test_result["detail"] == detail


async def test_a_passing_check_of_the_active_local_host_is_recorded_on_it(tmp_path):
    from src.config.schema import ToolHost

    active = ToolHost(address="127.0.0.1", ssh_user="root", os="macos", trust_mode="legacy")
    registry, manager = _manager(tmp_path, {"localhost": active})
    candidate = await manager.prepare(
        "localhost", {"address": "127.0.0.1", "os": "macos", "confirm_local": True},
        allow_tofu=False, existing=active)
    assert (await manager.test(candidate.token)).tested is True
    assert registry.get("localhost").last_test["ok"] is True


async def test_retesting_an_active_host_never_hands_its_trust_to_cleanup(tmp_path, monkeypatch):
    """Odin 4.15 (#658) on the Mac's lift: a candidate whose trust file a committed host already
    uses never owns it, so discarding the candidate leaves the host's trust in place."""
    from src.config.schema import ToolHost
    from src.tools.hosts import control
    from src.tools.hosts.trust import fingerprint_public_key

    key = "ssh-ed25519 " + base64.b64encode(b"mac-active").decode("ascii")

    async def fake(argv, timeout, **_kwargs):
        if argv[0] == "ssh-keyscan":
            return 0, f"example.invalid {key}\n".encode()
        return 0, b"odin-host-test linux\n"

    monkeypatch.setattr(control, "_run_argv", fake)
    active = ToolHost(address="example.invalid", ssh_user="deploy", os="linux",
                      trust_mode="pinned", host_keys=[key])
    _registry, manager = _manager(tmp_path, {"build": active})
    committed = set(tmp_path.glob("*.known_hosts"))
    assert len(committed) == 1
    candidate = await manager.prepare(
        "build", {"address": "example.invalid", "ssh_user": "deploy", "os": "linux",
                  "trust_mode": "pinned", "expected_fingerprints": [fingerprint_public_key(key)]},
        allow_tofu=False, existing=active)
    assert (await manager.test(candidate.token)).tested is True
    manager.discard(candidate.token)
    assert set(tmp_path.glob("*.known_hosts")) == committed and all(p.exists() for p in committed)


async def test_a_remote_check_is_odins_ssh_probe(tmp_path, monkeypatch):
    from src.tools.hosts import control
    from src.tools.hosts.trust import fingerprint_public_key

    key = "ssh-ed25519 " + base64.b64encode(b"mac-remote").decode("ascii")
    calls = []
    answers = iter([(0, b"odin-host-test linux\n"),
                    (255, b"deploy@example.invalid: Permission denied (publickey)."),
                    TimeoutError()])

    async def fake(argv, timeout, **_kwargs):
        calls.append(argv)
        if argv[0] == "ssh-keyscan":
            return 0, f"example.invalid {key}\n".encode()
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(control, "_run_argv", fake)
    _registry, manager = _manager(tmp_path)
    candidate = await manager.prepare(
        "build", {"address": "example.invalid", "ssh_user": "deploy", "os": "linux",
                  "trust_mode": "pinned", "expected_fingerprints": [fingerprint_public_key(key)]},
        allow_tofu=False)
    tested = await manager.test(candidate.token)
    assert tested.tested is True and tested.test_result["platform"] == "linux"
    ssh = calls[-1]
    assert ssh[0] == "ssh" and ssh[-2:-1] == ["deploy@example.invalid"]
    assert f"HostKeyAlias=odin-{candidate.host_id}" in ssh and "BatchMode=yes" in ssh
    assert "uname -s" in ssh[-1]  # the remote system is asked, as Odin asks it
    refused = await manager.test(candidate.token)
    assert refused.tested is False
    assert refused.test_result["detail"] == "deploy@example.invalid: Permission denied (publickey)."
    assert refused.test_result["platform"] == ""  # the probe never ran
    late = await manager.test(candidate.token)
    assert late.test_result == {"ok": False, "checked_at": late.test_result["checked_at"],
                                "platform": "", "detail": "connection test timed out"}
    # The candidate's own trust file goes when it is discarded (Odin 4.15, #658).
    trust = list(tmp_path.glob("*.known_hosts"))
    assert len(trust) == 1 and f"UserKnownHostsFile={trust[0]}" in ssh
    manager.discard(candidate.token)
    assert not trust[0].exists()
