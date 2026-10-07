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

No lab VMs, live desktop session, running service, `/opt/odin` or CI runner
configuration was touched during development. No new product dependencies.

## Native lab verification, 2026-10-07

Packaged candidate built from main `61d70cb` + #89 + #95 + this branch `f6d6dfd`,
installed in the three lab guests, Odin started hidden and the core confirmed ready
before each logout.

| Desktop | Observed at logout | Receipts afterwards |
| --- | --- | --- |
| Cinnamon/X11 (cinnamon-session 6.0.4) | `QueryEndSession` answered in 5 ms; `EndSession`; Odin's Exit finished and the client answered 224 ms later; then `Stop` | app and core clean; app `process-exited`, shutdown accepted |
| GNOME/Wayland | `QueryEndSession` answered at once; Odin kept running for the whole 60 s confirmation; `EndSession`; client answered 211 ms later; then `Stop` | app and core clean |
| KDE/Wayland (Plasma 5.27, Ubuntu 24.04) | the hook ran `--exit`; core complete 0.47 s and app receipt 0.61 s after the logout request; KWin stopped 0.19 s after that; the hook removed itself | app and core clean |

Before this branch, the same logout left the app receipt `running` on all three.
A logout in the first seconds after login, while the core is still starting,
records `unknown` (the app cannot get an accepted shutdown from a core that is not
ready yet); that is the startup-Exit gap tracked with issue #93, not a logout
regression.

The query-then-cancel path was not driven natively. GNOME Shell's dialog buttons
expose no accessible action, and cinnamon-session 6.0.4 hangs on its own when a
no-prompt logout meets an inhibitor (reproduced with Odin not running). It stays
covered by the private-bus behaviour tests and the Electron logout E2E.

Evidence root: `/mnt/storage/odin-desktop-evidence/logout-exit-20261007/`.
`logout-exit-artifacts.sha256` records SHA-256 and absolute path for each retained
artifact, including initial failures rather than quietly deleting them.
