"""P6 Windows sealing and clean-revision provenance refusal tests."""
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seal = load('test_sealing_module', HERE / 'finalize-manifest.py')
build = load('test_build_module', HERE / 'build-runtime.py')


class WindowsSealing(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'runtime').mkdir()
        (self.root / 'runtime/python.exe').write_bytes(b'python-fixture')
        (self.root / 'app.asar').write_bytes(b'asar-fixture')
        self.manifest = self.root / 'bundle-manifest.json'
        self.manifest.write_text(json.dumps({'schema': 1, 'platform': 'win32'}))
        seal.finalize(self.root)

    def test_every_file_and_self_exclusion(self):
        document = json.loads(self.manifest.read_text())
        self.assertEqual([item['path'] for item in document['files']],
                         ['app.asar', 'runtime/python.exe'])
        self.assertTrue(all(item['size'] > 0 and len(item['sha256']) == 64
                            for item in document['files']))
        self.assertEqual(seal.verify_resources(self.root)['files'], 2)

    def test_missing_extra_modified(self):
        original = (self.root / 'app.asar').read_bytes()
        (self.root / 'app.asar').unlink()
        with self.assertRaisesRegex(ValueError, 'missing.*app.asar'):
            seal.verify_resources(self.root)
        (self.root / 'app.asar').write_bytes(original)
        (self.root / 'extra.txt').write_text('unexpected')
        with self.assertRaisesRegex(ValueError, 'extra.*extra.txt'):
            seal.verify_resources(self.root)
        (self.root / 'extra.txt').unlink()
        (self.root / 'app.asar').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'modified.*app.asar'):
            seal.verify_resources(self.root)

    def test_duplicate_manifest(self):
        document = json.loads(self.manifest.read_text())
        document['files'].append(document['files'][0])
        self.manifest.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            seal.verify_resources(self.root)

    def test_release_consumer_refuses_development_provenance(self):
        with self.assertRaisesRegex(ValueError, 'worktree/unbound'):
            seal.verify_resources(self.root, release=True)
        with self.assertRaisesRegex(ValueError, 'worktree/unbound'):
            seal.finalize(self.root, release=True)
        document = json.loads(self.manifest.read_text())
        document['source'] = {'mode': 'release', 'immutable': True}
        self.manifest.write_text(json.dumps(document))
        self.assertEqual(seal.verify_resources(self.root, release=True)['files'], 2)

    @unittest.skipIf(os.name == 'nt', 'Windows symlink privilege not assumed')
    def test_symlink_root_child_and_manifest(self):
        link = self.root / 'runtime/link'
        link.symlink_to('../app.asar')
        with self.assertRaisesRegex(ValueError, 'reparse point'):
            seal.verify_resources(self.root)
        link.unlink()
        root_link = self.root.parent / (self.root.name + '-link')
        root_link.symlink_to(self.root, target_is_directory=True)
        self.addCleanup(root_link.unlink)
        with self.assertRaisesRegex(ValueError, 'reparse point'):
            seal.windows_inventory(root_link)
        document = self.manifest.read_bytes()
        self.manifest.unlink()
        (self.root / 'manifest-source').write_bytes(document)
        self.manifest.symlink_to('manifest-source')
        with self.assertRaisesRegex(ValueError, 'reparse point'):
            seal.verify_resources(self.root)

    def test_non_symlink_reparse_attribute(self):
        info = (self.root / 'app.asar').lstat()
        class Reparse:
            st_mode = info.st_mode
            st_file_attributes = 0x400
        with patch.object(Path, 'lstat', return_value=Reparse()):
            with self.assertRaisesRegex(ValueError, 'reparse point'):
                seal.ordinary_windows_path(self.root / 'app.asar')

    @unittest.skipUnless(os.name == 'nt', 'Native Windows junction qualification')
    def test_native_junction_refused_without_traversal(self):
        outside = self.root.parent / (self.root.name + '-outside')
        outside.mkdir()
        self.addCleanup(outside.rmdir)
        junction = self.root / 'junction'
        subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(junction), str(outside)],
                       check=True, capture_output=True)
        self.addCleanup(lambda: os.rmdir(junction))
        with self.assertRaisesRegex(ValueError, 'reparse point'):
            seal.windows_inventory(self.root)
        self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipIf(os.name == 'nt', 'Windows filesystem prevents creating aliases')
    def test_windows_aliases_and_case_collision(self):
        for name in ['CON.txt', 'file:stream', 'trailing.', 'LPT1', 'COM¹']:
            path = self.root / name
            path.write_bytes(b'x')
            with self.assertRaisesRegex(ValueError, 'Unsafe Windows resource path'):
                seal.windows_inventory(self.root)
            path.unlink()
        (self.root / 'APP.ASAR').write_bytes(b'x')
        with self.assertRaisesRegex(ValueError, 'case collision'):
            seal.windows_inventory(self.root)

    def test_platform_payload_refusals(self):
        # ownership.py is the installed Windows app's guardian too, so Windows ships it.
        seal.assert_platform_resources([{'path': 'ownership.py'}], 'win32')
        windows_forbidden = ['apparmor-profile', 'runtime/helpers/foo',
                             'runtime/python/bin/python3',
                             'runtime/browser/chrome-headless-shell-linux64/chrome',
                             'foo.so', 'wrapper.sh']
        for name in windows_forbidden:
            with self.assertRaisesRegex(ValueError, 'Forbidden win32'):
                seal.assert_platform_resources([{'path': name}], 'win32')
        linux_forbidden = ['tools/curl/curl.exe', 'runtime/foo.dll',
                           'runtime/browser/chrome-headless-shell-win64/chrome.exe']
        for name in linux_forbidden:
            with self.assertRaisesRegex(ValueError, 'Forbidden linux'):
                seal.assert_platform_resources([{'path': name}], 'linux')
        seal.assert_platform_resources(
            [{'path': 'runtime/src/platform/windows_backend.py'}], 'linux')

    def test_linux_pip_exception_is_exact_path_hash_size_only(self):
        sha, size = seal.PIP_LINUX_LAUNCHER_DATA['t64.exe']
        entry = {'path': 'runtime/python/lib/python3.12/site-packages/pip/_vendor/distlib/t64.exe',
                 'sha256': sha, 'size': size}
        seal.assert_platform_resources([entry], 'linux')
        for changed in [{**entry, 'sha256': 'bad'}, {**entry, 'size': size + 1},
                        {**entry, 'path':
                            'runtime/python/lib/python3.12/site-packages/pip/t64.exe'}]:
            with self.assertRaisesRegex(ValueError, 'Forbidden linux'):
                seal.assert_platform_resources([changed], 'linux')


class SourceProvenance(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name) / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        for name in ['src/example.py', 'uv.lock', 'app/package-lock.json']:
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('original')
        self.git('add', '--all')
        self.git('commit', '-qm', 'fixture')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True)

    def test_clean_release_and_dirty_refusal(self):
        record = build.source_record(self.repo, 'release')
        self.assertTrue(record['immutable'])
        (self.repo / 'src/example.py').write_text('dirty')
        with self.assertRaisesRegex(ValueError, 'clean committed revision'):
            build.source_record(self.repo, 'release')
        dev = build.source_record(self.repo, 'worktree')
        self.assertFalse(dev['immutable'])
        self.assertNotEqual(record['source_manifest_sha256'], dev['source_manifest_sha256'])

    def test_git_object_snapshot_not_mutable_worktree(self):
        record = build.source_record(self.repo, 'release')
        (self.repo / 'src/example.py').write_text('changed-after-record')
        with build.immutable_source(self.repo, record, self.repo.parent) as snapshot:
            self.assertEqual((snapshot / 'src/example.py').read_text(), 'original')
            tracked = subprocess.check_output(['git', '-C', str(snapshot), 'ls-files'], text=True)
            self.assertIn('src/example.py', tracked)
            self.assertNotEqual(snapshot, self.repo)
        self.assertFalse(snapshot.exists())

    def test_untracked_development_source_is_bound(self):
        first = build.source_record(self.repo, 'worktree')
        (self.repo / 'src/new.py').write_text('new')
        second = build.source_record(self.repo, 'worktree')
        self.assertNotEqual(first['source_manifest_sha256'], second['source_manifest_sha256'])
        with self.assertRaisesRegex(ValueError, 'clean committed revision'):
            build.source_record(self.repo, 'release')

    def test_release_uses_git_bytes_not_autocrlf_checkout(self):
        (self.repo / 'src/example.py').write_bytes(b'line1\nline2\n')
        self.git('add', '--all')
        self.git('commit', '-qm', 'lines')
        expected = build.source_record(self.repo, 'release')
        self.git('config', 'core.autocrlf', 'true')
        (self.repo / 'src/example.py').unlink()
        self.git('checkout', '--', 'src/example.py')
        self.assertEqual((self.repo / 'src/example.py').read_bytes(), b'line1\r\nline2\r\n')
        self.assertEqual(self.git('status', '--porcelain'), '')
        record = build.source_record(self.repo, 'release')
        self.assertEqual(record, expected)
        with build.immutable_source(self.repo, record, self.repo.parent) as snapshot:
            self.assertEqual((snapshot / 'src/example.py').read_bytes(), b'line1\nline2\n')

    def test_windows_whole_stage_failure_is_unpublished(self):
        target = self.repo.parent / 'resources'
        source = build.source_record(self.repo, 'worktree')
        def fail(stage, *args):
            (stage / 'partial.exe').write_bytes(b'partial')
            raise ValueError('simulated second-lane failure')
        argv = ['build-runtime.py', '--platform', 'win32', '--stage', str(target),
                '--cache', str(self.repo.parent / 'cache')]
        with patch.object(build, 'REPO', self.repo), patch.object(build.sys, 'platform', 'win32'), \
                patch.object(build.sys, 'argv', argv), \
                patch.object(build, 'stage_build', side_effect=fail), \
                patch.object(build, 'source_record', return_value=source):
            with self.assertRaisesRegex(ValueError, 'second-lane'):
                build.main()
        self.assertFalse(target.exists())
        self.assertFalse(list(target.parent.glob('.runtime-stage-*')))

    def test_windows_existing_stage_is_never_mixed(self):
        target = self.repo.parent / 'resources'
        target.mkdir()
        (target / 'old').write_text('old')
        argv = ['build-runtime.py', '--platform', 'win32', '--stage', str(target),
                '--cache', str(self.repo.parent / 'cache')]
        with patch.object(build, 'REPO', self.repo), patch.object(build.sys, 'platform', 'win32'), \
                patch.object(build.sys, 'argv', argv), patch.object(build, 'stage_build') as stage:
            with self.assertRaisesRegex(ValueError, 'stage mixing'):
                build.main()
        stage.assert_not_called()
        self.assertEqual((target / 'old').read_text(), 'old')


class BuilderResourceMappings(unittest.TestCase):
    def test_real_builder_platform_matchers(self):
        repo = HERE.parents[1]
        if not (repo / 'app/node_modules/app-builder-lib/out/fileMatcher.js').exists():
            self.skipTest('Provisioned pinned Electron builder required')
        script = """
const fs = require('fs');
const yaml = require('./app/node_modules/js-yaml');
const {getFileMatchers} = require('./app/node_modules/app-builder-lib/out/fileMatcher');
const config = yaml.load(fs.readFileSync('app/electron-builder.yml','utf8'));
for (const platform of ['linux', 'win']) {
 const matchers = getFileMatchers(config, 'extraResources', process.cwd()+'/fixture/resources', {
  macroExpander:x=>x, customBuildOptions:config[platform] || {},
  globalOutDir:process.cwd()+'/fixture/out', defaultSrc:process.cwd()+'/app'
 });
 const apparmor=matchers.some(x=>x.to.endsWith('apparmor-profile'));
 if(apparmor !== (platform==='linux')) throw Error('apparmor platform mapping failure');
 const tools=matchers.find(x=>x.patterns.includes('tools/**'));
 if(!tools || tools.patterns.length!==1) throw Error('tools matcher not constrained');
}
"""
        result = subprocess.run(['node', '-e', script], cwd=repo, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
