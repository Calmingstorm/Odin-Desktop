"""Every font the renderer bundles ships with its licence in the package's legal folder."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_runtime', HERE / 'build-runtime.py')
build_runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_runtime)


class FontNotices(unittest.TestCase):
    def test_each_bundled_font_family_has_its_ofl_notice_in_legal(self):
        fonts = sorted(build_runtime.FONTS.glob('*.woff2'))
        self.assertTrue(fonts, 'the renderer bundles fonts')
        with tempfile.TemporaryDirectory() as directory:
            legal = Path(directory)
            names = build_runtime.stage_font_notices(legal)
            staged = sorted(path.name for path in (legal / 'fonts').iterdir())
            self.assertEqual(staged, names)
            families = {font.name.split('-latin')[0].replace('-', '') for font in fonts}
            covered = {name.removeprefix('OFL-').removesuffix('.txt').lower() for name in names}
            self.assertEqual(families, covered)
            for name in names:
                text = (legal / 'fonts' / name).read_text()
                self.assertIn('SIL OPEN FONT LICENSE Version 1.1', text)
                self.assertTrue(text.startswith('Copyright '), name)
                self.assertEqual(text, (build_runtime.FONTS / name).read_text())


if __name__ == '__main__':
    unittest.main()
