#!/usr/bin/env python3
"""Check a kept signed Mac candidate (macos-release.yml's retained job).

The folder holds exactly the disk image, its receipt and the acceptance report; the image is the
receipt's; both notarizations are Apple's Accepted answers with their own submission IDs; and the
acceptance report is this image's, at the receipt's revision, with the full set of checks.

    check-signed-candidate.py FOLDER SOURCE_COMMIT
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

SUBMISSION = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
CHECKS = 16  # the installed-app acceptance's checks (tests/macos/test_packaged_app.py)


class CandidateError(RuntimeError):
    pass


def check(kept: Path, source: str) -> str:
    receipt = json.loads((kept / 'receipt.json').read_text())
    names = sorted(path.name for path in kept.iterdir())
    expected = sorted([receipt['disk_image'], 'receipt.json', 'acceptance.json'])
    if names != expected:
        raise CandidateError(f'the folder holds {names}, not {expected}')
    with open(kept / receipt['disk_image'], 'rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != receipt['sha256'] or receipt['revision'] != source:
        raise CandidateError('the disk image or the revision differs from the receipt')
    submissions = set()
    for record in ('app_notarization', 'disk_image_notarization'):
        answer = receipt[record]['notarization']
        if (answer.get('status') != 'Accepted' or answer.get('exit') != 0
                or not isinstance(answer.get('id'), str)
                or not SUBMISSION.fullmatch(answer['id'])):
            raise CandidateError(f'{record} is not an Accepted submission: {answer}')
        submissions.add(answer['id'])
    if len(submissions) != 2:
        raise CandidateError('the app and the disk image name the same submission')
    report = json.loads((kept / 'acceptance.json').read_text())
    if report.get('disk_image_sha256') != digest or report.get('revision') != receipt['revision']:
        raise CandidateError('the acceptance report is for another candidate')
    checks = report.get('checks')
    if not isinstance(checks, dict) or len(checks) < CHECKS:
        held = len(checks) if isinstance(checks, dict) else 0
        raise CandidateError(f'the acceptance report holds {held} checks, not {CHECKS}')
    return f"{receipt['disk_image']} {digest} at {receipt['revision']}"


def main(argv=None) -> int:
    folder, source = sys.argv[1:] if argv is None else argv
    try:
        print('kept:', check(Path(folder), source))
    except (CandidateError, OSError, ValueError, KeyError, TypeError) as error:
        print(f'::error::{type(error).__name__}: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
