"""Behavior of the build-time PDF resource pin, not document wording."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / 'python/pdf.py'
spec = importlib.util.spec_from_file_location('pdf_stager', MODULE)
pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf)


class PdfPinBehaviour(unittest.TestCase):
    def setUp(self):
        self.lock = json.loads(pdf.LOCK_PATH.read_text())

    def test_production_lock_accepts_the_exact_wheel(self):
        wheel = pdf._locked_wheel(self.lock)
        self.assertEqual(wheel['hash'], 'sha256:' + self.lock['sha256'])

    def test_hash_version_url_and_filename_drift_rejected(self):
        for key, value in [('sha256', '0' * 64), ('version', '0'),
                           ('url', 'https://example.invalid/not-locked.whl'),
                           ('wheel', 'not-locked.whl')]:
            with self.subTest(key=key):
                drift = copy.deepcopy(self.lock)
                drift[key] = value
                with self.assertRaises(ValueError):
                    pdf._locked_wheel(drift)

    def test_pymupdf_smoke_uses_isolated_non_bytecompiling_interpreter(self):
        completed = type('Result', (), {'stdout': '{"version":"proof"}\n'})()
        with patch.object(pdf.subprocess, 'run', return_value=completed) as run:
            self.assertEqual(pdf._pdf_smoke(Path('/bundled/python'), Path('/bundled/site'),
                                           Path('/private/work')), {'version': 'proof'})
        argv = run.call_args.args[0]
        self.assertEqual(argv[:4], ['/bundled/python', '-I', '-B', '-c'])
        self.assertIn('fitz.open', argv[4])


if __name__ == '__main__':
    unittest.main()
