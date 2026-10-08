// Exercises the driver's orchestration against a stateful renderer/core model.
// This does not qualify real Vue, keyring or provider behavior. Native gates do.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { onboardingSmoke } from '../src/main/onboarding-smoke'

const disk = vi.hoisted(() => ({ read: vi.fn(), write: vi.fn() }))
vi.mock('node:fs', () => ({ readFileSync: disk.read, writeFileSync: disk.write }))
beforeEach(() => {
  vi.clearAllMocks(); vi.useFakeTimers(); disk.read.mockReturnValue('{"retained":true}');
  vi.stubEnv('ODIN_SMOKE_CONTROL', '/mock/control.json');
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllEnvs() })
function fixture(scenario: string) {
  vi.stubEnv('ODIN_SMOKE_ONBOARDING', scenario);
  let state = scenario === 'ready-second' ? 'effective-ready' : scenario === 'saved-second' ? 'saved' : ['locked', 'missing'].includes(scenario) ? 'degraded' : 'fresh';
  let section = '', settingsOpen = false, model = 'codex:gpt-5.4';
  let accounts = 0, auth = 'pending', keyring = state === 'degraded' ? scenario : 'healthy', unlockCalls = 0;
  let autostart = scenario.endsWith('-second') && scenario !== 'fresh-second', previews = !autostart;
  let enabled = true, compatEnabled = false, credential = false, level = 'INFO', conflict = false, disconnected = false;
  let probeFailure = false, guardDegraded = false, localRevision = false;
  const controls: any[] = [];
  disk.read.mockImplementation(() => JSON.stringify({ retained: true, unlock_calls: unlockCalls }));
  disk.write.mockImplementation((path: string, bytes: string) => {
    if (path !== '/mock/control.json') return;
    const control = JSON.parse(bytes); controls.push(control);
    if (control.auth) auth = control.auth;
    if (control.keyring) keyring = control.keyring;
    if (control.probe_failure !== undefined) probeFailure = control.probe_failure;
    if (control.guard_degraded !== undefined) guardDegraded = control.guard_degraded;
  });
  const sections: string[] = [], clicked: string[] = [], edits: string[] = [];
  const core: any = { linkState: 'ready', request: vi.fn(async (method: string, params?: any) => {
    if (method === 'status.get') return { ok: true, result: { first_run: { state, reason: state === 'fresh' ? 'provider_not_configured' : state === 'degraded' && guardDegraded ? 'provider_health_degraded' : 'provider_effective', keyring_unavailable: keyring !== 'healthy' } } };
    if (method === 'settings.schema') return { ok: true, result: { revision: 'fixture-rev', fields: [
      { path: 'llm_provider.model', desired: model, effective: model }, { path: 'openai_codex.enabled', desired: enabled },
      { path: 'logging.level', desired: level }, { path: 'openai_compatible.api_key', desired: credential },
      { path: 'openai_compatible.enabled', desired: compatEnabled }
    ] } };
    if (method === 'codex.accounts.list') return { ok: true, result: { configured: accounts > 0 } };
    if (method === 'settings.set') { if (params.expected_revision) { level = 'DEBUG'; localRevision = true } return { ok: true, result: {} } }
    throw new Error(`Unmodeled core request ${method}`);
  }), close: vi.fn(() => { disconnected = true; core.linkState = 'reconnecting' }),
    connect: vi.fn(() => { disconnected = false; core.linkState = 'ready' }), startEvents: vi.fn() };
  const win: any = { webContents: { isLoading: () => false, executeJavaScript: vi.fn(async (script: string) => {
    if (script.startsWith('document.querySelectorAll(')) {
      const selector = JSON.parse(script.slice('document.querySelectorAll('.length, script.indexOf(').length')));
      if (selector === '.settings') return settingsOpen ? 1 : 0;
      if (selector === '.settings-nav-item') return 3;
      if (selector === '.msg') return 0;
      if (selector === '.account') return accounts;
      if (selector === '#start-at-login, #notifications-enabled, #notification-previews') return section === 'General' && settingsOpen ? 3 : 0;
      if (selector.includes('settings-curated-logging.level')) return settingsOpen && section === 'Advanced settings' ? 1 : 0;
      if (selector === '.codex-accounts' || selector.includes('settings-field-') || selector === 'button[title="Settings (Ctrl+,)"]' || selector === '.settings-nav .back') return 1;
      throw new Error(`Unmodeled count ${selector}`);
    }
    if (script.startsWith('document.querySelector(') && script.includes('?.innerText')) {
      if (script.includes('openai_compatible.enabled') && script.includes("querySelector('.warn')")) return probeFailure ? 'Qualification rejected' : '';
      if (script.includes('.settings-body h2')) return section;
      if (script.includes('.first-run-banner')) return settingsOpen ? '' : keyring !== 'healthy' ? 'Keyring unavailable' : 'Ready';
      if (script.includes('.login-code')) return 'TEST-CODE';
      if (script.includes('.login')) return auth === 'expired' ? 'Login expired' : 'Pending';
      if (script.includes('logging.level')) return disconnected ? 'Connection unavailable' : conflict ? 'Changed elsewhere, reloaded' : '';
      throw new Error(`Unmodeled text ${script}`);
    }
    if (script.startsWith('document.querySelector(') && script.endsWith('.click()')) {
      if (script.includes('Settings (Ctrl+,)')) settingsOpen = true;
      else if (script.includes('.settings-nav .back')) settingsOpen = false;
      else throw new Error(`Unmodeled click ${script}`);
      clicked.push(script); return undefined;
    }
    if (script.includes('const buttons = Array.from')) {
      const label = JSON.parse(script.match(/b\.innerText\.trim\(\) === ("(?:[^"\\]|\\.)*")/)![1]!);
      if (script.includes('.settings-nav button')) { section = label; sections.push(label) }
      else if (label === 'Advanced settings' && section === 'General') { section = label; sections.push(label) }
      else if (label === 'Add account') { if (auth === 'success') accounts = 1 }
      else if (label === 'Retry') { if (keyring === 'locked') unlockCalls++; keyring = 'healthy'; state = 'fresh' }
      else if (!['Set up later', 'Stop waiting'].includes(label)) throw new Error(`Unmodeled button ${label}`);
      clicked.push(label); return undefined;
    }
    if (script.startsWith('Boolean(document.querySelector')) {
      const expected = script.match(/data-state="([^"]+)"/)?.[1];
      return !settingsOpen && expected === state;
    }
    if (script.startsWith('Array.from(document.querySelectorAll')) return [autostart, true, previews];
    if (script.includes("querySelector('#start-at-login')")) { autostart = true; return undefined }
    if (script.includes("querySelector('#notification-previews')")) { previews = false; return undefined }
    if (script.includes('await window.odin.getSettings()')) return autostart && !previews;
    if (script.includes('openai_compatible.api_key') && script.includes(".value === ''")) return true;
    if (script.includes('openai_compatible.enabled') && script.includes("querySelector('.warn')")) return probeFailure ? 'Qualification rejected' : '';
    if (script.includes('input.type ===')) {
      const value = JSON.parse(script.match(/input\.checked = ("(?:[^"\\]|\\.)*"|true|false)/)![1]!);
      if (script.includes('settings-field-llm_provider.model')) { model = value; state = guardDegraded ? 'degraded' : 'effective-ready' }
      else if (script.includes('settings-field-openai_codex.enabled')) { enabled = value; state = value ? 'effective-ready' : 'incomplete' }
      else if (script.includes('settings-field-openai_compatible.api_key')) { credential = keyring === 'healthy' }
      else if (script.includes('settings-field-openai_compatible.enabled')) { if (!probeFailure) compatEnabled = value }
      else if (script.includes('settings-curated-logging.level')) {
        await core.request('settings.set', { changes: [{ path: 'logging.level', value }] });
        if (disconnected) level = 'WARNING';
        else if (localRevision) { localRevision = false; conflict = true; level = 'DEBUG' }
        else { conflict = false; level = value }
      } else throw new Error(`Unmodeled edit ${script}`);
      edits.push(value); return undefined;
    }
    if (script.includes('JSON.stringify({html:') || script.includes('JSON.stringify([await window.odin.settingsSchema()')) return '{"fixture":"public-only"}';
    throw new Error(`Unmodeled renderer script ${script}`);
  }) } };
  return { win, core, sections, clicked, edits, controls };
}
async function runScenario(scenario: string) {
  const f = fixture(scenario); const pending = onboardingSmoke(f.win, f.core, '/mock/result.json');
  // Attach the rejection handler before advancing timers, avoiding unhandled
  // rejections if a driver's assertion fails during the scheduled work.
  const settled = pending.then(() => ({ ok: true as const }), error => ({ ok: false as const, error }));
  await vi.runAllTimersAsync(); const result = await settled; if (!result.ok) throw result.error;
  return f;
}
describe('onboarding smoke orchestration without a display', () => {
  it.each(['fresh', 'fresh-second'])('checks %s defaults, setup-later and collision-free section reentry', async scenario => {
    const f = await runScenario(scenario);
    expect(f.sections).toEqual(['General', 'Models and providers', 'General', 'Models and providers', 'General', 'Models and providers', 'General']);
    expect(f.clicked).toContain('Set up later'); expect(f.edits).toEqual([]);
    expect(disk.write).toHaveBeenCalledExactlyOnceWith('/mock/result.json', JSON.stringify({ scenario, passed: true, states: ['fresh'], checks: ['setup-later', 'section-reentry', 'defaults', 'secret-readback-absent'] }), { mode: 0o600 });
    expect(f.core.request.mock.calls.every(([method]: string[]) => method === 'status.get')).toBe(true);
  })
  it('checks persisted preferences and adopted provider on the second ready launch', async () => {
    const f = await runScenario('ready-second'); expect(f.sections).toEqual(['General']);
    expect(disk.write).toHaveBeenCalledExactlyOnceWith('/mock/result.json', JSON.stringify({ scenario: 'ready-second', passed: true, states: ['effective-ready'], checks: ['preferences-persisted', 'startup-provider-adopted', 'secret-readback-absent'] }), { mode: 0o600 });
  })
  it('retries a saved provider through a changed model and retains unrelated adapter-control keys', async () => {
    const f = await runScenario('saved-second'); expect(f.edits).toEqual(['codex:gpt-5.3-codex']);
    expect(disk.write).toHaveBeenCalledWith('/mock/control.json', '{"retained":true,"unlock_calls":0,"startup_provider_unavailable":false}', { mode: 0o600 });
    expect(disk.write).toHaveBeenCalledWith('/mock/result.json', JSON.stringify({ scenario: 'saved-second', passed: true, states: ['saved', 'effective-ready'], checks: ['preferences-persisted', 'saved-not-effective', 'secret-readback-absent'] }), { mode: 0o600 });
  })
  it('redacts a failing renderer operation rather than reporting success', async () => {
    const f = fixture('fresh'); f.win.webContents.executeJavaScript.mockRejectedValueOnce(new Error('renderer failed'));
    await expect(onboardingSmoke(f.win, f.core, '/mock/result.json')).rejects.toThrow('Onboarding renderer operation failed');
    expect(disk.write).not.toHaveBeenCalled();
  })
  it.each(['locked', 'missing'])('keeps %s keyring failure degraded until owner Retry, then completes login/model', async scenario => {
    const f = await runScenario(scenario); expect(f.clicked).toContain('Retry'); expect(f.clicked).toContain('Add account');
    expect(f.edits).toEqual(['E2E-WRITE-ONLY-NEVER-RENDER', 'codex:gpt-5.4']);
    expect(disk.write).toHaveBeenCalledWith('/mock/result.json', JSON.stringify({ scenario, passed: true, states: ['degraded', 'fresh', 'effective-ready'], checks: ['keyring-retry', 'secret-readback-absent', 'secret-readback-absent'] }), { mode: 0o600 });
    expect(f.controls.some(control => control.keyring === 'healthy')).toBe(scenario === 'missing');
  })
  it('checks cancellation, expiry, revision/disconnect and provider qualification recovery in the full onboarding plan', async () => {
    const f = await runScenario('ready');
    expect(f.sections).toContain('Advanced settings'); expect(f.sections).not.toContain('Records');
    expect(f.clicked.filter(label => label === 'Add account')).toHaveLength(3); expect(f.clicked).toContain('Stop waiting');
    expect(f.core.close).toHaveBeenCalledOnce(); expect(f.core.connect).toHaveBeenCalledOnce(); expect(f.core.startEvents).toHaveBeenCalledOnce();
    const result = JSON.parse(disk.write.mock.calls.find(([path]) => path === '/mock/result.json')![1] as string);
    expect(result).toEqual({ scenario: 'ready', passed: true, states: ['fresh', 'incomplete', 'effective-ready', 'degraded'], checks: [
      'defaults-and-opt-in', 'secret-readback-absent', 'canceled-login', 'secret-readback-absent', 'expired-login', 'secret-readback-absent',
      'revision-retry', 'connection-retry', 'secret-cleared', 'provider-save-retry', 'degraded-health-recovery', 'secret-readback-absent'
    ] });
    expect(f.controls).toEqual(expect.arrayContaining([expect.objectContaining({ probe_failure: true }), expect.objectContaining({ probe_failure: false }), expect.objectContaining({ guard_degraded: true }), expect.objectContaining({ guard_degraded: false })]));
  })
  it('enforces its handshake timeout rather than reporting a completed onboarding', async () => {
    const f = fixture('fresh'); f.core.linkState = 'reconnecting';
    const settled = onboardingSmoke(f.win, f.core, '/mock/result.json').then(() => null, error => error);
    await vi.advanceTimersByTimeAsync(26000); expect(await settled).toMatchObject({ message: 'onboarding fresh: timed out at app/core handshake' });
    expect(f.win.webContents.executeJavaScript).not.toHaveBeenCalled(); expect(disk.write).not.toHaveBeenCalled();
  })
  it.each(['html', 'preload', 'transcript'])('fails the %s leakage invariant without writing passed evidence', async leakage => {
    const f = fixture('ready-second'); const actual = f.win.webContents.executeJavaScript.getMockImplementation()!;
    f.win.webContents.executeJavaScript.mockImplementation(async (script: string) => {
      if (leakage === 'html' && script.includes('JSON.stringify({html:')) return 'E2E-OAUTH-ACCESS-NEVER-RENDER';
      if (leakage === 'preload' && script.includes('JSON.stringify([await window.odin.settingsSchema()')) return 'E2E-OAUTH-REFRESH-NEVER-RENDER';
      if (leakage === 'transcript' && script === 'document.querySelectorAll(".msg").length') return 1;
      return actual(script);
    });
    const settled = onboardingSmoke(f.win, f.core, '/mock/result.json').then(() => null, error => error);
    await vi.runAllTimersAsync(); expect(await settled).toBeInstanceOf(Error); expect(disk.write).not.toHaveBeenCalled();
  })
})
