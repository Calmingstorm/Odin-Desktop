// Registered by execution-containment.spec.ts only. Do not name this .test.ts:
// Vitest's unit lane must never collect Playwright's PID-isolated acceptance.
import { expect, test } from '@playwright/test'
import { assertIsolated } from './harness'
import { EFFECTS_TIMEOUT_MS, SETUP_TIMEOUT_MS, waitForExecutionAdmission, type AdmissionObservation } from './execution-admission'

test.describe('execution admission observation bounds', () => {
  test.beforeEach(() => assertIsolated())
  function clock() {
    let time = 0
    return { now: () => time, delay: async (ms: number) => { time += ms } }
  }
  function view(setupReady = false, effectsReady = false, failure?: string): AdmissionObservation {
    return { setupReady, effectsReady, failure, diagnostics: { stage: 'measured-test-stage' } }
  }
  test('cold setup over 15 seconds is separate from effects observation', async () => {
    const timer = clock()
    const result = await waitForExecutionAdmission(() => view(timer.now() >= 16_000, timer.now() >= 16_100), timer)
    expect(result).toEqual({ setupMs: 16_000, effectsMs: 100, totalMs: 16_100 })
  })
  test('stuck imports remain bounded even with repeated progress observations', async () => {
    const timer = clock()
    await expect(waitForExecutionAdmission(() => view(), timer)).rejects.toThrow(`setup failed after ${SETUP_TIMEOUT_MS}ms`)
    expect(timer.now()).toBe(SETUP_TIMEOUT_MS)
  })
  test('effects cannot borrow unused setup time or renew their deadline', async () => {
    const timer = clock()
    await expect(waitForExecutionAdmission(() => view(true, timer.now() >= EFFECTS_TIMEOUT_MS), timer)).rejects.toThrow(`effects failed after ${EFFECTS_TIMEOUT_MS}ms`)
    expect(timer.now()).toBe(EFFECTS_TIMEOUT_MS)
  })
  test('actual admission failure or child death fails immediately with diagnostics', async () => {
    for (const failure of ['registry_start_failed: refusing workspace', 'core child 48 died', 'supervisor 77 died']) {
      const timer = clock()
      await expect(waitForExecutionAdmission(() => view(false, false, failure), timer)).rejects.toThrow(`${failure}; diagnostics={"stage":"measured-test-stage"}`)
      expect(timer.now()).toBe(0)
    }
  })
  test('late setup readiness is not accepted after the fixed bound', async () => {
    const timer = clock()
    await expect(waitForExecutionAdmission(() => view(timer.now() >= SETUP_TIMEOUT_MS, true), timer)).rejects.toThrow('setup failed')
  })
  test('a late observer cannot renew the real compose-to-effects deadline', async () => {
    const timer = clock()
    await timer.delay(16_000)
    await expect(waitForExecutionAdmission(() => ({ ...view(true, true), setupCompletedAtMs: 0 }), timer))
      .rejects.toThrow('effects failed after 16000ms')
  })
  test('already completed setup reports zero observed duration without moving the effects clock', async () => {
    const timer = clock()
    await timer.delay(1_000)
    const result = await waitForExecutionAdmission(() => ({ ...view(true, true), setupCompletedAtMs: 500 }), timer)
    expect(result).toEqual({ setupMs: 0, effectsMs: 500, totalMs: 0 })
  })
})
