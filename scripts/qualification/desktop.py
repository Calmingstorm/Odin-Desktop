#!/usr/bin/env python3
"""D11 candidate matrix runner and fail-closed evidence accounting.

Only the already provisioned, marked Incus guests may render an app. The
runner requires the cross-lane p36 lock, never accesses host graphics, and
never removes guests/disks. A successful security probe is LIMITED evidence,
not keyboard/Orca, native computer, lifecycle or release qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tarfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = Path('/run/odq-lab.lock/owner')
ROWS = ('cinnamon', 'gnome', 'kde', 'hyprland')
ENVIRONMENT = (
    'distro', 'kernel', 'desktop', 'compositor', 'session', 'portal', 'gpu',
    'driver', 'electron', 'chromium', 'python', 'helpers',
)
APP_CASES = (
    'rendering', 'keyboard_orca', 'renderer_security', 'tray_no_tray',
    'notifications', 'startup_exit_parent_loss', 'content_paging',
    'focus_resize_scaling_recovery', 'native_dialogs', 'computer',
)
EXTRA_CASES = {'gnome': ('no_tray_reopen_exit',),
               'kde': ('sni_tray', 'kwallet_secret_service', 'portal_dialogs')}
STATUSES = ('proven', 'limited', 'pending', 'blocked')


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def identity(candidate: Path, source: str) -> dict:
    if not re.fullmatch(r'[0-9a-f]{40}', source):
        raise ValueError('Exact source SHA required')
    if candidate.is_symlink() or not candidate.is_file() or candidate.suffix != '.deb':
        raise ValueError('Regular immutable .deb candidate required')
    return {'source_sha': source, 'package_sha256': digest(candidate),
            'package_bytes': candidate.stat().st_size, 'format': 'deb',
            'architecture': 'x86-64'}


def required_cases(row: str) -> tuple:
    if row not in ROWS:
        raise ValueError('Unknown D11 row')
    if row == 'hyprland':
        return ('safe_targets', 'recovery_containment', 'packaged_helpers', 'computer')
    return APP_CASES + EXTRA_CASES.get(row, ())


def validate_row(row: dict, candidate: dict) -> list[str]:
    """Validate machine evidence, not document wording or an operator's optimism."""
    errors = []
    name = row.get('row')
    if name not in ROWS:
        return ['unknown row']
    status = row.get('status')
    if status not in STATUSES:
        errors.append('invalid row status')
    if not isinstance(row.get('limitation'), str) or not row['limitation'].strip():
        errors.append('explicit scope/limitation required')
    if status in ('proven', 'limited'):
        if not isinstance(candidate, dict):
            errors.append('measured row needs candidate identity')
        if row.get('candidate') != candidate:
            errors.append('candidate identity mismatch')
        environment = row.get('environment', {})
        for key in ENVIRONMENT:
            if not environment.get(key):
                errors.append(f'missing environment: {key}')
        expected = 'x11' if name == 'cinnamon' else 'wayland'
        if environment.get('session') != expected:
            errors.append('wrong rendering session')
        if not row.get('artifacts'):
            errors.append('artifact manifest required')
    cases = row.get('cases', {})
    for key in required_cases(name):
        case = cases.get(key, {})
        if case.get('status') not in STATUSES:
            errors.append(f'missing/invalid case: {key}')
        if case.get('status') in ('proven', 'limited'):
            if not case.get('evidence') or not case.get('command'):
                errors.append(f'case lacks evidence/command: {key}')
            reused = case.get('reused_from')
            if reused is not None and (
                reused.get('candidate') != candidate
                or reused.get('environment') != row.get('environment')
            ):
                errors.append(f'reused evidence candidate/environment mismatch: {key}')
        if status == 'proven' and case.get('status') != 'proven':
            errors.append(f'unqualified required case: {key}')
    return errors


def check_artifacts(row: dict, directory: Path) -> list[str]:
    errors = []
    directory = directory.resolve(strict=True)
    for item in row.get('artifacts', []):
        path = directory / item.get('path', '')
        if (path.is_symlink() or not path.is_file()
                or not path.resolve().is_relative_to(directory)):
            errors.append(f'unsafe/missing artifact: {item.get("path")}')
        elif digest(path) != item.get('sha256'):
            errors.append(f'artifact hash mismatch: {item.get("path")}')
    for case in row.get('cases', {}).values():
        if case.get('status') in ('proven', 'limited'):
            paths = {item['path'] for item in row.get('artifacts', [])}
            if not set(case.get('evidence', [])) <= paths:
                errors.append('case evidence absent from artifact manifest')
    return errors


def validate_matrix(matrix: dict, artifact_root: Path | None = None) -> dict:
    errors = []
    candidate = matrix.get('candidate')
    if candidate is not None:
        for key, size in (('source_sha', 40), ('package_sha256', 64)):
            if not re.fullmatch(r'[0-9a-f]{' + str(size) + '}', candidate.get(key, '')):
                errors.append(f'invalid candidate {key}')
        if candidate.get('architecture') != 'x86-64':
            errors.append('only x86-64 qualified')
        if candidate.get('package_bytes', 0) <= 0 or candidate.get('format') != 'deb':
            errors.append('candidate bytes/format required')
    rows = matrix.get('rows', [])
    if sorted(row.get('row', '') for row in rows) != sorted(ROWS):
        errors.append('exactly four distinct D11 rows required')
    for row in rows:
        errors.extend(f'{row.get("row")}: {error}' for error in validate_row(row, candidate))
        if artifact_root is not None and row.get('artifacts'):
            errors.extend(check_artifacts(row, artifact_root / row['row']))
    gates = matrix.get('gates', {})
    needed = ('ui_parity', 'p31', 'p32', 'p33', 'p34', 'p35', 'p42',
              'phase2_suites', 'd19', 'runtime_fresh_host', 'final_candidate')
    for name in needed:
        gate = gates.get(name, {})
        if gate.get('status') not in ('done', 'in_progress', 'missing', 'blocked'):
            errors.append(f'missing/invalid gate: {name}')
        if not gate.get('evidence') or not gate.get('detail'):
            errors.append(f'gate requires inventory/evidence: {name}')
    ready = (not errors and artifact_root is not None and candidate is not None
             and matrix.get('final_run') is True
             and all(row.get('status') == 'proven' for row in rows)
             and all(gates.get(name, {}).get('status') == 'done' for name in needed))
    return {'valid': not errors, 'ready': ready, 'errors': errors,
            'artifacts_verified': artifact_root is not None and not errors,
            'scope': 'D11 evidence accounting, not Aaron live acceptance or release permission'}


def run(*argv: str, timeout: int = 180) -> str:
    result = subprocess.run(argv, check=True, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout)
    return result.stdout


def admit(vm: str) -> None:
    if vm not in ('odq-cinnamon', 'odq-gnome', 'odq-kde'):
        raise ValueError('Hyprland consumes identical-candidate P3.5 evidence, not an app row')
    if (LOCK.is_symlink() or not LOCK.is_file() or LOCK.stat().st_uid != 0
            or not LOCK.read_text().startswith('p36 ')):
        raise ValueError('Acquire the cross-lane p36 lab lock first')
    instances = json.loads(run('sudo', '-n', 'incus', 'list', '--format=json'))
    # Existing reviewed lab ownership/device/capacity checks remain binding.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'p36_lab', ROOT / 'scripts/qualification/lab/lab.py',
    )
    lab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab)
    target = next(item for item in instances if item['name'] == vm)
    lab.owned(target)
    if any(item['status'] != 'Stopped' for item in instances):
        raise ValueError('A guest is running/frozen; do not touch or stop it')


def validate_tools(path: Path) -> None:
    expected = {'desktop-guest.cjs', 'desktop-probe.cjs', 'environment.py'}
    seen = set()
    with tarfile.open(path) as archive:
        for item in archive.getmembers():
            name = Path(item.name)
            if (name.is_absolute() or '..' in name.parts or item.issym() or item.islnk()
                    or not (item.isfile() or item.isdir())):
                raise ValueError('Unsafe guest tooling archive')
            if item.name in expected:
                if item.name in seen:
                    raise ValueError('Duplicate runner entry')
                source = ROOT / 'scripts/qualification' / (
                    'desktop-environment.py' if item.name == 'environment.py' else item.name)
                if archive.extractfile(item).read() != source.read_bytes():
                    raise ValueError('Guest runner differs from reviewed checkout')
                seen.add(item.name)
            elif (len(name.parts) < 2 or name.parts[0] != 'node_modules'
                  or name.parts[1] not in ('playwright', 'playwright-core')):
                raise ValueError('Unrecognized guest tooling entry')
            elif item.isfile():
                source = ROOT / 'app' / name
                if (source.is_symlink() or not source.is_file()
                        or archive.extractfile(item).read() != source.read_bytes()):
                    raise ValueError('Guest Playwright differs from locked local dependencies')
    if seen != expected:
        raise ValueError('Incomplete guest tools')


def pack_tools(output: Path) -> None:
    if output.exists() or output.resolve().is_relative_to(ROOT):
        raise ValueError('Fresh external tools archive required')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, 'w') as archive:
        for source, target in (
            ('desktop-guest.cjs', 'desktop-guest.cjs'),
            ('desktop-probe.cjs', 'desktop-probe.cjs'),
            ('desktop-environment.py', 'environment.py'),
        ):
            archive.add(ROOT / 'scripts/qualification' / source, arcname=target)
        for package in ('playwright', 'playwright-core'):
            directory = ROOT / 'app/node_modules' / package
            if not directory.is_dir():
                raise ValueError('Locked Playwright dependencies missing')
            archive.add(directory, arcname='node_modules/' + package)
    validate_tools(output)


def collect(args) -> int:
    candidate = args.candidate.resolve(strict=True)
    if args.candidate.is_symlink():
        raise ValueError('Candidate symlink refused')
    candidate_id = identity(candidate, args.source_sha)
    validate_tools(args.tools)
    output = args.output.resolve()
    if output.exists() or output.is_relative_to(ROOT):
        raise ValueError('New external evidence directory required')
    admit(args.vm)
    output.mkdir(parents=True, mode=0o700)
    commands = []

    def execute(*argv, timeout=180):
        commands.append(list(argv))
        try:
            text = run(*argv, timeout=timeout)
        except subprocess.CalledProcessError as exc:
            with (output / 'runner.log').open('a') as stream:
                stream.write(json.dumps(list(argv)) + '\n' + (exc.stdout or '')
                             + f'\nFAILED exit={exc.returncode}\n')
            print(exc.stdout or '', end='', flush=True)
            raise
        print(text, end='', flush=True)
        with (output / 'runner.log').open('a') as stream:
            stream.write(json.dumps(list(argv)) + '\n' + text)
        return text

    started = False
    cleanup = 'not started'
    failure = None
    probe_command = []
    guest_root = '/var/tmp/p36-' + uuid.uuid4().hex
    try:
        execute('sudo', '-n', 'python3', str(ROOT / 'scripts/qualification/lab/lab.py'),
                'start', args.vm, timeout=240)
        started = True
        execute('sudo', '-n', 'incus', 'file', 'push', str(candidate),
                f'{args.vm}/var/tmp/p36-candidate.deb', timeout=300)
        transported = execute('sudo', '-n', 'incus', 'exec', args.vm, '--', 'sha256sum',
                              '/var/tmp/p36-candidate.deb').split()[0]
        if transported != candidate_id['package_sha256']:
            raise ValueError('Transported candidate hash mismatch; no installation')
        execute('sudo', '-n', 'incus', 'exec', args.vm, '--', 'env',
                'DEBIAN_FRONTEND=noninteractive', 'apt-get', 'install', '-y', 'nodejs',
                timeout=300)
        execute('sudo', '-n', 'incus', 'exec', args.vm, '--', '/root/odq/sessrun',
                'odin-desktop', '--exit')
        execute('sudo', '-n', 'incus', 'exec', args.vm, '--', 'dpkg', '-i',
                '/var/tmp/p36-candidate.deb', timeout=300)
        execute('sudo', '-n', 'incus', 'file', 'push', str(args.tools.resolve(strict=True)),
                f'{args.vm}/var/tmp/p36-tools.tar', timeout=180)
        execute('sudo', '-n', 'incus', 'exec', args.vm, '--', 'mkdir', guest_root)
        execute('sudo', '-n', 'incus', 'exec', args.vm, '--', 'tar', '-xf',
                '/var/tmp/p36-tools.tar', '-C', guest_root)
        execute('sudo', '-n', 'incus', 'exec', args.vm, '--', 'chown', '-R',
                'odq:odq', guest_root)
        # Guest-only package installation; no host apt, desktop capture or input.
        env = execute('sudo', '-n', 'incus', 'exec', args.vm, '--', '/root/odq/sessrun',
                      'python3', guest_root + '/environment.py', args.vm)
        (output / 'environment.json').write_text(env)
        # The actual candidate verifies its own sealed bundle. The helper checks
        # the manifest source against the caller's declared candidate identity.
        probe_command = ['sudo', '-n', 'incus', 'exec', args.vm, '--', '/root/odq/sessrun',
                         'node', guest_root + '/desktop-guest.cjs', args.source_sha]
        execute(*probe_command, timeout=240)
        for name in ('probe.json', 'renderer.png'):
            execute('sudo', '-n', 'incus', 'file', 'pull',
                    f'{args.vm}{guest_root}/{name}', str(output / name))
    except (subprocess.SubprocessError, ValueError, OSError) as exc:
        failure = str(exc)
        (output / 'failure.txt').write_text(failure + '\n')
    finally:
        if started:
            try:
                for name in ('probe.json', 'renderer.png'):
                    if not (output / name).exists():
                        try:
                            execute('sudo', '-n', 'incus', 'file', 'pull',
                                    f'{args.vm}{guest_root}/{name}', str(output / name))
                        except subprocess.SubprocessError:
                            pass
                execute('sudo', '-n', 'python3', str(ROOT / 'scripts/qualification/lab/lab.py'),
                        'stop', args.vm, timeout=240)
                cleanup = 'graceful guest poweroff confirmed; no host graphical input/capture'
            except (subprocess.SubprocessError, OSError) as exc:
                cleanup = f'UNKNOWN: {exc}; retain lab lock, no automatic retry'
    row = {'row': args.vm[4:], 'status': 'blocked' if failure else 'limited',
           'candidate': candidate_id, 'environment': {}, 'cases': {}, 'commands': commands,
           'guest_evidence_root': guest_root,
           'cleanup': cleanup, 'limitation': failure or
           ('Interim real packaged rendering/security probe only. '
            'No Orca/native/lifecycle acceptance.')}
    if (output / 'environment.json').exists():
        row['environment'] = json.loads((output / 'environment.json').read_text())
        if row['environment'].get('package_source_sha') != args.source_sha:
            failure = 'Installed package source differs from declared candidate'
            row['status'] = 'blocked'
            row['limitation'] = failure
    if (output / 'probe.json').exists():
        proof = json.loads((output / 'probe.json').read_text())
        if proof.get('passed') is not True:
            failure = 'Guest renderer assertions did not pass'
            row['status'] = 'blocked'
            row['limitation'] = failure
        for name in ('electron', 'chromium'):
            row['environment'][name] = proof.get('versions', {}).get(name, 'not measured')
    elif not failure:
        failure = 'Guest probe result missing'
        row['status'] = 'blocked'
        row['limitation'] = failure
    for name in required_cases(row['row']):
        proven = not failure and name in ('rendering', 'renderer_security')
        row['cases'][name] = {'status': 'proven' if proven else 'pending',
                             'evidence': ['probe.json', 'renderer.png'] if proven else [],
                             'command': probe_command if proven else [],
                             'detail': 'Measured packaged renderer only' if proven else 'Not run'}
    if digest(candidate) != candidate_id['package_sha256']:
        row['status'] = 'blocked'
        row['limitation'] = 'Candidate mutated during run'
    row['artifacts'] = [{'path': path.name, 'sha256': digest(path),
                         'bytes': path.stat().st_size} for path in sorted(output.iterdir())
                        if path.is_file()]
    errors = validate_row(row, candidate_id) + check_artifacts(row, output)
    if errors:
        row['status'] = 'blocked'
        row['limitation'] = 'Evidence incomplete: ' + '; '.join(errors)
        failure = row['limitation']
    (output / 'row.json').write_text(json.dumps(row, indent=2) + '\n')
    return 1 if failure or cleanup.startswith('UNKNOWN') else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    check = sub.add_parser('check')
    check.add_argument('matrix', type=Path)
    check.add_argument('--artifact-root', type=Path)
    check.add_argument('--require-ready', action='store_true')
    pack = sub.add_parser('pack-tools')
    pack.add_argument('--output', type=Path, required=True)
    row = sub.add_parser('row')
    row.add_argument('--vm', required=True, choices=['odq-' + item for item in ROWS[:3]])
    row.add_argument('--candidate', type=Path, required=True)
    row.add_argument('--source-sha', required=True)
    row.add_argument('--tools', type=Path, required=True)
    row.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'pack-tools':
        pack_tools(args.output)
        print(json.dumps({'path': str(args.output), 'sha256': digest(args.output)}))
        return 0
    if args.action == 'row':
        return collect(args)
    result = validate_matrix(json.loads(args.matrix.read_text()), args.artifact_root)
    print(json.dumps(result, indent=2))
    return int(not result['valid'] or (args.require_ready and not result['ready']))


if __name__ == '__main__':
    raise SystemExit(main())
