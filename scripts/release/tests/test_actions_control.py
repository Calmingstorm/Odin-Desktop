"""Offline control plane tests. No network or real publication."""

import copy
import hashlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import actions_control as c


def sha(data):
    return hashlib.sha256(data).hexdigest()


class ActionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.calls = []
        self.source = 'a' * 40
        self.files = {
            'odin-desktop-0.1.0-candidate-amd64.deb': b'deb fixture',
            'odin-desktop-0.1.0-candidate-x86_64.AppImage': b'appimage fixture',
            'release-notes.md': b'Fixture notes.\n',
        }
        self.receipt = {
            'schema': 1,
            'repository': c.helper.REPOSITORY,
            'version': '0.1.0',
            'source_commit': self.source,
            'workflow_sha': self.source,
            'run_id': '42',
            'resource_manifest_sha256': 'c' * 64,
            'notes_sha256': sha(self.files['release-notes.md']),
            'builder_command': 'npm run package:candidate',
            'scan': 'p41-credential-signatures-passed',
            'input_hashes': {name: 'd' * 64 for name in c.helper.INPUTS},
            'artifacts': [
                {'name': n, 'bytes': len(d), 'sha256': sha(d)}
                for n, d in self.files.items()
                if n != 'release-notes.md'
            ],
        }
        self.files['candidate-receipt.json'] = json.dumps(self.receipt).encode()
        self.zip = self.make_zip()
        self.approval = {
            k: copy.deepcopy(self.receipt[k])
            for k in (
                'repository',
                'version',
                'source_commit',
                'workflow_sha',
                'run_id',
                'artifacts',
            )
        }
        self.approval.update(
            approved_by='Calmingstorm',
            action='publish-identical-candidate',
            receipt_sha256=sha(self.files['candidate-receipt.json']),
            artifact_id='99',
            artifact_digest='sha256:' + sha(self.zip),
            p45_evidence='https://github.com/Calmingstorm/Odin-Desktop/issues/45',
            p46_evidence='https://github.com/Calmingstorm/Odin-Desktop/issues/46',
        )
        self.env = {
            'GH_TOKEN': 'fixture-token',
            'PATH': '/usr/bin:/bin',
            'CANDIDATE_RUN_ID': '42',
            'CANDIDATE_ARTIFACT_ID': '99',
            'CANDIDATE_ARTIFACT_DIGEST': 'sha256:' + sha(self.zip),
            'EXPECTED_SOURCE_SHA': self.source,
            'EXPECTED_WORKFLOW_SHA': self.source,
            'EXPECTED_RECEIPT_SHA': sha(self.files['candidate-receipt.json']),
            'EXPECTED_VERSION': '0.1.0',
            'APPROVAL_JSON': json.dumps(self.approval),
            'GITHUB_ACTOR': 'Calmingstorm',
            'GITHUB_SHA': self.source,
            'GITHUB_WORKFLOW_SHA': self.source,
            'GITHUB_REF': 'refs/heads/master',
            'GITHUB_EVENT_NAME': 'workflow_dispatch',
            'GITHUB_REPOSITORY': c.helper.REPOSITORY,
            'GITHUB_STEP_SUMMARY': str(self.root / 'summary'),
        }
        self.e = f'{c.BASE}/environments/{c.ENVIRONMENT}'
        self.r = f'{c.BASE}/actions/runs/42'
        self.a = f'{c.BASE}/actions/artifacts/99'
        self.j = self.r + '/attempts/1/jobs?per_page=100&page=1'
        self.p = self.e + '/deployment-branch-policies?per_page=100&page=1'
        self.l = f'{c.BASE}/releases?per_page=100&page=1'
        self.t = f'{c.BASE}/git/ref/tags/v0.1.0'
        self.assets = f'{c.BASE}/releases/88/assets?per_page=100&page=1'
        self.responses = {
            'users/Calmingstorm': {'login': 'Calmingstorm', 'type': 'User', 'id': 123},
            self.e: {
                'id': 77,
                'node_id': 'EN_fixture',
                'name': c.ENVIRONMENT,
                'url': f'https://api.github.com/{self.e}',
                'html_url': f'https://github.com/{c.helper.REPOSITORY}/deployments/activity_log?environments={c.ENVIRONMENT}',
                'created_at': '2026-10-08T00:00:00Z',
                'updated_at': '2026-10-08T00:00:00Z',
                'can_admins_bypass': False,
                'protection_rules': [
                    {
                        'type': 'required_reviewers',
                        'prevent_self_review': False,
                        'reviewers': [
                            {'type': 'User', 'reviewer': {'login': 'Calmingstorm', 'id': 123}}
                        ],
                    }
                ],
                'deployment_branch_policy': {
                    'custom_branch_policies': True,
                    'protected_branches': False,
                },
            },
            self.p: {'branch_policies': [{'name': 'master', 'type': 'branch'}]},
            self.r: {
                'id': 42,
                'run_attempt': 1,
                'status': 'completed',
                'conclusion': 'success',
                'event': 'workflow_dispatch',
                'pull_requests': [],
                'head_sha': self.source,
                'path': c.WORKFLOW,
                'workflow_id': 7,
                'repository': {'id': 10, 'full_name': c.helper.REPOSITORY},
                'head_repository': {'id': 10, 'full_name': c.helper.REPOSITORY},
            },
            f'{c.BASE}/actions/workflows/7': {'id': 7, 'path': c.WORKFLOW},
            self.j: {
                'jobs': [
                    {'name': n, 'status': 'completed', 'conclusion': result}
                    for n, result in [
                        ('Build candidate', 'success'),
                        ('Verify approved candidate', 'skipped'),
                        ('Publish identical approved candidate', 'skipped'),
                    ]
                ]
            },
            self.a: {
                'id': 99,
                'name': 'release-candidate-42',
                'expired': False,
                'size_in_bytes': len(self.zip),
                'digest': 'sha256:' + sha(self.zip),
                'workflow_run': {
                    'id': 42,
                    'head_sha': self.source,
                    'repository_id': 10,
                    'head_repository_id': 10,
                },
            },
            self.l: [],
            self.t: {'object': {'type': 'commit', 'sha': self.source}},
            f'{c.BASE}/releases/tags/v0.1.0': {
                'id': 88,
                'tag_name': 'v0.1.0',
                'draft': False,
                'prerelease': False,
            },
            self.assets: [
                {'name': n, 'size': len(d), 'digest': 'sha256:' + sha(d), 'state': 'uploaded'}
                for n, d in self.files.items()
                if n != 'release-notes.md'
            ],
        }
        # Exercise the actual workflow/API job-name contract, not two copies of
        # our own invented allowlist. A YAML rename must break happy verification.
        workflow = yaml.safe_load((Path(__file__).resolve().parents[3] / c.WORKFLOW).read_text())
        for job, key in zip(self.responses[self.j]['jobs'], ('build', 'verify', 'publish')):
            job['name'] = workflow['jobs'][key]['name']
        env_patch = patch.dict(os.environ, self.env, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        fake_patch = patch.object(c.subprocess, 'Popen', side_effect=self.fake_gh)
        fake_patch.start()
        self.addCleanup(fake_patch.stop)

    def make_zip(self, rename=None, symlink=None, extra=None):
        stream = io.BytesIO()
        with warnings.catch_warnings(), zipfile.ZipFile(stream, 'w') as z:
            warnings.simplefilter('ignore', UserWarning)
            for n, data in self.files.items():
                info = zipfile.ZipInfo(rename.get(n, n) if rename else n)
                info.create_system = 3
                info.external_attr = (
                    (stat.S_IFLNK | 0o777) if n == symlink else (stat.S_IFREG | 0o600)
                ) << 16
                z.writestr(info, data)
            if extra:
                z.writestr(extra, b'extra')
        return stream.getvalue()

    def fake_gh(self, argv, **kwargs):
        self.calls.append(argv)
        env = kwargs['env']
        self.assertEqual(env['GH_HOST'], 'github.com')
        self.assertEqual(env['GH_TOKEN'], 'fixture-token')
        self.assertEqual(env['HOME'], env['GH_CONFIG_DIR'])
        self.assertNotIn('GITHUB_TOKEN', env)
        self.assertNotIn('APPROVAL_JSON', env)
        if argv[1] == 'api':
            self.assertEqual(argv[2:4], ['--method', 'GET'])
            if argv[-1] == self.a + '/zip':
                data = self.zip
            else:
                response = self.responses[argv[-1]]
                if isinstance(response, Exception):
                    raise response
                data = json.dumps(response).encode()
            kwargs['stdout'].write(data)
            kwargs['stdout'].flush()
        else:
            self.assertEqual(argv[:3], ['gh', 'release', 'create'])
        class Process:
            returncode = 0
            def poll(self):
                return self.returncode

            def wait(self):
                return self.returncode

            def kill(self):
                self.returncode = -9
        return Process()

    def run_control(self, action='verify'):
        return c.control(action, self.root / 'fresh')

    def denied(self):
        with self.assertRaises((ValueError, KeyError, TypeError)):
            self.run_control()
        self.assertFalse(any(a[:3] == ['gh', 'release', 'create'] for a in self.calls))
        shutil.rmtree(self.root / 'fresh', ignore_errors=True)

    def test_verify_exact_files_summary(self):
        self.assertEqual(self.run_control(), self.receipt)
        self.assertEqual({p.name for p in (self.root / 'fresh').iterdir()}, set(self.files))
        for n, data in self.files.items():
            self.assertEqual((self.root / 'fresh' / n).read_bytes(), data)
        summary = (self.root / 'summary').read_text()
        for text in (
            self.source,
            self.approval['receipt_sha256'],
            self.approval['artifact_digest'],
            'issues/45',
        ):
            self.assertIn(text, summary)
        self.assertFalse(any(a[1] == 'release' for a in self.calls))

    def test_publish_exact_plan(self):
        self.run_control('publish')
        argv = [a for a in self.calls if a[1] == 'release']
        d = self.root / 'fresh'
        self.assertEqual(
            argv,
            [
                [
                    'gh',
                    'release',
                    'create',
                    'v0.1.0',
                    *(str(d / a['name']) for a in self.receipt['artifacts']),
                    str(d / 'candidate-receipt.json'),
                    '--repo',
                    c.helper.REPOSITORY,
                    '--verify-tag',
                    '--target',
                    self.source,
                    '--title',
                    'Odin Desktop 0.1.0',
                    '--notes-file',
                    str(d / 'release-notes.md'),
                ]
            ],
        )
        self.assertEqual(sum(a[-1] == self.e for a in self.calls), 2)

    def test_dispatch_rejections(self):
        for key, value in [
            ('GITHUB_ACTOR', 'Other'),
            ('GITHUB_EVENT_NAME', 'push'),
            ('GITHUB_REF', 'refs/heads/other'),
            ('GITHUB_REPOSITORY', 'Other/repo'),
            ('GITHUB_SHA', 'b' * 40),
            ('GITHUB_WORKFLOW_SHA', 'b' * 40),
            ('CANDIDATE_ARTIFACT_DIGEST', 'a' * 64),
            ('EXPECTED_VERSION', 'v0.1.0'),
            ('GH_TOKEN', ''),
            ('APPROVAL_JSON', ''),
            ('EXPECTED_RECEIPT_SHA', ''),
            ('GITHUB_STEP_SUMMARY', ''),
        ]:
            with self.subTest(key=key), patch.dict(os.environ, {key: value}):
                self.denied()

    def test_run_rejections(self):
        original = copy.deepcopy(self.responses[self.r])
        for key, value in [
            ('conclusion', 'failure'),
            ('status', 'in_progress'),
            ('run_attempt', 2),
            ('event', 'pull_request'),
            ('pull_requests', [{'number': 1}]),
            ('head_sha', 'b' * 40),
            ('path', 'other.yml'),
            ('repository', {'full_name': 'Other/repo'}),
            ('head_repository', {'full_name': 'Other/repo'}),
        ]:
            self.responses[self.r] = {**original, key: value}
            with self.subTest(key=key):
                self.denied()

    def test_workflow_identity_and_revision(self):
        self.responses[f'{c.BASE}/actions/workflows/7']['path'] = 'other.yml'
        self.denied()
        self.responses[f'{c.BASE}/actions/workflows/7']['path'] = c.WORKFLOW
        with patch.dict(
            os.environ,
            {
                'EXPECTED_WORKFLOW_SHA': 'b' * 40,
                'GITHUB_WORKFLOW_SHA': 'b' * 40,
                'GITHUB_SHA': 'b' * 40,
            },
        ):
            self.denied()

    def test_jobs_skipped_and_successful(self):
        for i, conclusion in ((0, 'failure'), (1, 'success'), (2, 'success')):
            job = self.responses[self.j]['jobs'][i]
            original = job['conclusion']
            job['conclusion'] = conclusion
            self.denied()
            job['conclusion'] = original

    def test_artifact_metadata(self):
        original = copy.deepcopy(self.responses[self.a])
        for key, value in [
            ('id', 100),
            ('expired', True),
            ('name', 'other'),
            ('digest', 'sha256:' + 'e' * 64),
            ('workflow_run', {'id': 43, 'head_sha': self.source}),
            ('size_in_bytes', 0),
        ]:
            self.responses[self.a] = {**original, key: value}
            with self.subTest(key=key):
                self.denied()

    def test_download_hash_mismatch(self):
        self.zip += b'changed'
        self.denied()

    def test_zip_traversal_symlink_duplicate_extra(self):
        n = next(iter(self.files))
        for archive in (
            self.make_zip(rename={n: '../outside'}),
            self.make_zip(rename={n: '/absolute'}),
            self.make_zip(symlink=n),
            self.make_zip(extra=n),
            self.make_zip(extra='extra'),
        ):
            d = self.root / sha(archive)
            d.mkdir()
            with self.assertRaises(ValueError):
                c.extract_candidate(io.BytesIO(archive), d)
            self.assertEqual(list(d.iterdir()), [])

    def test_package_tamper(self):
        self.files[next(iter(self.files))] = b'tamper'
        self.zip = self.make_zip()
        digest = 'sha256:' + sha(self.zip)
        self.responses[self.a]['digest'] = digest
        with patch.dict(os.environ, {'CANDIDATE_ARTIFACT_DIGEST': digest}):
            self.denied()

    def test_approval_and_receipt_hash(self):
        for key, value in [
            ('artifact_id', '100'),
            ('artifact_digest', 'sha256:' + 'f' * 64),
            ('approved_by', 'Other'),
            ('action', 'other'),
            ('p45_evidence', 'https://example.com/'),
        ]:
            with patch.dict(
                os.environ, {'APPROVAL_JSON': json.dumps({**self.approval, key: value})}
            ):
                self.denied()
        with patch.dict(os.environ, {'EXPECTED_RECEIPT_SHA': 'f' * 64}):
            self.denied()

    def test_unset_unprotected_environment(self):
        original = copy.deepcopy(self.responses[self.e])
        for env in (
            {},
            {**original, 'can_admins_bypass': True},
            {k: v for k, v in original.items() if k != 'can_admins_bypass'},
            {**original, 'protection_rules': []},
            {**original, 'deployment_branch_policy': None},
        ):
            self.responses[self.e] = env
            self.denied()
        self.responses[self.e] = copy.deepcopy(original)
        for key, value in [
            ('prevent_self_review', True),
            ('reviewers', []),
            ('reviewers', [{'type': 'User', 'reviewer': {'login': 'Calmingstorm', 'id': 456}}]),
        ]:
            rule = copy.deepcopy(original['protection_rules'][0])
            rule[key] = value
            self.responses[self.e]['protection_rules'] = [rule]
            self.denied()

    def test_admin_bypass_requires_literal_false_from_api(self):
        original = copy.deepcopy(self.responses[self.e])
        result = c.audit_environment()
        self.assertTrue(result['prevent_admin_bypass'])  # Internal receipt, not an API field.
        for value in (True, None, 0, 1, 'false', '', [], {}):
            with self.subTest(value=value):
                self.responses[self.e] = {**original, 'can_admins_bypass': value}
                with self.assertRaisesRegex(ValueError, 'admin bypass protection absent'):
                    c.audit_environment()
        self.responses[self.e] = {
            k: v for k, v in original.items() if k != 'can_admins_bypass'
        }
        self.responses[self.e]['prevent_admin_bypass'] = True
        with self.assertRaisesRegex(ValueError, 'admin bypass protection absent'):
            c.audit_environment()

    def test_environment_branches(self):
        for policies in (
            [],
            [{'name': 'master', 'type': 'tag'}],
            [{'name': '*', 'type': 'branch'}],
            [{'name': 'master', 'type': 'branch'}, {'name': 'v*', 'type': 'tag'}],
        ):
            self.responses[self.p] = {'branch_policies': policies}
            self.denied()

    def test_existing_release_api_error_and_tag_mismatch(self):
        self.responses[self.l] = [{'tag_name': 'v0.1.0'}]
        self.denied()
        self.responses[self.l] = ValueError('fixture API failure')
        self.denied()
        self.responses[self.l] = []
        self.responses[self.t]['object']['sha'] = 'b' * 40
        self.denied()

    def test_recursive_tag_push_candidate(self):
        self.responses[self.r].update(event='push', head_branch='v0.1.0')
        self.responses[self.t] = {'object': {'type': 'tag', 'sha': 'b' * 40}}
        self.responses[f'{c.BASE}/git/tags/{"b" * 40}'] = {
            'sha': 'b' * 40,
            'object': {'type': 'tag', 'sha': 'c' * 40},
        }
        self.responses[f'{c.BASE}/git/tags/{"c" * 40}'] = {
            'sha': 'c' * 40,
            'object': {'type': 'commit', 'sha': self.source},
        }
        self.run_control()

    def test_non_tag_push(self):
        self.responses[self.r].update(event='push', head_branch='master')
        self.denied()

    def test_post_publish_mismatch_no_retry(self):
        self.responses[self.assets][0]['digest'] = None
        with self.assertRaises(ValueError):
            self.run_control('publish')
        self.assertEqual(sum(a[1] == 'release' for a in self.calls), 1)

    def test_partial_publication_no_retry(self):
        original = self.fake_gh

        def fail(argv, **kwargs):
            p = original(argv, **kwargs)
            if argv[1] == 'release':
                p.returncode = 1
            return p

        with patch.object(c.subprocess, 'Popen', side_effect=fail):
            with self.assertRaises(ValueError):
                self.run_control('publish')
        self.assertEqual(sum(a[1] == 'release' for a in self.calls), 1)

    def test_bounds_duplicate_json_fresh_directory(self):
        with self.assertRaises(ValueError):
            c.parse_json('{"id":1,"id":2}')
        with patch.object(c, 'JSON_LIMIT', 2):
            with self.assertRaises(ValueError):
                c.api('users/Calmingstorm')
        (self.root / 'fresh').mkdir()
        self.denied()

    def test_cli_verify_and_publish(self):
        for action in ('verify', 'publish'):
            with (
                patch.object(
                    sys,
                    'argv',
                    ['actions_control.py', action, '--directory', str(self.root / 'fresh')],
                ),
                patch('builtins.print') as printed,
            ):
                c.main()
                self.assertEqual(printed.call_count, 1)
            shutil.rmtree(self.root / 'fresh')

    def test_environment_api_error_is_not_auto_creation(self):
        self.responses[self.e] = ValueError('environment API denied or absent')
        self.denied()
        self.assertTrue(all(a[1] == 'api' and a[2:4] == ['--method', 'GET'] for a in self.calls))

    def test_second_publish_environment_audit_denies_drift(self):
        original = self.fake_gh
        count = 0
        def drift(argv, **kwargs):
            nonlocal count
            if argv[-1] == self.e:
                count += 1
                if count == 2:
                    self.responses[self.e]['can_admins_bypass'] = True
            return original(argv, **kwargs)

        with patch.object(c.subprocess, 'Popen', side_effect=drift):
            with self.assertRaises(ValueError):
                self.run_control('publish')
        self.assertEqual(count, 2)
        self.assertFalse(any(a[1] == 'release' for a in self.calls))

    def test_execute_timeout_terminates_without_retry(self):
        class Hanging:
            returncode = None
            killed = False

            def poll(self):
                return self.returncode

            def kill(self):
                self.killed = True
                self.returncode = -9

            def wait(self):
                return self.returncode

        process = Hanging()
        with (
            patch.object(c.subprocess, 'Popen', return_value=process) as popen,
            patch.object(c.time, 'monotonic', side_effect=[0, 2]),
        ):
            with self.assertRaisesRegex(ValueError, 'timeout'):
                c.execute(['gh', 'api', 'fixture'], timeout=1)
        self.assertTrue(process.killed)
        self.assertEqual(popen.call_count, 1)


if __name__ == '__main__':
    unittest.main()
