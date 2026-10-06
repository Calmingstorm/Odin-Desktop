import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, copyFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve } from 'node:path'
import { spawnSync } from 'node:child_process'

test('actual gate orchestration strips tokens and wraps process suites in namespace', () => {
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
    const stub = '#!/usr/bin/python3\nimport json,os,sys\nwith open(' + JSON.stringify(resolve(root, 'calls')) + ',"a") as f: f.write(json.dumps({"name":sys.argv[0],"args":sys.argv[1:],"env":dict(os.environ)})+"\\n")\n'
    for (const name of ['bin/python3', 'bin/npm', 'bin/node', 'bin/sudo', '.venv/bin/python', '.venv/bin/uv']) {
      writeFileSync(resolve(root, name), stub, { mode: 0o755 })
    }
    const result = spawnSync(process.execPath, [resolve(root, 'scripts/release/gates.mjs')], {
      env: { PATH: resolve(root, 'bin') + ':/usr/bin:/bin', GH_TOKEN: 'fixture-secret',
        GITHUB_TOKEN: 'fixture-secret', NODE_OPTIONS: '--trace-warnings', DISPLAY: ':0',
        DBUS_SESSION_BUS_ADDRESS: 'fixture-bus', HOME: '/fixture-owner' }, encoding: 'utf8'
    })
    assert.equal(result.status, 0, result.stderr)
    const calls = readFileSync(resolve(root, 'calls'), 'utf8').trim().split('\n').map(JSON.parse)
    for (const call of calls) {
      for (const key of ['GH_TOKEN', 'GITHUB_TOKEN', 'DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'NODE_OPTIONS']) {
        assert.equal(call.env[key], undefined)
      }
      assert.notEqual(call.env.HOME, '/fixture-owner')
    }
    const sudo = calls.filter(call => call.name.endsWith('/sudo'))
    assert.equal(sudo.length, 2)
    assert(sudo.every(call => call.args.includes('unshare') && call.args.includes('--pid') && call.args.includes('--mount-proc')))
    assert(sudo.some(call => call.args.slice(-3).join(' ') === 'npm run check'))
    const app = calls.filter(call => call.name.endsWith('/npm')).map(call => call.args.join(' '))
    assert.deepEqual(app, ['run smoke', 'run test:real-core', 'run smoke:real-core', 'run test:a11y'])
  } finally { rmSync(root, { recursive: true, force: true }) }
})
