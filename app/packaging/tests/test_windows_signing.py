"""The release build's signing tools: pinned, hash-checked, unpacked fresh, and set to sign in with
the Azure CLI (GitHub's identity token) only."""
import importlib.util
import io
import json
import re
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('provision_signing', HERE / 'provision-signing.py')
signing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signing)

SETTINGS = {'endpoint': 'https://eus.codesigning.azure.net', 'account': 'Odin',
            'profile': 'OdinDesktop'}
ENV = {'ODIN_SIGNING_ENDPOINT': SETTINGS['endpoint'], 'ODIN_SIGNING_ACCOUNT': 'Odin',
       'ODIN_SIGNING_PROFILE': 'OdinDesktop'}


def package(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


class Packages:
    """Two fake NuGet packages shaped like the pinned ones, and a lock naming them."""

    def __init__(self, root: Path, *, dlib_entries=None):
        self.signtool = package(root / 'buildtools.nupkg', {
            'bin/10.0.26100.0/x64/signtool.exe': b'MZ signtool',
            'bin/10.0.26100.0/x64/en-US/signtool.exe.mui': b'mui',
            'bin/10.0.26100.0/x86/signtool.exe': b'MZ x86, not wanted',
            'build/Microsoft.Windows.SDK.BuildTools.props': b'<Project/>',
        })
        self.dlib = package(root / 'client.nupkg', dlib_entries or {
            'bin/x64/Azure.CodeSigning.Dlib.dll': b'MZ dlib',
            'bin/x64/Azure.Identity.dll': b'MZ identity',
            'bin/x86/Azure.CodeSigning.Dlib.dll': b'MZ x86, not wanted',
        })
        self.lock = {'packages': {
            'signtool': {'package': 'Microsoft.Windows.SDK.BuildTools', 'version': 'test',
                         'size': self.signtool.stat().st_size, 'folder': 'bin/10.0.26100.0/x64',
                         'file': 'signtool.exe', 'url': 'https://example.invalid/a',
                         'sha256': 'a' * 64},
            'dlib': {'package': 'Microsoft.ArtifactSigning.Client', 'version': 'test',
                     'size': self.dlib.stat().st_size, 'folder': 'bin/x64',
                     'file': 'Azure.CodeSigning.Dlib.dll', 'url': 'https://example.invalid/b',
                     'sha256': 'b' * 64},
        }}
        self.asked = []

    def download(self, spec, cache):
        self.asked.append((spec['package'], cache))
        return self.signtool if spec['package'] == 'Microsoft.Windows.SDK.BuildTools' else self.dlib


class SigningTools(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_the_pinned_packages_are_unpacked_with_the_librarys_settings(self):
        packages = Packages(self.root)
        out = self.root / 'signing'
        found = signing.provision(out, self.root / 'cache', SETTINGS, lock=packages.lock,
                                  download=packages.download)
        self.assertEqual(found, {
            'ODIN_SIGNTOOL': str(out / 'signtool' / 'signtool.exe'),
            'ODIN_SIGNING_DLIB': str(out / 'dlib' / 'Azure.CodeSigning.Dlib.dll'),
            'ODIN_SIGNING_METADATA': str(out / 'metadata.json')})
        self.assertEqual([name for name, _ in packages.asked],
                         ['Microsoft.Windows.SDK.BuildTools', 'Microsoft.ArtifactSigning.Client'])
        self.assertEqual((out / 'signtool' / 'signtool.exe').read_bytes(), b'MZ signtool')
        self.assertEqual((out / 'signtool' / 'en-US' / 'signtool.exe.mui').read_bytes(), b'mui')
        # Only the x64 folders: no other architecture, no build metadata.
        unpacked = sorted(p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file())
        self.assertEqual(unpacked, [
            'dlib/Azure.CodeSigning.Dlib.dll', 'dlib/Azure.Identity.dll', 'metadata.json',
            'signtool/en-US/signtool.exe.mui', 'signtool/signtool.exe'])
        metadata = json.loads((out / 'metadata.json').read_text())
        self.assertEqual({key: metadata[key] for key in ('Endpoint', 'CodeSigningAccountName',
                                                         'CertificateProfileName')},
                         {'Endpoint': 'https://eus.codesigning.azure.net',
                          'CodeSigningAccountName': 'Odin',
                          'CertificateProfileName': 'OdinDesktop'})

    def test_only_the_azure_cli_may_sign_in(self):
        excluded = set(signing.EXCLUDED_CREDENTIALS)
        self.assertNotIn('AzureCliCredential', excluded)
        # Every other source DefaultAzureCredential tries, a stored secret's included.
        self.assertEqual(excluded, {
            'EnvironmentCredential', 'WorkloadIdentityCredential', 'ManagedIdentityCredential',
            'SharedTokenCacheCredential', 'VisualStudioCredential', 'VisualStudioCodeCredential',
            'AzurePowerShellCredential', 'AzureDeveloperCliCredential',
            'InteractiveBrowserCredential'})

    def test_refuses_an_unsafe_entry_a_missing_tool_or_other_bytes(self):
        (self.root / 'a').mkdir()
        unsafe = Packages(self.root / 'a', dlib_entries={
            'bin/x64/Azure.CodeSigning.Dlib.dll': b'MZ', 'bin/x64/../../escape.dll': b'MZ'})
        with self.assertRaisesRegex(ValueError, 'Unsafe package entry'):
            signing.provision(self.root / 'a' / 'out', self.root, SETTINGS, lock=unsafe.lock,
                              download=unsafe.download)
        (self.root / 'b').mkdir()
        missing = Packages(self.root / 'b', dlib_entries={'bin/x64/Azure.Identity.dll': b'MZ'})
        with self.assertRaisesRegex(ValueError, 'has no bin/x64/Azure.CodeSigning.Dlib.dll'):
            signing.provision(self.root / 'b' / 'out', self.root, SETTINGS, lock=missing.lock,
                              download=missing.download)
        (self.root / 'c').mkdir()
        resized = Packages(self.root / 'c')
        resized.lock['packages']['signtool']['size'] += 1
        with self.assertRaisesRegex(ValueError, 'not the pinned size'):
            signing.provision(self.root / 'c' / 'out', self.root, SETTINGS, lock=resized.lock,
                              download=resized.download)

    def test_never_unpacks_over_an_earlier_folder(self):
        packages = Packages(self.root)
        (self.root / 'signing').mkdir()
        with self.assertRaises(FileExistsError):
            signing.provision(self.root / 'signing', self.root, SETTINGS, lock=packages.lock,
                              download=packages.download)
        self.assertEqual(packages.asked, [])

    def test_the_account_settings_must_be_present_and_well_formed(self):
        self.assertEqual(signing.settings_from(ENV), SETTINGS)
        for name, value in [('ODIN_SIGNING_ENDPOINT', 'http://eus.codesigning.azure.net'),
                            ('ODIN_SIGNING_ENDPOINT', 'https://example.com'),
                            ('ODIN_SIGNING_ACCOUNT', ''), ('ODIN_SIGNING_PROFILE', 'ab'),
                            ('ODIN_SIGNING_PROFILE', 'Odin Desktop')]:
            with self.subTest(name=name, value=value), self.assertRaisesRegex(ValueError, name):
                signing.settings_from({**ENV, name: value})

    def test_the_command_line_prints_github_env_lines_or_refuses(self):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stderr(errors):
            self.assertEqual(signing.main([], env=ENV), 2)
            self.assertEqual(signing.main([str(self.root / 'out')], env={}), 1)
        self.assertIn('Signing tools refused: ODIN_SIGNING_ENDPOINT', errors.getvalue())
        packages = Packages(self.root)
        original = signing.provision
        signing.provision = lambda out, cache, settings: original(
            out, cache, settings, lock=packages.lock, download=packages.download)
        try:
            with redirect_stdout(output):
                cached = {**ENV, 'ODIN_PACKAGING_CACHE': str(self.root)}
                self.assertEqual(signing.main([str(self.root / 'out')], env=cached), 0)
        finally:
            signing.provision = original
        self.assertEqual([line.split('=', 1)[0] for line in output.getvalue().splitlines()],
                         ['ODIN_SIGNTOOL', 'ODIN_SIGNING_DLIB', 'ODIN_SIGNING_METADATA'])
        self.assertEqual(packages.asked[0][1], self.root / 'signing-tools')


class TheLock(unittest.TestCase):
    def test_both_tools_are_pinned_to_nugets_bytes(self):
        lock = json.loads(signing.LOCK.read_text())
        self.assertEqual(sorted(lock['packages']), ['dlib', 'signtool'])
        for key, item in lock['packages'].items():
            with self.subTest(key=key):
                name, version = item['package'].lower(), item['version']
                self.assertEqual(item['url'], f'https://api.nuget.org/v3-flatcontainer/{name}/{version}/'
                                              f'{name}.{version}.nupkg')
                self.assertRegex(item['sha256'], r'^[0-9a-f]{64}$')
                self.assertIsInstance(item['size'], int)
                self.assertTrue(item['folder'].endswith('x64'))
        self.assertEqual(lock['packages']['dlib']['package'], 'Microsoft.ArtifactSigning.Client')
        self.assertEqual(lock['packages']['dlib']['file'], 'Azure.CodeSigning.Dlib.dll')

    def test_signtool_is_a_version_artifact_signing_supports(self):
        # Microsoft's minimum is 10.0.22621.755, and the 10.0.20348 SDK's SignTool isn't supported.
        item = json.loads(signing.LOCK.read_text())['packages']['signtool']
        version = tuple(int(part) for part in item['version'].split('.'))
        self.assertGreaterEqual(version, (10, 0, 22621, 755))
        self.assertNotEqual(version[:3], (10, 0, 20348))
        self.assertTrue(re.fullmatch(rf'bin/{re.escape(".".join(map(str, version[:3])))}\.0/x64',
                                     item['folder']), item['folder'])


if __name__ == '__main__':
    unittest.main()
