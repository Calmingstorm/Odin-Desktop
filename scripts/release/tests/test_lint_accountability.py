"""Exercise maintenance release lint coverage without invoking real Ruff."""

import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    'p43_lint_gate', ROOT / 'scripts/maintenance/lint_gate.py'
)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class LintAccountabilityTests(unittest.TestCase):
    def test_release_targets_and_new_findings_fail_closed(self):
        finding = {
            'filename': str(ROOT / 'scripts/release/workflow_entry.py'),
            'code': 'F401',
            'message': 'Unused import',
        }

        def ruff(argv, **kwargs):
            self.assertIn('scripts/release', argv)
            self.assertIn('src', argv)
            self.assertIn('scripts/maintenance', argv)
            self.assertIn('tests/desktop_adapters', argv)
            self.assertEqual(kwargs['cwd'], ROOT)
            return SimpleNamespace(returncode=1, stdout=json.dumps([finding]), stderr='')

        with patch.object(gate.subprocess, 'run', side_effect=ruff), patch('builtins.print'):
            self.assertEqual(gate.main(), 1)
        allowed, new = gate.classify([finding])
        self.assertEqual(allowed, [])
        self.assertEqual(new, [finding])

    def test_release_target_clean_result_passes(self):
        clean = SimpleNamespace(returncode=0, stdout='[]', stderr='')
        with patch.object(gate.subprocess, 'run', return_value=clean), patch('builtins.print'):
            self.assertEqual(gate.main(), 0)


if __name__ == '__main__':
    unittest.main()
