"""Fresh, independent Desktop state, never an import of a server installation."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from ..config.model_defaults import DEFAULT_AUXILIARY_MODEL, DEFAULT_MAIN_MODEL
from ..config.schema import Config, load_config
from ..permissions.persistence import write_private_atomic
from .authority import OwnerAuthority
from .paths import ProfilePaths
from .ssh_sockets import normalize_config_sockets, socket_directory


def system_timezone() -> str:
    """Use a valid system IANA zone for new Desktop profiles only."""
    candidates = [os.environ.get("TZ", "").removeprefix(":")]
    try:
        resolved = str(Path("/etc/localtime").resolve(strict=True))
        if "/zoneinfo/" in resolved:
            candidates.append(resolved.split("/zoneinfo/", 1)[1])
    except OSError:
        pass
    try:
        candidates.append(Path("/etc/timezone").read_text(encoding="utf-8").strip())
    except (OSError, UnicodeError):
        pass
    for candidate in candidates:
        if not candidate or candidate.startswith("/") or candidate.startswith(("posix/", "right/")):
            continue
        try:
            ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            continue
        return candidate
    return "UTC"


def fresh_config_document(paths: ProfilePaths) -> dict:
    """Bind every path default to the explicit profile, not the process HOME.

    These defaults also merge into existing profiles, so timezone keeps the
    schema's UTC default. Only file creation selects the system timezone.
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
            "ssh_pool": {"socket_dir": socket_directory(paths)},
            "audit_log_path": str(data / "audit.jsonl"),
            "trajectory_path": str(data / "trajectories"),
            "skill_allowed_urls": ["http://localhost:8188"],
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
        "browser": {
            "enabled": True,
            "allow_private_targets": ["http://127.0.0.1:3000", "http://localhost:3000"],
        },
    }


def fresh_config(paths: ProfilePaths) -> Config:
    return Config.model_validate(fresh_config_document(paths))


def _ensure_ssh_key(paths: ProfilePaths, authority: OwnerAuthority, config: Config) -> None:
    """Provision only the profile-owned key, under the shared authority lock.

    Generate in a private temporary directory, then publish with a no-replace
    link. An existing key (including a symlink) is never modified, even if a
    different writer creates it during generation. Hosts derives the public key
    from this private key, so no independently published .pub file is needed.
    """
    key = paths.secrets_dir / "id_ed25519"
    if config.tools.ssh_key_path != str(key) or key.exists() or key.is_symlink():
        return
    with tempfile.TemporaryDirectory(prefix=".ssh-key-", dir=paths.secrets_dir) as temporary:
        candidate = Path(temporary) / "id_ed25519"
        try:
            subprocess.run(
                ["ssh-keygen", "-t", "ed25519", "-f", str(candidate), "-N", "", "-q",
                 "-C", f"odin-desktop:{paths.profile_id}"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError("Could not provision the profile SSH key") from None
        with candidate.open("rb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            os.fsync(stream.fileno())
        try:
            os.link(candidate, key)
        except FileExistsError:
            return
        directory = os.open(paths.secrets_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            try:
                os.fsync(directory)
            except OSError:
                authority.durability_degraded = True
        finally:
            os.close(directory)


def ensure_profile(paths: ProfilePaths, *, authority: OwnerAuthority | None = None) -> Config:
    """Create absent config/key state; existing config and keys are not rewritten.

    Callers holding the runtime authority pass it here so durability uncertainty
    is exposed on that same authority. No global profile selection is required.
    """
    authority = authority or OwnerAuthority(paths)
    paths.create_private()
    with authority._locked():
        if not (paths.config_file.exists() or paths.config_file.is_symlink()):
            document = fresh_config_document(paths)
            document["timezone"] = system_timezone()
            config = Config.model_validate(document)
            _ensure_ssh_key(paths, authority, config)
            # Workspace is independent of protected profile state. Existing modes
            # are accepted, as in Odin; command execution validates its own fence.
            Path(config.tools.local_working_dir).mkdir(parents=True, exist_ok=True, mode=0o700)
            durable = write_private_atomic(
                paths.config_file, yaml.safe_dump(document, sort_keys=False)
            )
            authority.durability_degraded = authority.durability_degraded or not durable
            return config
    # Selected-profile migrations construct an authority of their own. Never
    # load config while holding its non-reentrant cross-process identity lock.
    config = normalize_config_sockets(load_config(paths.config_file), paths)
    with authority._locked():
        _ensure_ssh_key(paths, authority, config)
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
        document = fresh_config_document(paths)
        document["timezone"] = system_timezone()
        config = Config.model_validate(document)
        _ensure_ssh_key(paths, authority, config)
        Path(config.tools.local_working_dir).mkdir(parents=True, exist_ok=True, mode=0o700)
        durable = write_private_atomic(
            paths.config_file, yaml.safe_dump(document, sort_keys=False)
        )
        authority.durability_degraded = authority.durability_degraded or not durable
    return authority
