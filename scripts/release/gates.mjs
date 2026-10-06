// Release gates. Reviewed code only, dedicated nonprivileged runner, never an active seat.
import { spawnSync } from 'node:child_process'
import { mkdtempSync, readlinkSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { buildEnvironment } from './rehearse.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const home = mkdtempSync(resolve(tmpdir(), 'odin-release-gates-'))
const env = { ...buildEnvironment(process.env, home), VIRTUAL_ENV: resolve(root, '.venv') }
const helper = '/usr/local/sbin/odin-desktop-isolate'
// As in run-phase1-tests.py on the reviewed #25 branch, probe the restricted
// helper first. Verify identity and PID isolation again before running a suite.
// Select the launcher before any suite runs; a failed suite is NEVER retried.
const supervisor = `
import os, signal, subprocess, sys
uid, gid, parent_namespace = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
namespace = os.readlink('/proc/self/ns/pid')
if (uid == 0 or os.getuid() != uid or os.geteuid() != uid
        or os.getgid() != gid or os.getegid() != gid or os.getpid() != 1
        or namespace == parent_namespace or os.readlink('/proc/1/ns/pid') != namespace):
    raise SystemExit('Refusing release gates: PID namespace or invoking identity not verified')
status = open('/proc/self/status').read()
fields = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
if (int(fields['CapEff'].strip(), 16) or int(fields['CapBnd'].strip(), 16)
        or fields['NoNewPrivs'].strip() != '1' or fields['Groups'].strip()):
    raise SystemExit('Refusing release gates: capabilities, groups or privilege escalation remain')
if len(sys.argv) == 4:
    raise SystemExit(0)
def terminate(signum, frame):
    raise SystemExit(128 + signum)
signal.signal(signal.SIGINT, terminate)
signal.signal(signal.SIGTERM, terminate)
child = subprocess.Popen([sys.executable, '-c',
    'import subprocess, sys; raise SystemExit(subprocess.call(sys.argv[1:]))', *sys.argv[4:]])
while True:
    pid, status = os.wait()
    if pid == child.pid:
        raise SystemExit(os.waitstatus_to_exitcode(status))
`
let namespace
function run(command, args, cwd = root) {
  const result = spawnSync(command, args, { cwd, env, stdio: 'inherit' })
  if (result.status !== 0) throw Error('Release gate failed: ' + command + ' ' + args.join(' '))
}
function isolated(command, args, cwd = root) {
  run('sudo', [...namespace, command, ...args], cwd)
}
function selectNamespace() {
  const uid = process.getuid(), gid = process.getgid()
  if (uid === 0 || gid === 0 || process.geteuid() !== uid || process.getegid() !== gid) {
    throw Error('Release gates require a dedicated nonprivileged runner')
  }
  const payload = ['env', '-i', ...Object.entries(env).map(([k, v]) => `${k}=${v}`),
    resolve(root, '.venv/bin/python'), '-c', supervisor, String(uid), String(gid), readlinkSync('/proc/self/ns/pid')]
  const options = { cwd: root, env, stdio: 'pipe', timeout: 10000 }
  const permission = spawnSync('sudo', ['-n', '-l', helper], options)
  const candidates = []
  if (permission.status === 0) candidates.push(['restricted isolation helper', ['-n', helper]])
  candidates.push(['non-interactive sudo fallback', ['-n', 'unshare', '--mount', '--propagation', 'private',
    '--pid', '--fork', '--mount-proc', '--kill-child=SIGKILL', 'setpriv', `--reuid=${uid}`, `--regid=${gid}`,
    '--clear-groups', '--no-new-privs', '--inh-caps=-all', '--bounding-set=-all', '--']])
  const failures = []
  for (const [label, prefix] of candidates) {
    const probe = spawnSync('sudo', [...prefix, ...payload], options)
    if (probe.status === 0) {
      console.log(`PID isolation: ${label}; invoking UID ${uid}`)
      return [...prefix, ...payload]
    }
    failures.push(`${label}: ${probe.error?.message ?? 'exit ' + probe.status}`)
  }
  throw Error('Cannot establish a verified non-root PID namespace; no suites started. ' + failures.join('; '))
}
try {
  if (process.getuid() === 0) throw Error('Release gates require a dedicated nonprivileged runner')
  run('python3', ['-m', 'venv', '--copies', '.venv'])
  run('.venv/bin/python', ['-m', 'pip', 'install', 'uv==0.12.23', 'setuptools==84.0.0', 'wheel==0.48.0'])
  run('.venv/bin/uv', ['sync', '--locked', '--extra', 'dev', '--active',
    '--no-build-isolation-package', 'odin-desktop-engine'])
  namespace = selectNamespace()
  isolated(resolve(root, '.venv/bin/python'), ['-B', '-m', 'unittest', 'discover', '-s', 'scripts/release/tests', '-v'])
  run('node', ['--test', 'scripts/release/tests/rehearse.test.mjs', 'scripts/release/tests/gates.test.mjs'])
  isolated('npm', ['run', 'check'], resolve(root, 'app'))
  for (const name of ['smoke', 'test:real-core', 'smoke:real-core', 'test:a11y']) {
    run('npm', ['run', name], resolve(root, 'app'))
  }
} finally {
  rmSync(home, { recursive: true, force: true })
}
