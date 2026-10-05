"""Explicit fresh-profile configuration provisioning, never existing-state import."""
from __future__ import annotations

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
    from .provisioning import provision_fresh_profile as provision

    return provision(paths)
