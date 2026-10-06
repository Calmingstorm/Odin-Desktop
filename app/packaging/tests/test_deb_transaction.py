"""Behavior of real lock/fence operations in disposable paths, never live state."""
import fcntl
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('deb_transaction', HERE / 'deb_transaction.py')
deb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deb)
build_spec = importlib.util.spec_from_file_location(
    'build_deb_control', HERE / 'build-deb-control.py')
build = importlib.util.module_from_spec(build_spec)
build_spec.loader.exec_module(build)


@unittest.skipUnless(os.geteuid() == 0, 'Run in an isolated root namespace/container')
class DebTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / 'state' / 'package-ownership'
        self.install = self.base / 'install'
        self.proc = self.base / 'proc'
        self.proc.mkdir()
        self.launcher = self.base / 'odin-desktop'

    def tearDown(self):
        self.temp.cleanup()

    def call(self, script, *args):
        deb.transaction(script, list(args), root=self.root, install=self.install,
                        proc=self.proc, launcher=self.launcher)

    def test_install_remove_purge_keep_lease_inode_and_data(self):
        data = self.base / 'user-history'
        data.write_text('receipt/quarantine sentinel')
        self.call('preinst', 'install')
        inode = (self.root / 'lease').stat().st_ino
        self.assertTrue((self.root / 'transaction.json').exists())
        self.call('postinst', 'configure')
        self.assertEqual(os.readlink(self.launcher), str(self.install / 'odin-desktop'))
        self.call('prerm', 'remove')
        self.call('postrm', 'remove')
        self.call('postrm', 'purge')
        self.assertEqual(inode, (self.root / 'lease').stat().st_ino)
        self.assertEqual(data.read_text(), 'receipt/quarantine sentinel')
        self.assertFalse(self.launcher.is_symlink())

    def test_independent_shared_app_and_core_reject_preflight(self):
        deb.provision(self.root)
        app = os.open(self.root / 'lease', os.O_RDONLY)
        core = os.open(self.root / 'lease', os.O_RDONLY)
        try:
            fcntl.flock(app, fcntl.LOCK_SH)
            fcntl.flock(core, fcntl.LOCK_SH)
            with self.assertRaises(deb.Refusal):
                self.call('preinst', 'upgrade', '0.1.0')
            os.close(app)
            app = None
            with self.assertRaises(deb.Refusal):
                self.call('prerm', 'remove')
            self.assertFalse((self.root / 'transaction.json').exists())
        finally:
            if app is not None:
                os.close(app)
            os.close(core)

    def test_interrupted_upgrade_keeps_fence_until_configure(self):
        self.call('preinst', 'install')
        self.call('postinst', 'configure')
        self.call('prerm', 'upgrade', '0.2.0')
        self.call('preinst', 'upgrade', '0.1.0', '0.2.0')
        before = (self.root / 'transaction.json').read_bytes()
        self.call('postrm', 'upgrade', '0.2.0')
        self.call('postinst', 'abort-upgrade', '0.2.0')
        self.assertEqual(before, (self.root / 'transaction.json').read_bytes())
        self.call('postinst', 'configure', '0.1.0')
        self.assertFalse((self.root / 'transaction.json').exists())

    def test_unknown_receipt_no_pid_does_not_mean_clean(self):
        deb.provision(self.root)
        receipt = self.root / 'receipts' / 'core.json'
        receipt.write_text(json.dumps({'state': 'unknown'}))
        with self.assertRaises(deb.Refusal):
            self.call('preinst', 'upgrade')
        self.assertEqual(json.loads(receipt.read_text())['state'], 'unknown')

    def test_legacy_executable_maps_and_argv_each_reject(self):
        process = self.proc / '1234'
        process.mkdir()
        (process / 'exe').symlink_to('/usr/bin/python3')
        (process / 'maps').write_text('')
        (process / 'cmdline').write_bytes(b'python3\0')
        for seam in ('exe', 'maps', 'cmdline'):
            with self.subTest(seam=seam):
                if seam == 'exe':
                    (process / 'exe').unlink()
                    (process / 'exe').symlink_to(self.install / 'odin-desktop')
                elif seam == 'maps':
                    (process / 'maps').write_text(
                        f'1-2 r-xp 0 0:0 1 {self.install}/runtime/python/lib/'
                        'libpython.so (deleted)\n')
                else:
                    (process / 'cmdline').write_bytes(
                        str(self.install / 'runtime/entry.py').encode() + b'\0')
                with self.assertRaises(deb.Refusal):
                    self.call('preinst', 'upgrade')
                if seam == 'exe':
                    (process / 'exe').unlink()
                    (process / 'exe').symlink_to('/usr/bin/python3')
                (process / 'maps').write_text('')

    def test_configure_failure_preserves_fence(self):
        self.call('preinst', 'install')
        self.launcher.write_text('other package sentinel')
        with self.assertRaises(deb.Refusal):
            self.call('postinst', 'configure')
        self.assertTrue((self.root / 'transaction.json').exists())
        self.assertEqual(self.launcher.read_text(), 'other package sentinel')

    def test_configure_cannot_clear_removal_fence(self):
        self.call('prerm', 'remove')
        with self.assertRaises(deb.Refusal):
            self.call('postinst', 'configure')
        self.assertTrue((self.root / 'transaction.json').exists())

    def test_old_alternatives_link_transitions_only_exact_install(self):
        alternative = self.base / 'alternative'
        alternative.symlink_to(self.install / 'odin-desktop')
        self.launcher.symlink_to(alternative)
        self.call('preinst', 'install')
        self.call('postinst', 'configure')
        self.assertEqual(os.readlink(self.launcher), str(self.install / 'odin-desktop'))

    def test_unguarded_predecessor_upgrade_refuses_without_scan_or_mutation(self):
        self.install.mkdir()
        sentinel = self.install / 'odin-desktop'
        sentinel.write_text('old unguarded executable')
        with self.assertRaisesRegex(deb.Refusal, 'Unguarded predecessor'):
            self.call('preinst', 'upgrade', '0.1.0')
        self.assertEqual(sentinel.read_text(), 'old unguarded executable')
        self.assertFalse((self.root / 'transaction.json').exists())

    def test_guarded_predecessor_upgrade_uses_normal_transaction(self):
        resources = self.install / 'resources'
        resources.mkdir(parents=True)
        (resources / 'ownership.py').write_text('guarded predecessor fixture')
        self.call('preinst', 'upgrade', '0.1.0')
        self.assertTrue((self.root / 'transaction.json').exists())

    def test_changed_lease_inode_refuses_configure(self):
        self.call('preinst', 'install')
        old = os.open(self.root / 'lease', os.O_RDONLY)
        try:
            (self.root / 'lease').unlink()
            (self.root / 'lease').write_text('')
            with self.assertRaises(deb.Refusal):
                self.call('postinst', 'configure')
        finally:
            os.close(old)


class HookGeneratorTests(unittest.TestCase):
    def test_generated_hooks_execute_without_installed_imports(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            build.generate(output)
            for hook in ('preinst', 'postinst', 'prerm', 'postrm'):
                # --help executes argparse and exits without any host-state operation.
                result = subprocess.run(
                    [str(output / hook), '--help'], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('usage:', result.stdout)


if __name__ == '__main__':
    unittest.main()
