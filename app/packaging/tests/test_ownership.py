import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BOOT_A = 'a1b2c3d4-0000-4000-8000-00000000000a'
BOOT_B = 'a1b2c3d4-0000-4000-8000-00000000000b'

MODULE = Path(__file__).resolve().parents[1] / 'ownership.py'
spec = importlib.util.spec_from_file_location('ownership_fixture', MODULE)
own = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = own
spec.loader.exec_module(own)


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = own.OwnershipPaths(self.root / 'install')
        self.app = self.root / 'app.json'
        self.core = self.root / 'core.json'

    def tearDown(self):
        self.temp.cleanup()

    def clean(self):
        self.app.write_text(json.dumps({'journalVersion': 2, 'warning': None, 'current': {
            'state': 'process-exited', 'shutdownAccepted': True, 'processOutcome': 'exited',
            'unsaved': False, 'unreceipted': 0, 'eventId': os.urandom(8).hex()}}))
        self.core.write_text(json.dumps({'version': 1, 'state': 'complete',
            'previous_unknown': None, 'resources': {'processes': {'state': 'released'},
                                                  'computer': {'state': 'not_started'}},
            'at': os.urandom(8).hex()}))

    def lease(self, role='app'):
        return own.acquire_lifetime(self.paths, role, self.app, self.core)

    def test_app_and_core_independent_lifetimes(self):
        app, core = self.lease(), self.lease('core')
        try:
            with self.assertRaises(own.OwnershipError):
                with own.replacement_guard(self.paths):
                    pass
            self.clean()
            app.finish()
            app.close()
            with self.assertRaises(own.OwnershipError):
                with own.replacement_guard(self.paths):
                    pass
            core.finish()
            core.close()
            with own.replacement_guard(self.paths):
                pass
        finally:
            app.close()
            core.close()

    def test_pending_transaction_denies_launch_before_receipts(self):
        with own.replacement_guard(self.paths):
            self.paths.pending.write_text('{}')
        with self.assertRaises(own.OwnershipError):
            self.lease()
        self.assertEqual(list(self.paths.receipts.iterdir()), [])

    def test_readonly_refused_start_leaves_no_dirty_lifetime_receipt(self):
        with own.acquire_lifetime(self.paths, 'core', self.app, self.core,
                                  provisional=True):
            with self.assertRaises(own.OwnershipError):
                with own.replacement_guard(self.paths):
                    pass
            self.assertEqual(list(self.paths.receipts.iterdir()), [])
        with own.replacement_guard(self.paths):
            pass

    def test_provisional_admission_publishes_before_owned_work(self):
        with own.acquire_lifetime(self.paths, 'app', self.app, self.core,
                                  provisional=True) as lease:
            lease.begin()
            self.assertEqual(len(list(self.paths.receipts.iterdir())), 1)
            self.clean()
            lease.finish()
        with own.replacement_guard(self.paths):
            pass

    def test_appimage_recovery_guard_allowed_but_launcher_denied(self):
        with own.replacement_guard(self.paths):
            (self.paths.directory / 'appimage-replacement.json').write_text('{}')
        with self.assertRaises(own.OwnershipError):
            self.lease()
        with own.replacement_guard(self.paths):
            pass

    def test_stale_clean_receipt_does_not_clean_new_lifetime(self):
        self.clean()
        lease = self.lease()
        try:
            with self.assertRaises(own.OwnershipError):
                lease.finish()
        finally:
            lease.close()
        with self.assertRaises(own.OwnershipError):
            with own.replacement_guard(self.paths):
                pass

    def boot(self, identity):
        path = self.root / 'boot_id'
        path.write_text(identity + '\n')
        return mock.patch.object(own, 'BOOT_ID', path)

    def guard_refuses(self):
        with self.assertRaisesRegex(own.OwnershipError, 'Unresolved lifetime evidence'):
            with own.replacement_guard(self.paths):
                pass

    def history(self, boot):
        """The core's retained unknown from an earlier lifetime, stamped with its boot."""
        core = json.loads(self.core.read_text())
        core['previous_unknown'] = {'state': 'unknown', 'boot_id': boot}
        self.core.write_text(json.dumps(core))

    def test_earlier_unknown_fences_its_boot_not_the_next(self):
        with self.boot(BOOT_A):
            crashed = self.lease('core')
            crashed.close()  # ended without finish: its receipt stays running
            later = self.lease()
            try:
                self.clean()
                self.history(BOOT_A)  # this lifetime's own Exit is clean
                app = json.loads(self.app.read_text())
                app['warning'] = {'id': 'notice', 'records': [{'state': 'unknown'}]}
                self.app.write_text(json.dumps(app))
                with self.assertRaisesRegex(own.OwnershipError, 'Core resource cleanup'):
                    later.finish()
            finally:
                later.close()
            states = sorted(json.loads(path.read_text())['state']
                            for path in self.paths.receipts.iterdir())
            self.assertEqual(states, ['running', 'running'])
            self.guard_refuses()
        with self.boot(BOOT_B):
            with own.replacement_guard(self.paths):
                pass
            # The same retained history no longer fences a lifetime in a later boot.
            lease = self.lease()
            try:
                self.clean()
                self.history(BOOT_A)
                lease.finish()
            finally:
                lease.close()
            with own.replacement_guard(self.paths):
                pass

    def test_an_unknown_this_boot_fences_another_installation_on_the_profile(self):
        # The .deb and AppImage keep separate registries but share one profile.
        other = own.OwnershipPaths(self.root / 'other-installation')
        with self.boot(BOOT_A):
            crashed = own.acquire_lifetime(other, 'core', self.app, self.core)
            crashed.close()  # unknown cleanup, fenced in its own registry
            lease = self.lease()
            try:
                self.clean()
                self.history(BOOT_A)  # the next core retains it in the shared profile
                with self.assertRaisesRegex(own.OwnershipError, 'Core resource cleanup'):
                    lease.finish()
            finally:
                lease.close()
            self.guard_refuses()
        with self.boot(BOOT_B):
            lease = self.lease()
            try:
                self.clean()
                self.history(BOOT_A)
                lease.finish()
            finally:
                lease.close()
            with own.replacement_guard(self.paths):
                pass

    def test_history_without_a_boot_identity_stays_fenced(self):
        with self.boot(BOOT_B):
            lease = self.lease()
            try:
                self.clean()
                core = json.loads(self.core.read_text())
                core['previous_unknown'] = {'state': 'unknown'}
                self.core.write_text(json.dumps(core))
                with self.assertRaisesRegex(own.OwnershipError, 'Core resource cleanup'):
                    lease.finish()
            finally:
                lease.close()

    def test_malformed_boot_identity_is_not_an_earlier_boot(self):
        self.paths.directory.mkdir(mode=0o700)
        self.paths.receipts.mkdir(mode=0o700)
        (self.paths.receipts / 'forged.json').write_text(json.dumps(
            {'version': 1, 'role': 'app', 'state': 'running', 'boot_id': 'not-a-kernel-boot-id'}))
        with self.boot(BOOT_B):
            self.guard_refuses()

    def test_own_unclean_exit_stays_unclean_with_history_present(self):
        lease = self.lease()
        try:
            self.clean()
            app = json.loads(self.app.read_text())
            app['current']['shutdownAccepted'] = False
            self.app.write_text(json.dumps(app))
            with self.assertRaises(own.OwnershipError):
                lease.finish()
        finally:
            lease.close()

    def test_receipt_without_boot_identity_stays_fenced(self):
        self.paths.directory.mkdir(mode=0o700)
        self.paths.receipts.mkdir(mode=0o700)
        (self.paths.receipts / 'older.json').write_text(json.dumps(
            {'version': 1, 'role': 'app', 'state': 'running'}))
        with self.boot(BOOT_B):
            self.guard_refuses()

    def test_unreadable_boot_identity_keeps_every_unclean_receipt_fenced(self):
        with self.boot(BOOT_A):
            self.lease('core').close()
        with mock.patch.object(own, 'BOOT_ID', self.root / 'missing'):
            self.guard_refuses()

    def test_hold_guardian_outlives_stop_signals_and_records_a_clean_exit(self):
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.root),
               'XDG_STATE_HOME': str(self.root / 'state')}
        child = subprocess.Popen(
            [sys.executable, '-I', '-B', str(MODULE), '--kind', 'appimage', '--role', 'app',
             '--app-cleanup', str(self.app), '--core-cleanup', str(self.core), 'hold'],
            env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline(), 'READY\n')
            child.stdin.write('ADMIT\n')
            child.stdin.flush()
            self.assertEqual(child.stdout.readline(), 'ADMITTED\n')
            for number in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
                child.send_signal(number)
                with self.assertRaises(subprocess.TimeoutExpired):
                    child.wait(timeout=0.5)
            self.clean()
            child.stdin.close()
            self.assertEqual(child.wait(timeout=10), 0)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            child.stdout.close()
        receipts = self.root / 'state/odin-desktop/install-ownership/appimage/receipts'
        rows = [json.loads(path.read_text()) for path in receipts.iterdir()]
        self.assertEqual([(row['role'], row['state']) for row in rows], [('app', 'clean')])
        self.assertTrue(rows[0]['boot_id'])

    def test_incomplete_or_malformed_core_evidence_refuses(self):
        for resources in ({}, [], {'processes': {'state': 'released'}, 'computer': []}):
            with self.subTest(resources=resources):
                lease = self.lease()
                try:
                    self.clean()
                    value = json.loads(self.core.read_text())
                    value['resources'] = resources
                    self.core.write_text(json.dumps(value))
                    with self.assertRaises(own.OwnershipError):
                        lease.finish()
                finally:
                    lease.close()


if __name__ == '__main__':
    unittest.main()
