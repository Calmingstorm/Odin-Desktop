"""Behaviour checks against inventory verifier, package scanner and isolation."""
import io
import json
import os
from pathlib import Path
import pwd
import shutil
import struct
import sys
import tempfile
import unittest

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


class NamespaceBehaviour(unittest.TestCase):
    @unittest.skipUnless(shutil.which('bwrap') and shutil.which('sudo') and shutil.which('ssh-keygen'),
                         'namespace/OpenSSH tools unavailable')
    def test_private_namespace_identity_allows_real_first_start_ssh_keygen(self):
        account = pwd.getpwnam('hyprlab')
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            base.chmod(0o755)
            root, work = base / 'candidate', base / 'profile'
            root.mkdir()
            work.mkdir()
            os.chown(work, account.pw_uid, account.pw_gid)
            command = ['/bin/sh', '-ec',
                       'test "$(id -un)" = hyprlab; '
                       'test "$(getent passwd hyprlab | cut -d: -f6)" = /work/home; '
                       'test "$(getent passwd | wc -l)" = 2; '
                       '! (echo changed >> /etc/passwd); '
                       '! (echo changed >> /work/.namespace-etc/passwd); '
                       'ssh-keygen -t ed25519 -f /work/ephemeral-key -N "" -q -C qualification; '
                       'ssh-keygen -y -f /work/ephemeral-key > /work/derived-public; '
                       'test "$(stat -c %a /work/ephemeral-key)" = 600; '
                       'grep -q "^ssh-ed25519 " /work/derived-public; echo identity-keygen-ok']
            previous_umask = os.umask(0o077)
            try:
                result = qualify.run(qualify.sandbox(root, work, 'hyprlab', command))
            finally:
                os.umask(previous_umask)
            self.assertIn('identity-keygen-ok', result)

    @unittest.skipUnless(shutil.which('bwrap') and shutil.which('sudo'), 'namespace tools unavailable')
    def test_real_namespace_hides_checkout_network_and_system_python(self):
        account = pwd.getpwnam('odin')
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            base.chmod(0o755)
            root, work = base / 'candidate', base / 'profile'
            root.mkdir()
            work.mkdir()
            os.chown(work, account.pw_uid, account.pw_gid)
            root.joinpath('proof').write_text('immutable')
            command = ['/bin/sh', '-c',
                       'test ! -e /home/odin/desktop-p41-work && test ! -e /opt/odin && '
                       'test ! -x /usr/bin/python3 && test ! -e /usr/local/bin/python3 && '
                       'test "$(stat -c %a /tmp)" = 1777 && '
                       'test "$(stat -c %a /dev/shm)" = 1777 && '
                       'test -w /tmp/.X11-unix && '
                       'test "$(id -u)" = 1003 && '
                       'test "$(ls /sys/class/net 2>/dev/null | wc -l)" = 0 && '
                       'test "$(grep -c : /proc/net/dev)" = 1 && '
                       '! (echo changed > "/candidate with spaces/proof") && '
                       'echo namespace-proof-ok']
            result = qualify.run(qualify.sandbox(root, work, 'odin', command))
            self.assertIn('namespace-proof-ok', result)
            self.assertEqual(root.joinpath('proof').read_text(), 'immutable')

    @unittest.skipUnless(shutil.which('dpkg-deb') and shutil.which('bwrap'), 'package tools unavailable')
    def test_disposable_dpkg_install_executes_real_maintainer_script(self):
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
            qualify.install_deb(deb, package, installed, 'odin')
            self.assertEqual(installed.joinpath('maintainer-proof').read_text(), 'configured\n')
            self.assertEqual(installed.joinpath('opt/qualification/payload').read_text(), 'package payload')
            self.assertIn('Status: install ok installed', installed.joinpath('var/lib/dpkg/status').read_text())

if __name__ == '__main__':
    unittest.main()
