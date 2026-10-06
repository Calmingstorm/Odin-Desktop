"""Execute the generated launcher from real after-pack through a symlink."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / 'after-pack.cjs'


class LauncherTests(unittest.TestCase):
    def test_symlink_launcher_resolves_install_and_preserves_argv(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / 'install with spaces'
            app.mkdir()
            (app / 'odin-desktop').write_text('original executable fixture')
            python = app / 'resources/runtime/python/bin/python3'
            python.parent.mkdir(parents=True)
            python.write_text('#!/usr/bin/python3\nimport json,sys\n'
                              'print(json.dumps(sys.argv[1:]))\n')
            python.chmod(0o755)
            tools = root / 'tools'
            tools.mkdir()
            # Real hook generates the wrapper; only manifest finalization is stubbed.
            finalize = tools / 'python3'
            finalize.write_text('#!/bin/sh\nexit 0\n')
            finalize.chmod(0o755)
            environment = {**os.environ, 'PATH': str(tools) + ':' + os.environ['PATH']}
            build = subprocess.run(['node', '-e',
                'require(process.argv[1])({appOutDir:process.argv[2]}).catch(e=>{'
                'console.error(e);process.exit(1)})', str(HOOK), str(app)],
                env=environment, capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            link = root / 'desktop-launcher'
            link.symlink_to(app / 'odin-desktop')
            launch = subprocess.run([str(link), '--exit', 'argument with spaces'],
                                    capture_output=True, text=True)
            self.assertEqual(launch.returncode, 0, launch.stderr)
            args = json.loads(launch.stdout)
            self.assertEqual(args, ['-I', '-B', str(app / 'resources/ownership.py'),
                'exec', '--kind', 'appimage', '--', str(app / 'odin-desktop.bin'),
                '--exit', 'argument with spaces'])


if __name__ == '__main__':
    unittest.main()
