"""Real shared ownership barrier integration, not mocked cleanup or PID probes."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_appimage_replacement import image

sys.path.insert(0, str(Path(__file__).parents[1]))
import ownership

spec = importlib.util.spec_from_file_location(
    'appimage_replace', Path(__file__).parents[1] / 'replace-appimage.py')
replacement = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replacement)

class SharedOwnershipIntegration(unittest.TestCase):
    def setUp(self):
        self.assertNotEqual(os.getuid(), 0, 'Use ordinary namespace owner')
        self.temporary = tempfile.TemporaryDirectory(prefix='AppImage lease spaces ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.env = {'HOME': str(self.root), 'XDG_STATE_HOME': str(self.root / 'state')}
        self.paths = ownership.ownership_paths(kind='appimage', env=self.env)
        self.app = self.root / 'app-cleanup.json'
        self.core = self.root / 'core-cleanup.json'
        self.old = self.root / 'Odin current.AppImage'
        self.new = self.root / 'Odin new.AppImage'
        self.old_hash = image(self.old, b'old image')
        self.new_hash = image(self.new, b'new image')
        self.app.write_text(json.dumps({'journalVersion': 2, 'current': {
            'state': 'process-exited', 'shutdownAccepted': True,
            'processOutcome': 'exited', 'unsaved': False, 'unreceipted': 0},
            'warning': None, 'archived': []}))
        self.core.write_text(json.dumps({'version': 1, 'state': 'complete',
            'resources': {'computer': {'state': 'not_started'},
                          'processes': {'state': 'released'}}, 'previous_unknown': None}))

    def lease(self, role='app'):
        return ownership.acquire_lifetime(self.paths, role, self.app, self.core)

    def replace(self):
        return replacement.replace(self.new, self.old, self.new_hash, env=self.env)

    def clean_exit(self, lease):
        # New per-lifetime evidence, never reuse a previously clean fingerprint.
        core = json.loads(self.core.read_text())
        core['at'] = os.urandom(16).hex()
        self.core.write_text(json.dumps(core))
        app = json.loads(self.app.read_text())
        app['current']['at'] = core['at']
        self.app.write_text(json.dumps(app))
        lease.finish()

    def test_busy_app_and_surviving_core_each_block_without_signalling(self):
        for role in ('app', 'core'):
            with self.lease(role) as lease:
                with self.assertRaises(ownership.OwnershipError):
                    self.replace()
                self.assertEqual(self.old.read_bytes()[-9:], b'old image')
                self.clean_exit(lease)
        self.assertEqual(self.replace()['status'], 'replaced')

    def test_closed_lease_without_receipt_is_not_safe_exit(self):
        self.lease().close()
        receipts = {path: path.read_bytes() for path in self.paths.receipts.iterdir()}
        with self.assertRaises(ownership.OwnershipError):
            self.replace()
        self.assertEqual({path: path.read_bytes() for path in receipts}, receipts)

    def test_old_clean_evidence_cannot_finish_a_new_lifetime(self):
        with self.lease() as lease:
            with self.assertRaises(ownership.OwnershipError):
                lease.finish()
        with self.assertRaises(ownership.OwnershipError):
            self.replace()

    def test_unknown_native_release_blocks_its_boot_and_preserves_evidence(self):
        # A core lifetime ends with native input release unknown: its receipt stays running.
        with self.lease('core') as lease:
            core = json.loads(self.core.read_text())
            core.update(state='unknown', at=os.urandom(16).hex(), resources={
                'computer': {'state': 'unknown'}, 'processes': {'state': 'released'}})
            self.core.write_text(json.dumps(core))
            with self.assertRaises(ownership.OwnershipError):
                lease.finish()
        # A later lifetime exits cleanly, but the core keeps that unknown as history from this
        # boot, so the later lifetime cannot be clean evidence before a restart either.
        boot = ownership._boot_id()
        with self.lease() as lease:
            core = json.loads(self.core.read_text())
            unknown = {'state': 'unknown', 'boot_id': boot,
                       'resources': {'computer': {'state': 'unknown'}}}
            clean = {'computer': {'state': 'not_started'}, 'processes': {'state': 'released'}}
            core.update(state='complete', previous_unknown=unknown, resources=clean)
            self.core.write_text(json.dumps(core))
            with self.assertRaisesRegex(ownership.OwnershipError, 'Core resource cleanup'):
                self.clean_exit(lease)
        evidence = [self.core, self.app, *self.paths.receipts.iterdir()]
        before = {path: path.read_bytes() for path in evidence}
        with self.assertRaisesRegex(ownership.OwnershipError, 'Unresolved lifetime evidence'):
            self.replace()
        self.assertEqual({path: path.read_bytes() for path in evidence}, before)
        self.assertEqual(self.old.read_bytes()[-9:], b'old image')
        # Nothing that lifetime held survives a restart, so the next boot may replace.
        # The evidence itself is still never cleared.
        later = self.root / 'next-boot'
        later.write_text('a1b2c3d4-0000-4000-8000-00000000000b\n')
        self.assertNotEqual(later.read_text().strip(), boot)
        with mock.patch.object(ownership, 'BOOT_ID', later):
            self.assertEqual(self.replace()['status'], 'replaced')
        self.assertEqual(self.core.read_bytes(), before[self.core])

    def test_manual_relocation_does_not_evade_stable_lifetime_lock(self):
        with self.lease() as lease:
            relocated = self.root / 'Relocated Applications'
            relocated.mkdir()
            self.old = self.old.rename(relocated / self.old.name)
            with self.assertRaises(ownership.OwnershipError):
                self.replace()
            self.clean_exit(lease)
        self.assertEqual(self.replace()['status'], 'replaced')

    def test_pending_helper_transaction_fences_launch_but_can_recover(self):
        with self.lease() as lease:
            self.clean_exit(lease)
        destination = self.root / 'Applications nonwritable'
        destination.mkdir()
        self.old = self.old.rename(destination / self.old.name)
        destination.chmod(0o555)
        self.addCleanup(destination.chmod, 0o700)
        with self.assertRaises(PermissionError):
            self.replace()
        self.assertTrue((self.paths.directory / 'appimage-replacement.json').exists())
        with self.assertRaises(ownership.OwnershipError):
            self.lease()
        destination.chmod(0o700)
        self.assertEqual(self.replace()['status'], 'replaced')
        with self.lease() as lease:
            self.clean_exit(lease)


if __name__ == '__main__':
    unittest.main()
