# PR #47, P3.1 slice 5, review round 1

Reviewed head: `e28a02a7151d8093c85ef27527b9c84589562e84`.
Corrected source/gate head: `400a35807636d5b66be83ffa4c7409dbcfa0d7b4`.
Branch: `app/p31-real-core-slice5`, still based on #37's
`phase-2/services-part-b` at `4ede9e75fb079a0a305c7b24f89700d7fb7c4416`.
This review does not merge main or change the stack's base.

## Finding dispositions

### P1, blocking: production-entry smoke restored

`npm run smoke:real-core` now executes two sequential, separately labelled
passes, without retries. Each pass gets its own PID namespace and fresh private
HOME/XDG profile through the existing isolation runner; Electron runs only under
Xvfb. The first launches `python -B -P -m src`, not the test bootstrap. The second
uses the same bootstrap entry as `RealCoreHarness({ workProof: true })`.

The production pass restores all four removed freshness assertions:

- Zero `.msg` elements in the initial real conversation.
- Audit result exactly `[]`.
- Log entries exactly `[]`.
- Rendered audit says `Nothing recorded.`; logs say `No entries.`.

It additionally proves that the work-proof marker is absent, the real Work list
is empty, schedules are empty and the rendered running-work panel is empty.
Turn-state availability remains `available`, as actually served on this base;
the old `not_enabled` expectation is not reinstated.

The second pass retains real harmless task/report execution, D12 catch-up and
recovery-required observations, stored page-two navigation, effect counters and
the journaled cancellation receipt replay. Every screenshot includes a visible
`seeded work proof` banner with the agent/process metadata-only limitation. Its
screen names and JSON evidence also explicitly identify the seeded proof.

The original slice-five validation record now corrects its production-smoke
claim and links here. Historical evidence remains retained, not retroactively
renamed into production-entry evidence.

### P2: executor substitution narrowed

The bootstrap intercepts only `run_command` with exactly `proof:wait` or
`proof:lost`. Every other call forwards the original tool, input, positional
arguments and keyword arguments unchanged to the captured real executor.

A behavioral Broker/core regression admits scheduled workflows using ordinary
`manage_process list` and an unrelated harmless `run_command`. Both succeed and
publish real output, without changing the independent task/report counters.
The process metadata seed remains unknown with unproven resource release.

The regression passes with the correction. Substituting only the original
executor wrapper in the owned qualification checkout makes it fail: the first
workflow returns `status: failure` rather than `success`. The witness is isolated
and intentionally expected to fail; the original wrapper was then removed and
the checkout was verified clean. It is not a retry of a failed final gate.

### P3, non-blocking: keep metadata seeds explicit

Agent mailbox and restored-process rows remain controlled metadata seeds.
Neither is counted as provider/native process execution qualification. The new
real executor list regression is not process admission. Native process/agent
admission was not added to this review's scope, preserving the honest unknown
release observation rather than manufacturing a qualification claim.

## Final source verification

Fresh detached checkout: `/home/odin/desktop-pr47-r1-fresh-20261006` at the
corrected source head. Dependencies installed from the existing frozen uv/npm
locks; no dependency versions changed. Tests ran as ordinary user `odin`
(UID/GID 1003), never root, inside PID isolation and disposable profiles.

| Gate | Result |
| --- | --- |
| `npm run check` | Typecheck, **658 app tests / 71 files**, production build passed |
| `npm run test:real-core` | **26 Broker/core tests / 3 files**, then **6 onboarding tests** passed |
| `npm run smoke:real-core`, production pass | **21 labelled screen observations**, fresh-profile assertions passed |
| `npm run smoke:real-core`, seeded pass | **22 labelled screen observations**, D12/report/receipt assertions passed |
| `npm run test:a11y` | **16 tests** passed |
| Drift | No errors; existing independent review state remains pending |
| Lint | Zero new findings; 7 inherited findings |
| Phase-two ownership plan and `git diff --check` | Passed |

Production evidence records empty audit and logs. Seeded evidence records
`background=1, report=1`, a done cancellation receipt and manager-task-finished
settlement. Screenshots were inspected for the visible seeded proof label.
No final requested gate needed a retry or assertion relaxation.

## Evidence, exploratory corrections and limits

Raw artifacts live outside Git at
`/mnt/storage/odin-desktop-evidence/pr47-review1-20261006/`.
The committed SHA-256 manifest lists each retained artifact's absolute path.
Final gate logs: `final-check.log`, `final-real-core.log`,
`final-smoke-both.log`, `final-a11y.log`; machine evidence:
`production-entry-evidence.json`,
`production-entry-seeded-work-proof-evidence.json`, `a11y.json`.

Three exploratory pass-through test mistakes were corrected before final
qualification: check actions do not allow `manage_process` (use workflow
admission); real process-list authorization filters out the metadata-only row;
settlement has additional fields beyond the minimal expected shape. Their logs
remain in the manifest. The final targeted regression passed before the full
requested gates; the old-executor witness failed as expected afterward.

The shared process registry had all 20 background slots occupied, so final gates
used observable synchronous script execution with pipefail and tee rather than
terminating anyone else's process. Disk was checked before heavy work and stayed
at least 120 GB free, above the 60 GB minimum. Only this lane's inactive fresh
qualification/worktree copies are cleanup candidates; evidence is retained.

This is renderer/Broker/core qualification, not native execution, Orca, release,
whole P3.1 or Phase-two-exit qualification. No production engine Python changed;
no ledger approval or provenance edits were required. No attribution trailers,
merge, rebase, force-push, deployment, live-service changes or active-desktop input.
The follow-up evidence commit changes only small validation/manifest files.
