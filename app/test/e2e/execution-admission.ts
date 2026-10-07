// Observation budgets only. Production startup/supervisor/settlement bounds are
// untouched. Setup ends at original management composition, after cold imports
// and profile construction. Use the harness's existing 45s cold-start bound;
// registry admission, completed core start and effects keep the original 15s
// bound and cannot borrow unused setup time.
export const SETUP_TIMEOUT_MS = 45_000
export const EFFECTS_TIMEOUT_MS = 15_000

export interface AdmissionObservation {
  setupReady: boolean
  setupCompletedAtMs?: number
  effectsReady: boolean
  failure?: string
  diagnostics: unknown
}
export interface AdmissionClock {
  now(): number
  delay(ms: number): Promise<void>
}
const monotonicClock: AdmissionClock = {
  // Linux libuv hrtime and Python monotonic_ns share CLOCK_MONOTONIC.
  now: () => Number(process.hrtime.bigint()) / 1_000_000,
  delay: ms => new Promise(done => setTimeout(done, ms))
}

export async function waitForExecutionAdmission(
  observe: () => AdmissionObservation,
  clock: AdmissionClock = monotonicClock
) {
  const started = clock.now()
  let phase: 'setup' | 'effects' = 'setup'
  let phaseStarted = started
  let setupMs = 0
  for (;;) {
    const view = observe()
    const now = clock.now()
    const budget = phase === 'setup' ? SETUP_TIMEOUT_MS : EFFECTS_TIMEOUT_MS
    // Deadline first: a ready result arriving after its phase bound is not proof
    // of a bounded admission. Progress never renews a deadline.
    if (view.failure || now - phaseStarted >= budget) {
      throw new Error(`Execution admission ${phase} failed after ${Math.round(now - phaseStarted)}ms: ${view.failure ?? `deadline ${budget}ms exceeded`}; diagnostics=${JSON.stringify(view.diagnostics)}`)
    }
    if (phase === 'setup' && view.setupReady) {
      phase = 'effects'
      // Use the fixture's actual transition, not when this polling worker got
      // CPU time. A delayed observation must not renew the effects budget.
      phaseStarted = view.setupCompletedAtMs ?? now
      // Electron callers already awaited waitForCore: setup preceded this
      // observer. Report zero observed setup, not a negative duration.
      setupMs = Math.max(0, phaseStarted - started)
      if (now - phaseStarted >= EFFECTS_TIMEOUT_MS) {
        throw new Error(`Execution admission effects failed after ${Math.round(now - phaseStarted)}ms: deadline ${EFFECTS_TIMEOUT_MS}ms exceeded; diagnostics=${JSON.stringify(view.diagnostics)}`)
      }
    }
    if (phase === 'effects' && view.effectsReady) {
      return { setupMs, effectsMs: now - phaseStarted, totalMs: now - started }
    }
    await clock.delay(Math.min(50, (phase === 'setup' ? SETUP_TIMEOUT_MS : EFFECTS_TIMEOUT_MS) - (clock.now() - phaseStarted)))
  }
}
