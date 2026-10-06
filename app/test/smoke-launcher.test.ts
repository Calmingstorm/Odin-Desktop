// Execute the real smoke script against a disposable harmless child stub, never Electron or a display.
import { spawnSync } from 'node:child_process'
import { copyFileSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { expect, it } from 'vitest'

it('fixture smoke uses the selected Node runtime directory without inheriting owner PATH/session state', () => {
  const root = mkdtempSync(join(tmpdir(), 'smoke-launcher-fixture-'))
  try {
    const scripts = join(root, 'scripts')
    mkdirSync(scripts)
    copyFileSync(resolve(import.meta.dirname, '../scripts/smoke.mjs'), join(scripts, 'smoke.mjs'))
    // A real Node copy gives process.execPath a tool-cache-shaped directory.
    const bin = join(root, 'cache/node/22.23.3/x64/bin')
    mkdirSync(bin, { recursive: true })
    const node = join(bin, 'node')
    copyFileSync(process.execPath, node)
    const evidence = join(root, 'child.json')
    const stub = '#!/usr/bin/python3\nimport json,os,pathlib\n' +
      `pathlib.Path(${JSON.stringify(evidence)}).write_text(json.dumps(dict(os.environ)))\n` +
      'pathlib.Path(os.environ["ODIN_SMOKE_OUT"]).touch()\nprint("smoke: ok link=ready")\n'
    writeFileSync(join(bin, 'dbus-run-session'), stub, { mode: 0o755 })
    const result = spawnSync(node, [join(scripts, 'smoke.mjs')], {
      env: { PATH: '/fixture/owner-path', DISPLAY: ':0', DBUS_SESSION_BUS_ADDRESS: 'owner-bus', GH_TOKEN: 'fixture' },
      encoding: 'utf8', timeout: 20_000
    })
    expect(result.status, result.stderr).toBe(0)
    const env = JSON.parse(readFileSync(evidence, 'utf8'))
    expect(env.PATH).toBe(`${dirname(node)}:/usr/local/bin:/usr/bin:/bin`)
    for (const key of ['DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'GH_TOKEN']) expect(env[key]).toBeUndefined()
    expect(result.stdout).toContain('smoke PASSED')
  } finally { rmSync(root, { recursive: true, force: true }) }
})
