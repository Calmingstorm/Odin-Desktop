"""Behavior of real lock/fence operations in disposable paths, never live state."""
import fcntl
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BOOT_A = 'a1b2c3d4-0000-4000-8000-00000000000a'
BOOT_B = 'a1b2c3d4-0000-4000-8000-00000000000b'

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
        self.legacy_install = self.base / 'Odin'
        self.proc = self.base / 'proc'
        self.proc.mkdir()
        self.launcher = self.base / 'odin-desktop'
        self.profile_source = self.install / 'resources' / 'apparmor-profile'
        self.profile_source.parent.mkdir(parents=True)
        (self.profile_source.parent / 'ownership.py').write_text('guarded package fixture')
        self.profile_source.write_text(
            'profile odin-desktop /opt/odin-desktop/odin-desktop { userns, }\n')
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
                        apparmor_dir=self.apparmor_dir, apparmor_parser=self.apparmor_parser,
                        legacy_install=self.legacy_install)

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
        receipt = self.receipt(state='running', boot_id=BOOT_A)
        before = receipt.read_bytes()
        self.boot(BOOT_B)
        self.call('prerm', 'remove')
        self.assertTrue((self.root / 'transaction.json').exists())
        self.assertEqual(receipt.read_bytes(), before)

    def test_unclean_receipt_from_this_boot_asks_for_a_restart(self):
        self.receipt(state='running', boot_id=BOOT_A)
        self.boot(BOOT_A)
        with self.assertRaisesRegex(deb.Refusal, 'Restart the computer'):
            self.call('preinst', 'upgrade')
        self.assertFalse((self.root / 'transaction.json').exists())

    def test_receipt_without_boot_identity_stays_fenced(self):
        self.receipt(state='running')
        self.boot(BOOT_B)
        with self.assertRaisesRegex(deb.Refusal, 'cleanup is unresolved'):
            self.call('preinst', 'upgrade')

    def test_refused_change_unwinds_while_odin_holds_the_lease(self):
        self.call('preinst', 'install')
        self.call('postinst', 'configure')
        lease = os.open(self.root / 'lease', os.O_RDONLY)
        try:
            fcntl.flock(lease, fcntl.LOCK_SH)
            # dpkg's own sequence for a busy upgrade, then a busy removal.
            busy = ((('prerm', 'upgrade', '0.1.0'), ('postinst', 'abort-upgrade', '0.1.0')),
                    (('prerm', 'remove'), ('postinst', 'abort-remove')))
            for refused, unwind in busy:
                with self.subTest(refused=refused):
                    with self.assertRaisesRegex(deb.Refusal, 'Exit Odin'):
                        self.call(*refused)
                    self.call(*unwind)  # the old version stays installed
            for unwind in (('postrm', 'abort-upgrade', '0.1.0'), ('postrm', 'abort-install'),
                           ('postinst', 'abort-deconfigure', 'in-favour', 'other', '1')):
                self.call(*unwind)
            self.assertFalse((self.root / 'transaction.json').exists())
            self.assertEqual(os.readlink(self.launcher), str(self.install / 'odin-desktop'))
        finally:
            os.close(lease)

    def test_malformed_boot_identity_is_not_an_earlier_boot(self):
        self.receipt(state='running', boot_id='not-a-kernel-boot-id')
        self.boot(BOOT_B)
        with self.assertRaisesRegex(deb.Refusal, 'cleanup is unresolved'):
            self.call('prerm', 'remove')
        self.assertFalse((self.root / 'transaction.json').exists())

    def test_unreadable_boot_identity_keeps_unclean_receipts_fenced(self):
        self.receipt(state='running', boot_id=BOOT_A)
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


class LegacyInstallTransactionTests(unittest.TestCase):
    """Real transaction/lock/process behaviour, with only privileged seams mocked.

    Run as the ordinary user behind the repository PID launcher. Every path,
    including the legacy directory and procfs evidence, is a disposable fixture.
    Root ownership provisioning and AppArmor application are covered separately
    by the existing privileged fixture tests, not claimed by these tests.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'state' / 'package-ownership'
        self.install = self.base / 'opt' / 'odin-desktop'
        self.legacy_install = self.base / 'opt' / 'Odin'
        self.proc = self.base / 'proc'
        self.proc.mkdir()
        (self.install / 'resources').mkdir(parents=True)
        (self.install / 'resources' / 'ownership.py').write_text('current desktop')
        self.launcher = self.base / 'odin-desktop'
        self.enterContext(mock.patch.object(deb.os, 'geteuid', return_value=0))
        self.enterContext(mock.patch.object(deb, 'provision', side_effect=self.provision_fixture))
        self.enterContext(mock.patch.object(deb, 'apparmor_profile'))

    def provision_fixture(self, root):
        root.mkdir(parents=True, exist_ok=True)
        (root / 'lease').touch(exist_ok=True)
        (root / 'receipts').mkdir(exist_ok=True)

    def call(self, script, *args, legacy_install=None):
        deb.transaction(
            script, list(args), root=self.root, install=self.install,
            proc=self.proc, launcher=self.launcher,
            apparmor_dir=self.base / 'apparmor.d',
            apparmor_parser=self.base / 'apparmor_parser',
            legacy_install=self.legacy_install if legacy_install is None else legacy_install)

    def legacy_fixture(self, *, guarded):
        self.legacy_install.mkdir(parents=True)
        (self.legacy_install / 'foreign.py').write_text('foreign sentinel')
        if guarded:
            resources = self.legacy_install / 'resources'
            resources.mkdir()
            (resources / 'ownership.py').write_text('old desktop')

    def legacy_snapshot(self):
        return {str(path.relative_to(self.legacy_install)):
                (path.lstat().st_ino, path.lstat().st_mode,
                 path.lstat().st_mtime_ns, path.read_bytes() if path.is_file() else None)
                for path in [self.legacy_install, *self.legacy_install.rglob('*')]}

    def process(self, install, seam='exe'):
        process = self.proc / '1234'
        process.mkdir()
        (process / 'exe').symlink_to(
            install / 'odin-desktop' if seam == 'exe' else '/usr/bin/python3')
        (process / 'maps').write_text(
            f'1-2 r-xp 0 0:0 1 {install}/resources/app.asar\n' if seam == 'maps' else '')
        (process / 'cmdline').write_bytes(
            str(install / 'runtime/entry.py').encode() + b'\0'
            if seam == 'cmdline' else b'python3\0')
        return process

    def test_fresh_install_ignores_running_foreign_legacy_path_and_writes_only_new_paths(self):
        self.legacy_fixture(guarded=False)
        self.process(self.legacy_install)
        before = self.legacy_snapshot()
        with mock.patch.object(deb, 'legacy_process_check',
                               wraps=deb.legacy_process_check) as scan:
            self.call('preinst', 'install')
            self.call('postinst', 'configure')
        scan.assert_called_once_with(self.install, self.proc)
        self.assertEqual(self.legacy_snapshot(), before)
        self.assertEqual(os.readlink(self.launcher), str(self.install / 'odin-desktop'))
        self.assertFalse((self.root / 'transaction.json').exists())

    def test_upgrade_ignores_running_foreign_legacy_path_without_writes(self):
        self.legacy_fixture(guarded=False)
        self.process(self.legacy_install)
        before = self.legacy_snapshot()
        with mock.patch.object(deb, 'legacy_process_check',
                               wraps=deb.legacy_process_check) as scan:
            self.call('prerm', 'upgrade', '1.0.0')
            self.call('preinst', 'upgrade', '0.9.0', '1.0.0')
        self.assertEqual(scan.call_args_list, [mock.call(self.install, self.proc)] * 2)
        self.assertEqual(self.legacy_snapshot(), before)
        self.assertTrue((self.root / 'transaction.json').exists())

    def test_guarded_legacy_upgrade_refuses_running_executable_maps_and_argv(self):
        self.legacy_fixture(guarded=True)
        before = self.legacy_snapshot()
        for script in ('preinst', 'prerm'):
            for seam in ('exe', 'maps', 'cmdline'):
                with self.subTest(script=script, seam=seam):
                    process = self.process(self.legacy_install, seam)
                    with self.assertRaisesRegex(deb.Refusal, 'still (running|mapped)'):
                        self.call(script, 'upgrade', '0.9.0')
                    self.assertFalse((self.root / 'transaction.json').exists())
                    self.assertEqual(self.legacy_snapshot(), before)
                    for path in process.iterdir():
                        path.unlink()
                    process.rmdir()

    def test_stopped_guarded_legacy_upgrade_checks_both_paths_without_legacy_writes(self):
        self.legacy_fixture(guarded=True)
        self.launcher.symlink_to(self.legacy_install / 'odin-desktop')
        before = self.legacy_snapshot()
        with mock.patch.object(deb, 'legacy_process_check',
                               wraps=deb.legacy_process_check) as scan:
            self.call('prerm', 'upgrade', '1.0.0')
            self.call('preinst', 'upgrade', '0.9.0', '1.0.0')
            self.call('postrm', 'upgrade', '1.0.0')
            self.call('postinst', 'configure', '0.9.0')
        self.assertEqual(scan.call_args_list,
                         [mock.call(self.install, self.proc),
                          mock.call(self.legacy_install, self.proc)] * 2)
        self.assertEqual(self.legacy_snapshot(), before)
        self.assertEqual(os.readlink(self.launcher), str(self.install / 'odin-desktop'))
        self.assertFalse((self.root / 'transaction.json').exists())

    def test_other_hook_phases_never_inspect_legacy_path(self):
        class ForbiddenLegacyPath:
            def __truediv__(self, other):
                raise AssertionError('Non-upgrade hook inspected the old directory')

        forbidden = ForbiddenLegacyPath()
        phases = (
            ('preinst', 'install'), ('postinst', 'configure'),
            ('prerm', 'remove'), ('postrm', 'remove'), ('postrm', 'purge'),
            ('preinst', 'install'), ('prerm', 'deconfigure'), ('postrm', 'remove'),
            ('postinst', 'triggered'), ('postrm', 'upgrade'),
            ('preinst', 'unknown'), ('prerm', 'unknown'),
        )
        for script, operation in phases:
            with self.subTest(script=script, operation=operation):
                self.call(script, operation, legacy_install=forbidden)
        self.call('preinst', 'upgrade')
        self.call('postrm', 'upgrade', legacy_install=forbidden)
        self.call('postinst', 'configure', legacy_install=forbidden)
        for script in ('preinst', 'postinst', 'prerm', 'postrm'):
            self.call(script, legacy_install=forbidden)
            for operation in deb.UNWIND:
                with self.subTest(script=script, operation=operation):
                    self.call(script, operation, legacy_install=forbidden)

    def test_stopped_legacy_alternatives_launcher_transitions_without_resolving_old_path(self):
        self.legacy_fixture(guarded=True)
        self.launcher.symlink_to('/etc/alternatives/odin-desktop')
        self.call('preinst', 'upgrade', '0.9.0', '1.0.0')
        readlink = os.readlink
        with (mock.patch.object(deb.os, 'readlink', side_effect=lambda path:
                                str(self.legacy_install / 'odin-desktop')
                                if path == '/etc/alternatives/odin-desktop' else readlink(path)),
              mock.patch.object(Path, 'resolve', side_effect=AssertionError('Resolved old path'))):
            self.call('postinst', 'configure')
        self.assertEqual(os.readlink(self.launcher), str(self.install / 'odin-desktop'))

    def test_old_launcher_without_guarded_upgrade_evidence_is_not_replaced_or_resolved(self):
        self.launcher.symlink_to(self.legacy_install / 'odin-desktop')
        for operation in ('install', 'upgrade'):
            with self.subTest(operation=operation):
                self.call('preinst', operation)
                with mock.patch.object(Path, 'resolve',
                                       side_effect=AssertionError('Resolved foreign old path')):
                    with self.assertRaisesRegex(deb.Refusal, 'another launcher'):
                        self.call('postinst', 'configure')
                self.assertEqual(os.readlink(self.launcher),
                                 str(self.legacy_install / 'odin-desktop'))
                self.assertTrue((self.root / 'transaction.json').exists())

    def test_primary_alternatives_launcher_still_transitions_by_exact_link_text(self):
        self.launcher.symlink_to('/etc/alternatives/odin-desktop')
        self.call('preinst', 'install')
        readlink = os.readlink
        with mock.patch.object(deb.os, 'readlink', side_effect=lambda path:
                               str(self.install / 'odin-desktop')
                               if path == '/etc/alternatives/odin-desktop' else readlink(path)):
            self.call('postinst', 'configure')
        self.assertEqual(os.readlink(self.launcher), str(self.install / 'odin-desktop'))

    def test_arbitrary_alternatives_chain_transitions_to_dangling_new_target(self):
        alternatives = self.base / 'alternatives'
        alternatives.mkdir()
        first = alternatives / 'first'
        second = alternatives / 'second'
        first.symlink_to('second')
        second.symlink_to('../opt/odin-desktop/odin-desktop')
        self.launcher.symlink_to(first)
        self.call('preinst', 'install')
        target = str(self.install / 'odin-desktop')
        readlink = os.readlink

        def guarded_readlink(path):
            self.assertNotEqual(os.fspath(path), target, 'Inspected terminal new target')
            self.assertFalse(os.fspath(path).startswith(str(self.legacy_install)))
            return readlink(path)

        with (mock.patch.object(deb.os, 'readlink', side_effect=guarded_readlink),
              mock.patch.object(Path, 'resolve', side_effect=AssertionError('Resolved target'))):
            self.call('postinst', 'configure')
        self.assertEqual(os.readlink(self.launcher), target)
        self.assertEqual(os.readlink(first), 'second')
        self.assertEqual(os.readlink(second), '../opt/odin-desktop/odin-desktop')
        self.assertFalse((self.root / 'transaction.json').exists())

    def test_guarded_upgrade_accepts_arbitrary_old_alternative_without_terminal_access(self):
        self.legacy_fixture(guarded=True)
        alternative = self.base / 'alternative'
        alternative.symlink_to(self.legacy_install / 'odin-desktop')
        self.launcher.symlink_to(alternative)
        self.call('preinst', 'upgrade')
        readlink = os.readlink

        def guarded_readlink(path):
            self.assertFalse(os.fspath(path).startswith(str(self.legacy_install)),
                             'Configure inspected old destination')
            return readlink(path)

        with mock.patch.object(deb.os, 'readlink', side_effect=guarded_readlink):
            self.call('postinst', 'configure')
        self.assertEqual(os.readlink(self.launcher), str(self.install / 'odin-desktop'))
        self.assertEqual(os.readlink(alternative), str(self.legacy_install / 'odin-desktop'))

    def test_foreign_direct_and_indirect_launchers_stay_fenced(self):
        foreign = self.base / 'foreign'
        foreign.write_text('foreign executable sentinel')
        alternative = self.base / 'alternative'
        alternative.symlink_to(foreign)
        for destination in (foreign, alternative):
            with self.subTest(destination=destination):
                self.launcher.symlink_to(destination)
                self.call('preinst', 'install')
                with self.assertRaisesRegex(deb.Refusal, 'another launcher'):
                    self.call('postinst', 'configure')
                self.assertEqual(os.readlink(self.launcher), str(destination))
                self.assertEqual(foreign.read_text(), 'foreign executable sentinel')
                self.assertTrue((self.root / 'transaction.json').exists())
                self.launcher.unlink()

    def test_old_direct_indirect_and_parent_alias_launchers_never_access_old_tree(self):
        alternative = self.base / 'alternative'
        alternative.symlink_to(self.legacy_install / 'odin-desktop')
        alias = self.base / 'alias'
        alias.symlink_to(self.legacy_install, target_is_directory=True)
        readlink = os.readlink
        stat_path = Path.stat
        lstat_path = Path.lstat

        def guard(path):
            text = os.fspath(path)
            self.assertFalse(text == str(self.legacy_install)
                             or text.startswith(str(self.legacy_install) + '/'),
                             'Non-upgrade inspected old tree')

        def guarded_readlink(path):
            guard(path)
            return readlink(path)

        def guarded_stat(path, *args, **kwargs):
            guard(path)
            return stat_path(path, *args, **kwargs)

        def guarded_lstat(path, *args, **kwargs):
            guard(path)
            return lstat_path(path, *args, **kwargs)

        for destination in (self.legacy_install / 'odin-desktop', alternative,
                            alias / 'odin-desktop', alias / '..' / 'odin-desktop' / 'odin-desktop'):
            with self.subTest(destination=destination):
                self.launcher.symlink_to(destination)
                with (mock.patch.object(deb.os, 'readlink', side_effect=guarded_readlink),
                      mock.patch.object(Path, 'stat', guarded_stat),
                      mock.patch.object(Path, 'lstat', guarded_lstat),
                      mock.patch.object(Path, 'resolve',
                                        side_effect=AssertionError('Resolved old'))):
                    self.call('preinst', 'install')
                    with self.assertRaisesRegex(deb.Refusal, 'another launcher'):
                        self.call('postinst', 'configure')
                self.assertEqual(os.readlink(self.launcher), str(destination))
                self.assertTrue((self.root / 'transaction.json').exists())
                self.launcher.unlink()

    def test_link_cycle_and_excessive_depth_refuse_without_clearing_fence(self):
        cycle = self.base / 'cycle'
        cycle.symlink_to(cycle)
        chain = [self.base / f'link-{index}' for index in range(42)]
        for index, link in enumerate(chain):
            link.symlink_to(chain[index + 1] if index + 1 < len(chain)
                            else self.install / 'odin-desktop')
        for destination in (cycle, chain[0]):
            with self.subTest(destination=destination):
                self.launcher.symlink_to(destination)
                self.call('preinst', 'install')
                with self.assertRaisesRegex(deb.Refusal, 'another launcher'):
                    self.call('postinst', 'configure')
                self.assertEqual(os.readlink(self.launcher), str(destination))
                self.assertTrue((self.root / 'transaction.json').exists())
                self.launcher.unlink()

    def test_primary_process_fence_still_refuses_install_upgrade_remove_and_deconfigure(self):
        self.process(self.install)
        for script, operation in (('preinst', 'install'), ('preinst', 'upgrade'),
                                  ('prerm', 'upgrade'), ('prerm', 'remove'),
                                  ('prerm', 'deconfigure')):
            with self.subTest(script=script, operation=operation):
                with self.assertRaises(deb.Refusal):
                    self.call(script, operation)
                self.assertFalse((self.root / 'transaction.json').exists())

    def test_primary_lease_and_unclean_receipt_fences_still_refuse_upgrade(self):
        self.provision_fixture(self.root)
        fd = os.open(self.root / 'lease', os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            with self.assertRaisesRegex(deb.Refusal, 'Exit Odin'):
                self.call('preinst', 'upgrade')
        finally:
            os.close(fd)
        (self.root / 'receipts' / 'app.json').write_text(json.dumps({'state': 'unknown'}))
        with self.assertRaisesRegex(deb.Refusal, 'cleanup is unresolved'):
            self.call('preinst', 'upgrade')
        self.assertFalse((self.root / 'transaction.json').exists())

    def test_unguarded_primary_predecessor_still_refuses_before_scanning(self):
        (self.install / 'resources' / 'ownership.py').unlink()
        with mock.patch.object(deb, 'legacy_process_check') as scan:
            with self.assertRaisesRegex(deb.Refusal, 'Unguarded predecessor'):
                self.call('preinst', 'upgrade')
        scan.assert_not_called()
        self.assertFalse((self.root / 'transaction.json').exists())


    def test_default_install_creates_launcher_with_new_target_without_accessing_opt(self):
        # A new symlink stores its target without inspecting it. AppArmor is mocked.
        self.call('preinst', 'install')
        deb.transaction(
            'postinst', ['configure'], root=self.root, proc=self.proc,
            launcher=self.launcher, apparmor_dir=self.base / 'apparmor.d',
            apparmor_parser=self.base / 'apparmor_parser', legacy_install=self.legacy_install)
        self.assertEqual(os.readlink(self.launcher), '/opt/odin-desktop/odin-desktop')
        self.assertFalse((self.root / 'transaction.json').exists())


class HookGeneratorTests(unittest.TestCase):
    def test_default_install_and_launcher_target_use_distinct_desktop_directory(self):
        self.assertEqual(deb.INSTALL, Path('/opt/odin-desktop'))
        self.assertEqual(deb.transaction.__kwdefaults__['install'], deb.INSTALL)
        self.assertEqual(str(deb.INSTALL / 'odin-desktop'), '/opt/odin-desktop/odin-desktop')

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
