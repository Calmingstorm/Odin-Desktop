"""Execute the real helper with inert command/dialog fixtures and temporary sysctls.

No Electron, GUI, candidate package, or host sysctl is executed/changed.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / 'ownership.py'
DRIVER = '''
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location('ownership_test', sys.argv[1])
own = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = own
spec.loader.exec_module(own)
root = pathlib.Path(sys.argv[2])
if sys.argv[3] == 'deb':
    own.DEB_ROOT = root / 'deb-lease'
    own.DEB_ROOT.mkdir()
    (own.DEB_ROOT / 'lease').touch(mode=0o600)
if sys.argv[4] == 'dialog':
    original = own._show_appimage_refusal
    own._show_appimage_refusal = lambda reason: original(reason, dialog=root / 'zenity')
raise SystemExit(own.main(sys.argv[5:], sysctl_root=root / 'sysctl'))
'''


class AppImagePreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sysctl = self.root / 'sysctl'
        self.sysctl.mkdir()
        self.marker = self.root / 'executed.json'
        self.command = [sys.executable, '-I', '-B', '-c',
                        'import json,pathlib,sys; '
                        'pathlib.Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:])); '
                        'sys.exit(23)', str(self.marker), 'argument with spaces', '--exit']
        self.env = {**os.environ, 'HOME': str(self.root / 'home'),
                    'XDG_STATE_HOME': str(self.root / 'state'),
                    'DISPLAY': '', 'WAYLAND_DISPLAY': ''}

    def tearDown(self):
        self.temp.cleanup()

    def policy(self, relative, value):
        path = self.sysctl / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def launch(self, kind='appimage', dialog=False, extra=()):
        return subprocess.run([sys.executable, '-I', '-B', '-c', DRIVER,
                               str(MODULE), str(self.root), kind,
                               'dialog' if dialog else 'none', 'exec', '--kind', kind,
                               *extra, '--', *self.command], env=self.env,
                              capture_output=True, text=True, timeout=10)

    def assert_refused(self, result):
        self.assertEqual(result.returncode, 78, result.stderr)
        self.assertIn('Install the Odin Desktop .deb package instead.', result.stderr)
        self.assertIn('Electron was not started.', result.stderr)
        self.assertIn('Do not disable the Chromium sandbox', result.stderr)
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.root / 'state').exists())

    def test_restricted_policies_refuse_before_command_or_lease(self):
        for relative, value in (
            ('kernel/apparmor_restrict_unprivileged_userns', '1\n'),
            ('kernel/unprivileged_userns_clone', '0\n'),
            ('user/max_user_namespaces', '0\n'),
            ('user/max_user_namespaces', '-1\n'),
        ):
            with self.subTest(policy=relative, value=value):
                self.policy(relative, value)
                result = self.launch()
                self.assert_refused(result)
                self.assertIn(relative, result.stderr)
                (self.sysctl / relative).unlink()

    def test_malformed_or_unreadable_policy_fails_closed(self):
        path = self.sysctl / 'kernel/apparmor_restrict_unprivileged_userns'
        self.policy('kernel/apparmor_restrict_unprivileged_userns', 'not-an-integer')
        self.assert_refused(self.launch())
        path.unlink()
        path.mkdir()  # EISDIR remains deterministic for a real-root test runner.
        self.assert_refused(self.launch())

    def test_unrestricted_policies_preserve_command_arguments_and_status(self):
        for relative, value in (
            ('kernel/apparmor_restrict_unprivileged_userns', '0\n'),
            ('kernel/unprivileged_userns_clone', '1\n'),
            ('user/max_user_namespaces', '123\n'),
        ):
            self.policy(relative, value)
        result = self.launch()
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(json.loads(self.marker.read_text()), ['argument with spaces', '--exit'])
        self.assertEqual(list((self.root / 'state/odin-desktop/install-ownership/appimage/receipts').iterdir()), [])

    def test_absent_optional_sysctls_do_not_block_launch(self):
        result = self.launch()
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertTrue(self.marker.exists())

    @unittest.skipUnless(os.getuid() == 0, 'Deb lease fixture requires real root ownership')
    def test_deb_bypasses_appimage_policy(self):
        self.policy('kernel/apparmor_restrict_unprivileged_userns', '1\n')
        result = self.launch(kind='deb')
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertTrue(self.marker.exists())
        self.assertNotIn('cannot start safely', result.stderr)

    def test_environment_cannot_override_preflight(self):
        self.policy('kernel/apparmor_restrict_unprivileged_userns', '1\n')
        self.env.update({'ODIN_SYSCTL_ROOT': str(self.root / 'missing'),
                         'ODIN_DESKTOP_SKIP_SANDBOX_CHECK': '1',
                         'APPIMAGE': '', 'ELECTRON_DISABLE_SANDBOX': '1'})
        self.assert_refused(self.launch())

    def test_no_command_line_sysctl_override(self):
        result = self.launch(extra=('--sysctl-root', str(self.root / 'missing')))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('unrecognized arguments', result.stderr)
        self.assertFalse(self.marker.exists())

    def test_dialog_arguments_use_plain_text_without_running_candidate(self):
        self.policy('kernel/apparmor_restrict_unprivileged_userns', '1\n')
        dialog = self.root / 'zenity'
        dialog.write_text('#!' + sys.executable + '\nimport json,pathlib,sys\n'
                          'pathlib.Path(__file__).with_name("dialog.json").write_text(json.dumps(sys.argv[1:]))\n')
        dialog.chmod(0o755)
        self.env['DISPLAY'] = ':test-only'
        self.assert_refused(self.launch(dialog=True))
        arguments = json.loads((self.root / 'dialog.json').read_text())
        self.assertIn('--error', arguments)
        self.assertIn('--no-markup', arguments)
        self.assertIn('--timeout=15', arguments)
        self.assertTrue(any(arg.startswith('--text=') and '.deb' in arg for arg in arguments))

    def test_missing_dialog_keeps_stderr_failure(self):
        self.policy('kernel/apparmor_restrict_unprivileged_userns', '1\n')
        self.env['WAYLAND_DISPLAY'] = 'test-only'
        self.assert_refused(self.launch(dialog=True))


if __name__ == '__main__':
    unittest.main()
