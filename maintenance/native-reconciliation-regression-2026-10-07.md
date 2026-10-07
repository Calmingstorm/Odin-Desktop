# Native reconciliation fixture regression

## Cause and first bad main merge

The adjacent first-parent boundary is PR #37:

- `810c634c7e43cbfd71df2b411995c2f216cc8559`, immediately before #37:
  original native reconciliation spec **3 passed**.
- `cd527d18c264e3d5dc4bf12fbbd607390cdf5cc1`, #37 merge:
  original spec **3 failed**, each at line 145 with `complete` instead of `unknown`.
- Requested main `0ed8ca60b54f4a787aca25001745181c3086342b`:
  reproduced the same **3 failures** before the fix.

Reviewed production wiring in [PR #37](https://github.com/Calmingstorm/Odin-Desktop/pull/37)
deliberately shares the management computer controller with admitted foreground
requests. At that merge, `src/desktop/core.py:415` calls the new foreground
binding after management startup; lines 496-508 bind the management service and
replace `deps.native_owners["computer"]` at line 507. The dispatcher shares that
same mutable owners dictionary.

The old test fixture put its separate dormant native controller directly into
the dispatcher during **compose**, before this later binding. Startup replaced
that fixture owner with the management controller's different, empty store.
Cleanup correctly described the empty store it actually owned, while the
fixture's original quarantine was orphaned outside the retained graph. This is
a stale qualification composition, not evidence that production upgraded an
unresolved quarantine to confirmed release.

## Fix

Inject the original dormant controller and integration into the management
service before `start()`. The unchanged production foreground binding then
shares that exact controller/store with the request dispatcher and cleanup
barrier. No second native owner, recovery actuation or authority is introduced.

The original `app/test/e2e/native-reconciliation.spec.ts` is **unchanged**. It
still requires unknown computer/overall cleanup, retained quarantine and
unknown action receipts, session-busy refusal, no replay, and public
`reconciliation_required` after the next restart. No stale-byte assertion is
removed and no production policy is changed.

New parameterized core-binding regression tests cover both a genuinely empty
store and an unresolved quarantine through the actual foreground binding:
exact controller/store identity, no live backend, quarantine preservation,
absent release receipt, unknown cleanup journal and durable reconciliation.
Every executable statement in the new fixture-binding helper is covered by
those tests. Whole fixture coverage is not claimed: its native subprocess modes
are exercised by the isolated e2e cases, not by the unit coverage collector.

## Validation

All source-core/Electron qualification used the existing self-isolating runner,
non-root UID, separate PID namespace, private HOME/XDG, Xvfb and private bus.
No lab VM, live desktop, service or `/opt/odin` was touched.

- Fixed original native spec: **3 passed**.
- Related isolated Python suites: **114 passed**.
- App `npm run check`: typecheck/build passed; **1,035 tests passed**.
- Inventory exact-byte report: **0 errors**; lint gate: **0 new findings**.
- Complete five-spec lifecycle family: **27 passed, 2 failed, 0 skipped**.
  Both failures are the explicitly excluded `notifications.spec.ts` cases at
  lines 43 and 118: target highlighted/focused but not in viewport. No changes
  made to that lane. The remaining 24 cases passed in this run.
- A second four-spec diagnostic (excluding notifications) yielded **23 passed,
  1 failed**. The unrelated direct parent-EOF containment case at line 87 exited
  1 with `core startup failed`; its evidence still proved registry shutdown,
  absent descendants and removed socket. Native reconciliation was **3/3**.
  A separate unchanged containment-only diagnostic then passed **4/4**.
  This does not erase the failed family run or establish a universally clean
  lifecycle gate. Both original results are retained.

The second diagnostic temporarily added stronger post-exit native assertions;
those passed in all three cases. They were removed before submission to retain
the original reviewed spec byte-for-byte. The new core-binding tests provide
the additional ownership/quarantine checks without replacing old witnesses.

Raw logs, reports and traces are outside Git under
`/mnt/storage/odin-desktop-evidence/native-recon-20261007/`.
The adjacent artifact manifest lists paths and SHA-256 values. Ledger entries
were recorded with `inventory.py record`; review remains pending.
