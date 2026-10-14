#!/usr/bin/env python3
"""Sign the Mac app's Resources before finalize-manifest seals them (python/macos_sign.py)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'python'))
from macos_sign import SigningError, sign  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('resources', type=Path)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--keychain', type=Path)
    args = parser.parse_args(argv)
    try:
        count = sign(args.resources, args.identity, args.keychain)
    except SigningError as error:
        print(error, file=sys.stderr)
        return 1
    print(f'signed and verified {count} Mach-O files under Resources')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
