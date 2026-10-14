#!/usr/bin/env python3
"""Check a kept signed Mac candidate (macos-release.yml's retained job).

The folder holds exactly the disk image, its receipt and the acceptance report; the image is the
receipt's; both notarizations are Apple's Accepted answers, from a command that exited 0, with their
own submission IDs; and the acceptance report is this image's, at the receipt's revision, with
exactly the acceptance's checks, each passed.

    check-signed-candidate.py FOLDER SOURCE_COMMIT
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

SUBMISSION = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
HEX64 = re.compile(r'[0-9a-f]{64}')


def _evidence(value) -> bool:
    return isinstance(value, (dict, list)) and bool(value)


# The installed-app acceptance's checks (tests/macos/test_packaged_app.py), each with what a passed
# one records: True, its evidence, the app's exit status 0, no change in the app, or the manifest's
# digest. The report is written even when the acceptance fails, holding the checks passed so far.
CHECKS = {
    'engine under the guardian': _evidence,
    'a provider and its key in the login keychain': lambda value: value is True,
    "a command, with the Mac's PATH": _evidence,
    'a failing command': lambda value: value is True,
    'patches and a raw read': lambda value: value is True,
    'a background job stopped from Work': _evidence,
    'search by meaning, offline, with the bundled model': lambda value: value is True,
    'the PDF reader installed on first use, into the profile': lambda value: value is True,
    'the bundled browser read a page': _evidence,
    "a skill's dependency installed into the profile": lambda value: value is True,
    'an MCP server child, stopped with its tree': lambda value: value is True,
    'the app exited': lambda value: type(value) is int and value == 0,
    'the guardian, the engine and the browser are gone': lambda value: value is True,
    'clean Exit records (app, engine, lease)': lambda value: value is True,
    'what the session changed in the app':
        lambda value: isinstance(value, dict) and bool(value) and not any(value.values()),
    'the start check passed, and nothing wrote into the app':
        lambda value: isinstance(value, str) and bool(HEX64.fullmatch(value)),
}


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
        if (answer.get('status') != 'Accepted' or type(answer.get('exit')) is not int
                or answer['exit'] != 0
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
    if not isinstance(checks, dict) or set(checks) != set(CHECKS):
        held = sorted(checks) if isinstance(checks, dict) else checks
        raise CandidateError(f'the acceptance report holds {held}, not the {len(CHECKS)} checks')
    failed = sorted(name for name, passed in CHECKS.items() if not passed(checks[name]))
    if failed:
        raise CandidateError(f'the acceptance report does not show these checks passed: {failed}')
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
