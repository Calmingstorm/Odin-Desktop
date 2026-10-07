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
        self.profile_source = self.install / 'resources' / 'apparmor-profile'
        self.profile_source.parent.mkdir(parents=True)
        (self.profile_source.parent / 'ownership.py').write_text('guarded package fixture')
        self.profile_source.write_text('profile odin-desktop /opt/Odin/odin-desktop { userns, }\n')
        self.apparmor_dir = self.base / 'apparmor.d'
        self.parser_log = self.base / 'parser.log'
        self.apparmor_parser = self.base / 'apparmor_parser'
        self.apparmor_parser.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$@" >> "' + str(self.parser_log) + '"\n')
        self.apparmor_parser.chmod(0o755)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, script, *args):
        deb.transaction(script, list(args), root=self.root, install=self.install,
                        proc=self.proc, launcher=self.launcher,
                        apparmor_dir=self.apparmor_dir, apparmor_parser=self.apparmor_parser)

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

    def boot(self, identity):
        path = self.proc / 'sys/kernel/random/boot_id'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(identity + '\n')

    def receipt(self, **value):
        deb.provision(self.root)
        path = self.root / 'receipts' / 'app.json'
        path.write_text(json.dumps({'version': 1, 'role': 'app', **value}))
        return path

    def test_unclean_receipt_from_an_earlier_boot_no_longer_blocks_removal(self):
        receipt = self.receipt(state='running', boot_id='boot-a')
        before = receipt.read_bytes()
        self.boot('boot-b')
        self.call('prerm', 'remove')
        self.assertTrue((self.root / 'transaction.json').exists())
        self.assertEqual(receipt.read_bytes(), before)

    def test_unclean_receipt_from_this_boot_asks_for_a_restart(self):
        self.receipt(state='running', boot_id='boot-a')
        self.boot('boot-a')
        with self.assertRaisesRegex(deb.Refusal, 'Restart the computer'):
            self.call('preinst', 'upgrade')
        self.assertFalse((self.root / 'transaction.json').exists())

    def test_receipt_without_boot_identity_stays_fenced(self):
        self.receipt(state='running')
        self.boot('boot-b')
        with self.assertRaisesRegex(deb.Refusal, 'cleanup is unresolved'):
            self.call('preinst', 'upgrade')

    def test_unreadable_boot_identity_keeps_unclean_receipts_fenced(self):
        self.receipt(state='running', boot_id='boot-a')
        with self.assertRaisesRegex(deb.Refusal, 'cleanup is unresolved'):
            self.call('prerm', 'remove')
        self.assertFalse((self.root / 'transaction.json').exists())

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
        (self.install / 'resources' / 'ownership.py').unlink()
        self.install.mkdir(exist_ok=True)
        sentinel = self.install / 'odin-desktop'
        sentinel.write_text('old unguarded executable')
        with self.assertRaisesRegex(deb.Refusal, 'Unguarded predecessor'):
            self.call('preinst', 'upgrade', '0.1.0')
        self.assertEqual(sentinel.read_text(), 'old unguarded executable')
        self.assertFalse((self.root / 'transaction.json').exists())

    def test_guarded_predecessor_upgrade_uses_normal_transaction(self):
        resources = self.install / 'resources'
        resources.mkdir(parents=True, exist_ok=True)
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


    def test_profile_install_load_remove_after_source_is_gone(self):
        self.call('preinst', 'install')
        self.call('postinst', 'configure')
        profile = self.apparmor_dir / 'odin-desktop'
        self.assertEqual(profile.read_bytes(), self.profile_source.read_bytes())
        self.assertEqual(profile.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.parser_log.read_text().splitlines(), ['-r', str(profile)])
        self.call('prerm', 'remove')
        self.profile_source.unlink()  # dpkg unpacks/removes resources before postrm.
        self.call('postrm', 'remove')
        self.call('postrm', 'purge')
        self.assertFalse(profile.exists())
        self.assertFalse((self.root / 'apparmor-profile.json').exists())
        self.assertEqual(self.parser_log.read_text().splitlines(),
                         ['-r', str(profile), '-R', str(profile)])

    def test_profile_upgrade_replaces_owned_bytes_and_reloads(self):
        self.call('preinst', 'install')
        self.call('postinst', 'configure')
        (self.install / 'resources' / 'ownership.py').write_text('guarded')
        self.call('preinst', 'upgrade')
        self.profile_source.write_text('profile odin-desktop { userns, }\n')
        self.call('postrm', 'upgrade')
        self.assertEqual(len(self.parser_log.read_text().splitlines()), 2)
        self.call('postinst', 'configure')
        self.assertEqual((self.apparmor_dir / 'odin-desktop').read_bytes(),
                         self.profile_source.read_bytes())
        self.assertEqual(self.parser_log.read_text().splitlines()[2], '-r')

    def test_foreign_profile_is_not_overwritten_or_removed(self):
        self.apparmor_dir.mkdir()
        profile = self.apparmor_dir / 'odin-desktop'
        profile.write_text('foreign sentinel')
        self.call('preinst', 'install')
        with self.assertRaisesRegex(deb.Refusal, 'another AppArmor'):
            self.call('postinst', 'configure')
        self.assertTrue((self.root / 'transaction.json').exists())
        self.call('prerm', 'remove')
        self.call('postrm', 'remove')
        self.call('postrm', 'purge')
        self.assertEqual(profile.read_text(), 'foreign sentinel')
        self.assertFalse(self.parser_log.exists())

    def test_locally_replaced_profile_and_unrelated_files_survive_removal(self):
        self.call('preinst', 'install')
        self.call('postinst', 'configure')
        profile = self.apparmor_dir / 'odin-desktop'
        profile.write_text('local replacement')
        unrelated = self.apparmor_dir / 'other-package'
        unrelated.write_text('unrelated sentinel')
        self.call('prerm', 'remove')
        self.call('postrm', 'remove')
        self.call('postrm', 'purge')
        self.assertEqual(profile.read_text(), 'local replacement')
        self.assertEqual(unrelated.read_text(), 'unrelated sentinel')
        self.assertEqual(len(self.parser_log.read_text().splitlines()), 2)

    def test_parser_failure_retains_fence_and_configure_can_retry(self):
        self.apparmor_parser.write_text('#!/bin/sh\nexit 1\n')
        self.call('preinst', 'install')
        with self.assertRaisesRegex(deb.Refusal, 'parser failed'):
            self.call('postinst', 'configure')
        self.assertTrue((self.root / 'transaction.json').exists())
        self.assertTrue((self.root / 'apparmor-profile.json').exists())
        self.apparmor_parser.write_text('#!/bin/sh\nexit 0\n')
        self.call('postinst', 'configure')
        self.assertFalse((self.root / 'transaction.json').exists())

    def test_parser_unload_failure_keeps_owned_profile_and_fence(self):
        self.call('preinst', 'install')
        self.call('postinst', 'configure')
        self.call('prerm', 'remove')
        self.apparmor_parser.write_text('#!/bin/sh\nexit 1\n')
        with self.assertRaisesRegex(deb.Refusal, 'parser failed'):
            self.call('postrm', 'remove')
        self.assertTrue((self.apparmor_dir / 'odin-desktop').exists())
        self.assertTrue((self.root / 'transaction.json').exists())
        self.apparmor_parser.write_text('#!/bin/sh\nexit 0\n')
        self.call('postrm', 'remove')
        self.assertFalse((self.apparmor_dir / 'odin-desktop').exists())

    def test_missing_parser_still_installs_and_removes_profile(self):
        self.apparmor_parser.unlink()
        self.call('preinst', 'install')
        self.call('postinst', 'configure')
        self.assertTrue((self.apparmor_dir / 'odin-desktop').exists())
        self.call('prerm', 'remove')
        self.call('postrm', 'remove')
        self.assertFalse((self.apparmor_dir / 'odin-desktop').exists())

    def test_symlink_source_and_destination_are_rejected(self):
        actual = self.base / 'actual-profile'
        actual.write_text('sentinel')
        self.profile_source.unlink()
        self.profile_source.symlink_to(actual)
        self.call('preinst', 'install')
        with self.assertRaises(OSError):
            self.call('postinst', 'configure')
        self.profile_source.unlink()
        self.profile_source.write_text('profile fixture')
        self.apparmor_dir.mkdir()
        (self.apparmor_dir / 'odin-desktop').symlink_to(actual)
        with self.assertRaises(OSError):
            self.call('postinst', 'configure')
        self.assertEqual(actual.read_text(), 'sentinel')

    def test_writable_source_directories_are_rejected_without_repair(self):
        for directory in (self.install, self.profile_source.parent):
            for mode in (0o775, 0o777):
                with self.subTest(directory=directory, mode=oct(mode)):
                    directory.chmod(mode)
                    self.call('preinst', 'install')
                    with self.assertRaisesRegex(deb.Refusal, 'source directory is not immutable'):
                        self.call('postinst', 'configure')
                    self.assertEqual(directory.stat().st_mode & 0o777, mode)
                    self.assertFalse((self.apparmor_dir / 'odin-desktop').exists())
                    self.assertTrue((self.root / 'transaction.json').exists())
                    self.assertFalse(self.parser_log.exists())
                    directory.chmod(0o755)

    def test_writable_source_is_rejected_without_installing(self):
        self.profile_source.chmod(0o666)
        self.call('preinst', 'install')
        with self.assertRaisesRegex(deb.Refusal, 'root-owned and immutable'):
            self.call('postinst', 'configure')
        self.assertFalse((self.apparmor_dir / 'odin-desktop').exists())
        self.assertTrue((self.root / 'transaction.json').exists())
        self.assertFalse(self.parser_log.exists())


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
