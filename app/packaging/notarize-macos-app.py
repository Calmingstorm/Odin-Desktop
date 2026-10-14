#!/usr/bin/env python3
"""Notarize and staple the signed Mac app, keeping Apple's verdict (python/macos_notary.py)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'python'))
from macos_notary import NotaryError, seal_app  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('app', type=Path)
    parser.add_argument('--key', type=Path, required=True)
    parser.add_argument('--key-id', required=True)
    parser.add_argument('--issuer', required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        evidence = seal_app(args.app, args.key, args.key_id, args.issuer)
    except NotaryError as error:
        print(error, file=sys.stderr)
        return 1
    args.evidence.write_text(json.dumps(evidence, indent=2) + '\n')
    print(f"{args.app.name}: notarization {evidence['notarization']['status']} "
          f"({evidence['notarization']['id']}), stapled")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
