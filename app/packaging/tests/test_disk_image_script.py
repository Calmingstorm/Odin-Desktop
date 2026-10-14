"""disk-image.sh with stub diskutil/hdiutil on PATH: which tool it runs, with which arguments."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'macos' / 'disk-image.sh'


class DiskImageScriptTests(unittest.TestCase):
    def run_script(self, *args, image_verb=True):
        with tempfile.TemporaryDirectory() as folder:
            bin_dir, log = Path(folder), Path(folder) / 'calls.log'
            # Harmless stubs: they only record their arguments.
            verb = 'exit 0' if image_verb else 'echo "image is not a recognized command" >&2; exit 1'
            (bin_dir / 'diskutil').write_text(
                '#!/bin/sh\n'
                f'if [ "$1 $2 $3" = "image attach --help" ]; then {verb}; fi\n'
                f'echo "diskutil $*" >> "{log}"\n')
            (bin_dir / 'hdiutil').write_text(f'#!/bin/sh\necho "hdiutil $*" >> "{log}"\n')
            for name in ('diskutil', 'hdiutil'):
                (bin_dir / name).chmod(0o755)
            env = dict(os.environ, PATH=f'{bin_dir}:/usr/bin:/bin')
            run = subprocess.run(['/bin/bash', str(SCRIPT), *args], env=env,
                                 capture_output=True, text=True)
            calls = log.read_text().splitlines() if log.exists() else []
            return run, calls

    def test_attach_uses_diskutils_image_verb_where_it_exists(self):
        run, calls = self.run_script('attach', '/tmp/a b.dmg', '/tmp/mount point')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(calls, ['diskutil image attach --readOnly --nobrowse '
                                 '--mountPoint /tmp/mount point /tmp/a b.dmg'])

    def test_attach_falls_back_to_hdiutil_without_it(self):
        run, calls = self.run_script('attach', '/tmp/a.dmg', '/tmp/m', image_verb=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(calls, ['hdiutil attach -nobrowse -readonly -mountpoint /tmp/m /tmp/a.dmg'])

    def test_detach_ejects_with_diskutil(self):
        run, calls = self.run_script('detach', '/tmp/mount point')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(calls, ['diskutil eject /tmp/mount point'])

    def test_wrong_arguments_refuse_without_running_anything(self):
        for args in ((), ('attach', '/tmp/a.dmg'), ('detach',), ('mount', 'x')):
            run, calls = self.run_script(*args)
            self.assertEqual(run.returncode, 2, args)
            self.assertEqual(calls, [], args)


if __name__ == '__main__':
    unittest.main()
