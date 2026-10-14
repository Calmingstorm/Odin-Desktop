#!/usr/bin/env python3
"""Sign, notarize, staple and assess the signed Mac build's .dmg (python/macos_notary.py)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'python'))
from macos_notary import NotaryError, seal  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('dmg', type=Path)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--keychain', type=Path)
    parser.add_argument('--key', type=Path, required=True)
    parser.add_argument('--key-id', required=True)
    parser.add_argument('--issuer', required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        evidence = seal(args.dmg, args.identity, args.key, args.key_id, args.issuer,
                        keychain=args.keychain)
    except NotaryError as error:
        print(error, file=sys.stderr)
        return 1
    args.evidence.write_text(json.dumps(evidence, indent=2) + '\n')
    print(f"{args.dmg.name}: notarization {evidence['notarization']['status']} "
          f"({evidence['notarization']['id']}); {evidence['assessment']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
