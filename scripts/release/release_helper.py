#!/usr/bin/env python3
"""Offline release validation. No builds, credential access or publication."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

REPOSITORY = 'Calmingstorm/Odin-Desktop'
VERSION = re.compile(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z')
SHA = re.compile(r'[0-9a-f]{40}\Z')
HASH = re.compile(r'[0-9a-f]{64}\Z')
RUN = re.compile(r'[1-9][0-9]*\Z')
INPUTS = (
    'uv.lock',
    'app/package-lock.json',
    'app/packaging/app-inputs.json',
    'app/packaging/runtime-lock.json',
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=unique)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def release_notes(changelog, version):
    require(VERSION.fullmatch(version), 'invalid stable product version')
    sections = []
    heading = re.compile(r'^## \[([^\]]+)\](?: - \d{4}-\d{2}-\d{2})?\s*$')
    lines = changelog.splitlines()
    for index, line in enumerate(lines):
        match = heading.fullmatch(line)
        if match and match[1] == version:
            end = next(
                (i for i in range(index + 1, len(lines)) if lines[i].startswith('## ')), len(lines)
            )
            sections.append('\n'.join(lines[index + 1 : end]).strip())
    require(len(sections) == 1, 'missing or duplicate exact CHANGELOG version section')
    notes = sections[0]
    substantive = re.sub(r'<!--.*?-->', '', notes, flags=re.S).strip()
    require(bool(substantive) and any(c.isalnum() for c in substantive), 'empty release notes')
    return notes + '\n'


def versions(package, lock, tag=None):
    version = package.get('version')
    require(isinstance(version, str) and VERSION.fullmatch(version), 'invalid product version')
    require(
        lock.get('version') == version
        and lock.get('packages', {}).get('', {}).get('version') == version,
        'npm root/lock product version mismatch',
    )
    if tag is not None:
        require(tag == 'v' + version, 'tag/product version mismatch')
    return version


def validate_receipt(receipt):
    require(
        receipt.get('schema') == 1 and receipt.get('repository') == REPOSITORY,
        'invalid receipt identity',
    )
    require(
        isinstance(receipt.get('version'), str) and VERSION.fullmatch(receipt['version']),
        'invalid receipt version',
    )
    for key, pattern in (
        ('source_commit', SHA),
        ('workflow_sha', SHA),
        ('run_id', RUN),
        ('resource_manifest_sha256', HASH),
        ('notes_sha256', HASH),
    ):
        require(
            isinstance(receipt.get(key), str) and pattern.fullmatch(receipt[key]), 'invalid ' + key
        )
    require(receipt.get('builder_command') == 'npm run package:candidate', 'unexpected builder')
    require(receipt.get('scan') == 'p41-credential-signatures-passed', 'missing credential scan')
    require(set(receipt.get('input_hashes', {})) == set(INPUTS), 'missing pinned input hashes')
    require(
        all(isinstance(h, str) and HASH.fullmatch(h) for h in receipt['input_hashes'].values()),
        'invalid input hash',
    )
    artifacts = receipt.get('artifacts')
    require(isinstance(artifacts, list) and len(artifacts) == 2, 'both artifact formats required')
    expected = {
        f'odin-desktop-{receipt["version"]}-candidate-amd64.deb',
        f'odin-desktop-{receipt["version"]}-candidate-x86_64.AppImage',
    }
    require({a.get('name') for a in artifacts} == expected, 'unexpected names or duplicate format')
    for artifact in artifacts:
        require(
            isinstance(artifact.get('sha256'), str) and HASH.fullmatch(artifact['sha256']),
            'invalid artifact hash',
        )
        require(
            type(artifact.get('bytes')) is int and artifact['bytes'] > 0, 'invalid artifact size'
        )
    return receipt


def validate_approval(receipt, approval, receipt_sha256, actor):
    validate_receipt(receipt)
    require(
        actor == 'Calmingstorm' and approval.get('approved_by') == 'Calmingstorm',
        'explicit Aaron approval required',
    )
    require(approval.get('action') == 'publish-identical-candidate', 'publication not authorized')
    for key in ('repository', 'version', 'source_commit', 'workflow_sha', 'run_id', 'artifacts'):
        require(approval.get(key) == receipt[key], 'approval mismatch: ' + key)
    require(
        approval.get('receipt_sha256') == receipt_sha256 and HASH.fullmatch(receipt_sha256),
        'receipt approval mismatch',
    )
    for gate in ('p45_evidence', 'p46_evidence'):
        url = approval.get(gate, '')
        require(
            isinstance(url, str)
            and re.fullmatch(
                r'https://github\.com/Calmingstorm/Odin-Desktop/'
                r'(?:issues|pull)/[1-9][0-9]*(?:#[-A-Za-z0-9]+)?',
                url,
            ),
            'missing reviewed ' + gate,
        )
    return True


def validate_files(directory, receipt):
    validate_receipt(receipt)
    directory = Path(directory)
    for artifact in receipt['artifacts']:
        path = directory / artifact['name']
        require(path.is_file() and not path.is_symlink(), 'missing or linked candidate')
        require(
            path.stat().st_size == artifact['bytes'] and digest(path) == artifact['sha256'],
            'candidate bytes changed',
        )
    notes = directory / 'release-notes.md'
    require(
        notes.is_file() and not notes.is_symlink() and digest(notes) == receipt['notes_sha256'],
        'release notes changed',
    )
    return [str(directory / a['name']) for a in receipt['artifacts']]


def publication_plan(directory, approval_path, actor, tag, tag_source):
    """Return argv only. The Actions caller executes it after environment approval."""
    directory = Path(directory)
    receipt_path = directory / 'candidate-receipt.json'
    require(receipt_path.is_file() and not receipt_path.is_symlink(), 'missing or linked receipt')
    receipt = load_json(receipt_path)
    require(tag == 'v' + receipt.get('version', ''), 'publication tag mismatch')
    require(tag_source == receipt.get('source_commit'), 'resolved tag/source SHA mismatch')
    paths = validate_files(directory, receipt)
    validate_approval(receipt, load_json(approval_path), digest(receipt_path), actor)
    return [
        'gh',
        'release',
        'create',
        tag,
        *paths,
        str(receipt_path),
        '--repo',
        REPOSITORY,
        '--verify-tag',
        '--target',
        receipt['source_commit'],
        '--title',
        'Odin Desktop ' + receipt['version'],
        '--notes-file',
        str(directory / 'release-notes.md'),
    ]


def validate_manifest(manifest, source, version, input_hashes):
    require(manifest.get('schema') == 1, 'invalid bundle schema')
    require(
        manifest.get('product', {}).get('name') == 'odin-desktop'
        and manifest['product'].get('version') == version,
        'bundled product version mismatch',
    )
    require(manifest.get('source', {}).get('commit') == source, 'bundled source mismatch')
    require(
        manifest['source'].get('uv_lock_sha256') == input_hashes['uv.lock']
        and manifest['source'].get('npm_lock_sha256') == input_hashes['app/package-lock.json'],
        'bundled lock mismatch',
    )


def asar_product(path):
    """Read Electron's embedded package.json; never execute the packaged app."""
    import struct

    with Path(path).open('rb') as stream:
        header = stream.read(16)
        require(len(header) == 16, 'truncated ASAR')
        marker, pickle_size, payload_size, json_size = struct.unpack('<4I', header)
        require(
            marker == 4 and pickle_size == payload_size + 4 and json_size < 64 * 1024 * 1024,
            'invalid ASAR',
        )
        tree = json.loads(stream.read(json_size))
        entry = tree['files']['package.json']
        require(not entry.get('unpacked') and 'link' not in entry, 'unexpected ASAR package entry')
        offset, size = int(entry['offset']), int(entry['size'])
        require(
            offset >= 0
            and 0 < size < 1024 * 1024
            and 8 + pickle_size + offset + size <= path.stat().st_size,
            'invalid embedded package bounds',
        )
        stream.seek(8 + pickle_size + offset)
        return json.loads(stream.read(size))


def rehearse(repo, candidates, output, source, workflow_sha, run_id, tag=None):
    import importlib.util
    import shutil
    import subprocess
    import sys
    import tempfile

    repo, candidates, output = (
        Path(repo).resolve(),
        Path(candidates).resolve(),
        Path(output).resolve(),
    )
    require(not output.exists(), 'evidence output must be fresh')
    require(
        SHA.fullmatch(source) and SHA.fullmatch(workflow_sha) and RUN.fullmatch(run_id),
        'invalid workflow provenance',
    )
    require(
        source
        == subprocess.check_output(
            ['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True
        ).strip(),
        'checkout/source mismatch',
    )
    require(
        not subprocess.check_output(
            ['git', '-C', str(repo), 'status', '--porcelain', '--untracked-files=no'], text=True
        ).strip(),
        'tracked checkout changes',
    )
    version = versions(
        load_json(repo / 'app/package.json'), load_json(repo / 'app/package-lock.json'), tag
    )
    notes = release_notes((repo / 'CHANGELOG.md').read_text(), version)
    inputs = {name: digest(repo / name) for name in INPUTS}
    sys.path.insert(0, str(repo / 'app/packaging/python'))
    spec = importlib.util.spec_from_file_location(
        'p41_qualification', repo / 'app/packaging/qualify.py'
    )
    qualify = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qualify)
    from manifest import verify

    artifacts, manifests = [], []
    with tempfile.TemporaryDirectory(prefix='odin-release-scan-') as temporary:
        for extension, arch in (('deb', 'amd64'), ('AppImage', 'x86_64')):
            name = f'odin-desktop-{version}-candidate-{arch}.{extension}'
            path, extracted = candidates / name, Path(temporary) / extension
            require(path.is_file() and not path.is_symlink(), 'missing candidate format')
            if extension == 'deb':
                fields = [
                    subprocess.check_output(['dpkg-deb', '-f', str(path), field], text=True).strip()
                    for field in ('Package', 'Version', 'Architecture')
                ]
                require(
                    fields == ['odin-desktop', version, 'amd64'],
                    'deb identity/version/architecture mismatch',
                )
                subprocess.run(
                    ['dpkg-deb', '--extract', str(path), str(extracted)], check=True, timeout=300
                )
            else:
                qualify.extract_appimage(path, extracted)
            resources = qualify.find_resources(extracted)
            validation = verify(resources)
            embedded = asar_product(resources / 'app.asar')
            require(
                embedded.get('name') == 'odin-desktop' and embedded.get('version') == version,
                'embedded app version mismatch',
            )
            validate_manifest(
                load_json(resources / 'bundle-manifest.json'), source, version, inputs
            )
            qualify.scan_package(extracted)
            manifests.append(validation['manifest_sha256'])
            artifacts.append({'name': name, 'bytes': path.stat().st_size, 'sha256': digest(path)})
        require(manifests[0] == manifests[1], 'format resource manifests differ')
    output.mkdir(parents=True)
    (output / 'release-notes.md').write_text(notes)
    receipt = {
        'schema': 1,
        'repository': REPOSITORY,
        'version': version,
        'source_commit': source,
        'workflow_sha': workflow_sha,
        'run_id': run_id,
        'builder_command': 'npm run package:candidate',
        'resource_manifest_sha256': manifests[0],
        'input_hashes': inputs,
        'artifacts': artifacts,
        'notes_sha256': digest(output / 'release-notes.md'),
        'scan': 'p41-credential-signatures-passed',
    }
    validate_receipt(receipt)
    for artifact in artifacts:
        shutil.copyfile(candidates / artifact['name'], output / artifact['name'])
    validate_files(output, receipt)
    # Rehearsal explicitly exercises the denied publication path, without a token.
    try:
        validate_approval(receipt, {}, '0' * 64, '')
    except ValueError:
        pass
    else:
        raise ValueError('publication gate failed open')
    (output / 'candidate-receipt.json').write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + '\n'
    )
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    scan = commands.add_parser('rehearse')
    for name in ('repo', 'candidates', 'output', 'source', 'workflow-sha', 'run-id'):
        scan.add_argument('--' + name, required=True)
    scan.add_argument('--tag')
    plan = commands.add_parser('publication-plan')
    for name in ('directory', 'approval', 'actor', 'tag', 'tag-source'):
        plan.add_argument('--' + name, required=True)
    args = vars(parser.parse_args())
    command = args.pop('command')
    result = (
        rehearse(**args)
        if command == 'rehearse'
        else publication_plan(
            args['directory'], args['approval'], args['actor'], args['tag'], args['tag_source']
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
