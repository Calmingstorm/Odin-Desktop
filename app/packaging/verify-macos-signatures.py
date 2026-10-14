#!/usr/bin/env python3
"""Check every Mach-O in the signed Mac app's Resources (python/macos_sign.py verify_signed)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'python'))
from macos_sign import SigningError, verify_signed  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('app', type=Path)
    parser.add_argument('--team', required=True)
    args = parser.parse_args(argv)
    try:
        count = verify_signed(args.app / 'Contents' / 'Resources', args.team)
    except SigningError as error:
        print(error, file=sys.stderr)
        return 1
    print(f'{count} Mach-O files under Resources: team {args.team}, hardened runtime, timestamp, '
          'exactly their role entitlements (Resources only; codesign verifies the rest)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
