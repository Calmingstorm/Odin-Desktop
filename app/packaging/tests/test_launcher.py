"""Execute the generated launcher from real after-pack through a symlink."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / 'after-pack.cjs'
PROFILE = HOOK.with_name('apparmor-profile')


class LauncherTests(unittest.TestCase):
    def test_apparmor_attachment_covers_executable_in_generated_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / 'install with spaces'
            resources = app / 'resources'
            resources.mkdir(parents=True)
            # A real ELF fixture is renamed by the real hook, just as Electron is.
            shutil.copy2('/bin/true', app / 'odin-desktop')
            chromium_lock = json.loads((HOOK.parent / 'python/chromium.lock.json').read_text())
            headless = resources / 'runtime/browser/chromium' / chromium_lock['chromium']['executable']
            headless.parent.mkdir(parents=True)
            shutil.copy2('/bin/true', headless)
            shutil.copy2(PROFILE, resources / 'apparmor-profile')
            tools = root / 'tools'
            tools.mkdir()
            finalize = tools / 'python3'
            finalize.write_text('#!/bin/sh\nexit 0\n')
            finalize.chmod(0o755)
            environment = {**os.environ, 'PATH': str(tools) + ':' + os.environ['PATH']}
            build = subprocess.run(['node', '-e',
                'require(process.argv[1])({appOutDir:process.argv[2]}).catch(e=>{'
                'console.error(e);process.exit(1)})', str(HOOK), str(app)],
                env=environment, capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            profile = (resources / 'apparmor-profile').read_text()
            attachments = re.findall(r'^profile\s+\S+\s+"([^"]+)"\s+flags=',
                                     profile, re.MULTILINE)
            self.assertEqual(set(attachments), {
                '/opt/odin-desktop/odin-desktop.bin',
                '/opt/odin-desktop/resources/runtime/browser/chromium/' + chromium_lock['chromium']['executable'],
            })
            for attachment in attachments:
                attached = app / Path(attachment).relative_to('/opt/odin-desktop')
                self.assertTrue(attached.is_file(), attachment)
                self.assertTrue(os.access(attached, os.X_OK), attachment)
                # A shell wrapper is not the ELF that needs userns permission.
                self.assertEqual(attached.read_bytes()[:4], b'\x7fELF')
                self.assertEqual(subprocess.run([str(attached)]).returncode, 0)
            self.assertRegex(profile, re.compile(r'^\s+userns,\s*$', re.MULTILINE))

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

    def test_generated_launcher_classifies_only_the_new_managed_install_as_deb(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / 'unpacked'
            (app / 'resources').mkdir(parents=True)
            (app / 'odin-desktop').write_text('original executable fixture')
            tools = root / 'tools'
            tools.mkdir()
            finalize = tools / 'python3'
            finalize.write_text('#!/bin/sh\nexit 0\n')
            finalize.chmod(0o755)
            build = subprocess.run(['node', '-e',
                'require(process.argv[1])({appOutDir:process.argv[2]}).catch(e=>{'
                'console.error(e);process.exit(1)})', str(HOOK), str(app)],
                env={**os.environ, 'PATH': str(tools) + ':' + os.environ['PATH']},
                capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            # Execute the generated shell logic, but intercept its cd/pwd/exec.
            # Virtual /opt paths are only strings: never inspect or launch them.
            harness = ('cd() { :; }; pwd() { printf "%s\\n" "$FIXTURE_ROOT"; }; '
                       'exec() { printf "%s\\n" "$@"; }; . "$1"')
            for install, kind in (
                    ('/opt/odin-desktop', 'deb'), ('/opt/Odin', 'appimage'),
                    ('/opt/odin', 'appimage'), ('/opt/odin-desktop-copy', 'appimage'),
                    ('/tmp/.mount_odin-desktop', 'appimage')):
                with self.subTest(install=install):
                    launch = subprocess.run(['/bin/bash', '-c', harness, str(app / 'odin-desktop'),
                                             str(app / 'odin-desktop')],
                        env={**os.environ, 'FIXTURE_ROOT': install}, capture_output=True, text=True)
                    self.assertEqual(launch.returncode, 0, launch.stderr)
                    self.assertEqual(launch.stdout.splitlines(), [
                        install + '/resources/runtime/python/bin/python3', '-I', '-B',
                        install + '/resources/ownership.py', 'exec', '--kind', kind, '--',
                        install + '/odin-desktop.bin', str(app / 'odin-desktop')])


if __name__ == '__main__':
    unittest.main()
