"""Request-local gate driver. Each gate runs once; all receipts remain external."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path('/mnt/storage/odin-desktop-evidence/pr35-main3-reqcb82eaf7')
PYTHON = str(ROOT / '.venv/bin/python')


def main():
    if subprocess.check_output(['id', '-un'], text=True).strip() != 'odin':
        raise SystemExit('Must run as ordinary odin')
    if __import__('shutil').disk_usage('/').free < 60 * 1024**3:
        raise SystemExit('Less than 60 GiB free')
    plan = json.loads((ROOT / 'maintenance/qualification-plan.json').read_text())
    restored = sorted({p for g in plan['groups']
                       if g['name'].startswith('phase2-step') and 'restored' in g['name']
                       for p in g['files']})
    assert restored
    boundary = sorted(str(p.relative_to(ROOT)) for p in (ROOT / 'tests').glob('test_desktop_*request*.py'))
    boundary += ['tests/test_desktop_attachment_knowledge.py', 'tests/test_desktop_attachments.py',
                 'tests/test_desktop_phase2_suite_map.py', 'tests/test_desktop_pr35_round2_dispositions.py']
    commands = [
        ('inventory', [PYTHON, 'scripts/maintenance/inventory.py', 'report'], ROOT),
        ('lint', [PYTHON, 'scripts/maintenance/lint_gate.py'], ROOT),
        ('phase2-plan', [PYTHON, 'scripts/maintenance/phase2_plan.py'], ROOT),
        ('d19', [PYTHON, 'scripts/maintenance/d19.py', 'report'], ROOT),
        ('phase2-suites', [PYTHON, 'scripts/maintenance/phase2_suites.py', 'check'], ROOT),
        ('pip-check', [PYTHON, '-m', 'pip', 'check'], ROOT),
        ('fixtures', [PYTHON, 'scripts/run-phase1-tests.py', 'tests/test_lab_cinnamon.py',
                      'tests/test_lab_gnome.py', '-rs', '--junitxml=' + str(EVIDENCE / 'fixtures.xml')], ROOT),
        ('restored-request-attachment', [PYTHON, 'scripts/run-phase1-tests.py', *sorted(set(restored + boundary)),
                 '-rs', '--junitxml=' + str(EVIDENCE / 'restored-request-attachment.xml')], ROOT),
        ('npm-ci', ['npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund'], ROOT / 'app'),
        ('npm-check', ['npm', 'run', 'check'], ROOT / 'app'),
        ('real-core', ['npm', 'run', 'test:real-core'], ROOT / 'app'),
    ]
    results = {'tested_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
               'main_sha': subprocess.check_output(['git', 'rev-parse', 'origin/main'], cwd=ROOT, text=True).strip(),
               'uid': __import__('os').getuid(), 'gates': []}
    for name, command, cwd in commands:
        print('START', name, flush=True)
        start = time.monotonic()
        log = EVIDENCE / (name + '.log')
        with log.open('wb') as f:
            rc = subprocess.call(command, cwd=cwd, stdout=f, stderr=subprocess.STDOUT)
        results['gates'].append({'name': name, 'command': command, 'cwd': str(cwd),
                                'exit': rc, 'seconds': round(time.monotonic()-start, 3),
                                'log': str(log), 'sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
        (EVIDENCE / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
        print('END', name, 'exit', rc, flush=True)
        print(log.read_text(errors='replace')[-5000:], flush=True)
    return int(any(g['exit'] for g in results['gates']))


if __name__ == '__main__':
    sys.exit(main())
