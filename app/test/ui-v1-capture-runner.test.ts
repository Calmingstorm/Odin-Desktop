// Focused harmless runner tests. No Electron launch, display, core or live configuration.
import { spawnSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { expect, it } from 'vitest'
import { developmentArgv } from '../src/main/core-command'

const script = resolve(import.meta.dirname, '../scripts/ui-v1-capture.mjs')
function evaluate(expression: string): unknown {
  const result = spawnSync(process.execPath, ['--input-type=module', '-e',
    `import * as runner from ${JSON.stringify(script)}; console.log(JSON.stringify(${expression}))`],
  { encoding: 'utf8', timeout: 5000 })
  expect(result.status, result.stderr).toBe(0)
  return JSON.parse(result.stdout)
}

it('uses exact nine primary destinations and only requested large screenshots', () => {
  expect(evaluate('runner.PRIMARY_NAV')).toEqual(['General', 'Models and providers', 'Personality', 'Tools',
    'Skills', 'MCP servers', 'Hosts and access', 'Work', 'Data and privacy'])
  expect(evaluate('runner.CAPTURE_VARIANTS')).toEqual([
    { key: '1180x780-dark', width: 1180, height: 780, theme: 'dark' },
    { key: '1920x1080-light', width: 1920, height: 1080, theme: 'light' }
  ])
  expect(evaluate('runner.BOUNDS_VARIANTS.map(x => x.key)')).toEqual([
    'minimum-720x480', 'zoom-200-percent', 'narrow-720x780'
  ])
  const source = readFileSync(resolve(import.meta.dirname, 'e2e/ui-v1-capture.spec.ts'), 'utf8')
  // Each large variant includes the otherwise offscreen notification controls.
  expect(source).toContain("await screenshot('general-notifications')")
  expect(readFileSync(script, 'utf8')).toContain('manifest.screenshots.length !== 10')
})

it('uses private D-Bus and 2048x1200 Xvfb with only allowed isolation overlays', () => {
  const plan = evaluate(`runner.captureLaunchPlan('/fixture/app', '/evidence/config.ts', '/evidence')`) as {
    command: string; args: string[]; options: { timeoutMs: number; env: Record<string, string> }
  }
  expect(plan.command).toBe('dbus-run-session')
  expect(plan.args).toContain('-screen 0 2048x1200x24 -nolisten tcp')
  expect(plan.args).toContain('/fixture/app/node_modules/@playwright/test/cli.js')
  expect(plan.args).not.toContain('--no-sandbox')
  expect(plan.options.timeoutMs).toBe(600000)
  expect(plan.options.env).toEqual({ ODIN_APP_E2E: '1', ODIN_APP_E2E_OUT: '/evidence', ODIN_APP_UI_CAPTURE: '1', ODIN_APP_UI_PLAN: '/evidence/capture-plan.json' })
})

it('requires explicit Python/fixture and deterministic fixture presentation time', () => {
  const command = evaluate(`runner.fixtureCommand('/engine/python', '/app/fixture-core/fixture_core.py')`) as string[]
  expect(command.slice(0, 4)).toEqual(['/engine/python', '-B', '-P', '-c'])
  expect(command.at(-1)).toBe('/app/fixture-core/fixture_core.py')
  expect(command[4]).toContain('datetime.datetime = FrozenDateTime')
  expect(command[4]).toContain('fixture_random = random.Random(20261008)')
  expect(command[4]).toContain("runpy.run_path(fixture, run_name='__main__')")
  expect(command.every((argument) => !/[\u0000-\u001f\u007f]/.test(argument))).toBe(true)
  expect(developmentArgv(JSON.stringify(command))).toEqual(command)
  expect(evaluate(`(() => { try { runner.fixtureCommand('', '/fixture'); return false } catch { return true } })()`)).toBe(true)
  expect(evaluate(`runner.sha256('abc')`)).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
})

it('runs the fixed presentation clock bootstrap with real Python and preserves app-owned arguments', () => {
  const root = mkdtempSync(join(tmpdir(), 'ui-capture-clock-test-'))
  try {
    const fixture = join(root, 'harmless-clock.py')
    writeFileSync(fixture, 'import datetime,json,sys\nprint(json.dumps({"now":datetime.datetime.now(datetime.timezone.utc).isoformat(),"argv":sys.argv}))\n')
    const command = evaluate(`runner.fixtureCommand('/usr/bin/python3', ${JSON.stringify(fixture)})`) as string[]
    const result = spawnSync(command[0]!, [...command.slice(1), '--profile', 'disposable-test'],
      { encoding: 'utf8', timeout: 5000 })
    expect(result.status, result.stderr).toBe(0)
    expect(JSON.parse(result.stdout)).toEqual({ now: '2026-10-08T03:43:00+00:00', argv: [fixture, '--profile', 'disposable-test'] })
  } finally { rmSync(root, { recursive: true, force: true }) }
})

it('rejects repository paths and symlink redirects while allowing external nonexistent children', () => {
  const root = mkdtempSync(join(tmpdir(), 'ui-capture-path-test-'))
  try {
    const repository = join(root, 'repo')
    mkdirSync(repository)
    symlinkSync(repository, join(root, 'redirect'))
    const inspect = (path: string) => evaluate(`(() => { try { return runner.externalOutput(${JSON.stringify(path)}, ${JSON.stringify(repository)}) } catch (e) { return e.message } })()`)
    expect(inspect(join(repository, 'new'))).toBe('UI evidence must remain outside the repository')
    expect(inspect(join(root, 'redirect', 'new'))).toBe('UI evidence must remain outside the repository')
    expect(inspect(join(root, 'external', 'new'))).toBe(join(root, 'external', 'new'))
  } finally { rmSync(root, { recursive: true, force: true }) }
})
