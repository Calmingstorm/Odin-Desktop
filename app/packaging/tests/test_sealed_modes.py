"""Real after-pack seals canonical permissions and still rejects tampering."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

PACKAGING = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGING / 'python'))
from manifest import verify


class SealedModes(unittest.TestCase):
    def test_hook_canonicalizes_before_sealing_under_collaborative_umask(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / 'install with spaces'
            resources = app / 'resources'
            resources.mkdir(parents=True)
            shutil.copy2('/bin/true', app / 'odin-desktop')
            archive = resources / 'app.asar'
            archive.write_bytes(b'archive fixture')
            archive.chmod(0o664)
            profile = resources / 'apparmor-profile'
            shutil.copy2(PACKAGING / 'apparmor-profile', profile)
            profile.chmod(0o600)
            binary = resources / 'runtime/python/bin/python3.12'
            binary.parent.mkdir(parents=True)
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
