# Logout Exit implementation gate result, 2026-10-07

Base: `61d70cb7846756592fb92372fc35d0fb5404d986` (latest main when branched,
still latest main at the end of local gates). Branch: `fix/orderly-session-logout`.

| Gate | Observed result |
| --- | --- |
| Private-bus monitor behaviour | 5 passed |
| Hook/runtime unit behaviour | 6 passed |
| New real-engine Electron logout E2E | 3 passed, including query cancellation, EndSession, Stop and actual generated Plasma hook |
| Full app check | 1,042 passed; typecheck and production build passed |
| Isolated real-core contracts | 66 passed |
| Isolated onboarding | 6 passed |
| Full source lifecycle E2E | 34 passed, no retries, including all three new cases and native reconciliation |
| Additional Desktop boundaries | 468 passed |
| Full classified qualification | 38/38 groups passed; 19,308 passed, 3 skipped |
| Offline lab orchestration | 281 passed |
| Offline lab fixture corpus | 159 passed, 4 explicit KDE subordinate-UID mapping skips |
| Packaging tests | 124 run, 24 explicit prerequisite skips (100 passed) |
| Lineage / lint / Phase 2 ownership / D19 / closure inventories | passed; no drift errors and no new lint findings (7 inherited findings) |
| Monitor statement coverage from unit/private-bus run | 83%; CLI pipe path additionally exercised by the Electron E2E, not included in that coverage total |

Qualification emitted existing warning categories (aiohttp NotAppKeyWarning,
an unraisable closed-event-loop transport warning, and pending coroutine/asyncgen
warnings). No failed test or hidden retry was converted into a pass. Packaging
prerequisite skips are not native package qualification.

Initial touched-test setup found a test-directory cleanup mistake, corrected
before full gates. The first targeted Electron attempt could not start because
npm had not installed Electron's binary; running the project's own Electron
installer supplied that missing dependency. The ready targeted run passed 3/3.
After those changes, all full gates passed on their first final invocation.

All successful end E2Es assert the app journal's current `process-exited` record,
accepted shutdown and absent warning, plus the core's `complete` resource receipt.
The SessionManager fake is a real native D-Bus service on the private bus, not a
direct main-process callback. The Plasma test executes the generated shell hook
and waits for app exit; it does not pretend to be a Plasma compositor.

Native Cinnamon/GNOME/KDE guest logout verification remains outstanding for
Claudia. No lab VMs, live desktop session, running service, `/opt/odin` or CI runner
configuration was touched. No new product dependencies. Ledger changes are
pending independent review, not self-approved.

Evidence root: `/mnt/storage/odin-desktop-evidence/logout-exit-20261007/`.
`logout-exit-artifacts.sha256` records SHA-256 and absolute path for each retained
artifact, including initial failures rather than quietly deleting them.
