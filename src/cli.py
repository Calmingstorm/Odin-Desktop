"""Explicit app-supervised core arguments and authenticated local diagnostics."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .desktop.paths import ProfilePaths


@dataclass(frozen=True, slots=True)
class CoreOptions:
    socket: Path
    token_file: Path
    paths: ProfilePaths


def parse_core_args(argv: Sequence[str] | None = None) -> CoreOptions:
    parser = argparse.ArgumentParser(description="App-supervised Odin Desktop core")
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        paths = ProfilePaths.from_app(
            args.profile, token_file=args.token_file, data_dir=args.data_dir
        )
        if (not args.socket.is_absolute() or ".." in args.socket.parts
                or any(ord(c) < 32 for c in str(args.socket))):
            raise ValueError("socket must be an absolute local path")
    except ValueError as exc:
        parser.error(str(exc))
    return CoreOptions(args.socket, args.token_file, paths)


def main() -> int:
    """Run the local diagnostic client, never start or detach a core."""
    from .desktop.local_client import main as client_main

    return client_main()


if __name__ == "__main__":
    raise SystemExit(main())
