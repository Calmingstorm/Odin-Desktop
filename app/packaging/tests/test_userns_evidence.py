"""Offline regression coverage for the one-shot qualification evidence helpers."""
from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


inventory = load('userns_inventory', 'scripts/maintenance/inventory.py')
probe = load('userns_probe', 'scripts/packaging/ubuntu_userns_probe.py')


class UsernsEvidenceTests(unittest.TestCase):
    def test_helpers_have_exact_pending_accounting_not_qualification(self):
        entries = {entry['path']: entry for entry in inventory.ledger(ROOT)['entries']}
        for path in ('scripts/packaging/ubuntu_userns_driver.py',
                     'scripts/packaging/ubuntu_userns_probe.py'):
            with self.subTest(path=path):
                entry = entries[path]
                actual = (ROOT / path).read_bytes()
                errors, pending, statuses = [], [], []
                inventory.validate_delta(ROOT, entry, b'', actual, errors, pending, statuses)
                self.assertEqual(errors, [])
                self.assertEqual(pending, [path])
                self.assertEqual(statuses, [(path, 'ledgered-exact-delta')])
                self.assertEqual(entry['state'], 'pending')
                self.assertIn('not test execution', entry['evidence'])
                mutated = copy.deepcopy(entry)
                errors = []
                inventory.validate_delta(ROOT, mutated, b'', actual + b'\n', errors, [], [])
                self.assertTrue(any('Current bytes differ' in error for error in errors))

    def test_failed_gui_checkpoint_retains_witnesses_without_relaunch(self):
        # Popen is a mock. No candidate, display, VM, or native case is executed.
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with patch.object(probe.subprocess, 'Popen') as popen:
                popen.return_value.poll.return_value = 1
                popen.return_value.returncode = 1
                with self.assertRaises(AssertionError):
                    probe.gui(output, ['/opt/odin-desktop/odin-desktop', '--smoke-test'])
                popen.assert_called_once()
            observations = json.loads((output / 'observations.json').read_text())
            self.assertEqual(observations['exit'], 1)
            self.assertEqual(observations['renderers'], [])
            self.assertNotIn('passed', observations)


if __name__ == '__main__':
    unittest.main()
