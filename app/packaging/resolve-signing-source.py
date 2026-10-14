#!/usr/bin/env python3
"""The source the signed Mac build may sign: macos-release.yml's target job, which holds no secrets.

Accepted: a release tag vX.Y.Z on master's history whose app version is X.Y.Z (release), or one of
the port's candidate branches, by name or by exactly its head (candidate; until the port merges).
Prints "<commit> <mode>"; refuses anything else. Reads the remote refs the job fetched
(refs/remotes/origin/...), never the local checkout's branches.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

# The port's branch, and the scratch branch its signed probes run from; both go when it merges.
CANDIDATES = ('macos/port', 'macos/probe')
RELEASE = re.compile(r'v(\d+\.\d+\.\d+)')


class SourceRefusedError(RuntimeError):
    pass


def _git(*args: str, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True)


def resolve(ref: str, cwd=None) -> tuple[str, str]:
    release = RELEASE.fullmatch(ref)
    if release:
        tagged = _git('rev-parse', '--verify', '--quiet', f'refs/tags/{ref}^{{commit}}', cwd=cwd)
        if tagged.returncode != 0:
            raise SourceRefusedError(f'{ref} is not a tag')
        commit = tagged.stdout.strip()
        if _git('merge-base', '--is-ancestor', commit, 'refs/remotes/origin/master',
                cwd=cwd).returncode != 0:
            raise SourceRefusedError(f'{ref} is not on master')
        shown = _git('show', f'{commit}:app/package.json', cwd=cwd)
        version = json.loads(shown.stdout).get('version') if shown.returncode == 0 else None
        if version != release.group(1):
            raise SourceRefusedError(f'{ref} builds app version {version}')
        return commit, 'release'
    for branch in CANDIDATES:
        head = _git('rev-parse', '--verify', '--quiet', f'refs/remotes/origin/{branch}', cwd=cwd)
        if head.returncode == 0 and ref in (branch, head.stdout.strip()):
            return head.stdout.strip(), 'candidate'
    raise SourceRefusedError(
        f"{ref} is neither a release tag on master nor a candidate branch's head")


def main(argv=None) -> int:
    (ref,) = sys.argv[1:] if argv is None else argv
    try:
        commit, mode = resolve(ref)
    except SourceRefusedError as error:
        print(f'::error::{error}', file=sys.stderr)
        return 1
    print(commit, mode)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
