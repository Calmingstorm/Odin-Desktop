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
HOMEBREW = ['/opt/homebrew/bin', '/opt/homebrew/sbin']


def _passed(value) -> bool:
    return value is True


def _pids(value) -> bool:
    return (isinstance(value, list) and bool(value)
            and all(type(pid) is int and pid > 0 for pid in value))


def _guardian(value) -> bool:
    return isinstance(value, dict) and set(value) == {'guardian', 'engine'} and all(
        _pids(pids) for pids in value.values())


def _path(value) -> bool:
    return (isinstance(value, list) and value[:2] == HOMEBREW and len(value) == len(set(value))
            and all(isinstance(folder, str) and folder.startswith('/') for folder in value))


def _stopped(value) -> bool:
    return (isinstance(value, dict) and value.get('state') == 'settled'
            and value.get('resource_release') == 'best_effort')


def _browser(value) -> bool:
    return isinstance(value, dict) and set(value) == {'browser'} and _pids(value['browser'])


def _unchanged(value) -> bool:
    return (value == {'changed': {}, 'changed_count': 0, 'added': [], 'removed': []}
            and type(value['changed_count']) is int)


def _digest(value) -> bool:
    return isinstance(value, str) and bool(HEX64.fullmatch(value))


def _exited(value) -> bool:
    return type(value) is int and value == 0


# The installed-app acceptance's checks (tests/macos/test_packaged_app.py), each with what a passed
# one records there: True; the guardian's and the engine's processes; the PATH, Homebrew's folders
# first; the stopped job's settled, best-effort settlement; the browser's processes; the app's exit
# status 0; no change in the app; the manifest's digest. The report is written even when the
# acceptance fails, holding the checks passed so far.
CHECKS = {
    'engine under the guardian': _guardian,
    'a provider and its key in the login keychain': _passed,
    "a command, with the Mac's PATH": _path,
    'a failing command': _passed,
    'patches and a raw read': _passed,
    'a background job stopped from Work': _stopped,
    'search by meaning, offline, with the bundled model': _passed,
    'the PDF reader installed on first use, into the profile': _passed,
    'the bundled browser read a page': _browser,
    "a skill's dependency installed into the profile": _passed,
    'an MCP server child, stopped with its tree': _passed,
    'the app exited': _exited,
    'the guardian, the engine and the browser are gone': _passed,
    'clean Exit records (app, engine, lease)': _passed,
    'what the session changed in the app': _unchanged,
    'the start check passed, and nothing wrote into the app': _digest,
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
