#!/usr/bin/env python3
"""Actions candidate entry. No upload, publication, version write or credentials."""

import json
import os
import subprocess
from pathlib import Path

from release_helper import REPOSITORY, RUN, SHA, digest, load_json, require, versions

ROOT = Path(__file__).resolve().parents[2]


def candidate_arguments(env, root=ROOT):
    require(env.get('GITHUB_REPOSITORY') == REPOSITORY, 'fixed repository required')
    require(env.get('RELEASE_ATTEMPT') == '1', 'candidate reruns require a new run ID')
    require(
        SHA.fullmatch(env.get('RELEASE_SOURCE', ''))
        and SHA.fullmatch(env.get('RELEASE_WORKFLOW_SHA', '')),
        'invalid provenance',
    )
    require(RUN.fullmatch(env.get('RELEASE_RUN_ID', '')), 'invalid run ID')
    version = versions(
        load_json(root / 'app/package.json'), load_json(root / 'app/package-lock.json')
    )
    event, ref, mode = (
        env.get(key, '') for key in ('RELEASE_EVENT', 'RELEASE_REF', 'RELEASE_MODE')
    )
    if event == 'push':
        require(ref == 'refs/tags/v' + version, 'tag must equal current product version')
        require(env.get('RELEASE_ACTOR') == 'Calmingstorm', 'Aaron-authorized tag required')
        tag = 'v' + version
    else:
        require(
            event == 'workflow_dispatch' and mode in ('dry-run', 'retain-candidate'),
            'not a candidate request',
        )
        require(ref == 'refs/heads/main', 'manual candidates require reviewed main')
        require(
            env.get('RELEASE_VERSION') == version, 'dispatch version must equal current version'
        )
        require(
            mode == 'dry-run' or env.get('RELEASE_ACTOR') == 'Calmingstorm',
            'Aaron-authorized retention required',
        )
        tag = None
    args = [
        'node',
        'scripts/release/rehearse.mjs',
        '--build=true',
        '--output=' + str(root / 'release-output'),
        '--source=' + env['RELEASE_SOURCE'],
        '--workflow-sha=' + env['RELEASE_WORKFLOW_SHA'],
        '--run-id=' + env['RELEASE_RUN_ID'],
    ]
    if tag:
        args.append('--tag=' + tag)
    return args


def main():
    args = candidate_arguments(os.environ)
    subprocess.run(args, cwd=ROOT, check=True)
    subprocess.run(['node', 'scripts/release/gates.mjs'], cwd=ROOT, check=True)
    receipt = load_json(ROOT / 'release-output/candidate-receipt.json')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as out:
            out.write(
                '## Nonpublishing candidate\n\n```json\n'
                + json.dumps(receipt, indent=2)
                + '\n```\n'
            )
            out.write(
                'Receipt SHA256: `' + digest(ROOT / 'release-output/candidate-receipt.json') + '`\n'
            )
            out.write('Dry-run has no upload step; retention never creates a tag or Release.\n')


if __name__ == '__main__':
    main()
