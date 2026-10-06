"""Behaviour checks against inventory verifier, package scanner and isolation."""
import io
import json
import os
from pathlib import Path
import pwd
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qualify
from manifest import inventory, verify


def asar(path, name='main.js', content=b'console.log("candidate")'):
    header = json.dumps({'files': {name: {'size': len(content), 'offset': '0'}}}).encode()
    padding = b'\0' * ((-len(header)) % 4)
    payload_size = 4 + len(header) + len(padding)
    path.write_bytes(struct.pack('<4I', 4, payload_size + 4, payload_size, len(header)) + header + padding + content)


class ManifestBehaviour(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.resources = Path(self.temporary.name) / 'resources'
        self.runtime = self.resources / 'runtime'
        (self.runtime / 'python/bin').mkdir(parents=True)
        self.python = self.runtime / 'python/bin/python3.12'
        self.python.write_bytes(b'packaged binary')
        self.python.chmod(0o755)
        self.link = self.python.with_name('python3')
        self.link.symlink_to('python3.12')
        self.seal()

    def seal(self):
        self.document = {'schema': 1, 'product': {'name': 'odin-desktop', 'version': '0.1.0'},
                         'files': inventory(self.resources, prefix='', exclude=('bundle-manifest.json',))}
        self.save()

    def save(self):
        (self.resources / 'bundle-manifest.json').write_text(json.dumps(self.document))

    def test_closed_inventory_and_relocation(self):
        result = verify(self.resources)
        self.assertEqual(result['files'], 2)
        target = self.resources.with_name('relocated resources with spaces')
        self.resources.rename(target)
        self.assertEqual(verify(target), result)

    def test_digest_tamper_same_size(self):
        self.python.write_bytes(b'altered! binary')
        with self.assertRaises(ValueError):
            verify(self.resources)

    def test_missing_file(self):
        self.link.unlink()
        with self.assertRaises(ValueError):
            verify(self.resources)

    def test_unlisted_file(self):
        self.runtime.joinpath('unlisted').write_text('unexpected')
        with self.assertRaises(ValueError):
            verify(self.resources)

    def test_asar_digest_is_in_closure(self):
        archive = self.resources / 'app.asar'
        asar(archive)
        self.seal()
        verify(self.resources)
        archive.write_bytes(archive.read_bytes() + b'tamper')
        with self.assertRaises(ValueError):
            verify(self.resources)

    def test_unlisted_legal_resource_rejected(self):
        self.resources.joinpath('license.txt').write_text('unlisted legal resource')
        with self.assertRaises(ValueError):
            verify(self.resources)

    def test_duplicate_manifest_entry(self):
        self.document['files'].append(self.document['files'][0])
        self.save()
        with self.assertRaises(ValueError):
            verify(self.resources)

    def test_mode_tamper(self):
        self.python.chmod(0o644)
        with self.assertRaises(ValueError):
            verify(self.resources)

    def test_symlink_retarget_existing_internal_file(self):
        other = self.python.with_name('other')
        other.write_bytes(self.python.read_bytes())
        self.seal()
        self.link.unlink()
        self.link.symlink_to('other')
        with self.assertRaises(ValueError):
            verify(self.resources)

    def test_absolute_link_rejected(self):
        self.link.unlink()
        self.link.symlink_to(self.python)
        with self.assertRaises(ValueError):
            inventory(self.runtime)

    def test_escape_relative_link_rejected(self):
        outside = self.resources / 'outside'
        outside.write_text('outside')
        self.link.unlink()
        self.link.symlink_to('../../../outside')
        with self.assertRaises(ValueError):
            inventory(self.runtime)

    def test_dangling_link_rejected(self):
        self.link.unlink()
        self.link.symlink_to('missing')
        with self.assertRaises(ValueError):
            inventory(self.runtime)

    def test_cyclic_link_rejected(self):
        self.link.unlink()
        self.link.symlink_to('python3')
        with self.assertRaises((ValueError, RuntimeError)):
            inventory(self.runtime)

    def test_special_file_rejected(self):
        os.mkfifo(self.runtime / 'pipe')
        with self.assertRaises(ValueError):
            inventory(self.runtime)

    def test_unsafe_declared_path_rejected(self):
        self.document['files'][0]['path'] = 'runtime/../../escape'
        self.save()
        with self.assertRaises(ValueError):
            verify(self.resources)

    def test_root_symlink_rejected(self):
        other = self.runtime.with_name('external-runtime')
        self.runtime.rename(other)
        self.runtime.symlink_to(other)
        with self.assertRaises(ValueError):
            verify(self.resources)


class PackageScannerBehaviour(unittest.TestCase):
    def test_packed_asar_source_scanned(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'app.asar'
            asar(path)
            self.assertEqual(qualify.scan_asar(path), 1)

    def test_fixture_inside_asar_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'app.asar'
            asar(path, 'fixture_core.py')
            with self.assertRaises(qualify.QualificationError):
                qualify.scan_asar(path)

    def test_private_content_inside_asar_rejected_without_echo(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'app.asar'
            token = b'ghp_' + b'X' * 36
            asar(path, content=b'const token="' + token + b'"')
            with self.assertRaises(qualify.QualificationError) as error:
                qualify.scan_asar(path)
            self.assertNotIn(token.decode(), str(error.exception))

    def test_secret_crossing_chunk_boundary_rejected(self):
        stream = io.BytesIO(b'x' * (1024 * 1024 - 9) + b' ' + b'ghp_' + b'X' * 36)
        with self.assertRaises(qualify.QualificationError):
            qualify.scan_stream(stream, 'payload')

    def test_package_scan_checks_non_asar_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asar(root / 'app.asar')
            root.joinpath('private.pem').write_bytes(b'-----BEGIN OPENSSH PRIVATE KEY-----\n' + b'A' * 100 + b'\n')
            with self.assertRaises(qualify.QualificationError):
                qualify.scan_package(root)

    def test_bad_asar_payload_offset_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'app.asar'
            asar(path)
            path.write_bytes(path.read_bytes()[:-10])
            with self.assertRaises(qualify.QualificationError):
                qualify.scan_asar(path)

    def test_development_and_review_paths_rejected(self):
        for name in ['reviews/evidence.json', 'fixture-core/core.py', '.git/config',
                     '.env.production', 'dist/main.js.map', 'src/__pycache__/core.pyc']:
            with self.subTest(name=name), self.assertRaises(qualify.QualificationError):
                qualify.inspect_name(name)

    def test_production_license_and_models_allowed(self):
        for name in ['runtime/models/model.onnx', 'runtime/python/lib/site-packages/pkg/LICENSE',
                     'resources/LICENSES.chromium.html']:
            qualify.inspect_name(name)

    def test_pdf_wheel_native_library_license_and_legacy_package_refused(self):
        for name in ['runtime/python/site-packages/fitz/__init__.py',
                     'runtime/python/site-packages/pymupdf/_mupdf.so',
                     'runtime/python/licenses/pymupdf/COPYING',
                     'runtime/libmupdf.so.28.2', 'resources/PyMuPDF-1.28.2.whl']:
            with self.subTest(name=name), self.assertRaises(qualify.QualificationError):
                qualify.inspect_name(name)

    def test_actual_package_pdf_payload_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asar(root / 'app.asar')
            root.joinpath('libmupdf.so').write_bytes(b'native PDF bytes')
            with self.assertRaises(qualify.QualificationError):
                qualify.scan_package(root)

    def test_pdf_inside_asar_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'app.asar'
            asar(path, 'pymupdf.whl')
            with self.assertRaises(qualify.QualificationError):
                qualify.scan_asar(path)

    def test_vendored_pem_parser_markers_not_treated_as_private_keys(self):
        qualify.scan_stream(io.BytesIO(b'-----BEGIN RSA PRIVATE KEY-----\0parser constant'), 'crypto.so')
        qualify.scan_stream(io.BytesIO(b'aAKIA' + b'A' * 16 + b'Z embedded image data'), 'ImageFont.py')

    def test_missing_asar_not_a_package_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            Path(temporary, 'binary').write_text('not an app')
            with self.assertRaises(qualify.QualificationError):
                qualify.scan_package(Path(temporary))

    def test_asar_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'app.asar'
            asar(path, '../private.js')
            with self.assertRaises(qualify.QualificationError):
                qualify.scan_asar(path)


def require_tools(case, *names):
    missing = [name for name in names if not shutil.which(name)]
    if missing:
        case.skipTest('required tools unavailable: ' + ', '.join(missing))


def require_user_namespace(case):
    require_tools(case, 'bwrap')
    # Probe only kernel/bwrap availability, not the qualification implementation.
    # Failure of the real sandbox after this succeeds must remain a test failure.
    try:
        result = subprocess.run(
            ['bwrap', '--unshare-user', '--unshare-pid', '--unshare-net', '--unshare-ipc', '--unshare-uts',
             '--cap-drop', 'ALL', '--die-with-parent', '--new-session',
             '--ro-bind', '/', '/', '--', '/bin/true'],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as error:
        case.skipTest('private user namespaces unavailable: ' + str(error))
    if result.returncode:
        case.skipTest('private user namespaces unavailable: ' + result.stdout.strip())


def require_namespace(case):
    # Real root must retain its host permissions until bwrap binds the inputs:
    # entering a user namespace first cannot traverse another user's 0750 home.
    # Ordinary callers still need no sudo and retain their invoking identity.
    require_tools(case, 'bwrap')
    if os.geteuid() == 0:
        return False
    require_user_namespace(case)
    return True


def require_real_root(case):
    if os.geteuid() == 0:
        return
    require_tools(case, 'sudo')
    try:
        result = subprocess.run(['sudo', '-n', 'true'], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as error:
        case.skipTest('disposable dpkg install requires real root: ' + str(error))
    if result.returncode:
        case.skipTest('disposable dpkg install requires real root; sudo -n true failed: ' + result.stdout.strip())


class NamespaceBehaviour(unittest.TestCase):
    def test_private_namespace_identity_allows_real_first_start_ssh_keygen(self):
        require_tools(self, 'ssh-keygen', 'getent', 'id', 'cut', 'wc', 'stat', 'grep')
        user_namespace = require_namespace(self)
        account = pwd.getpwuid(os.getuid())
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            base.chmod(0o755)
            root, work = base / 'candidate', base / 'profile'
            root.mkdir()
            work.mkdir()
            command = ['/bin/sh', '-ec',
                       f'test "$(id -un)" = {shlex.quote(account.pw_name)}; '
                       f'test "$(getent passwd {shlex.quote(account.pw_name)} | cut -d: -f6)" = /work/home; '
                       f'test "$(getent passwd | wc -l)" = {1 if account.pw_uid == 0 else 2}; '
                       '! (echo changed >> /etc/passwd); '
                       '! (echo changed >> /work/.namespace-etc/passwd); '
                       'ssh-keygen -t ed25519 -f /work/ephemeral-key -N "" -q -C qualification; '
                       'ssh-keygen -y -f /work/ephemeral-key > /work/derived-public; '
                       'test "$(stat -c %a /work/ephemeral-key)" = 600; '
                       'grep -q "^ssh-ed25519 " /work/derived-public; echo identity-keygen-ok']
            previous_umask = os.umask(0o077)
            try:
                result = qualify.run(qualify.sandbox(root, work, account.pw_name, command,
                                                   user_namespace=user_namespace))
            finally:
                os.umask(previous_umask)
            self.assertIn('identity-keygen-ok', result)

    def test_real_namespace_hides_checkout_network_and_system_python(self):
        require_tools(self, 'id', 'stat', 'ls', 'wc', 'grep')
        user_namespace = require_namespace(self)
        account = pwd.getpwuid(os.getuid())
        checkout = Path(__file__).resolve().parents[3]
        self.assertTrue(checkout.is_dir())
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            base.chmod(0o755)
            root, work = base / 'candidate', base / 'profile'
            root.mkdir()
            work.mkdir()
            root.joinpath('proof').write_text('immutable')
            command = ['/bin/sh', '-ec',
                       f'test ! -e {shlex.quote(str(checkout))} && test ! -e /opt/odin && '
                       'test ! -x /usr/bin/python3 && test ! -e /usr/local/bin/python3 && '
                       'test "$(stat -c %a /tmp)" = 1777 && '
                       'test "$(stat -c %a /dev/shm)" = 1777 && '
                       'test -w /tmp/.X11-unix && '
                       f'test "$(id -u)" = {account.pw_uid} && '
                       f'test "$(id -g)" = {account.pw_gid} && '
                       'test "$(ls /sys/class/net 2>/dev/null | wc -l)" = 0 && '
                       'test "$(grep -c : /proc/net/dev)" = 1 && '
                       '! (echo changed > "/candidate with spaces/proof") && '
                       'echo namespace-proof-ok']
            result = qualify.run(qualify.sandbox(root, work, account.pw_name, command,
                                               user_namespace=user_namespace))
            self.assertIn('namespace-proof-ok', result)
            self.assertEqual(root.joinpath('proof').read_text(), 'immutable')

    def test_disposable_dpkg_install_executes_real_maintainer_script(self):
        require_tools(self, 'dpkg', 'dpkg-deb', 'bwrap', 'ldd', 'bash', 'sh', 'ln', 'chmod',
                      'readlink', 'unshare', 'update-alternatives', 'chown')
        require_real_root(self)
        account = pwd.getpwuid(os.getuid())
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            package = base / 'package'
            package.joinpath('DEBIAN').mkdir(parents=True)
            package.joinpath('DEBIAN/control').write_text(
                'Package: odin-desktop\nVersion: 0.0.0\nArchitecture: all\nMaintainer: test <test@example.invalid>\n'
                'Description: disposable packaging behaviour test\n')
            postinst = package.joinpath('DEBIAN/postinst')
            postinst.write_text('#!/bin/bash\necho safe > /dev/null || exit 1\nprintf "configured\\n" > /maintainer-proof\n')
            postinst.chmod(0o755)
            package.joinpath('opt/qualification').mkdir(parents=True)
            package.joinpath('opt/qualification/payload').write_text('package payload')
            deb, installed = base / 'candidate.deb', base / 'installed'
            qualify.run(['dpkg-deb', '--build', str(package), str(deb)])
            qualify.install_deb(deb, package, installed, account.pw_name)
            self.assertEqual(installed.joinpath('maintainer-proof').read_text(), 'configured\n')
            self.assertEqual(installed.joinpath('opt/qualification/payload').read_text(), 'package payload')
            self.assertIn('Status: install ok installed', installed.joinpath('var/lib/dpkg/status').read_text())

class NamespacePrerequisiteBehaviour(unittest.TestCase):
    def test_root_uses_real_root_sandbox_without_user_namespace_probe_or_sudo(self):
        account = pwd.struct_passwd(('root', 'x', 0, 0, '', '/root', '/bin/sh'))
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(os, 'geteuid', return_value=0), \
                mock.patch.object(pwd, 'getpwnam', return_value=account), \
                mock.patch.object(shutil, 'which', return_value='/usr/bin/bwrap'), \
                mock.patch(__name__ + '.require_user_namespace') as probe:
            user_namespace = require_namespace(self)
            command = qualify.sandbox(Path(temporary), Path(temporary), account.pw_name,
                                      ['/bin/true'], user_namespace=user_namespace)
            self.assertFalse(user_namespace)
            probe.assert_not_called()
            self.assertEqual(command[0], 'bwrap')
            self.assertNotIn('--unshare-user', command)
            self.assertNotIn('--cap-drop', command)
            self.assertNotIn('sudo', command)
            self.assertIn('/usr/bin/setpriv', command)
            self.assertIn('--reuid=0', command)
            self.assertIn('--unshare-pid', command)
            self.assertIn('--ro-bind', command)

    def test_ordinary_user_keeps_unprivileged_sandbox_and_invoking_identity(self):
        account = pwd.struct_passwd(('ordinary-user', 'x', 1234, 2345, '', '/home/user', '/bin/sh'))
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(os, 'geteuid', return_value=1234), \
                mock.patch.object(os, 'getuid', return_value=1234), \
                mock.patch.object(os, 'getgid', return_value=2345), \
                mock.patch.object(pwd, 'getpwnam', return_value=account), \
                mock.patch.object(shutil, 'which', return_value='/usr/bin/bwrap'), \
                mock.patch(__name__ + '.require_user_namespace') as probe:
            user_namespace = require_namespace(self)
            command = qualify.sandbox(Path(temporary), Path(temporary), account.pw_name,
                                      ['/bin/true'], user_namespace=user_namespace)
            self.assertTrue(user_namespace)
            probe.assert_called_once_with(self)
            self.assertEqual(command[0], 'bwrap')
            self.assertIn('--unshare-user', command)
            self.assertIn('--cap-drop', command)
            self.assertNotIn('sudo', command)
            self.assertNotIn('/usr/bin/setpriv', command)
            self.assertIn('--unshare-pid', command)

    def test_unavailable_user_namespace_has_a_plain_skip_reason(self):
        with mock.patch.object(shutil, 'which', return_value='/usr/bin/bwrap'), \
                mock.patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess(
                    [], 1, 'bwrap: user namespaces disabled')):
            with self.assertRaisesRegex(unittest.SkipTest, 'private user namespaces unavailable:.*disabled'):
                require_user_namespace(self)

    def test_sudo_denial_skips_only_the_real_root_prerequisite(self):
        with mock.patch.object(os, 'geteuid', return_value=1234), \
                mock.patch.object(shutil, 'which', return_value='/usr/bin/sudo'), \
                mock.patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess(
                    [], 1, 'sudo: a password is required')) as run:
            with self.assertRaisesRegex(unittest.SkipTest, 'requires real root; sudo -n true failed'):
                require_real_root(self)
            self.assertEqual(run.call_args.args[0], ['sudo', '-n', 'true'])

    def test_root_needs_no_sudo_for_the_prerequisite(self):
        with mock.patch.object(os, 'geteuid', return_value=0), mock.patch.object(subprocess, 'run') as run:
            require_real_root(self)
            run.assert_not_called()

    def test_missing_tool_skip_names_the_missing_dependency(self):
        with mock.patch.object(shutil, 'which', side_effect=lambda name: None if name == 'bwrap' else '/bin/id'):
            with self.assertRaisesRegex(unittest.SkipTest, 'required tools unavailable: bwrap'):
                require_tools(self, 'bwrap', 'id')

    def test_sandbox_failure_after_available_prerequisite_is_not_a_skip(self):
        with mock.patch.object(shutil, 'which', return_value='/usr/bin/bwrap'), \
                mock.patch.object(subprocess, 'run', side_effect=[
                    subprocess.CompletedProcess([], 0, ''),
                    subprocess.CompletedProcess([], 1, 'sandbox regression')]):
            require_user_namespace(self)
            with self.assertRaisesRegex(qualify.QualificationError, 'sandbox regression'):
                qualify.run(['bwrap'])

    def test_user_namespace_rejects_real_root_install(self):
        account = pwd.getpwuid(os.getuid())
        with self.assertRaisesRegex(qualify.QualificationError, 'invoking identity and no real-root install'):
            qualify.sandbox(Path('/unused'), Path('/unused'), account.pw_name,
                            ['/bin/true'], root_user=True, user_namespace=True)

    def test_user_namespace_rejects_a_different_host_identity(self):
        account = pwd.struct_passwd(('other-user', 'x', os.getuid() + 1, os.getgid(), '', '/', '/bin/sh'))
        with mock.patch.object(pwd, 'getpwnam', return_value=account):
            with self.assertRaisesRegex(qualify.QualificationError, 'invoking identity and no real-root install'):
                qualify.sandbox(Path('/unused'), Path('/unused'), account.pw_name,
                                ['/bin/true'], user_namespace=True)


if __name__ == '__main__':
    unittest.main()
