// Harmless runner contract tests; no core/display/Electron launch.
import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { expect, it } from 'vitest'
const script = resolve(import.meta.dirname, '../scripts/real-core-advanced-capture.mjs')
function evaluate(expression: string): unknown {
  const result = spawnSync(process.execPath, ['--input-type=module', '-e',
    `import * as runner from ${JSON.stringify(script)}; console.log(JSON.stringify(${expression}))`], { encoding: 'utf8', timeout: 5000 })
  expect(result.status, result.stderr).toBe(0)
  return JSON.parse(result.stdout)
}
it('keeps strict isolation launcher with private D-Bus/Xvfb and no fixture command', () => {
  const plan = evaluate(`runner.captureLaunchPlan('/repo/app', '/external/config.ts', '/external', '/engine/python')`) as { command: string; args: string[]; options: { env: Record<string, string> } }
  expect(plan.command).toBe('dbus-run-session')
  expect(plan.args).toContain('-screen 0 1280x800x24 -nolisten tcp')
  expect(plan.args).not.toContain('--no-sandbox')
  expect(plan.options.env).toEqual({ ODIN_APP_E2E: '1', ODIN_APP_E2E_OUT: '/external', ODIN_APP_REAL_ADVANCED_CAPTURE: '1', ODIN_DESKTOP_ENGINE_PYTHON: '/engine/python' })
  const source = readFileSync(script, 'utf8')
  expect(source).toContain('await launchIsolated(plan.command, plan.args, plan.options)')
  expect(source).toContain("engineCommand: [python, '-B', '-P', '-m', 'src']")
  expect(source).toContain('Source/build changed during capture')
  const spec = readFileSync(resolve(import.meta.dirname, 'e2e/ui-v1-real-advanced.spec.ts'), 'utf8')
  expect(spec).toContain('realCore: true')
  expect(spec).not.toContain('realCore: false')
  expect(spec).not.toContain('fixture_core.py')
  expect(spec).toContain('assertAdvancedInventory(schema.fields, paths, categories, presentation)')
  expect(spec).toContain('assertAdvancedScrollCoverage(frames, paths)')
  expect(spec).toContain('coreProcess.args.slice(0, 5)')
  expect(spec).toContain('read-only capture must not write engine settings')
})
it('rejects tiny fixture receipts, missing identity/cleanup, unstable scroll and incomplete bottom evidence', () => {
  const result = evaluate(`(() => {
    const make=()=>({outcome:'passed',realCore:true,fixture:false,variant:{...runner.VARIANT},schema:{revision:'r'},inventory:Array(55).fill({}),core:{instanceId:'real'},cleanup:{orderlyExit:true},frames:[{top:0,client:100,height:180},{top:80,client:100,height:180}]});
    const check=mutation=>{const receipt=make();mutation(receipt);try{runner.verifyRealCaptureReceipt(receipt);return 'passed'}catch(e){return e.message}};
    return [check(()=>{}),check(x=>x.fixture=true),check(x=>x.inventory=[]),check(x=>delete x.inventory),check(x=>x.core={}),check(x=>x.cleanup={}),check(x=>x.variant.width=720),check(x=>x.frames.pop()),check(x=>x.frames[1].top=110),check(x=>x.frames[1].height=200),check(x=>x.frames[1].top=50)];
  })()`)
  expect(result).toEqual(['passed', 'Passing REAL core receipt required',
    'Missing real-schema inventory, core identity or orderly cleanup evidence', 'Missing real-schema inventory, core identity or orderly cleanup evidence', 'Missing real-schema inventory, core identity or orderly cleanup evidence',
    'Missing real-schema inventory, core identity or orderly cleanup evidence', 'Expected 1180x780 dark capture',
    'Missing full Advanced scroll evidence', 'Scroll coverage is unstable or has gaps', 'Scroll coverage is unstable or has gaps', 'Scroll evidence does not reach the bottom'])
})
it('rejects repository and symlink-output paths, hashes evidence outside Git', () => {
  const root = mkdtempSync(join(tmpdir(), 'real-advanced-path-test-'))
  try {
    const repo = join(root, 'repo'); mkdirSync(repo); symlinkSync(repo, join(root, 'redirect'))
    const result = evaluate(`(() => {const check=value=>{try{return runner.externalOutput(value,${JSON.stringify(repo)})}catch(e){return e.message}};return [check(${JSON.stringify(repo)}),check(${JSON.stringify(join(root, 'redirect', 'child'))}),check(${JSON.stringify(join(root, 'external', 'child'))}),runner.sha256('abc')]})()`)
    expect(result).toEqual(['Real-core evidence must remain outside the repository', 'Real-core evidence must remain outside the repository', join(root, 'external', 'child'), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'])
  } finally { rmSync(root, { recursive: true, force: true }) }
})
