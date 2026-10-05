"""Explicit, CWD-independent startup inputs for configuration and setup state."""
from __future__ import annotations

import argparse
import os
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .environment import EnvironmentSource, warn_group_writable_directory_once
from .initialization import InitializationStore, InstallationBinding


def _absolute(path: str | Path) -> Path:
    """Make a path CWD-independent without dereferencing its final symlink."""
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def default_environment_path(config_path: Path) -> Path:
    """Private desktop profile credentials, never CWD or another installation."""
    del config_path
    from ..runtime_paths import runtime_profile_paths

    return runtime_profile_paths().environment_file


def default_initialization_state_path(config_path: Path) -> Path:
    """Keep state in a private child, not the shared application data directory."""
    del config_path
    from ..runtime_paths import runtime_profile_paths

    return runtime_profile_paths().data_dir / "initialization" / "state.json"


def _validate_initialization_ancestor(
    info: os.stat_result, *, path: Path, terminal: bool
) -> None:
    mode = stat.S_IMODE(info.st_mode)
    if terminal:
        if info.st_uid != os.geteuid() or mode & 0o077:
            raise RuntimeError("initialization directory has unsafe mode")
    else:
        warn_group_writable_directory_once(path, info)


def provision_initialization_parent(state_path: Path) -> None:
    """Create the terminal private state directory through no-follow descriptors."""
    from ..desktop.paths import private_directory
    private_directory(_absolute(state_path).parent)


def installation_id(config_path: Path) -> str:
    """Persisted profile install identity, never inferred from machine state."""
    from ..desktop.authority import OwnerAuthority
    from ..runtime_paths import runtime_profile_paths
    paths = runtime_profile_paths()
    if config_path != paths.config_file:
        raise ValueError("startup configuration must belong to the selected desktop profile")
    authority = OwnerAuthority(paths)
    if authority.durability_degraded:
        raise RuntimeError("profile identity durability unproven")
    return authority.installation_id


@dataclass(frozen=True, slots=True)
class StartupContext:
    config_path: Path
    environment_path: Path
    initialization_state_path: Path
    config_launch_path: Path

    def onboarding_store(self) -> InitializationStore:
        return InitializationStore(
            self.initialization_state_path,
            InstallationBinding(installation_id(self.config_path), self.config_path),
        )

    def environment_source(self) -> EnvironmentSource:
        return EnvironmentSource(self.environment_path)


def resolve_startup_context(
    config_path: str | Path,
    *,
    env_file: str | Path | None = None,
    initialization_state: str | Path | None = None,
) -> StartupContext:
    """Resolve supported inputs once, independently of later CWD changes."""
    # The canonical path binds persistence/setup identity. Keep the lexical
    # launch alias separately: re-exec replays it, so workspace protection must
    # protect both the alias and its target through load_config's existing path.
    # Unlike abspath(), absolute() retains '..': resolving a symlink before
    # its parent traversal can select a different file than lexical collapse.
    launch = Path(config_path).expanduser().absolute()
    config = launch.resolve()
    env = _absolute(env_file) if env_file is not None else default_environment_path(config)
    state = (_absolute(initialization_state) if initialization_state is not None
             else default_initialization_state_path(config))
    return StartupContext(config, env, state, launch)


def parse_startup_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="odin")
    parser.add_argument("config_positional", nargs="?", help="active configuration file")
    parser.add_argument(
        "-c", "--config", dest="config_override", help="active configuration file"
    )
    parser.add_argument("--env-file", default=os.environ.get("ODIN_ENV_FILE"))
    parser.add_argument(
        "--initialization-state", default=os.environ.get("ODIN_INITIALIZATION_STATE")
    )
    parser.add_argument(
        "--provision-fresh-initialization", action="store_true", help=argparse.SUPPRESS
    )
    args = parser.parse_args(argv)
    from ..runtime_paths import runtime_profile_paths
    args.config = (
        args.config_override or args.config_positional
        or str(runtime_profile_paths().config_file)
    )
    return args


def provision_fresh_from_cli(argv: Sequence[str] | None = None) -> int:
    """Package-only entrypoint creating a pending record as the service user."""
    args = parse_startup_arguments(argv)
    if not args.provision_fresh_initialization:
        raise SystemExit("--provision-fresh-initialization is required")
    context = resolve_startup_context(
        args.config, env_file=args.env_file, initialization_state=args.initialization_state
    )
    context.onboarding_store().provision_fresh()
    return 0


if __name__ == "__main__":
    raise SystemExit(provision_fresh_from_cli())
