"""D17 owner parity with real authentication and isolated host inventory."""
import asyncio
import json
from dataclasses import replace

import pytest

from src.config.schema import ToolHost
from src.json_store import StoreCorruptError
from src.permissions.host_access import HostAccessManager
from src.permissions.persistence import write_private_atomic
from src.tools.hosts import HostRegistry
from tests.desktop_adapters.tools_cases import owner_fixture


@pytest.fixture
def owner(tmp_path):
    with owner_fixture(tmp_path) as state:
        yield state


def access_for(owner, **kwargs):
    return HostAccessManager(
        owner.paths.config_dir / "host-preferences.json",
        permission_manager=owner.manager,
        **kwargs,
    )


@pytest.mark.parametrize("legacy", [
    "missing", "empty", "corrupt", "empty-allowlist", "insecure", "private",
])
def test_legacy_policy_is_not_read_or_migrated(owner, monkeypatch, legacy):
    path = owner.paths.config_dir / "host-policy.json"
    if legacy != "missing":
        payload = {
            "empty": "", "corrupt": "{broken",
            "empty-allowlist": '{"allowed_hosts":[],"default_host":""}',
            "insecure": '{"allowed_hosts":[]}',
            "private": '{"allowed_hosts":["alpha"],"default_host":"alpha"}',
        }[legacy]
        write_private_atomic(path, payload)
        if legacy == "insecure":
            path.chmod(0o644)
    before = path.read_bytes() if path.exists() else None
    monkeypatch.setattr("src.permissions.host_access.runtime_profile_paths", lambda: owner.paths)
    access = HostAccessManager(available_hosts=["alpha", "beta"], permission_manager=owner.manager)
    assert access._path == owner.paths.config_dir / "host-preferences.json"
    assert access.get_allowed_hosts(owner.authority.owner_id) == ["alpha", "beta"]
    assert access.get_default_host(owner.authority.owner_id) == ""
    assert access.is_host_allowed(owner.authority.owner_id, "beta")
    assert not access._path.exists()
    assert (path.read_bytes() if path.exists() else None) == before
    assert not list(owner.paths.config_dir.glob("host-policy.json.corrupt-*"))


async def test_default_only_preference_persists_and_never_grants_or_narrows(owner):
    access = access_for(owner, available_hosts=["alpha", "beta"])
    assert await access.set_default_host(owner.authority.owner_id, "beta")
    assert json.loads(access._path.read_text()) == {"default_host": "beta"}
    assert access._path.stat().st_mode & 0o777 == 0o600
    reloaded = access_for(owner, available_hosts=["alpha", "beta"])
    assert reloaded.get_default_host(owner.authority.owner_id) == "beta"
    assert reloaded.get_allowed_hosts(owner.authority.owner_id) == ["alpha", "beta"]
    with pytest.raises(ValueError, match="not configured or available"):
        await reloaded.set_default_host(owner.authority.owner_id, "absent")
    with pytest.raises(StoreCorruptError):
        await reloaded.set_default_host(owner.authority.owner_id, ["alpha"])
    reloaded.set_available_hosts(["alpha"])
    assert reloaded.get_default_host(owner.authority.owner_id) == ""
    assert reloaded.get_allowed_hosts(owner.authority.owner_id) == ["alpha"]
    reloaded.set_available_hosts(["alpha", "beta"])
    assert reloaded.get_default_host(owner.authority.owner_id) == "beta"
    assert await reloaded.set_default_host(owner.authority.owner_id, "")
    assert reloaded.get_default_host(owner.authority.owner_id) == ""
    assert not hasattr(access, "set_policy")
    assert not hasattr(access, "set_request_host_scope")
    assert not hasattr(access, "default_policy")


@pytest.mark.parametrize("preference", [
    "missing", "corrupt", "insecure", "unknown", "symlink", "directory",
])
def test_bad_preference_unavailable_but_inventory_unaffected(owner, preference):
    access = access_for(owner, available_hosts=["alpha", "beta"])
    if preference in {"corrupt", "insecure", "unknown"}:
        write_private_atomic(access._path, "{broken" if preference == "corrupt" else json.dumps(
            {"default_host": "absent" if preference == "unknown" else "beta"}
        ))
        if preference == "insecure":
            access._path.chmod(0o644)
    elif preference == "symlink":
        target = owner.paths.config_dir / "target.json"
        write_private_atomic(target, '{"default_host":"beta"}')
        access._path.symlink_to(target)
    elif preference == "directory":
        access._path.mkdir(mode=0o700)
    assert access.get_default_host(owner.authority.owner_id) == ""
    assert access.get_allowed_hosts(owner.authority.owner_id) == ["alpha", "beta"]


async def test_live_enrollment_retirement_and_force_revocation_keep_trust_and_leases(owner):
    alpha = ToolHost(address="localhost")
    registry = HostRegistry({"alpha": alpha}, profile_paths=owner.paths)
    access = access_for(owner, available_hosts_provider=registry.active_aliases)
    target = registry.get("alpha")
    lease = registry.acquire("alpha")
    assert lease is not None
    assert access.get_allowed_hosts(owner.authority.owner_id) == ["alpha"]
    # Enrollment publication is immediately visible with no access-store write.
    registry.publish({"alpha": alpha, "beta": ToolHost(address="127.0.0.1")})
    assert access.get_allowed_hosts(owner.authority.owner_id) == ["alpha", "beta"]
    assert registry.get("alpha") is target
    assert lease.target is target
    assert not access._path.exists()
    # Disabling/replacing a leased generation drains it without silently revoking it.
    registry.publish({"beta": ToolHost(address="127.0.0.1")})
    assert access.get_allowed_hosts(owner.authority.owner_id) == ["beta"]
    assert registry.draining_aliases() == ("alpha",)
    assert not lease.revoked
    assert registry.force_revoke("alpha") == 1
    assert lease.revoked
    lease.release()
    beta_lease = registry.acquire("beta")
    assert beta_lease is not None
    assert registry.force_revoke("beta") == 1
    assert access.get_allowed_hosts(owner.authority.owner_id) == []
    beta_lease.release()


def test_owner_access_never_overrides_trust_identity_or_enabled_state(owner):
    from src.tools.hosts.registry import deterministic_host_id

    duplicate = deterministic_host_id("duplicate")
    registry = HostRegistry({
        "usable": ToolHost(address="localhost"),
        "disabled": ToolHost(address="localhost", enabled=False),
        "untrusted": ToolHost(address="example.invalid", trust_mode="pinned"),
        "collision-a": ToolHost(address="localhost", host_id=duplicate),
        "collision-b": ToolHost(address="127.0.0.1", host_id=duplicate),
    }, profile_paths=owner.paths)
    snapshot = registry.snapshot()
    access = access_for(owner, available_hosts_provider=registry.active_aliases)
    assert access.get_allowed_hosts(owner.authority.owner_id) == ["usable"]
    assert registry.snapshot() is snapshot
    assert registry.get("untrusted").trust_state == "invalid"
    assert registry.get("collision-a").trust_state == "identity_collision"
    for alias in ("disabled", "untrusted", "collision-a", "collision-b"):
        assert not access.is_host_allowed(owner.authority.owner_id, alias)
        assert registry.acquire(alias) is None


async def test_concurrent_contexts_require_real_owner_without_ambient_privilege(owner):
    access = access_for(owner, available_hosts=["alpha", "beta"])
    genuine = owner.authority.authenticate_local(peer_uid=owner.authority.owner_uid)
    start = asyncio.Event()

    async def check(context, identity, expected):
        token = owner.manager.set_request_owner(context)
        try:
            await start.wait()
            assert access.get_allowed_hosts(identity) == expected
            assert access.is_host_allowed(identity, "alpha") is bool(expected)
            if not expected:
                with pytest.raises(PermissionError):
                    await access.set_default_host(identity, "alpha")
        finally:
            owner.manager.reset_request_owner(token)

    cases = (
        (genuine, owner.authority.owner_id, ["alpha", "beta"]),
        (None, owner.authority.owner_id, []),
        (genuine, "web-token-user", []),
        (replace(genuine, _seal=object()), owner.authority.owner_id, []),
    )
    tasks = [asyncio.create_task(check(*case)) for case in cases]
    start.set()
    await asyncio.gather(*tasks)
    assert access.get_allowed_hosts(owner.authority.owner_id) == ["alpha", "beta"]
    owner.authority.release_runtime()
    assert access.get_allowed_hosts(owner.authority.owner_id) == []
    assert HostAccessManager(available_hosts=["alpha"]).get_allowed_hosts("owner") == []


async def test_preference_durability_is_not_an_access_fence(owner, monkeypatch):
    import src.permissions.host_access as module

    original = module.write_private_atomic

    def committed_but_degraded(path, content):
        original(path, content)
        return False

    monkeypatch.setattr(module, "write_private_atomic", committed_but_degraded)
    access = access_for(owner, available_hosts=["alpha", "beta"])
    assert await access.set_default_host(owner.authority.owner_id, "alpha") is False
    assert access.durability_degraded
    assert access.get_default_host(owner.authority.owner_id) == "alpha"
    assert access.get_allowed_hosts(owner.authority.owner_id) == ["alpha", "beta"]


async def test_startup_default_warning_uses_preference_not_removed_policy(owner):
    from types import SimpleNamespace

    from src.health.startup import warn_missing_host_defaults

    access = access_for(owner, available_hosts=["alpha"])
    config = SimpleNamespace(hosts={"alpha": ToolHost(address="localhost")}, default_host="")
    assert warn_missing_host_defaults(config, access) == ["default_host"]
    await access.set_default_host(owner.authority.owner_id, "alpha")
    assert warn_missing_host_defaults(config, access) == []
