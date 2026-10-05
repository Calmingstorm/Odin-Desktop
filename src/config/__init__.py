"""Configuration package for Odin.

Exports:
- ``OdinConfig`` — immutable environment logging policy
- ``Config`` / ``load_config`` — pydantic model for config.yml
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _load_env(env_file: str | Path | None = None) -> None:
    """Load one declared environment file, never an ambient request directory."""
    configured = env_file
    env_path = (
        Path(os.path.abspath(os.fspath(Path(configured).expanduser())))
        if configured
        else _profile_environment_path()
    )
    if env_path.exists():
        load_dotenv(env_path)


@dataclass(frozen=True)
class OdinConfig:
    """Immutable logging policy; no transport credentials or ambient grants."""

    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> OdinConfig:
        """Build config from environment variables."""
        _load_env(env_file)
        return cls(
            log_level=os.getenv("ODIN_LOG_LEVEL", "INFO"),
        )

    def validate(self) -> list[str]:
        """Return a list of validation errors (empty if valid)."""
        errors = []
        if self.log_level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            errors.append("ODIN_LOG_LEVEL must be a standard log level")
        return errors


def __getattr__(name: str):
    if name in ("Config", "load_config"):
        from .schema import Config, load_config
        globals()["Config"] = Config
        globals()["load_config"] = load_config
        return Config if name == "Config" else load_config
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["OdinConfig", "Config", "load_config"]


def _profile_environment_path() -> Path:
    from ..runtime_paths import runtime_profile_paths

    return runtime_profile_paths().environment_file
