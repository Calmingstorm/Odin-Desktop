"""Offline D11 accounting regression, never connects to a display/Incus daemon."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'matrix_qualification', ROOT / 'scripts/qualification/desktop.py',
)
driver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(driver)


def matrix():
    candidate = {'source_sha': 'a' * 40, 'package_sha256': 'b' * 64,
                 'architecture': 'x86-64', 'package_bytes': 128, 'format': 'deb'}
    rows = []
    for name in driver.ROWS:
        environment = dict.fromkeys(driver.ENVIRONMENT, 'measured-version')
        environment['session'] = 'x11' if name == 'cinnamon' else 'wayland'
        rows.append({'row': name, 'candidate': copy.deepcopy(candidate), 'status': 'proven',
                     'limitation': 'VM virtual GPU only, not workstation acceptance',
                     'environment': environment,
                     'artifacts': [{'path': 'proof.json', 'sha256': 'c' * 64}],
                     'cases': {key: {'status': 'proven', 'evidence': ['proof.json'],
                                     'command': ['guest-only-observer']}
                               for key in driver.required_cases(name)}})
    gates = {key: {'status': 'done', 'evidence': ['exact-reviewed-proof'], 'detail': 'pass'}
             for key in ('ui_parity', 'p31', 'p32', 'p33', 'p34', 'p35', 'p42',
                         'phase2_suites', 'd19', 'runtime_fresh_host', 'final_candidate')}
    return {'candidate': candidate, 'rows': rows, 'final_run': True, 'gates': gates}


def test_complete_accounting_is_not_verified_evidence_or_release_authority():
    result = driver.validate_matrix(matrix())
    assert result['valid'] and not result['ready']
    assert not result['artifacts_verified']
    assert 'not Aaron live acceptance' in result['scope']


def test_actual_manifest_verification_required_before_readiness(tmp_path):
    value = matrix()
    for row in value['rows']:
        directory = tmp_path / row['row']
        directory.mkdir()
        proof = directory / 'proof.json'
        proof.write_text(json.dumps({'actual': 'result'}))
        row['artifacts'][0]['sha256'] = driver.digest(proof)
    result = driver.validate_matrix(value, tmp_path)
    assert result['ready'] and result['artifacts_verified']
    (tmp_path / 'kde' / 'proof.json').write_text('modified')
    assert not driver.validate_matrix(value, tmp_path)['ready']


def test_reuse_requires_identical_candidate_and_environment():
    value = matrix()
    row = value['rows'][0]
    case = row['cases']['keyboard_orca']
    case['reused_from'] = {'candidate': row['candidate'],
                           'environment': copy.deepcopy(row['environment'])}
    assert driver.validate_matrix(value)['valid']
    case['reused_from']['environment']['kernel'] = 'different'
    assert not driver.validate_matrix(value)['valid']


@pytest.mark.parametrize('name', driver.ROWS)
def test_wrong_candidate_never_reuses_previous_native_evidence(name):
    value = matrix()
    row = next(row for row in value['rows'] if row['row'] == name)
    row['candidate']['package_sha256'] = 'd' * 64
    result = driver.validate_matrix(value)
    assert not result['ready']
    assert f'{name}: candidate identity mismatch' in result['errors']


@pytest.mark.parametrize('key', driver.ENVIRONMENT)
def test_missing_version_or_hardware_identity_cannot_pass(key):
    value = matrix()
    del value['rows'][0]['environment'][key]
    assert not driver.validate_matrix(value)['valid']


@pytest.mark.parametrize('status', ('limited', 'pending', 'blocked'))
def test_unqualified_required_row_prevents_closure(status):
    value = matrix()
    value['rows'][0]['status'] = status
    result = driver.validate_matrix(value)
    assert result['valid'] and not result['ready']


def test_hyprland_cannot_replace_gnome_kde_app_evidence():
    value = matrix()
    value['rows'] = [value['rows'][3]]
    assert not driver.validate_matrix(value)['valid']


@pytest.mark.parametrize('row,key', [('gnome', 'no_tray_reopen_exit'),
                                    ('kde', 'sni_tray'), ('kde', 'kwallet_secret_service'),
                                    ('kde', 'portal_dialogs'),
                                    ('hyprland', 'recovery_containment')])
def test_row_specific_acceptance_is_mandatory(row, key):
    value = matrix()
    item = next(item for item in value['rows'] if item['row'] == row)
    item['cases'][key]['status'] = 'pending'
    assert not driver.validate_matrix(value)['ready']


def test_interim_candidate_cannot_close_final_gate():
    value = matrix()
    value['final_run'] = False
    assert not driver.validate_matrix(value)['ready']
    value['final_run'] = True
    value['gates']['p35']['status'] = 'in_progress'
    assert not driver.validate_matrix(value)['ready']


def test_case_evidence_requires_hashed_artifact_and_command(tmp_path):
    (tmp_path / 'proof.json').write_text(json.dumps({'actual': 'result'}))
    row = matrix()['rows'][0]
    row['artifacts'][0]['sha256'] = driver.digest(tmp_path / 'proof.json')
    assert not driver.check_artifacts(row, tmp_path)
    (tmp_path / 'proof.json').write_text('changed')
    assert driver.check_artifacts(row, tmp_path)
    row['artifacts'][0]['path'] = '../escape.json'
    assert driver.check_artifacts(row, tmp_path)


def test_regular_candidate_and_exact_source_required(tmp_path):
    package = tmp_path / 'candidate.deb'
    package.write_bytes(b'disposable-test-data')
    assert driver.identity(package, 'a' * 40)['package_sha256'] == driver.digest(package)
    with pytest.raises(ValueError):
        driver.identity(package, 'main')
    link = tmp_path / 'link.deb'
    link.symlink_to(package)
    with pytest.raises(ValueError):
        driver.identity(link, 'a' * 40)


def test_admission_refuses_other_lane_without_even_querying_daemon(monkeypatch, tmp_path):
    owner = tmp_path / 'owner'
    owner.write_text('p35 exact-owned-lab')
    monkeypatch.setattr(driver, 'LOCK', owner)
    monkeypatch.setattr(driver, 'run', lambda *args, **kwargs: pytest.fail('daemon queried'))
    with pytest.raises(ValueError, match='lock'):
        driver.admit('odq-gnome')
    with pytest.raises(ValueError, match='Hyprland'):
        driver.admit('odq-hyprland')
