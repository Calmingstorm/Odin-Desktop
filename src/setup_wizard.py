"""Desktop first-run onboarding, explicitly deferred to Phase 2.

Credential removal will not reset its separate completion record. Secure
environment publication remains shared with config persistence.
"""

from pathlib import Path


def is_setup_needed(*args, **kwargs) -> bool:
    raise RuntimeError("Desktop onboarding is deferred to Phase 2")


def write_env_file(path: Path, content: str) -> None:
    """Write .env file with restricted permissions."""
    from .permissions.persistence import write_private_atomic

    write_private_atomic(path, content)
