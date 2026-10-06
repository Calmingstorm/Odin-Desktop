import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

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
            'previous_unknown': None, 'resources': {'processes': {'state': 'released'}},
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

    def test_native_previous_unknown_rejects_clean_process_exit(self):
        lease = self.lease()
        try:
            self.clean()
            value = json.loads(self.core.read_text())
            value['previous_unknown'] = {'state': 'unknown'}
            self.core.write_text(json.dumps(value))
            with self.assertRaises(own.OwnershipError):
                lease.finish()
        finally:
            lease.close()


if __name__ == '__main__':
    unittest.main()
