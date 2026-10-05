"""First-use PDF pin and actual distribution exclusion behavior."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'python/pdf.py'
spec = importlib.util.spec_from_file_location('pdf_stager', MODULE)
pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf)


class PdfPinBehaviour(unittest.TestCase):
    def setUp(self):
        self.lock = json.loads(pdf.LOCK_PATH.read_text())

    def test_optional_lock_accepts_the_exact_wheel(self):
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

    def test_staging_only_copies_pin_without_wheel_or_license(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'runtime'
            result = pdf.stage_pdf(root, Path(temporary) / 'unused-cache')
            self.assertEqual([p.name for p in root.iterdir()], ['pdf.lock.json'])
            self.assertEqual(json.loads((root / 'pdf.lock.json').read_text()), self.lock)
            self.assertEqual(result['installed_payload'], [])
            self.assertEqual(result['licenses'], [])
            self.assertEqual(result['download']['sha256'], self.lock['sha256'])

    def test_staging_refuses_existing_pdf_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.joinpath('pymupdf').mkdir()
            with self.assertRaises(ValueError):
                pdf.stage_pdf(root, root / 'cache')
            self.assertFalse(root.joinpath('pdf.lock.json').exists())

    def test_package_check_detects_all_pdf_payload_lanes(self):
        for name in ['python/site-packages/fitz/__init__.py',
                     'python/site-packages/pymupdf-1.28.2.dist-info/METADATA',
                     'python/licenses/pymupdf/COPYING', 'native/libmupdf.so.28.2',
                     'wheels/PyMuPDF-1.28.2.whl']:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'forbidden PDF payload')
                with self.assertRaises(ValueError):
                    pdf.assert_no_pdf_payload(root)

    def test_production_export_excludes_pdf_but_optional_extra_keeps_pin(self):
        import shutil
        uv = shutil.which('uv')
        if not uv:
            self.skipTest('uv unavailable')
        command = [uv, 'export', '--offline', '--frozen', '--no-dev', '--no-default-groups',
                   '--no-emit-project', '--no-header', '--no-annotate']
        production = subprocess.check_output(command, cwd=pdf.REPOSITORY, text=True)
        self.assertNotIn('pymupdf==', production)
        optional = subprocess.check_output(command + ['--extra', 'pdf'], cwd=pdf.REPOSITORY, text=True)
        self.assertIn('pymupdf==' + self.lock['version'], optional)
        self.assertIn('sha256:' + self.lock['sha256'], optional)


if __name__ == '__main__':
    unittest.main()
