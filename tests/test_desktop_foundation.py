"""Foundation proofs use only temporary profiles and harmless failures."""
import json
import os
from dataclasses import replace

import pytest

from src.desktop.authority import OwnerAuthority
from src.desktop.capabilities import publish_capabilities
from src.desktop.paths import ProfilePaths, private_directory
from src.desktop.secrets import ProfileSecretStore
from src.permissions.host_access import HostAccessManager
from src.permissions.manager import PermissionManager


def paths(tmp_path, profile="default"):
    return ProfilePaths.from_xdg(profile, environ={}, home=tmp_path)

def test_xdg_namespaces(tmp_path):
    first, second = paths(tmp_path), paths(tmp_path, "second")
    assert first.data_dir == tmp_path / ".local/share/odin-desktop/default"
    assert first.config_dir != first.data_dir != first.cache_dir
    assert first.environment_file.parent == first.secrets_dir
    assert second.identity_file != first.identity_file
    assert not first.identity_file.exists()
    first.create_private()
    assert all(
        p.stat().st_mode & 0o777 == 0o700
        for p in (first.config_dir, first.data_dir, first.cache_dir, first.secrets_dir)
    )

@pytest.mark.parametrize("profile", ["", ".", "../other", "with space", "x" * 65])
def test_invalid_profile(tmp_path, profile):
    with pytest.raises(ValueError):
        paths(tmp_path, profile)

def test_invalid_xdg(tmp_path):
    with pytest.raises(ValueError):
        ProfilePaths.from_xdg(environ={"XDG_DATA_HOME": "relative"}, home=tmp_path)
    with pytest.raises(ValueError):
        ProfilePaths.from_xdg(
            environ={"XDG_DATA_HOME": str(tmp_path), "XDG_CACHE_HOME": str(tmp_path)},
            home=tmp_path,
        )

def test_directory_symlink_followed_without_unrelated_permission_repair(tmp_path):
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    private_directory(link / "private")
    assert (target / "private").stat().st_mode & 0o777 == 0o700
    target.chmod(0o755)
    private_directory(target)
    assert target.stat().st_mode & 0o777 == 0o755

def test_owner_identity_stable_context_runtime_bound(tmp_path):
    authority, second = OwnerAuthority(paths(tmp_path)), OwnerAuthority(paths(tmp_path))
    context = authority.authenticate_local(peer_uid=os.geteuid())
    assert second.installation_id == authority.installation_id
    assert second.owner_id == authority.owner_id
    assert second.runtime_id != authority.runtime_id
    assert authority.accepts(context)
    assert not second.accepts(context)
    assert not authority.accepts(replace(context, owner_id="not-owner"))
    assert not authority.accepts(replace(context, _seal=object()))
    with pytest.raises(PermissionError):
        authority.authenticate_local(peer_uid=os.geteuid() + 1)
    with pytest.raises(PermissionError):
        authority.authenticate_local(peer_uid=True)

def test_permission_manager_not_always_owner(tmp_path):
    authority = OwnerAuthority(paths(tmp_path))
    manager = PermissionManager(authority)
    assert not manager.is_owner(authority.owner_id)
    assert manager.allowed_tool_names(authority.owner_id) == set()
    marker = manager.set_request_owner(authority.authenticate_local(peer_uid=os.geteuid()))
    try:
        assert manager.is_owner(authority.owner_id)
        assert not manager.is_owner("payload-owner")
        assert manager.allowed_tool_names(authority.owner_id) is None
        assert manager.filter_tools("payload-owner", [{"name": "anything"}]) is None
    finally:
        manager.reset_request_owner(marker)
    assert not manager.is_owner(authority.owner_id)
    assert not hasattr(manager, "get_tier")
    assert not hasattr(manager, "is_admin")

def test_corrupt_foreign_identity_preserved(tmp_path):
    profile = paths(tmp_path)
    OwnerAuthority(profile)
    data = json.loads(profile.identity_file.read_text())
    data["owner_uid"] = os.geteuid() + 1
    profile.identity_file.write_text(json.dumps(data))
    before = profile.identity_file.read_bytes()
    with pytest.raises(ValueError):
        OwnerAuthority(profile)
    assert profile.identity_file.read_bytes() == before
    profile.identity_file.write_text("not-json")
    with pytest.raises(ValueError):
        OwnerAuthority(profile)

def test_fresh_identity_not_adopt_existing_config(tmp_path):
    profile = paths(tmp_path)
    profile.create_private()
    profile.config_file.write_text("{}")
    with pytest.raises(ValueError):
        OwnerAuthority(profile)
    assert not profile.identity_file.exists()

def test_runtime_exclusive_lock(tmp_path):
    first, second = OwnerAuthority(paths(tmp_path)), OwnerAuthority(paths(tmp_path))
    first.acquire_runtime()
    try:
        with pytest.raises(BlockingIOError):
            second.acquire_runtime()
    finally:
        first.release_runtime()
    second.acquire_runtime()
    second.release_runtime()

@pytest.mark.asyncio
async def test_host_owner_access_tracks_availability_not_preferences(tmp_path):
    authority = OwnerAuthority(paths(tmp_path))
    manager = PermissionManager(authority)
    access = HostAccessManager(
        authority.paths.config_dir / "host-preferences.json",
        ["local", "remote"],
        permission_manager=manager,
    )
    assert access.get_allowed_hosts(authority.owner_id) == []
    with pytest.raises(PermissionError):
        await access.set_default_host(authority.owner_id, "local")
    marker = manager.set_request_owner(authority.authenticate_local(peer_uid=os.geteuid()))
    try:
        await access.set_default_host(authority.owner_id, "remote")
        assert access.get_allowed_hosts(authority.owner_id) == ["local", "remote"]
        assert access.get_default_host(authority.owner_id) == "remote"
        access.set_available_hosts(["local"])
        assert access.get_allowed_hosts(authority.owner_id) == ["local"]
        assert access.get_default_host(authority.owner_id) == ""
    finally:
        manager.reset_request_owner(marker)

def test_secrets_private_separate(tmp_path):
    profile = paths(tmp_path)
    store = ProfileSecretStore(profile)
    assert store.get("example") is None
    store.set("example", "dummy-value")
    assert store.get("example") == "dummy-value"
    assert (profile.secrets_dir / "example").stat().st_mode & 0o777 == 0o600
    assert not (profile.config_dir / "example").exists()
    with pytest.raises(ValueError):
        store.get("../example")

@pytest.mark.parametrize("value", [None, False, 1, "true", {}, []])
def test_readiness_exact_true(value):
    assert publish_capabilities([{"name": "feature"}], {"feature": value}) == []

def test_unconfigured_publishes_nothing():
    assert publish_capabilities([{"name": "feature"}]) == []
    assert publish_capabilities([{"name": "feature"}], {"feature": True}) == [{"name": "feature"}]

def test_identity_durability_degraded_cannot_authenticate(tmp_path, monkeypatch):
    import src.desktop.authority as module
    original = module.write_private_atomic
    def committed_but_unproven(path, content):
        original(path, content)
        return False
    monkeypatch.setattr(module, "write_private_atomic", committed_but_unproven)
    authority = OwnerAuthority(paths(tmp_path))
    assert authority.durability_degraded
    with pytest.raises(PermissionError):
        authority.authenticate_local(peer_uid=os.geteuid())

def test_context_revoked_on_identity_corruption(tmp_path):
    authority = OwnerAuthority(paths(tmp_path))
    context = authority.authenticate_local(peer_uid=os.geteuid())
    authority.paths.identity_file.write_text("not-json")
    assert not authority.accepts(context)
    with pytest.raises(PermissionError):
        authority.authenticate_local(peer_uid=os.geteuid())

def test_private_persistence_precommit_failure_preserves_value(tmp_path, monkeypatch):
    import src.permissions.persistence as module
    directory = tmp_path / "private"
    private_directory(directory)
    path = directory / "state.json"
    module.write_private_atomic(path, "old")
    def failed(*args, **kwargs):
        raise OSError("harmless injected fsync failure")
    monkeypatch.setattr(module.os, "fsync", failed)
    with pytest.raises(OSError):
        module.write_private_atomic(path, "new")
    assert path.read_text() == "old"
    assert sorted(p.name for p in directory.iterdir()) == ["state.json"]

def test_private_persistence_postcommit_failure_reports_degraded(tmp_path, monkeypatch):
    import stat

    import src.permissions.persistence as module
    directory = tmp_path / "private"
    private_directory(directory)
    path = directory / "state.json"
    original = module.os.fsync
    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("harmless injected directory fsync failure")
        original(fd)
    monkeypatch.setattr(module.os, "fsync", fail_directory)
    assert module.write_private_atomic(path, "committed") is False
    assert path.read_text() == "committed"

def test_private_persistence_rejects_symlink(tmp_path):
    from src.permissions.persistence import write_private_atomic
    directory = tmp_path / "private"
    private_directory(directory)
    target = directory / "target"
    target.write_text("unchanged")
    alias = directory / "alias"
    alias.symlink_to(target)
    with pytest.raises(PermissionError):
        write_private_atomic(alias, "new")
    assert target.read_text() == "unchanged"

@pytest.mark.asyncio
async def test_host_preference_corruption_never_revokes_owner(tmp_path):
    authority = OwnerAuthority(paths(tmp_path))
    manager = PermissionManager(authority)
    path = authority.paths.config_dir / "host-preferences.json"
    access = HostAccessManager(path, ["local"], permission_manager=manager)
    marker = manager.set_request_owner(authority.authenticate_local(peer_uid=os.geteuid()))
    try:
        await access.set_default_host(authority.owner_id, "local")
        assert access.get_allowed_hosts(authority.owner_id) == ["local"]
        path.write_text("not-json")
        assert access.get_allowed_hosts(authority.owner_id) == ["local"]
        assert access.get_default_host(authority.owner_id) == ""
        path.write_text('{"default_host": "absent"}')
        assert access.get_allowed_hosts(authority.owner_id) == ["local"]
        assert access.get_default_host(authority.owner_id) == ""
    finally:
        manager.reset_request_owner(marker)
        authority.release_runtime()

def test_runtime_release_revokes_context(tmp_path):
    authority = OwnerAuthority(paths(tmp_path))
    context = authority.authenticate_local(peer_uid=os.geteuid())
    assert authority.accepts(context)
    authority.release_runtime()
    assert not authority.accepts(context)
