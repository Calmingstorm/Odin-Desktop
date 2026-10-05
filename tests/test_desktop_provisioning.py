"""Fresh-profile host parity through the real executor dispatch graph."""
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.config.schema import load_config
from src.desktop.authority import OwnerAuthority
from src.desktop.paths import ProfilePaths
from src.desktop.provisioning import ensure_profile, fresh_config, provision_fresh_profile
from src.permissions.host_access import HostAccessManager
from src.permissions.manager import PermissionManager
from src.tools.builtin_policy import BuiltinToolPolicy
from src.tools.executor import ToolExecutor
from src.tools.hosts.trust import fingerprint_public_key


@pytest.fixture
def profile(tmp_path):
    paths = ProfilePaths.from_xdg("fresh", environ={
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }, home=tmp_path)
    authority = OwnerAuthority(paths)
    manager = PermissionManager(authority)
    token = manager.set_request_owner(authority.authenticate_local(peer_uid=os.geteuid()))
    try:
        yield SimpleNamespace(paths=paths, authority=authority, manager=manager)
    finally:
        manager.reset_request_owner(token)
        authority.release_runtime()


def test_explicit_profile_independent_paths_and_alongside_sentinel(profile, tmp_path):
    sentinel = tmp_path / "other-installation.yml"
    sentinel.write_text("tools: {default_host: remote}\ncredential: unrelated\n")
    original = sentinel.read_bytes()
    config = ensure_profile(profile.paths, authority=profile.authority)
    assert config.tools.default_host == "localhost"
    assert config.tools.hosts["localhost"].address == "127.0.0.1"
    assert config.tools.hosts["localhost"].description == "Local Odin workspace"
    workspace = Path(config.tools.local_working_dir)
    assert workspace.is_dir() and not workspace.is_relative_to(profile.paths.data_dir)
    assert config.sessions.persist_directory == str(profile.paths.data_dir / "sessions")
    assert config.search.search_db_path == str(profile.paths.data_dir / "search")
    assert config.openai_codex.credentials_path == str(
        profile.paths.secrets_dir / "codex_auth.json"
    )
    assert load_config(profile.paths.config_file).tools == config.tools
    saved = profile.paths.config_file.read_bytes()
    ensure_profile(profile.paths, authority=profile.authority)
    assert profile.paths.config_file.read_bytes() == saved
    assert sentinel.read_bytes() == original
    with pytest.raises(FileExistsError):
        provision_fresh_profile(profile.paths)


def test_group_writable_parent_is_not_refused(profile, tmp_path):
    tmp_path.chmod(0o775)
    config = ensure_profile(profile.paths, authority=profile.authority)
    assert config.tools.default_host == "localhost"
    assert tmp_path.stat().st_mode & 0o777 == 0o775


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["ensure", "provision"])
async def test_fresh_profile_public_key_is_usable_and_preserved(profile, entrypoint):
    from src.desktop.hosts import HostsService
    from src.desktop.secrets import ProfileSecretStore
    from src.desktop.settings import SettingsService

    if entrypoint == "provision":
        provision_fresh_profile(profile.paths)
        config = load_config(profile.paths.config_file)
    else:
        config = ensure_profile(profile.paths, authority=profile.authority)
    key = profile.paths.secrets_dir / "id_ed25519"
    assert config.tools.ssh_key_path == str(key)
    assert key.stat().st_mode & 0o777 == 0o600
    private = key.read_bytes()
    before = key.stat()
    settings = SettingsService(
        profile.paths, ProfileSecretStore(profile.paths, backend=SimpleNamespace()), config=config
    )
    public = await HostsService(settings).handle("hosts.public_key", {})
    assert public["public_key"].startswith("ssh-ed25519 ")
    assert public["fingerprint"] == fingerprint_public_key(public["public_key"])
    assert not public["restart_pending"]
    # A second provisioning/start path must use the identical key, not just its type.
    config = ensure_profile(profile.paths, authority=profile.authority)
    settings = SettingsService(profile.paths, settings.secrets, config=config)
    assert await HostsService(settings).handle("hosts.public_key", {}) == public
    assert key.read_bytes() == private
    assert key.stat().st_ino == before.st_ino
    assert key.stat().st_mtime_ns == before.st_mtime_ns
    assert not list(profile.paths.secrets_dir.glob(".ssh-key-*"))


def test_existing_profile_repairs_absent_default_key_without_rewriting_config(profile):
    config = ensure_profile(profile.paths, authority=profile.authority)
    key = Path(config.tools.ssh_key_path)
    saved = profile.paths.config_file.read_bytes()
    key.unlink()
    ensure_profile(profile.paths, authority=profile.authority)
    assert key.read_bytes().startswith(b"-----BEGIN OPENSSH PRIVATE KEY-----")
    assert key.stat().st_mode & 0o777 == 0o600
    assert profile.paths.config_file.read_bytes() == saved


def test_existing_config_load_does_not_hold_identity_lock(profile, monkeypatch):
    import fcntl

    ensure_profile(profile.paths, authority=profile.authority)
    load = load_config
    observed = []

    def checked_load(path):
        with (profile.paths.config_dir / ".identity.lock").open("rb") as stream:
            # A second descriptor must be able to acquire the identity lock,
            # exactly as selected-profile migration's OwnerAuthority does.
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            observed.append(path)
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        return load(path)

    monkeypatch.setattr("src.desktop.provisioning.load_config", checked_load)
    ensure_profile(profile.paths, authority=profile.authority)
    assert observed == [profile.paths.config_file]


def test_existing_key_is_never_overwritten_during_first_provisioning(profile):
    key = profile.paths.secrets_dir / "id_ed25519"
    key.write_bytes(b"pre-existing-key-sentinel")
    before = key.stat()
    ensure_profile(profile.paths, authority=profile.authority)
    assert key.read_bytes() == b"pre-existing-key-sentinel"
    assert key.stat().st_ino == before.st_ino
    assert key.stat().st_mode == before.st_mode


def test_existing_config_custom_key_path_is_not_provisioned(profile, tmp_path):
    import yaml

    config = fresh_config(profile.paths)
    custom = tmp_path / "external-key"
    config.tools.ssh_key_path = str(custom)
    profile.paths.config_file.write_text(yaml.safe_dump(config.model_dump(mode="json")))
    profile.paths.config_file.chmod(0o600)
    saved = profile.paths.config_file.read_bytes()
    loaded = ensure_profile(profile.paths, authority=profile.authority)
    assert loaded.tools.ssh_key_path == str(custom)
    assert not custom.exists()
    assert not (profile.paths.secrets_dir / "id_ed25519").exists()
    assert profile.paths.config_file.read_bytes() == saved


def test_existing_key_symlink_is_not_replaced(profile, tmp_path):
    target = tmp_path / "external-key"
    key = profile.paths.secrets_dir / "id_ed25519"
    key.symlink_to(target)
    ensure_profile(profile.paths, authority=profile.authority)
    assert key.is_symlink() and key.readlink() == target
    assert not target.exists()


def test_key_created_during_generation_is_not_overwritten(profile, monkeypatch):
    import src.desktop.provisioning as provisioning

    key = profile.paths.secrets_dir / "id_ed25519"
    generate = provisioning.subprocess.run

    def racing_generation(*args, **kwargs):
        result = generate(*args, **kwargs)
        key.write_bytes(b"concurrent-key-sentinel")
        key.chmod(0o600)
        return result

    monkeypatch.setattr(provisioning.subprocess, "run", racing_generation)
    ensure_profile(profile.paths, authority=profile.authority)
    assert key.read_bytes() == b"concurrent-key-sentinel"
    assert not list(profile.paths.secrets_dir.glob(".ssh-key-*"))


def test_failed_key_generation_can_retry_without_publishing_config(profile, monkeypatch):
    import subprocess

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], stderr="dummy-secret")

    with monkeypatch.context() as patch:
        patch.setattr("src.desktop.provisioning.subprocess.run", fail)
        with pytest.raises(RuntimeError, match="^Could not provision the profile SSH key$"):
            ensure_profile(profile.paths, authority=profile.authority)
    assert not profile.paths.config_file.exists()
    assert not (profile.paths.secrets_dir / "id_ed25519").exists()
    assert not list(profile.paths.secrets_dir.glob(".ssh-key-*"))
    ensure_profile(profile.paths, authority=profile.authority)
    assert load_config(profile.paths.config_file).tools.default_host == "localhost"


def test_fresh_settings_image_intent_follows_defaults(profile):
    from src.desktop.secrets import ProfileSecretStore
    from src.desktop.settings import SettingsService

    backend = SimpleNamespace(get_password=lambda *_: None)
    config = ensure_profile(profile.paths, authority=profile.authority)
    settings = SettingsService(
        profile.paths, ProfileSecretStore(profile.paths, backend=backend), config=config
    )
    metadata = settings.schema()["image_models"]
    assert metadata["image_model"]["status"] == "follow"
    assert metadata["outer_model"]["status"] == "follow"


@pytest.mark.asyncio
@pytest.mark.parametrize("preference", ["{broken", '{"default_host":"absent"}',
                                       '{"allowed_hosts":[]}'])
async def test_real_executor_host_selection_and_local_probe(profile, preference):
    config = ensure_profile(profile.paths, authority=profile.authority)
    executor = ToolExecutor(config.tools, permission_manager=profile.manager,
                            profile_paths=profile.paths, app_config=config)
    access = HostAccessManager(profile.paths.config_dir / "host-preferences.json",
                               available_hosts_provider=executor.host_registry.active_aliases,
                               permission_manager=profile.manager)
    executor._host_access = access
    executor._builtin_policy = BuiltinToolPolicy(lambda: config, lambda: {
        "run_command": True, "http_probe": True,
    })
    # Stub only the transport primitive: actual policy/handler/default/lease
    # dispatch remains intact. No subprocess or real network is contacted.
    execute = AsyncMock(return_value=(0, "harmless fixture output"))
    executor._exec_command = execute
    executor._branch_freshness_enabled = False
    acquire = Mock(wraps=executor.host_registry.acquire)
    executor.host_registry.acquire = acquire
    preference_path = access._path
    preference_path.write_text(preference)
    preference_path.chmod(0o600)
    owner = profile.authority.owner_id
    assert access.get_allowed_hosts(owner) == ["localhost"]
    for host in ("localhost", None):
        params = {"command": "printf 'desktop-test\\n'"}
        if host:
            params["host"] = host
        result = await executor.execute("run_command", params, user_id=owner)
        assert result.ok, result.output
        assert execute.call_args.args[0] == "127.0.0.1"
        assert acquire.call_args.args[0] == "localhost"
    count = execute.await_count
    result = await executor.execute(
        "run_command", {"host": "missing-remote", "command": "printf test"}, user_id=owner
    )
    assert not result.ok and result.error == "host_denied"
    assert execute.await_count == count
    # http_probe deliberately keeps Odin's local fallback even with no default.
    executor.host_registry.publish(config.tools.hosts, default_host="")
    acquire.reset_mock()
    result = await executor.execute("http_probe", {"url": "https://example.invalid"}, user_id=owner)
    assert result.ok, result.output
    assert execute.call_args.args[0] == "127.0.0.1"
    assert "target" not in execute.call_args.kwargs
    acquire.assert_not_called()
    count = execute.await_count
    result = await executor.execute(
        "http_probe", {"url": "https://example.invalid", "host": "missing-remote"}, user_id=owner
    )
    assert not result.ok
    assert execute.await_count == count
    assert preference_path.read_text() == preference


def test_fresh_config_does_not_use_ambient_profile(profile, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "unrelated"))
    config = fresh_config(profile.paths)
    assert config.context.directory == str(profile.paths.data_dir / "context")
    assert config.tools.ssh_key_path == str(profile.paths.secrets_dir / "id_ed25519")
    assert config.computer.storage_dir == str(profile.paths.data_dir / "computer")


@pytest.mark.asyncio
async def test_shallow_app_profile_executes_only_in_its_workspace(tmp_path):
    paths = ProfilePaths.from_app(
        "shallow", token_file=tmp_path / "config" / "token",
        data_dir=tmp_path / "data", home=tmp_path,
        environ={"XDG_CACHE_HOME": str(tmp_path / "cache")},
    )
    authority = OwnerAuthority(paths)
    sentinel = tmp_path / "alongside" / "installation"
    sentinel.parent.mkdir()
    sentinel.write_bytes(b"not Desktop state")
    manager = PermissionManager(authority)
    token = manager.set_request_owner(authority.authenticate_local(peer_uid=os.geteuid()))
    try:
        config = ensure_profile(paths, authority=authority)
        workspace = Path(config.tools.local_working_dir)
        assert workspace.is_relative_to(tmp_path)
        assert not workspace.is_relative_to(paths.data_dir)
        executor = ToolExecutor(config.tools, permission_manager=manager,
                                profile_paths=paths, app_config=config)
        executor._builtin_policy = BuiltinToolPolicy(lambda: config, lambda: {"run_command": True})
        # This runs only printf and pwd, proving the real workspace fence/cwd.
        result = await executor.execute("run_command", {"command": "printf 'cwd:'; pwd"},
                                        user_id=authority.owner_id)
        assert result.ok, result.output
        assert f"cwd:{workspace}" in result.output
        assert sentinel.read_bytes() == b"not Desktop state"
    finally:
        manager.reset_request_owner(token)
        authority.release_runtime()
