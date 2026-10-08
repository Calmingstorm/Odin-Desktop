"""Real after-pack seals canonical permissions and still rejects tampering."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import io
import tempfile
import unittest

PACKAGING = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGING / 'python'))
from manifest import verify


class SealedModes(unittest.TestCase):
    def test_symlink_tree_roots_refused_before_writing_or_chmod(self):
        for symlink_root in ('app', 'resources'):
            with self.subTest(root=symlink_root), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                actual = base / 'actual'
                actual.mkdir(mode=0o775)
                actual.chmod(0o775)
                app = base / 'app'
                if symlink_root == 'app':
                    app.symlink_to(actual, target_is_directory=True)
                    (actual / 'resources').mkdir()
                else:
                    app.mkdir()
                    (app / 'resources').symlink_to(actual, target_is_directory=True)
                executable = app / 'odin-desktop'
                executable.write_bytes(b'untouched')
                result = subprocess.run(['node', '-e',
                    'require(process.argv[1])({appOutDir:process.argv[2]})'
                    '.catch(e=>{console.error(e);process.exit(1)})',
                    str(PACKAGING / 'after-pack.cjs'), str(app)], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Packaged tree root is not a directory', result.stderr)
                self.assertEqual(executable.read_bytes(), b'untouched')
                self.assertFalse((app / 'odin-desktop.bin').exists())
                self.assertFalse((app / 'resources/ownership.py').exists())
                self.assertEqual(stat.S_IMODE(actual.stat().st_mode), 0o775)

    def test_hook_canonicalizes_before_sealing_under_collaborative_umask(self):
        self.roundtrip()

    def test_real_fpm_directory_modes_and_root_ownership(self):
        fpm = os.environ.get('FPM_BINARY') or shutil.which('fpm')
        if not fpm:
            self.skipTest('Pinned builder fpm prerequisite: provide FPM_BINARY')
        self.roundtrip(fpm=fpm)

    def roundtrip(self, *, fpm=None):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / 'install with spaces'
            resources = app / 'resources'
            old_umask = os.umask(0o002)
            try:
                resources.mkdir(parents=True)
                (resources / 'runtime/python/bin').mkdir(parents=True)
                (app / 'locales').mkdir()
                outside = Path(temporary) / 'outside'
                outside.mkdir()
                (outside / 'untouched').write_bytes(b'not packaged')
            finally:
                os.umask(old_umask)
            self.assertEqual(stat.S_IMODE(app.stat().st_mode), 0o775)
            self.assertEqual(stat.S_IMODE(resources.stat().st_mode), 0o775)
            (app / 'linked-tree').symlink_to(outside, target_is_directory=True)
            (resources / 'linked-tree').symlink_to('runtime', target_is_directory=True)
            outside_mode = stat.S_IMODE(outside.stat().st_mode)
            outside_file_mode = stat.S_IMODE((outside / 'untouched').stat().st_mode)
            shutil.copy2('/bin/true', app / 'odin-desktop')
            archive = resources / 'app.asar'
            archive.write_bytes(b'archive fixture')
            archive.chmod(0o664)
            profile = resources / 'apparmor-profile'
            shutil.copy2(PACKAGING / 'apparmor-profile', profile)
            profile.chmod(0o600)
            binary = resources / 'runtime/python/bin/python3.12'
            shutil.copy2('/bin/true', binary)
            binary.chmod(0o775)
            link = binary.with_name('python3')
            link.symlink_to(binary.name)
            (resources / 'bundle-manifest.json').write_text(json.dumps({'schema': 1}))
            result = subprocess.run(['node', '-e',
                'process.umask(0o002);require(process.argv[1])({appOutDir:process.argv[2]})'
                '.catch(e=>{console.error(e);process.exit(1)})',
                str(PACKAGING / 'after-pack.cjs'), str(app)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for directory in (app, resources, app / 'locales', resources / 'runtime',
                              resources / 'runtime/python', binary.parent):
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o755, directory)
            for tree_link, target in ((app / 'linked-tree', str(outside)),
                                      (resources / 'linked-tree', 'runtime')):
                self.assertTrue(tree_link.is_symlink())
                self.assertEqual(os.readlink(tree_link), target)
            self.assertEqual(stat.S_IMODE(outside.stat().st_mode), outside_mode)
            self.assertEqual(stat.S_IMODE((outside / 'untouched').stat().st_mode), outside_file_mode)
            verified = verify(resources)
            for path in (archive, profile, resources / 'ownership.py'):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
            self.assertEqual(stat.S_IMODE(binary.stat().st_mode), 0o755)
            self.assertTrue(link.is_symlink())
            self.assertEqual(os.readlink(link), binary.name)
            # Actual deb packing/extraction must retain the sealed modes/digests.
            control = app / 'DEBIAN'
            control.mkdir()
            (control / 'control').write_text('Package: sealed-modes\nVersion: 1\n'
                'Architecture: all\nMaintainer: Test <test@example.invalid>\nDescription: fixture\n')
            package = app.with_suffix('.deb')
            subprocess.run(['dpkg-deb', '--build', '--root-owner-group', str(app), str(package)],
                           check=True, capture_output=True)
            extracted = app.with_name('extracted')
            subprocess.run(['dpkg-deb', '-x', str(package), str(extracted)], check=True)
            self.assertEqual(verify(extracted / 'resources'), verified)
            for directory in (extracted, extracted / 'resources', extracted / 'locales',
                              extracted / 'resources/runtime/python/bin'):
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o755, directory)
            # A tiny fixture, not a release candidate: exercise the actual fpm
            # mapping used by electron-builder, including its created /opt.
            if fpm:
                fpm_deb = app.with_name('fpm-fixture.deb')
                subprocess.run([fpm, '-s', 'dir', '-t', 'deb', '-n', 'sealed-modes',
                                '-v', '1', '--deb-user', 'root', '--deb-group', 'root',
                                '-p', str(fpm_deb), str(app) + '/=/opt/odin-desktop'],
                               check=True, capture_output=True, umask=0o002)
                payload = subprocess.run(['dpkg-deb', '--fsys-tarfile', str(fpm_deb)],
                                         check=True, capture_output=True).stdout
                with tarfile.open(fileobj=io.BytesIO(payload)) as archive_tar:
                    members = {m.name.removeprefix('./').rstrip('/'): m for m in archive_tar}
                for name in ('opt', 'opt/odin-desktop', 'opt/odin-desktop/resources',
                             'opt/odin-desktop/locales', 'opt/odin-desktop/resources/runtime/python/bin'):
                    member = members[name]
                    self.assertEqual((member.mode, member.uid, member.gid), (0o755, 0, 0), name)
                fpm_root = app.with_name('fpm extracted')
                subprocess.run(['dpkg-deb', '-x', str(fpm_deb), str(fpm_root)], check=True)
                self.assertEqual(verify(fpm_root / 'opt/odin-desktop/resources'), verified)
                for name in ('opt', 'opt/odin-desktop', 'opt/odin-desktop/resources'):
                    self.assertEqual(stat.S_IMODE((fpm_root / name).stat().st_mode), 0o755, name)
            # A real SquashFS round trip under normal extraction permissions.
            # This caught ASAR 0664 becoming 0644 in the original evidence.
            squashfs = app.with_suffix('.squashfs')
            subprocess.run(['mksquashfs', str(app), str(squashfs), '-noappend',
                            '-no-progress', '-processors', '1'], check=True, capture_output=True)
            image_root = app.with_name('squashfs extracted')
            subprocess.run(['unsquashfs', '-no-progress', '-d', str(image_root), str(squashfs)],
                           check=True, capture_output=True, umask=0o022)
            self.assertEqual(verify(image_root / 'resources'), verified)
            archive.chmod(0o664)
            with self.assertRaisesRegex(ValueError, 'app.asar'):
                verify(resources)
            archive.chmod(0o644)
            archive.write_bytes(b'changed fixture')
            with self.assertRaisesRegex(ValueError, 'app.asar'):
                verify(resources)


if __name__ == '__main__':
    unittest.main()
