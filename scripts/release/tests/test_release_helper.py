import copy
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('release_helper', Path(__file__).parents[1] / 'release_helper.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        artifacts = []
        for arch, extension in [('amd64', 'deb'), ('x86_64', 'AppImage')]:
            name = f'odin-desktop-0.1.0-candidate-{arch}.{extension}'
            (self.root / name).write_bytes(b'harmless package fixture ' + extension.encode())
            artifacts.append({'name': name, 'bytes': (self.root / name).stat().st_size, 'sha256': r.digest(self.root / name)})
        (self.root / 'release-notes.md').write_text('Curated notes\n')
        self.receipt = {'schema': 1, 'repository': r.REPOSITORY, 'version': '0.1.0',
            'source_commit': 'a' * 40, 'workflow_sha': 'b' * 40, 'run_id': '123',
            'builder_command': 'npm run package:candidate', 'resource_manifest_sha256': 'c' * 64,
            'notes_sha256': r.digest(self.root / 'release-notes.md'),
            'input_hashes': {name: 'd' * 64 for name in r.INPUTS},
            'scan': 'p41-credential-signatures-passed', 'artifacts': artifacts}
        (self.root / 'candidate-receipt.json').write_text(json.dumps(self.receipt))
        self.approval = {key: copy.deepcopy(self.receipt[key]) for key in
                         ('repository', 'version', 'source_commit', 'workflow_sha', 'run_id', 'artifacts')}
        self.approval.update(action='publish-identical-candidate', approved_by='Calmingstorm',
            receipt_sha256=r.digest(self.root / 'candidate-receipt.json'),
            p45_evidence='https://github.com/Calmingstorm/Odin-Desktop/issues/45',
            p46_evidence='https://github.com/Calmingstorm/Odin-Desktop/issues/46')

    def test_exact_notes(self):
        self.assertEqual(r.release_notes('## [0.1.0] - 2026-10-06\nReal notes\n## [0.2.0]\nOther', '0.1.0'), 'Real notes\n')
        for notes in ['## [0.1.00]\nWrong', '## [0.1.0]\n<!-- empty -->',
                      '## [0.1.0]\n\n', '## [0.1.0]\nFirst\n## [0.1.0]\nDuplicate']:
            with self.subTest(notes=notes), self.assertRaises(ValueError):
                r.release_notes(notes, '0.1.0')

    def test_versions(self):
        lock = {'version': '0.1.0', 'packages': {'': {'version': '0.1.0'}}}
        self.assertEqual(r.versions({'version': '0.1.0'}, lock, 'v0.1.0'), '0.1.0')
        for version, tag in [('0.1.0', 'v0.2.0'), ('0.1.0-beta', None), ('01.1.0', None)]:
            with self.subTest(version=version), self.assertRaises(ValueError):
                r.versions({'version': version}, lock, tag)
        lock['packages']['']['version'] = '0.2.0'
        with self.assertRaises(ValueError):
            r.versions({'version': '0.1.0'}, lock)

    def test_both_formats_and_provenance(self):
        for field, value in [('artifacts', self.receipt['artifacts'][:1]), ('scan', ''),
                             ('source_commit', 'not-sha'), ('repository', 'foreign/repo')]:
            receipt = copy.deepcopy(self.receipt)
            receipt[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                r.validate_receipt(receipt)

    def test_exact_approval_and_gates(self):
        receipt_hash = r.digest(self.root / 'candidate-receipt.json')
        self.assertTrue(r.validate_approval(self.receipt, self.approval, receipt_hash, 'Calmingstorm'))
        for key, value in [('source_commit', 'f' * 40), ('run_id', '124'), ('action', 'build'),
                           ('p45_evidence', ''), ('p46_evidence', 'https://elsewhere.invalid/46'),
                           ('receipt_sha256', '0' * 64), ('artifacts', [])]:
            approval = copy.deepcopy(self.approval)
            approval[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                r.validate_approval(self.receipt, approval, receipt_hash, 'Calmingstorm')
        with self.assertRaises(ValueError):
            r.validate_approval(self.receipt, self.approval, receipt_hash, 'someone-else')

    def test_plan_no_network_identical_bytes(self):
        approval = self.root / 'approval.json'
        approval.write_text(json.dumps(self.approval))
        with patch('subprocess.run', side_effect=AssertionError('network/process attempted')):
            argv = r.publication_plan(self.root, approval, 'Calmingstorm', 'v0.1.0', 'a' * 40)
        self.assertEqual(argv[:4], ['gh', 'release', 'create', 'v0.1.0'])
        self.assertIn(str(self.root / self.receipt['artifacts'][0]['name']), argv)
        with self.assertRaises(ValueError):
            r.publication_plan(self.root, approval, 'Calmingstorm', 'v0.1.0', 'b' * 40)
        (self.root / self.receipt['artifacts'][0]['name']).write_bytes(b'changed')
        with self.assertRaises(ValueError):
            r.publication_plan(self.root, approval, 'Calmingstorm', 'v0.1.0', 'a' * 40)

    def test_notes_and_symlinks(self):
        (self.root / 'release-notes.md').write_text('changed')
        with self.assertRaises(ValueError):
            r.validate_files(self.root, self.receipt)
        (self.root / 'release-notes.md').unlink()
        target = self.root / 'elsewhere'
        target.write_text('Curated notes\n')
        (self.root / 'release-notes.md').symlink_to(target)
        with self.assertRaises(ValueError):
            r.validate_files(self.root, self.receipt)

    def test_manifest_provenance(self):
        inputs = self.receipt['input_hashes']
        manifest = {'schema': 1, 'product': {'name': 'odin-desktop', 'version': '0.1.0'},
            'source': {'commit': 'a' * 40, 'uv_lock_sha256': inputs['uv.lock'], 'npm_lock_sha256': inputs['app/package-lock.json']}}
        r.validate_manifest(manifest, 'a' * 40, '0.1.0', inputs)
        manifest['source']['commit'] = 'b' * 40
        with self.assertRaises(ValueError):
            r.validate_manifest(manifest, 'a' * 40, '0.1.0', inputs)

    def test_embedded_product(self):
        package = json.dumps({'name': 'odin-desktop', 'version': '0.1.0'}).encode()
        tree = json.dumps({'files': {'package.json': {'size': len(package), 'offset': '0'}}}).encode()
        pickle_size = 8 + len(tree)
        archive = self.root / 'app.asar'
        archive.write_bytes(struct.pack('<4I', 4, pickle_size, pickle_size - 4, len(tree)) + tree + package)
        self.assertEqual(r.asar_product(archive)['version'], '0.1.0')
        archive.write_bytes(b'invalid')
        with self.assertRaises(ValueError):
            r.asar_product(archive)

    def test_duplicate_json(self):
        path = self.root / 'duplicate.json'
        path.write_text('{"version":"0.1.0","version":"0.2.0"}')
        with self.assertRaises(ValueError):
            r.load_json(path)


if __name__ == '__main__':
    unittest.main()
