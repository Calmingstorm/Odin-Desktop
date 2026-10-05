"""Explicit fresh-profile configuration provisioning, never existing-state import."""
from __future__ import annotations

import yaml

from ..config.model_defaults import DEFAULT_AUXILIARY_MODEL, DEFAULT_MAIN_MODEL
from ..config.schema import Config
from ..permissions.persistence import write_private_atomic
from ..runtime_paths import runtime_profile_paths
from .authority import OwnerAuthority
from .paths import ProfilePaths


def provision_fresh_profile(paths: ProfilePaths) -> OwnerAuthority:
    """Create identity then fresh model intent in a private profile config.

    Existing config is never rewritten. Post-commit durability uncertainty is
    exposed and blocks authority; the committed config is not rolled back.
    """
    if paths != runtime_profile_paths():
        raise ValueError("fresh provisioning must target the selected desktop profile")
    paths.create_private()
    if paths.config_file.exists() or paths.config_file.is_symlink():
        raise FileExistsError("profile configuration already exists")
    authority = OwnerAuthority(paths)
    with authority._locked():
        if paths.config_file.exists() or paths.config_file.is_symlink():
            raise FileExistsError("profile configuration already exists")
        config = Config.model_validate({
            "openai_codex": {"model": DEFAULT_MAIN_MODEL,
                             "auxiliary": {"model": DEFAULT_AUXILIARY_MODEL}},
            "llm_provider": {"model": DEFAULT_MAIN_MODEL},
        })
        durable = write_private_atomic(
            paths.config_file, yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False)
        )
        authority.durability_degraded = authority.durability_degraded or not durable
    return authority
