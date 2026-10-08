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
  expect(source).toContain("pages.push({ name, frames })")
  expect(source).toContain("await screenshot('pending-restart')")
  expect(source).not.toContain('waitForTimeout(')
  expect(evaluate('runner.DEFAULT_OUTPUT')).toBe('/mnt/storage/odin-desktop-evidence/ui-v1-slices3-4-20261008')
  const fields = evaluate('runner.CAPTURE_FIXTURE_FIELDS.map(row => row[0])') as string[]
  expect(fields).toEqual(expect.arrayContaining(['openai_codex.enabled', 'openai_codex.agent_reasoning_effort',
    'ollama.num_ctx', 'openai_compatible.openrouter.order', 'openai_compatible.openrouter.model_pins',
    'agents.model_selection_hints', 'attachments.retention_hours']))
})

it('requires every C page and special state with contiguous top-to-bottom scroll coverage', () => {
  const result = evaluate(`(() => {
    const make = () => runner.CAPTURE_VARIANTS.map(variant => ({variant, outcome:'passed',
      advancedCategories: runner.ADVANCED_CATEGORIES,
      pages: [...runner.PRIMARY_NAV, 'Advanced settings'].map(name => ({name, frames:[
        {top:0, client:100, height:180}, {top:80, client:100, height:180}]})),
      screenshots: runner.REQUIRED_STATES.map(label => ({label: label + '-scroll-01'}))}));
    const check = mutation => { const receipts=make(); mutation(receipts); try {runner.validateCaptureEvidence(receipts); return 'passed'} catch(e) {return e.message} };
    return [check(() => {}), check(x => x.pop()), check(x => x[0].pages.pop()),
      check(x => x[0].screenshots.pop()), check(x => x[0].pages[0].frames[0].top=1),
      check(x => x[0].pages[0].frames[1].top=110), check(x => x[0].advancedCategories=[]),
      check(x => x[0].outcome='failed'), check(x => x[0].pages[0].frames.pop())];
  })()`)
  expect(result).toEqual(['passed', 'Expected two passing variant receipts',
    'Incomplete full-page scroll evidence: 1180x780-dark Advanced settings',
    'Missing required state: 1180x780-dark data-records',
    'Incomplete full-page scroll evidence: 1180x780-dark General',
    'Scroll coverage gap: 1180x780-dark General', 'Advanced categories missing or reordered',
    'Missing passing variant: 1180x780-dark', 'Incomplete full-page scroll evidence: 1180x780-dark General'])
})

it('builds nonempty labelled contact sheets without replacing full-window source screenshots', () => {
  expect(evaluate(`runner.contactSheetArgs(['/evidence/a.png', '/evidence/b.png'], '/evidence/sheet.png')`)).toEqual([
    '-font', 'DejaVu-Sans', '-pointsize', '12', '-background', '#e5e7eb', '-fill', '#111827',
    '-label', '%f', '/evidence/a.png', '/evidence/b.png', '-thumbnail', '460x', '-tile', '3x', '-geometry', '+8+24', '/evidence/sheet.png'
  ])
  expect(evaluate(`(() => {try {runner.contactSheetArgs([], '/sheet'); return false} catch {return true}})()`)).toBe(true)
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

it('adds declared synthetic screenshot metadata without changing the fixture or its argument contract', () => {
  const root = mkdtempSync(join(tmpdir(), 'ui-capture-schema-test-'))
  try {
    const fixture = join(root, 'harmless-schema.py')
    writeFileSync(fixture, `import json,sys\nSETTINGS_FIELDS = {'llm_provider.model': {'default':'old','apply_handler':'models.main.set','enum':['gpt-6.1-sol']},'openai_compatible.api_key':{'default':None}}\nMETHODS = {}\ndef field(path,kind,label,default,apply_mode='live_read'):\n    return {'path':path,'type':kind,'label':label,'default':default,'apply_mode':apply_mode}\nasync def main():\n    print(json.dumps({'fields':SETTINGS_FIELDS,'argv':sys.argv,'models':METHODS['models.status'](None,{},None),'outbound':METHODS['webhooks.outbound.list'](None,{},None)}))\n    return 0\n`)
    const before = readFileSync(fixture, 'utf8')
    const command = evaluate(`runner.fixtureCommand('/usr/bin/python3', ${JSON.stringify(fixture)}, runner.CAPTURE_FIXTURE_FIELDS)`) as string[]
    expect(developmentArgv(JSON.stringify(command))).toEqual(command)
    const result = spawnSync(command[0]!, [...command.slice(1), '--profile', 'disposable-test'], { encoding: 'utf8', timeout: 5000 })
    expect(result.status, result.stderr).toBe(0)
    const parsed = JSON.parse(result.stdout)
    expect(parsed.argv).toEqual([fixture, '--profile', 'disposable-test'])
    expect(parsed.fields['attachments.retention_hours']).toMatchObject({ default: 24, apply_mode: 'restart' })
    expect(parsed.fields['tools.governor.host_overrides']).toMatchObject({ default: {}, type: 'object' })
    expect(parsed.fields['llm_provider.model']).toMatchObject({ default: 'gpt-6.1-sol', apply_handler: 'models.main.set', enum: ['gpt-6.1-sol'] })
    expect(parsed.fields['openai_compatible.api_key']).toMatchObject({ sensitivity: 'sensitive', secret_route: 'secrets.set' })
    expect(parsed.models.model_catalogue).toEqual(evaluate('runner.CAPTURE_MODEL_CATALOGUE'))
    expect(parsed.models).toEqual(evaluate('runner.CAPTURE_MODEL_STATUS'))
    expect(parsed.models.serving_provider).toBe('codex')
    expect(parsed.models.openai_compatible).toMatchObject({ configured: false, openrouter_recognized: true })
    expect(parsed.models.model_catalogue.codex[0].ref).toBe('gpt-6.1-sol')
    expect(parsed.models.model_catalogue.compat[0]).toMatchObject({ capability: 'chat', effort_capabilities: { values: [] } })
    expect(parsed.outbound).toEqual(evaluate('runner.CAPTURE_OUTBOUND_WEBHOOKS'))
    expect(parsed.outbound.webhooks[0]).toMatchObject({ enabled: false, has_secret: false })
    expect(parsed.models.model_catalogue.codex[0].effort_capabilities).toMatchObject({
      values: ['medium', 'high'], restrictions_known: true, source: 'synthetic_capture_fixture'
    })
    expect(readFileSync(fixture, 'utf8')).toBe(before)
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
