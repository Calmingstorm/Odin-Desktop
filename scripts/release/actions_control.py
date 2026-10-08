#!/usr/bin/env python3
"""Fail-closed Actions verification/publication. No builds, tags or gate repair."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

import release_helper as helper

BASE = f'repos/{helper.REPOSITORY}'
WORKFLOW = '.github/workflows/release.yml'
ENVIRONMENT = 'odin-desktop-release'
JSON_LIMIT = 8 * 1024 * 1024
ZIP_LIMIT = 2 * 1024 * 1024 * 1024
require = helper.require


def parse_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result

    require(len(data) <= JSON_LIMIT, 'JSON response too large')
    return json.loads(data, object_pairs_hook=unique)


def execute(argv, destination=None, limit=JSON_LIMIT, timeout=120):
    """Bound wall time and output without buffering ZIPs; isolate gh config."""
    require(bool(os.environ.get('GH_TOKEN')), 'workflow-scoped GH_TOKEN required')
    with (
        tempfile.TemporaryDirectory() as home,
        tempfile.TemporaryFile() as out,
        tempfile.TemporaryFile() as err,
    ):
        env = {
            'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
            'HOME': home,
            'GH_CONFIG_DIR': home,
            'GH_TOKEN': os.environ['GH_TOKEN'],
            'GH_HOST': 'github.com',
            'GH_PROMPT_DISABLED': '1',
        }
        output = destination if destination is not None else out
        start = time.monotonic()
        process = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=output, stderr=err, env=env
        )
        try:
            while process.poll() is None:
                require(time.monotonic() - start < timeout, 'gh timeout')
                require(os.fstat(output.fileno()).st_size <= limit, 'gh response too large')
                require(os.fstat(err.fileno()).st_size <= 65536, 'gh error too large')
                time.sleep(0.05)
            require(process.returncode == 0, 'gh failed; no automatic retry')
            require(os.fstat(output.fileno()).st_size <= limit, 'gh response too large')
            require(os.fstat(err.fileno()).st_size <= 65536, 'gh error too large')
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
        if destination is None:
            out.seek(0)
            return out.read(limit + 1)


def api(path):
    return parse_json(
        execute(
            [
                'gh',
                'api',
                '--method',
                'GET',
                '-H',
                'Accept: application/vnd.github+json',
                '-H',
                'X-GitHub-Api-Version: 2022-11-28',
                path,
            ]
        )
    )


def pages(path, key=None):
    result = []
    for page in range(1, 101):
        response = api(f'{path}?per_page=100&page={page}')
        items = response[key] if key else response
        require(isinstance(items, list) and len(items) <= 100, 'invalid API page')
        result.extend(items)
        if len(items) < 100:
            return result
    raise ValueError('API pagination limit exceeded')


def dispatch_inputs():
    names = (
        'CANDIDATE_RUN_ID',
        'CANDIDATE_ARTIFACT_ID',
        'CANDIDATE_ARTIFACT_DIGEST',
        'EXPECTED_SOURCE_SHA',
        'EXPECTED_WORKFLOW_SHA',
        'EXPECTED_RECEIPT_SHA',
        'EXPECTED_VERSION',
        'APPROVAL_JSON',
        'GITHUB_ACTOR',
        'GITHUB_WORKFLOW_SHA',
        'GITHUB_SHA',
        'GITHUB_REF',
        'GITHUB_REPOSITORY',
        'GITHUB_EVENT_NAME',
    )
    v = {name: os.environ.get(name, '') for name in names}
    require(all(v.values()), 'missing dispatch input')
    require(v['GITHUB_REPOSITORY'] == helper.REPOSITORY, 'wrong dispatch repository')
    require(v['GITHUB_EVENT_NAME'] == 'workflow_dispatch', 'manual dispatch required')
    require(v['GITHUB_REF'] == 'refs/heads/master', 'dispatch must use master')
    require(v['GITHUB_ACTOR'] == 'Calmingstorm', 'Aaron dispatch required')
    for key in ('CANDIDATE_RUN_ID', 'CANDIDATE_ARTIFACT_ID'):
        require(helper.RUN.fullmatch(v[key]), 'invalid ' + key)
    for key in (
        'EXPECTED_SOURCE_SHA',
        'EXPECTED_WORKFLOW_SHA',
        'GITHUB_WORKFLOW_SHA',
        'GITHUB_SHA',
    ):
        require(helper.SHA.fullmatch(v[key]), 'invalid ' + key)
    require(
        v['GITHUB_WORKFLOW_SHA'] == v['EXPECTED_WORKFLOW_SHA'] == v['GITHUB_SHA'],
        'workflow SHA mismatch',
    )
    require(helper.VERSION.fullmatch(v['EXPECTED_VERSION']), 'invalid expected version')
    require(helper.HASH.fullmatch(v['EXPECTED_RECEIPT_SHA']), 'invalid receipt SHA')
    require(
        v['CANDIDATE_ARTIFACT_DIGEST'].startswith('sha256:')
        and helper.HASH.fullmatch(v['CANDIDATE_ARTIFACT_DIGEST'][7:]),
        'invalid artifact digest',
    )
    v['approval'] = parse_json(v['APPROVAL_JSON'])
    require(isinstance(v['approval'], dict), 'invalid approval object')
    return v


def audit_environment():
    user = api('users/Calmingstorm')
    require(
        user.get('login') == 'Calmingstorm'
        and user.get('type') == 'User'
        and type(user.get('id')) is int
        and user['id'] > 0,
        'invalid Aaron identity',
    )
    env = api(f'{BASE}/environments/{ENVIRONMENT}')
    require(env.get('name') == ENVIRONMENT, 'missing release environment')
    require(env.get('can_admins_bypass') is False, 'admin bypass protection absent')
    reviewers = [
        r for r in env.get('protection_rules', []) if r.get('type') == 'required_reviewers'
    ]
    require(
        len(reviewers) == 1 and reviewers[0].get('prevent_self_review') is False,
        'invalid review policy',
    )
    entries = reviewers[0].get('reviewers', [])
    require(
        len(entries) == 1
        and entries[0].get('type') == 'User'
        and entries[0].get('reviewer', {}).get('login') == 'Calmingstorm'
        and entries[0]['reviewer'].get('id') == user['id'],
        'Aaron reviewer absent',
    )
    require(
        env.get('deployment_branch_policy')
        == {'protected_branches': False, 'custom_branch_policies': True},
        'unrestricted environment branches',
    )
    policies = pages(
        f'{BASE}/environments/{ENVIRONMENT}/deployment-branch-policies', 'branch_policies'
    )
    require(
        len(policies) == 1
        and policies[0].get('name') == 'master'
        and policies[0].get('type') == 'branch',
        'environment must allow only master branch',
    )
    return {
        'environment': ENVIRONMENT,
        'reviewer_id': user['id'],
        'prevent_admin_bypass': True,
        'prevent_self_review': False,
        'branch': 'master',
    }


def candidate_metadata(v):
    run_id = v['CANDIDATE_RUN_ID']
    run = api(f'{BASE}/actions/runs/{run_id}')
    require(str(run.get('id')) == run_id and run.get('run_attempt') == 1, 'invalid run or retry')
    require(
        run.get('status') == 'completed' and run.get('conclusion') == 'success',
        'candidate not successful',
    )
    require(
        run.get('event') in ('workflow_dispatch', 'push') and run.get('pull_requests') == [],
        'invalid event or PR',
    )
    require(
        run.get('repository', {}).get('full_name') == helper.REPOSITORY
        and run.get('head_repository', {}).get('full_name') == helper.REPOSITORY,
        'foreign repository',
    )
    require(run.get('head_sha') == v['EXPECTED_SOURCE_SHA'], 'source mismatch')
    require(
        run.get('path') == WORKFLOW and type(run.get('workflow_id')) is int, 'invalid workflow path'
    )
    workflow = api(f'{BASE}/actions/workflows/{run["workflow_id"]}')
    require(
        workflow.get('id') == run['workflow_id'] and workflow.get('path') == WORKFLOW,
        'workflow identity mismatch',
    )
    # Dispatch and tag push workflow code is at head_sha; no native workflow_sha exists on a run.
    require(run['head_sha'] == v['EXPECTED_WORKFLOW_SHA'], 'workflow revision mismatch')
    jobs = pages(f'{BASE}/actions/runs/{run_id}/attempts/1/jobs', 'jobs')
    for name, conclusion in {
        'Build candidate': 'success',
        'Verify approved candidate': 'skipped',
        'Publish identical approved candidate': 'skipped',
    }.items():
        matches = [job for job in jobs if job.get('name') == name]
        require(
            len(matches) == 1
            and matches[0].get('status') == 'completed'
            and matches[0].get('conclusion') == conclusion,
            'invalid candidate job: ' + name,
        )
    artifact = api(f'{BASE}/actions/artifacts/{v["CANDIDATE_ARTIFACT_ID"]}')
    require(
        str(artifact.get('id')) == v['CANDIDATE_ARTIFACT_ID']
        and artifact.get('name') == 'release-candidate-' + run_id
        and artifact.get('expired') is False,
        'invalid or expired artifact',
    )
    require(
        artifact.get('digest') == v['CANDIDATE_ARTIFACT_DIGEST'], 'API artifact digest mismatch'
    )
    p = artifact.get('workflow_run', {})
    require(
        str(p.get('id')) == run_id
        and p.get('head_sha') == run['head_sha']
        and p.get('repository_id') == run['repository'].get('id')
        and p.get('head_repository_id') == run['head_repository'].get('id')
        and type(p.get('repository_id')) is int,
        'artifact run provenance mismatch',
    )
    require(
        type(artifact.get('size_in_bytes')) is int and 0 < artifact['size_in_bytes'] <= ZIP_LIMIT,
        'artifact size invalid',
    )
    return run, artifact


def extract_candidate(archive, directory):
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        names = [e.filename for e in entries]
        require(len(entries) == 4 and len(set(names)) == 4, 'ZIP duplicate or extra entries')
        for e in entries:
            require(
                e.filename not in ('', '.', '..')
                and '/' not in e.filename
                and '\\' not in e.filename
                and '\x00' not in e.filename,
                'unsafe ZIP path',
            )
            require(
                not e.is_dir()
                and stat.S_IFMT(e.external_attr >> 16) in (0, stat.S_IFREG)
                and not e.flag_bits & 1,
                'ZIP link, special or encrypted entry',
            )
            require(0 < e.file_size <= ZIP_LIMIT, 'ZIP entry size invalid')
        require(sum(e.file_size for e in entries) <= ZIP_LIMIT, 'ZIP expanded size too large')
        require(
            'candidate-receipt.json' in names and 'release-notes.md' in names,
            'receipt or notes missing',
        )
        require(
            zipped.getinfo('candidate-receipt.json').file_size <= JSON_LIMIT, 'receipt too large'
        )
        receipt = helper.validate_receipt(parse_json(zipped.read('candidate-receipt.json')))
        require(
            set(names)
            == {
                'candidate-receipt.json',
                'release-notes.md',
                *(a['name'] for a in receipt['artifacts']),
            },
            'ZIP names do not match receipt',
        )
        for e in entries:
            with zipped.open(e) as source, (directory / e.filename).open('xb') as target:
                total = 0
                while chunk := source.read(1024 * 1024):
                    total += len(chunk)
                    require(total <= e.file_size, 'ZIP size overflow')
                    target.write(chunk)
                require(total == e.file_size, 'ZIP size mismatch')
    return receipt


def resolve_tag(tag):
    obj = api(f'{BASE}/git/ref/tags/{tag}')['object']
    seen = set()
    for _ in range(16):
        sha = obj.get('sha', '')
        require(
            isinstance(sha, str) and helper.SHA.fullmatch(sha) and sha not in seen,
            'invalid or cyclic tag',
        )
        seen.add(sha)
        if obj.get('type') == 'commit':
            return sha
        require(obj.get('type') == 'tag', 'tag not commit')
        annotated = api(f'{BASE}/git/tags/{sha}')
        require(annotated.get('sha') == sha, 'annotated tag identity mismatch')
        obj = annotated['object']
    raise ValueError('tag recursion limit')


def no_existing_release(tag):
    require(
        not any(r.get('tag_name') == tag for r in pages(f'{BASE}/releases')),
        'release already exists',
    )


def verify_published(directory, receipt, tag):
    release = api(f'{BASE}/releases/tags/{tag}')
    require(
        release.get('tag_name') == tag
        and release.get('draft') is False
        and release.get('prerelease') is False
        and type(release.get('id')) is int,
        'published identity mismatch',
    )
    require(resolve_tag(tag) == receipt['source_commit'], 'published tag source changed')
    expected = {a['name']: (a['bytes'], 'sha256:' + a['sha256']) for a in receipt['artifacts']}
    path = directory / 'candidate-receipt.json'
    expected[path.name] = (path.stat().st_size, 'sha256:' + helper.digest(path))
    assets = pages(f'{BASE}/releases/{release["id"]}/assets')
    require(
        len(assets) == 3 and {a.get('name') for a in assets} == set(expected),
        'published assets mismatch',
    )
    for asset in assets:
        require(
            (asset.get('size'), asset.get('digest')) == expected[asset['name']]
            and asset.get('state') == 'uploaded',
            'published asset digest/size mismatch',
        )


def write_summary(directory, receipt, v, evidence):
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    require(bool(summary), 'GITHUB_STEP_SUMMARY required')
    lines = [
        '## Verified candidate (not publication authorization)',
        f'Artifact ID: `{v["CANDIDATE_ARTIFACT_ID"]}`',
        f'Digest: `{v["CANDIDATE_ARTIFACT_DIGEST"]}`',
        f'Receipt SHA-256: `{helper.digest(directory / "candidate-receipt.json")}`',
        f'Environment audit: `{json.dumps(evidence, sort_keys=True)}`',
        f'P4.5: {v["approval"]["p45_evidence"]}',
        f'P4.6: {v["approval"]["p46_evidence"]}',
        'Exact downloaded receipt (includes source/workflow/run/file hashes):',
        '```json',
        (directory / 'candidate-receipt.json').read_text(),
        '```',
        'URL validation does not prove qualification or licensing closure.',
    ]
    with Path(summary).open('a', encoding='utf-8') as stream:
        stream.write('\n'.join(lines) + '\n')


def control(action, directory):
    require(action in ('verify', 'publish'), 'invalid action')
    v = dispatch_inputs()
    directory = Path(directory).absolute()
    require(not directory.exists() and not directory.is_symlink(), 'directory must be fresh')
    evidence = audit_environment()
    run, artifact = candidate_metadata(v)
    directory.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryFile() as archive:
        execute(
            [
                'gh',
                'api',
                '--method',
                'GET',
                '-H',
                'Accept: application/vnd.github+json',
                '-H',
                'X-GitHub-Api-Version: 2022-11-28',
                f'{BASE}/actions/artifacts/{artifact["id"]}/zip',
            ],
            destination=archive,
            limit=ZIP_LIMIT,
            timeout=300,
        )
        archive.seek(0)
        require(
            'sha256:' + hashlib.file_digest(archive, 'sha256').hexdigest()
            == v['CANDIDATE_ARTIFACT_DIGEST'],
            'downloaded ZIP digest mismatch',
        )
        archive.seek(0)
        receipt = extract_candidate(archive, directory)
    require(
        helper.digest(directory / 'candidate-receipt.json') == v['EXPECTED_RECEIPT_SHA'],
        'receipt hash mismatch',
    )
    for key, expected in (
        ('run_id', str(run['id'])),
        ('source_commit', run['head_sha']),
        ('workflow_sha', v['EXPECTED_WORKFLOW_SHA']),
        ('version', v['EXPECTED_VERSION']),
    ):
        require(receipt[key] == expected, 'receipt/API mismatch: ' + key)
    helper.validate_files(directory, receipt)
    approval = v['approval']
    helper.validate_approval(receipt, approval, v['EXPECTED_RECEIPT_SHA'], v['GITHUB_ACTOR'])
    require(
        approval.get('artifact_id') == v['CANDIDATE_ARTIFACT_ID']
        and approval.get('artifact_digest') == v['CANDIDATE_ARTIFACT_DIGEST'],
        'artifact approval mismatch',
    )
    tag = 'v' + receipt['version']
    source = resolve_tag(tag)
    require(source == receipt['source_commit'], 'tag source mismatch')
    if run['event'] == 'push':
        require(run.get('head_branch') == tag, 'push candidate must be version tag')
    no_existing_release(tag)
    if action == 'verify':
        write_summary(directory, receipt, v, evidence)
    else:
        audit_environment()
        with tempfile.TemporaryDirectory() as temporary:
            approval_path = Path(temporary) / 'approval.json'
            approval_path.write_text(json.dumps(approval), encoding='utf-8')
            argv = helper.publication_plan(directory, approval_path, v['GITHUB_ACTOR'], tag, source)
            execute(argv, timeout=300)
        verify_published(directory, receipt, tag)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('verify', 'publish'))
    parser.add_argument('--directory', required=True)
    args = parser.parse_args()
    try:
        control(args.action, args.directory)
    except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile, RuntimeError):
        # Never echo untrusted API/error bodies or credentials.
        parser.exit(
            1, 'release control failed closed; reconcile any partial publication manually\n'
        )
    print(
        'Candidate verified.'
        if args.action == 'verify'
        else 'Identical candidate published and assets verified.'
    )


if __name__ == '__main__':
    main()
