// Release gates. Reviewed code only, dedicated nonprivileged runner, never an active seat.
import { spawnSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { buildEnvironment } from './rehearse.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const home = mkdtempSync(resolve(tmpdir(), 'odin-release-gates-'))
const env = { ...buildEnvironment(process.env, home), VIRTUAL_ENV: resolve(root, '.venv') }
function run(command, args, cwd = root) {
  const result = spawnSync(command, args, { cwd, env, stdio: 'inherit' })
  if (result.status !== 0) throw Error('Release gate failed: ' + command + ' ' + args.join(' '))
}
function isolated(command, args, cwd = root) {
  run('sudo', ['-n', 'unshare', '--mount', '--pid', '--fork', '--mount-proc', '--kill-child',
    'setpriv', `--reuid=${process.getuid()}`, `--regid=${process.getgid()}`, '--clear-groups', '--no-new-privs',
    'env', '-i', ...Object.entries(env).map(([k, v]) => `${k}=${v}`), command, ...args], cwd)
}
try {
  if (process.getuid() === 0) throw Error('Release gates require a dedicated nonprivileged runner')
  run('python3', ['-m', 'venv', '.venv'])
  run('.venv/bin/python', ['-m', 'pip', 'install', 'uv==0.12.23'])
  run('.venv/bin/uv', ['sync', '--locked', '--extra', 'dev', '--active'])
  isolated(resolve(root, '.venv/bin/python'), ['-B', '-m', 'unittest', 'discover', '-s', 'scripts/release/tests', '-v'])
  run('node', ['--test', 'scripts/release/tests/rehearse.test.mjs', 'scripts/release/tests/gates.test.mjs'])
  isolated('npm', ['run', 'check'], resolve(root, 'app'))
  for (const name of ['smoke', 'test:real-core', 'smoke:real-core', 'test:a11y']) {
    run('npm', ['run', name], resolve(root, 'app'))
  }
} finally {
  rmSync(home, { recursive: true, force: true })
}
