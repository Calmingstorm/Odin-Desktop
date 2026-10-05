"""Fresh, independent Desktop state, never an import of a server installation."""
from __future__ import annotations

from pathlib import Path

import yaml

from ..config.model_defaults import DEFAULT_AUXILIARY_MODEL, DEFAULT_MAIN_MODEL
from ..config.schema import Config, load_config
from ..permissions.persistence import write_private_atomic
from .authority import OwnerAuthority
from .paths import ProfilePaths


def fresh_config_document(paths: ProfilePaths) -> dict:
    """Bind every path default to the explicit profile, not the process HOME.

    The local inventory/default match Odin's pinned config template. Local is
    already trusted: provisioning is not remote enrollment or owner consent.
    """
    data, cache, secrets = paths.data_dir, paths.cache_dir, paths.secrets_dir
    # A sibling namespace works for both XDG roots and shallow app roots.
    # Leading dot cannot collide with a valid profile identifier.
    workspace = paths.data_dir.parent / ".odin-desktop-workspaces" / paths.profile_id
    return {
        "context": {"directory": str(data / "context")},
        "sessions": {"persist_directory": str(data / "sessions")},
        "tools": {
            "hosts": {"localhost": {
                "address": "127.0.0.1", "ssh_user": "root", "os": "linux",
                "description": "Local Odin workspace",
            }},
            "default_host": "localhost",
            "local_working_dir": str(workspace),
            "ssh_key_path": str(secrets / "id_ed25519"),
            "ssh_known_hosts_path": str(secrets / "known_hosts"),
            "ssh_pool": {"socket_dir": str(cache / "ssh-sockets")},
            "audit_log_path": str(data / "audit.jsonl"),
            "trajectory_path": str(data / "trajectories"),
        },
        "logging": {"directory": str(data / "logs")},
        "usage": {"directory": str(data / "usage")},
        "openai_codex": {
            "enabled": True,
            "model": DEFAULT_MAIN_MODEL,
            "auxiliary": {"model": DEFAULT_AUXILIARY_MODEL},
            "credentials_path": str(secrets / "codex_auth.json"),
        },
        "llm_provider": {"model": DEFAULT_MAIN_MODEL},
        "search": {"chromadb_path": str(data / "search")},
        "turn_state": {"db_path": str(data / "turn_state" / "turns.sqlite3")},
        "attachments": {"temp_directory": str(cache / "attachments")},
        "computer": {"storage_dir": str(data / "computer")},
    }


def fresh_config(paths: ProfilePaths) -> Config:
    return Config.model_validate(fresh_config_document(paths))


def ensure_profile(paths: ProfilePaths, *, authority: OwnerAuthority | None = None) -> Config:
    """Create a config only when absent; existing profiles are not rewritten.

    Callers holding the runtime authority pass it here so durability uncertainty
    is exposed on that same authority. No global profile selection is required.
    """
    if paths.config_file.exists() or paths.config_file.is_symlink():
        return load_config(paths.config_file)
    authority = authority or OwnerAuthority(paths)
    paths.create_private()
    with authority._locked():
        if paths.config_file.exists() or paths.config_file.is_symlink():
            return load_config(paths.config_file)
        config = fresh_config(paths)
        # Workspace is independent of protected profile state. Existing modes
        # are accepted, as in Odin; command execution validates its own fence.
        Path(config.tools.local_working_dir).mkdir(parents=True, exist_ok=True, mode=0o700)
        durable = write_private_atomic(
            paths.config_file, yaml.safe_dump(fresh_config_document(paths), sort_keys=False)
        )
        authority.durability_degraded = authority.durability_degraded or not durable
    return config


def provision_fresh_profile(paths: ProfilePaths) -> OwnerAuthority:
    """Compatibility implementation for the selected-profile façade."""
    paths.create_private()
    if paths.config_file.exists() or paths.config_file.is_symlink():
        raise FileExistsError("profile configuration already exists")
    authority = OwnerAuthority(paths)
    # Hold the same cross-process lock across the absence check and creation.
    with authority._locked():
        if paths.config_file.exists() or paths.config_file.is_symlink():
            raise FileExistsError("profile configuration already exists")
        config = fresh_config(paths)
        Path(config.tools.local_working_dir).mkdir(parents=True, exist_ok=True, mode=0o700)
        durable = write_private_atomic(
            paths.config_file, yaml.safe_dump(fresh_config_document(paths), sort_keys=False)
        )
        authority.durability_degraded = authority.durability_degraded or not durable
    return authority
