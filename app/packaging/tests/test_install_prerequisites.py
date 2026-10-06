"""Disposable dpkg hook prerequisites, distinct from candidate runtime Python."""
import importlib.util
import json
import os
from pathlib import Path
import pwd
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qualify
from test_qualification import require_namespace, require_real_root, require_tools


class InstallPrerequisiteBehaviour(unittest.TestCase):
    def test_missing_interpreter_fails_before_candidate_execution(self):
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(Path, 'is_file', return_value=False), \
                mock.patch.object(qualify, 'run') as execute:
            with self.assertRaisesRegex(qualify.QualificationError, 'python3'):
                qualify.stage_install_python(Path(temporary))
            execute.assert_not_called()

    def test_missing_minimal_stdlib_package_fails_clearly(self):
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(qualify, 'run', side_effect=[
                    json.dumps({'version': '3.12', 'stdlib': '/usr/lib/python3.12'}),
                    qualify.QualificationError('package libpython3.12-minimal is not installed')]):
            with self.assertRaisesRegex(qualify.QualificationError, 'prerequisite unavailable.*libpython3.12-minimal'):
                qualify.stage_install_python(Path(temporary))

    def test_incomplete_minimal_stdlib_fails_clearly(self):
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(qualify, 'run', side_effect=[
                    json.dumps({'version': '3.12', 'stdlib': '/usr/lib/python3.12'}),
                    '/usr/lib/python3.12/os.py\n']):
            with self.assertRaisesRegex(qualify.QualificationError, 'incomplete minimal stdlib'):
                qualify.stage_install_python(Path(temporary))

    def test_missing_elf_library_fails_clearly(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / 'tool'
            binary.write_bytes(b'fixture executable')
            binary.chmod(0o755)
            with mock.patch.object(qualify, 'run', return_value='libmissing.so => not found\n'):
                with self.assertRaisesRegex(qualify.QualificationError, 'ELF prerequisite missing'):
                    qualify.copy_install_elf(binary, root / 'root', 'bin/tool')

    def test_missing_full_stdlib_fails_clearly(self):
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(qualify, 'run', side_effect=[
                    json.dumps({'version': '3.12', 'stdlib': '/usr/lib/python3.12'}),
                    '/usr/lib/python3.12/os.py\n/usr/lib/python3.12/encodings/__init__.py\n',
                    qualify.QualificationError('package libpython3.12-stdlib is not installed')]):
            with self.assertRaisesRegex(qualify.QualificationError, 'prerequisite unavailable.*libpython3.12-stdlib'):
                qualify.stage_install_python(Path(temporary))

    def test_production_predependency_includes_hook_json(self):
        builder = Path(qualify.__file__).parents[1] / 'electron-builder.yml'
        text = builder.read_text()
        self.assertIn('    - --deb-pre-depends\n    - python3\n', text)
        self.assertNotIn('python3-minimal', text)

    def test_real_distro_staging_excludes_host_configuration_and_site_packages(self):
        require_tools(self, 'dpkg-query', 'ldd')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staged = qualify.stage_install_python(root)
            self.assertEqual((root / 'usr/bin/python3').read_bytes(), Path('/usr/bin/python3').read_bytes())
            self.assertIn(root / 'usr/bin/python3', staged)
            self.assertTrue(list(root.glob('usr/lib/python*/encodings/__init__.py')))
            self.assertFalse(list(root.rglob('sitecustomize.py')))
            self.assertFalse(list(root.rglob('site-packages')))
            self.assertFalse(list(root.rglob('dist-packages')))
            self.assertFalse(list(root.rglob('*.pyc')))
            self.assertFalse(list(root.rglob('*.pth')))

    def test_generated_python_hooks_install_and_export_without_host_python(self):
        require_tools(self, 'dpkg', 'dpkg-deb', 'dpkg-query', 'bwrap', 'ldd', 'chroot',
                      'bash', 'sh', 'ln', 'chmod', 'readlink', 'unshare', 'update-alternatives', 'chown')
        require_real_root(self)
        namespace = require_namespace(self)
        account = pwd.getpwuid(os.getuid())
        here = Path(qualify.__file__).parent
        spec = importlib.util.spec_from_file_location('install_test_deb_control', here / 'build-deb-control.py')
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            package = base / 'package'
            control = package / 'DEBIAN'
            build.generate(control)
            control.joinpath('control').write_text(
                'Package: odin-desktop\nVersion: 0.0.0\nArchitecture: all\n'
                'Maintainer: test <test@example.invalid>\nPre-Depends: python3\n'
                'Description: disposable Python hook prerequisite test\n')
            package.joinpath('opt/Odin/resources').mkdir(parents=True)
            for directory in [package / 'opt', package / 'opt/Odin', package / 'opt/Odin/resources']:
                directory.chmod(0o755)
            package.joinpath('opt/Odin/odin-desktop').write_text('non-executable fixture payload')
            package.joinpath('opt/Odin/resources/apparmor-profile').write_text(
                'profile odin-desktop /opt/Odin/odin-desktop { userns, }\n')
            package.joinpath('opt/Odin/resources/apparmor-profile').chmod(0o644)
            # Trace hook execution without replacing the generated Python hooks.
            preinst = control / 'preinst'
            preinst.write_text(preinst.read_text().replace('set -eu\n', 'set -eu\nprintf preinst > /hook-proof\n'))
            deb, installed = base / 'candidate.deb', base / 'installed'
            qualify.run(['dpkg-deb', '--root-owner-group', '--build', str(package), str(deb)])
            log = qualify.install_deb(deb, package, installed, account.pw_name)
            self.assertIn('Setting up odin-desktop', log)
            self.assertEqual(installed.joinpath('hook-proof').read_text(), 'preinst')
            self.assertTrue(installed.joinpath('var/lib/odin-desktop/package-ownership/lease').is_file())
            self.assertFalse(installed.joinpath('var/lib/odin-desktop/package-ownership/transaction.json').exists())
            self.assertEqual(os.readlink(installed / 'usr/bin/odin-desktop'), '/opt/Odin/odin-desktop')
            self.assertIn('Status: install ok installed', installed.joinpath('var/lib/dpkg/status').read_text())
            self.assertFalse(installed.joinpath('usr/bin/python3').exists())
            self.assertFalse(list(installed.rglob('*.py')))
            self.assertFalse(list(installed.rglob('libpython*.so*')))
            # The unchanged runtime sandbox hides host Python and the exported
            # tree does not offer a second path to the install-only interpreter.
            profile = base / 'profile'
            profile.mkdir()
            text = qualify.run(qualify.sandbox(installed, profile, account.pw_name,
                ['/bin/sh', '-ec', 'test ! -x /usr/bin/python3; '
                 'test ! -e /usr/local/bin/python3; '
                 'test ! -e "/candidate with spaces/usr/bin/python3"; echo runtime-python-hidden'],
                user_namespace=namespace))
            self.assertIn('runtime-python-hidden', text)


if __name__ == '__main__':
    unittest.main()
