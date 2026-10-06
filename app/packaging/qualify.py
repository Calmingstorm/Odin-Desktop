#!/usr/bin/env python3
"""Candidate qualification controller; candidate code executes only in bwrap."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).parent / 'python'))
from pdf import assert_no_pdf_payload, is_pdf_payload

class QualificationError(ValueError):
    pass

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def inventory(root):
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in list(dirs) + files:
            path = Path(directory) / name
            if path.is_symlink():
                if name in dirs:
                    dirs.remove(name)
                result[path.relative_to(root).as_posix()] = path
            elif not path.is_dir():
                result[path.relative_to(root).as_posix()] = path
    return result

FORBIDDEN_PARTS = {'.git', '.venv', 'fixture-core', 'reviews', 'review-artifacts', 'coverage', '__tests__'}
SECRET_PATTERNS = [rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\r\n]+[A-Za-z0-9+/=\r\n]{64,}',
                   rb'(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{30,}(?![A-Za-z0-9_])',
                   rb'(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{50,}(?![A-Za-z0-9_])',
                   rb'(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])',
                   rb'(?<![A-Za-z0-9_-])sk-(?:proj-)?[A-Za-z0-9_-]{40,}(?![A-Za-z0-9_-])']

def inspect_name(name):
    parts = PurePosixPath(name).parts
    if (not isinstance(name, str) or not name or name.startswith('/') or '\\' in name
            or '..' in parts or str(PurePosixPath(name)) != name):
        raise QualificationError('unsafe package path')
    if is_pdf_payload(name):
        raise QualificationError('PyMuPDF/MuPDF is not distributed: ' + name)
    if (set(parts) & FORBIDDEN_PARTS or 'fixture_core.py' in parts
            or name.endswith(('.map', '.pyc', '.pyo'))
            or any(p.startswith('.env') and p not in {'.env.example', '.env.sample'} for p in parts)):
        raise QualificationError('development/fixture/private artifact: ' + name)

def scan_stream(stream, name, size=None):
    tail, remaining = b'', size
    while remaining is None or remaining > 0:
        chunk = stream.read(1024 * 1024 if remaining is None else min(1024 * 1024, remaining))
        if not chunk:
            if remaining:
                raise QualificationError('truncated content: ' + name)
            break
        data = tail + chunk
        if any(re.search(pattern, data) for pattern in SECRET_PATTERNS):
            raise QualificationError('secret-shaped content: ' + name)
        if b'/home/odin/desktop-p41-work' in data or b'/opt/odin/data/secrets/' in data:
            raise QualificationError('checkout/live-secret path leaked: ' + name)
        tail = data[-1024:]
        if remaining is not None:
            remaining -= len(chunk)

def scan_asar(path):
    with path.open('rb') as stream:
        header = stream.read(16)
        if len(header) != 16:
            raise QualificationError('truncated ASAR')
        marker, pickle_size, payload_size, json_size = struct.unpack('<4I', header)
        if marker != 4 or json_size > 64 * 1024 * 1024 or pickle_size != payload_size + 4:
            raise QualificationError('invalid ASAR header')
        def unique(pairs):
            value = {}
            for key, entry in pairs:
                if key in value:
                    raise QualificationError('duplicate ASAR key')
                value[key] = entry
            return value
        tree = json.loads(stream.read(json_size), object_pairs_hook=unique)
        base, total, count = 8 + pickle_size, path.stat().st_size, 0
        def walk(files, prefix=''):
            nonlocal count
            for leaf, entry in files.items():
                name = prefix + leaf
                inspect_name(name)
                if 'files' in entry:
                    walk(entry['files'], name + '/')
                elif 'link' in entry:
                    raise QualificationError('unexpected ASAR link: ' + name)
                elif not entry.get('unpacked'):
                    offset, size = int(entry['offset']), int(entry['size'])
                    if offset < 0 or size < 0 or base + offset + size > total:
                        raise QualificationError('ASAR entry outside archive: ' + name)
                    stream.seek(base + offset)
                    scan_stream(stream, name, size)
                    count += 1
        walk(tree['files'])
        return count

def scan_package(root):
    try:
        pdf_policy = assert_no_pdf_payload(root)
    except ValueError as exc:
        raise QualificationError(str(exc)) from exc
    files, entries = inventory(root), 0
    for name, path in files.items():
        inspect_name(name)
        if not path.is_symlink() and stat.S_ISREG(path.lstat().st_mode):
            if path.suffix == '.asar':
                entries += scan_asar(path)
            else:
                with path.open('rb') as stream:
                    scan_stream(stream, name)
    if not entries:
        raise QualificationError('no inspected application ASAR')
    return {'package_files': len(files), 'asar_entries': entries,
            'pdf_policy': pdf_policy,
            'secret_scan': 'credential signatures, not universal secret-absence proof'}

def find_resources(root):
    found = list(root.rglob('bundle-manifest.json'))
    if len(found) != 1:
        raise QualificationError('expected exactly one bundle manifest')
    return found[0].parent

def run(command, timeout=180):
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise QualificationError('command failed (%s): %s\n%s' % (
            result.returncode, command[0], result.stdout[-8000:]))
    return result.stdout

def sandbox(root, work, user, command, root_user=False, pdf_fixture=None, *, user_namespace=False):
    account = pwd.getpwnam(user)
    # The portable behaviour tests retain the invoking identity in a private
    # user namespace. This is not the privileged full-candidate/GUI lane: it
    # cannot switch to another host account or install as real root.
    if user_namespace and (root_user or (account.pw_uid, account.pw_gid) != (os.getuid(), os.getgid())):
        raise QualificationError('user namespace requires the invoking identity and no real-root install')
    # OpenSSH resolves the effective UID even when HOME is explicit. Do not
    # expose the workstation account database: provide only namespace identities.
    identity = work / '.namespace-etc'
    identity.mkdir(mode=0o755, exist_ok=True)
    identity.chmod(0o755)
    identity.joinpath('passwd').write_text(
        ('root:x:0:0:Namespace root:/root:/bin/sh\n' if account.pw_uid else '') +
        f'{account.pw_name}:x:{account.pw_uid}:{account.pw_gid}:Qualification:/work/home:/bin/sh\n')
    identity.joinpath('group').write_text(
        ('root:x:0:\n' if account.pw_gid else '') + f'{account.pw_name}:x:{account.pw_gid}:\n')
    for name in ('passwd', 'group'):
        identity.joinpath(name).chmod(0o644)
    prefix = [] if user_namespace or os.geteuid() == 0 else ['sudo', '-n']
    namespace = ['--unshare-user', '--cap-drop', 'ALL'] if user_namespace else []
    args = prefix + ['bwrap'] + namespace + ['--unshare-pid', '--unshare-net', '--unshare-ipc', '--unshare-uts',
            '--die-with-parent', '--new-session',
            '--ro-bind', '/usr', '/usr', '--proc', '/proc', '--dev', '/dev',
            '--perms', '1777', '--tmpfs', '/dev/shm',
            '--perms', '1777', '--tmpfs', '/tmp', '--perms', '1777', '--dir', '/tmp/.X11-unix',
            '--tmpfs', '/home', '--perms', '0755', '--dir', '/etc',
            '--perms', '0755', '--dir', '/run']
    for path in ['/lib', '/lib64', '/bin', '/sbin']:
        if Path(path).is_symlink():
            args += ['--symlink', os.readlink(path), path]
        elif Path(path).exists():
            args += ['--ro-bind', path, path]
    for path in ['/etc/ld.so.cache', '/etc/fonts']:
        if Path(path).exists():
            args += ['--ro-bind', path, path]
    python_paths = (list(Path('/usr/bin').glob('*python*')) + list(Path('/usr/lib').glob('python*'))
                    + list(Path('/usr/lib').glob('*/libpython*.so*')))
    for path in python_paths:
        args += ['--tmpfs', str(path)] if path.is_dir() else ['--ro-bind', '/dev/null', str(path)]
    args += ['--tmpfs', '/usr/local', '--ro-bind', str(root.resolve()), '/candidate with spaces',
             '--ro-bind', str(Path(__file__).with_name('tests').joinpath('candidate_probe.py').resolve()), '/probe.py',
             '--bind', str(work.resolve()), '/work',
             '--ro-bind', str(identity.resolve()), '/work/.namespace-etc',
             '--ro-bind', str(identity.joinpath('passwd').resolve()), '/etc/passwd',
             '--ro-bind', str(identity.joinpath('group').resolve()), '/etc/group',
             '--chdir', '/work', '--clearenv',
             '--setenv', 'HOME', '/work/home', '--setenv', 'PATH', '/usr/bin:/bin',
             '--setenv', 'XDG_CONFIG_HOME', '/work/home/config', '--setenv', 'XDG_DATA_HOME', '/work/home/data',
             '--setenv', 'XDG_CACHE_HOME', '/work/home/cache', '--setenv', 'XDG_RUNTIME_DIR', '/work/run']
    if pdf_fixture is not None:
        args += ['--ro-bind', str(Path(pdf_fixture).resolve()), '/pdf-fixture.whl']
    if not root_user and not user_namespace:
        command = ['/usr/bin/setpriv', '--reuid=' + str(account.pw_uid), '--regid=' + str(account.pw_gid),
                   '--clear-groups'] + command
    elif root_user:
        args += ['--dev', '/work/root/dev']
    return args + ['--'] + command

def probe(root, output, user, gui=False, pdf_fixture=None):
    resources = find_resources(root)
    python = '/candidate with spaces/' + str(resources.relative_to(root) / 'runtime/python/bin/python3')
    with tempfile.TemporaryDirectory(prefix='qualification profile ') as temporary:
        work, account = Path(temporary), pwd.getpwnam(user)
        os.chown(work, account.pw_uid, account.pw_gid)
        if gui:
            executables = [p for p in root.rglob('odin-desktop') if p.is_file() and os.access(p, os.X_OK)]
            if len(executables) != 1:
                raise QualificationError('expected one packaged Electron executable')
            arguments = ['--gui', '/candidate with spaces/' + str(executables[0].relative_to(root))]
        else:
            arguments = ['/candidate with spaces/' + str(resources.relative_to(root))]
        text = run(sandbox(root, work, user, [python, '-I', '-B', '/probe.py'] + arguments,
                           pdf_fixture=pdf_fixture), timeout=120)
        output.write_text(text)
        result = json.loads(text.strip().splitlines()[-1])
        if gui:
            shutil.copy2(work / 'smoke.png', output.with_suffix('.png'))
        return result

def extract_appimage(image, destination):
    with image.open('rb') as stream:
        offsets, tail, position = [], b'', 0
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            data = tail + chunk
            start = 0
            while (match := data.find(b'hsqs', start)) >= 0:
                offsets.append(position - len(tail) + match)
                start = match + 4
            position += len(chunk)
            tail = data[-3:]
    # The runtime binary itself contains the magic string. Validate candidate
    # superblocks without executing the AppImage before choosing its payload.
    offset = None
    for candidate in offsets:
        check = subprocess.run(['unsquashfs', '-s', '-offset', str(candidate), str(image)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        if check.returncode == 0:
            offset = candidate
            break
    if offset is None:
        raise QualificationError('no squashfs payload')
    run(['unsquashfs', '-no-progress', '-d', str(destination), '-offset', str(offset), str(image)], timeout=300)

def install_deb(deb, source, destination, user):
    with tempfile.TemporaryDirectory(prefix='dpkg disposable work ') as temporary:
        work = Path(temporary)
        shutil.copy2(deb, work / 'candidate.deb')
        (work / 'root/var/lib/dpkg').mkdir(parents=True)
        (work / 'root/var/lib/dpkg/status').touch()
        # Real maintainer-script proof in the disposable dpkg root. Copy only
        # the ELF closure for its small toolset, never writable host /usr.
        for directory in ['usr/bin', 'etc/alternatives', 'var/lib/dpkg/alternatives', 'dev']:
            (work / 'root' / directory).mkdir(parents=True, exist_ok=True)
        for name in ['bash', 'sh', 'ln', 'chmod', 'readlink', 'unshare', 'update-alternatives']:
            binary = Path(shutil.which(name))
            target = work / 'root' / ('bin/' + name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(binary.resolve(), target)
            dependencies = run(['ldd', str(binary)])
            for library in re.findall(r'(?:=>\s*)?(/[^\s]+)', dependencies):
                source_library = Path(library)
                library_target = work / 'root' / source_library.relative_to('/')
                library_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_library.resolve(), library_target)
        (work / 'root/etc/passwd').write_text('root:x:0:0:root:/root:/bin/bash\n')
        (work / 'root/etc/group').write_text('root:x:0:\n')
        account = pwd.getpwuid(os.getuid())
        script = ('PATH=/usr/sbin:/usr/bin:/sbin:/bin /usr/bin/dpkg --root=/work/root '
                  '--force-depends --install /work/candidate.deb; '
                  'result=$?; /bin/chown -R %s:%s /work/root; exit "$result"' %
                  (account.pw_uid, account.pw_gid))
        log = run(sandbox(source, work, user, ['/bin/sh', '-c', script], root_user=True))
        shutil.copytree(work / 'root', destination, symlinks=True)
    status = (destination / 'var/lib/dpkg/status').read_text()
    if 'Package: odin-desktop\n' not in status or 'Status: install ok installed' not in status:
        raise QualificationError('dpkg did not record installed odin-desktop')
    return log

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deb', type=Path)
    parser.add_argument('--appimage', type=Path)
    parser.add_argument('--resources', type=Path, help='resource-tree proof only, never full candidate gate pass')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--user', default='odin')
    parser.add_argument('--gui', action='store_true')
    parser.add_argument('--pdf-wheel', type=Path, required=True,
                        help='hash-pinned local first-use fixture, never included in candidates')
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--installed-root', type=Path,
                        help='tree exported from a parent-qualified disposable container dpkg install')
    parser.add_argument('--installed-log', type=Path,
                        help='required install evidence log for --installed-root')
    args = parser.parse_args()
    if not args.resources and (not args.deb or not args.appimage):
        parser.error('provide --resources or both --deb and --appimage')
    if args.resources and (args.deb or args.appimage or args.install or args.installed_root):
        parser.error('--resources cannot substitute for package/install qualification')
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'started': time.time(), 'lanes': {}, 'errors': [], 'gate': 'fail'}
    try:
        from manifest import verify
        pdf_lock = json.loads(Path(__file__).with_name('python').joinpath('pdf.lock.json').read_text())
        if not args.pdf_wheel.is_file() or digest(args.pdf_wheel) != pdf_lock['sha256']:
            raise QualificationError('--pdf-wheel must match the reviewed first-use download hash')
        report['pdf_fixture'] = {'sha256': pdf_lock['sha256'], 'source': pdf_lock['url'],
                                 'distribution': 'separate read-only local qualification fixture'}
        if args.resources:
            resources = args.resources.resolve()
            lane = {'manifest': verify(resources), 'pdf_policy': assert_no_pdf_payload(resources)}
            report['lanes']['resources-only'] = lane
            lane['core'] = probe(resources, args.output / 'resources-core.json', args.user,
                                 pdf_fixture=args.pdf_wheel)
            report['gate'] = 'partial'
            report['errors'].append('resource proof only; candidate package/install/GUI gates remain unproven')
            report['finished'] = time.time()
            args.output.joinpath('qualification.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(report, indent=2))
            return 1
        with tempfile.TemporaryDirectory(prefix='odin candidate qualification ') as temporary:
            base = Path(temporary)
            base.chmod(0o755)
            deb_root, image_root = base / 'deb extracted with spaces', base / 'AppImage extracted with spaces'
            run(['dpkg-deb', '-x', str(args.deb.resolve()), str(deb_root)], timeout=300)
            extract_appimage(args.appimage.resolve(), image_root)
            roots = [('deb-extracted', deb_root), ('appimage-extracted', image_root)]
            if args.installed_root:
                if not args.installed_log or not args.installed_log.is_file():
                    raise QualificationError('--installed-root requires disposable dpkg install evidence log')
                installed = args.installed_root.resolve()
                status = (installed / 'var/lib/dpkg/status').read_text()
                if 'Package: odin-desktop\n' not in status or 'Status: install ok installed' not in status:
                    raise QualificationError('exported root lacks dpkg installed state')
                roots.append(('deb-installed', installed))
                report['install_evidence'] = {'log': str(args.installed_log), 'sha256': digest(args.installed_log),
                                            'root': str(installed), 'provenance': 'parent-supplied disposable container'}
            elif args.install:
                installed = base / 'deb installed with spaces'
                log = install_deb(args.deb, deb_root, installed, args.user)
                args.output.joinpath('deb-install.log').write_text(log)
                roots.append(('deb-installed', installed))
                report['install_caveat'] = 'dpkg --force-depends; not dependency-resolution proof'
            for label, root in roots:
                lane = {}
                report['lanes'][label] = lane
                tests = [('manifest', lambda: verify(find_resources(root))),
                         ('scan', lambda: scan_package(root)),
                         ('core', lambda: probe(root, args.output / (label + '-core.json'), args.user,
                                                pdf_fixture=args.pdf_wheel))]
                if args.gui:
                    tests.append(('gui', lambda: probe(root, args.output / (label + '-gui.json'), args.user, gui=True)))
                for name, check in tests:
                    try:
                        lane[name] = check()
                    except (QualificationError, OSError, subprocess.TimeoutExpired, KeyError, ValueError) as exc:
                        lane[name] = {'failure': str(exc)}
                        report['errors'].append(label + '/' + name + ': ' + str(exc))
                    print(label + '/' + name + ': ' + ('FAIL' if 'failure' in lane[name] else 'PASS'), flush=True)
            hashes = [lane.get('manifest', {}).get('manifest_sha256') for lane in report['lanes'].values()]
            if any(value is None for value in hashes) or len(set(hashes)) != 1:
                report['errors'].append('formats/installed tree lack identical verified resource manifests')
            else:
                report['resource_identity'] = 'identical finalized manifests across formats and installed tree'
            report['candidates'] = {str(p): {'bytes': p.stat().st_size, 'sha256': digest(p)}
                                    for p in [args.deb, args.appimage]}
            installed_proven = bool(args.install or args.installed_root)
            if not installed_proven:
                report['errors'].append('installed .deb lane not requested/proven')
            if not args.gui:
                report['gui_gap'] = 'packaged main process/renderer not requested/proven'
            report['gate'] = 'fail' if report['errors'] else ('pass' if installed_proven and args.gui else 'partial')
    except (QualificationError, OSError, subprocess.TimeoutExpired, KeyError, ValueError, ImportError) as exc:
        report['errors'].append(str(exc))
    report['finished'] = time.time()
    args.output.joinpath('qualification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['gate'] == 'pass' else 1

if __name__ == '__main__':
    raise SystemExit(main())
