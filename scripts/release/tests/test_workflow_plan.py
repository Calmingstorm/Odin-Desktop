"""Execute actual YAML shell/env/conditions with fake builds. Not an Actions emulator."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[3]
# The candidate entry validates against the real product version, so the fixture must follow it.
VERSION = json.loads((ROOT / 'app/package.json').read_text())['version']
sys.path.insert(0, str(ROOT / 'scripts/release'))
from workflow_entry import candidate_arguments  # noqa: E402 - isolated script module path


def expression(source, context):
    # Limited declarative vocabulary used by the actual workflow, not arbitrary YAML.
    source = source.removeprefix('${{').removesuffix('}}').strip()
    source = source.replace('&&', ' and ').replace('||', ' or ')
    return eval(source, {'__builtins__': {}, 'startsWith': lambda s, p: s.startswith(p)}, context)


class WorkflowPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text())

    def context(
        self,
        mode='dry-run',
        event='workflow_dispatch',
        actor='Calmingstorm',
        ref='refs/heads/master',
        repo='Calmingstorm/Odin-Desktop',
    ):
        return {
            'github': SimpleNamespace(
                repository=repo,
                event_name=event,
                actor=actor,
                ref=ref,
                sha='a' * 40,
                workflow_sha='a' * 40,
                run_id='123',
                run_attempt='1',
            ),
            'inputs': SimpleNamespace(mode=mode, version=VERSION),
            'needs': SimpleNamespace(verify=SimpleNamespace(result='success')),
            'steps': SimpleNamespace(retain=SimpleNamespace(outcome='skipped')),
        }

    def jobs(self, ctx):
        return [key for key, job in self.workflow['jobs'].items() if expression(job['if'], ctx)]

    def test_plan_denies_publication_by_default_and_tags(self):
        trigger = self.workflow.get('on', self.workflow.get(True))  # PyYAML YAML1.1 boolean key.
        self.assertEqual(
            self.jobs(self.context(mode=trigger['workflow_dispatch']['inputs']['mode']['default'])),
            ['build'],
        )
        tag_push = self.context(event='push', ref=f'refs/tags/v{VERSION}')
        self.assertEqual(self.jobs(tag_push), ['build'])
        self.assertEqual(self.jobs(self.context(mode='retain-candidate')), ['build'])
        for ctx in [
            self.context(repo='foreign/repo'),
            self.context(event='pull_request'),
            self.context(event='push', actor='other', ref=f'refs/tags/v{VERSION}'),
            self.context(mode='retain-candidate', actor='other'),
            self.context(ref='refs/heads/unreviewed'),
            self.context(mode='publish-approved', actor='other'),
            self.context(mode='publish-approved', ref='refs/heads/unreviewed'),
        ]:
            self.assertEqual(self.jobs(ctx), [])
        self.assertEqual(self.jobs(self.context(actor='other')), ['build'])
        self.assertEqual(self.jobs(self.context(mode='publish-approved')), ['verify', 'publish'])
        failed = self.context(mode='publish-approved')
        failed['needs'].verify.result = 'failure'
        self.assertEqual(self.jobs(failed), ['verify'])

    def test_fake_upload_action_not_called_for_dry_run(self):
        upload = next(s for s in self.workflow['jobs']['build']['steps'] if s.get('id') == 'retain')
        calls = [
            mode
            for mode in ['dry-run', 'retain-candidate']
            if expression(upload['if'], self.context(mode=mode))
        ]
        self.assertEqual(calls, ['retain-candidate'])
        self.assertFalse(
            expression(
                upload['if'], self.context(event='push', actor='other', ref=f'refs/tags/v{VERSION}')
            )
        )

    def test_actual_yaml_shell_runs_candidate_entry(self):
        step = next(
            s
            for s in self.workflow['jobs']['build']['steps']
            if 'workflow_entry.py' in s.get('run', '')
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'scripts/release').mkdir(parents=True)
            (root / 'app').mkdir()
            for name in ['workflow_entry.py', 'release_helper.py']:
                shutil.copyfile(ROOT / 'scripts/release' / name, root / 'scripts/release' / name)
            for name in ['package.json', 'package-lock.json']:
                shutil.copyfile(ROOT / 'app' / name, root / 'app' / name)
            binary = root / 'bin'
            binary.mkdir()
            node = binary / 'node'
            node.write_text(
                '#!/usr/bin/python3\nimport sys,json,pathlib\n'
                'with open("calls.jsonl","a") as out: out.write(json.dumps(sys.argv[1:])+"\\n")\n'
                'if "scripts/release/rehearse.mjs" in sys.argv:\n'
                ' p=pathlib.Path("release-output");p.mkdir();'
                '(p/"candidate-receipt.json").write_text("{}")\n'
            )
            node.chmod(0o755)
            ctx = self.context()
            env = {
                'PATH': str(binary) + ':' + os.environ['PATH'],
                'GITHUB_REPOSITORY': 'Calmingstorm/Odin-Desktop',
            }
            env.update({
                key: str(expression(value, ctx)) if key != 'UV_PYTHON_DOWNLOADS' else value
                for key, value in step['env'].items()
            })
            result = subprocess.run(
                ['bash', '-e', '-c', step['run']],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = [json.loads(line) for line in (root / 'calls.jsonl').read_text().splitlines()]
            self.assertEqual(calls[0][0], 'scripts/release/rehearse.mjs')
            self.assertIn('--build=true', calls[0])
            self.assertIn('--source=' + 'a' * 40, calls[0])
            self.assertEqual(calls[1], ['scripts/release/gates.mjs'])
            self.assertNotIn(f'--tag=v{VERSION}', calls[0])
            (root / 'calls.jsonl').unlink()
            env['RELEASE_VERSION'] = '1.2.3'
            denied = subprocess.run(
                ['bash', '-e', '-c', step['run']],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertNotEqual(denied.returncode, 0)
            self.assertFalse((root / 'calls.jsonl').exists())

    def test_candidate_validation_before_builder(self):
        ctx = self.context(event='push', ref=f'refs/tags/v{VERSION}')
        step = next(
            s
            for s in self.workflow['jobs']['build']['steps']
            if 'workflow_entry.py' in s.get('run', '')
        )
        env = {
            key: str(expression(value, ctx)) if key != 'UV_PYTHON_DOWNLOADS' else value
            for key, value in step['env'].items()
        }
        env['GITHUB_REPOSITORY'] = 'Calmingstorm/Odin-Desktop'
        self.assertIn(f'--tag=v{VERSION}', candidate_arguments(env))
        for key, value in [
            ('RELEASE_REF', 'refs/tags/v1.2.3'),
            ('RELEASE_ATTEMPT', '2'),
            ('RELEASE_ACTOR', 'other'),
            ('RELEASE_EVENT', 'pull_request'),
            ('RELEASE_SOURCE', 'not-sha'),
            ('GITHUB_REPOSITORY', 'foreign/repo'),
        ]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                candidate_arguments({**env, key: value})

    def test_permission_and_runner_boundaries(self):
        self.assertEqual(self.workflow['permissions'], {})
        for name, job in self.workflow['jobs'].items():
            self.assertEqual(job['runs-on'], ['self-hosted', 'odin-desktop-ci'])
            self.assertEqual(
                job['permissions']['contents'], 'write' if name == 'publish' else 'read'
            )
            for step in job['steps']:
                if 'uses' in step:
                    self.assertRegex(step['uses'], r'@[0-9a-f]{40}$')
                self.assertNotIn('${{', step.get('run', ''))
                if 'actions/checkout@' in step.get('uses', ''):
                    self.assertFalse(step['with']['persist-credentials'])
        self.assertEqual(
            self.workflow['jobs']['publish']['environment']['name'], 'odin-desktop-release'
        )
        self.assertEqual(
            self.workflow['jobs']['verify']['steps'][-1]['env'],
            self.workflow['jobs']['publish']['steps'][-1]['env'],
        )
        build_entry = next(
            step for step in self.workflow['jobs']['build']['steps']
            if 'workflow_entry.py' in step.get('run', '')
        )
        self.assertNotIn('GH_TOKEN', build_entry['env'])
        self.assertNotIn('rehearse', self.workflow['jobs']['publish']['steps'][-1]['run'])

    def test_release_jobs_provision_cached_interpreters_without_setup_actions(self):
        for job_name, job in self.workflow['jobs'].items():
            with self.subTest(job=job_name):
                steps = job['steps']
                provisioning = [
                    step for step in steps
                    if 'provision_cached_tools.py' in step.get('run', '')
                ]
                self.assertEqual(len(provisioning), 1)
                uses = [step.get('uses', '').split('@', 1)[0] for step in steps]
                self.assertNotIn('actions/setup-python', uses)
                self.assertNotIn('actions/setup-node', uses)
                self.assertEqual(
                    '--require-node' in provisioning[0]['run'], job_name == 'build'
                )
        build = self.workflow['jobs']['build']
        entry = next(step for step in build['steps'] if 'workflow_entry.py' in step.get('run', ''))
        self.assertEqual(entry['env']['UV_PYTHON_DOWNLOADS'], 'never')

    def test_actual_yaml_job_names_accepted_by_candidate_api(self):
        # Verifier sees YAML's actual emitted identities, not parallel names.
        import actions_control
        from test_actions_control import ActionsTests
        fixture = ActionsTests(methodName='test_jobs_skipped_and_successful')
        fixture.setUp()
        try:
            fixture.responses[fixture.j]['jobs'] = [
                {
                    'name': job['name'],
                    'status': 'completed',
                    'conclusion': 'success' if key == 'build' else 'skipped',
                }
                for key, job in self.workflow['jobs'].items()
            ]
            run, artifact = actions_control.candidate_metadata(actions_control.dispatch_inputs())
            self.assertEqual(run['id'], 42)
            self.assertEqual(artifact['id'], 99)
        finally:
            fixture.doCleanups()


if __name__ == '__main__':
    unittest.main()
