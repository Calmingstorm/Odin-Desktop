"""Explicit app-supervised core arguments and authenticated local diagnostics."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .desktop import local_client
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


def legacy_server_arguments(arguments) -> bool:
    """Reject obsolete daemon/config input without inspecting a live profile."""
    for argument in arguments:
        if argument.startswith(("--config", "-c")) or argument.endswith((".yaml", ".yml")):
            return True
        try:
            if Path(argument).is_file():
                return True
        except OSError:
            pass
    return False


def main(argv=None) -> int:
    """Run the optional authenticated local client, never start or detach a core."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    # Only the leading positional is a legacy config candidate. Socket/token
    # files and explicit --prompt text are not daemon arguments.
    option_values = {"--socket", "--token-file", "--profile", "--prompt", "--conversation",
                     "--method", "--timeout"}
    flags, skip = [], False
    for argument in arguments:
        if skip:
            skip = False
            continue
        flags.append(argument)
        skip = argument in option_values
    if (any(arg.startswith(("--config", "-c")) for arg in flags)
            or (arguments and not arguments[0].startswith("-")
                and legacy_server_arguments(arguments[:1]))):
        print("The server command is now odin-server; desktop CLI never starts a daemon",
              file=sys.stderr)
        return 2
    if not arguments:
        try:
            prompt = "" if sys.stdin.isatty() else sys.stdin.read().strip()
        except OSError:
            prompt = ""
        if not prompt:
            print("Send a prompt: odin --socket PATH --token-file PATH --profile ID 'prompt'")
            return 1
        arguments = [prompt]
        return local_client.main(arguments)
    return local_client.main() if argv is None else local_client.main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
