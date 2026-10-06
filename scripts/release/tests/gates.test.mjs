import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, copyFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve } from 'node:path'
import { spawnSync } from 'node:child_process'

function fixture(mode, suiteFailure = false) {
  assert.notEqual(process.getuid(), 0)
  const root = mkdtempSync(resolve(tmpdir(), 'release-gate-fixture-'))
  try {
    mkdirSync(resolve(root, 'scripts/release'), { recursive: true })
    mkdirSync(resolve(root, 'app'))
    mkdirSync(resolve(root, '.venv/bin'), { recursive: true })
    mkdirSync(resolve(root, 'bin'))
    for (const name of ['gates.mjs', 'rehearse.mjs']) {
      copyFileSync(resolve(import.meta.dirname, '..', name), resolve(root, 'scripts/release', name))
    }
    const stub = '#!/usr/bin/python3\nimport json,os,sys\nwith open(' + JSON.stringify(resolve(root, 'calls')) + ',"a") as f: f.write(json.dumps({"name":sys.argv[0],"args":sys.argv[1:],"env":dict(os.environ)})+"\\n")\n' +
      'if sys.argv[0].endswith("/sudo"):\n' +
      '    if "-l" in sys.argv: sys.exit(0 if ' + JSON.stringify(mode) + ' in ("helper", "failed-probe") else 1)\n' +
      '    if ' + JSON.stringify(mode) + ' == "failed-probe" and "/usr/local/sbin/odin-desktop-isolate" in sys.argv: sys.exit(1)\n' +
      '    if ' + JSON.stringify(mode) + ' == "denied": sys.exit(1)\n' +
      '    if ' + (suiteFailure ? 'True' : 'False') + ' and "discover" in sys.argv: sys.exit(7)\n'
    for (const name of ['bin/python3', 'bin/npm', 'bin/node', 'bin/sudo', '.venv/bin/python', '.venv/bin/uv']) {
      writeFileSync(resolve(root, name), stub, { mode: 0o755 })
    }
    const result = spawnSync(process.execPath, [resolve(root, 'scripts/release/gates.mjs')], {
      env: { PATH: resolve(root, 'bin') + ':/usr/bin:/bin', GH_TOKEN: 'fixture-secret',
        GITHUB_TOKEN: 'fixture-secret', NODE_OPTIONS: '--trace-warnings', DISPLAY: ':0',
        DBUS_SESSION_BUS_ADDRESS: 'fixture-bus', HOME: '/fixture-owner' }, encoding: 'utf8'
    })
    const calls = readFileSync(resolve(root, 'calls'), 'utf8').trim().split('\n').map(JSON.parse)
    for (const call of calls) {
      for (const key of ['GH_TOKEN', 'GITHUB_TOKEN', 'DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'NODE_OPTIONS']) {
        assert.equal(call.env[key], undefined)
      }
      assert.notEqual(call.env.HOME, '/fixture-owner')
    }
    const sudo = calls.filter(call => call.name.endsWith('/sudo'))
    assert.deepEqual(sudo[0].args, ['-n', '-l', '/usr/local/sbin/odin-desktop-isolate'])
    if (mode === 'denied') {
      assert.notEqual(result.status, 0)
      assert.match(result.stderr, /no suites started/)
      assert.equal(sudo.length, 2)
      assert(!sudo.some(call => call.args.includes('discover') || call.args.includes('check')))
      return
    }
    if (suiteFailure) {
      assert.notEqual(result.status, 0)
      assert.equal(sudo.length, 3) // permission, probe, failing suite; no fallback/replay
      assert(!sudo.some(call => call.args.includes('unshare')))
      assert(!calls.some(call => call.name.endsWith('/npm')))
      return
    }
    assert.equal(result.status, 0, result.stderr)
    assert.equal(sudo.length, mode === 'failed-probe' ? 5 : 4)
    const launcher = sudo.slice(mode === 'failed-probe' ? 2 : 1)
    if (mode === 'helper') {
      assert.match(result.stdout, /PID isolation: restricted isolation helper/)
      assert(launcher.every(call => call.args[1] === '/usr/local/sbin/odin-desktop-isolate'))
      assert(!sudo.some(call => call.args.includes('unshare')))
    } else {
      assert.match(result.stdout, /PID isolation: non-interactive sudo fallback/)
      assert(launcher.every(call => call.args.includes('unshare') && call.args.includes('--pid') && call.args.includes('--mount-proc')))
    }
    assert(launcher.every(call => call.args.includes('-i') && call.args.includes(String(process.getuid())) &&
      call.args.some(arg => arg.includes('PID namespace or invoking identity not verified'))))
    assert(launcher.some(call => call.args.slice(-3).join(' ') === 'npm run check'))
    const app = calls.filter(call => call.name.endsWith('/npm')).map(call => call.args.join(' '))
    assert.deepEqual(app, ['run smoke', 'run test:real-core', 'run smoke:real-core', 'run test:a11y'])
  } finally { rmSync(root, { recursive: true, force: true }) }
}

test('actual gates select restricted helper first, strip credentials and verify the namespace', () => fixture('helper'))
test('actual gates use generic sudo only after helper permission is unavailable', () => fixture('fallback'))
test('actual gates can choose sudo fallback after a failed helper capability probe, before any suite', () => fixture('failed-probe'))
test('actual gates fail closed before any suites when neither namespace path is available', () => fixture('denied'))
test('an isolated suite failure never falls back or replays the suite', () => fixture('helper', true))
