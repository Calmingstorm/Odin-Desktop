# P3.1 slice 5: Work, schedules and stored reports on step 6B

Base: `phase-2/services-part-b` at `4ede9e75fb079a0a305c7b24f89700d7fb7c4416` (#37).
Branch: `app/p31-real-core-slice5`. The PR targets the base branch, not main.

Review round 1 found that the initial `smoke:real-core` run below used the seeded
Work bootstrap, not the unmodified production entry point. Its 22 observations
qualify only that seeded Work proof. They do not prove a fresh production profile.
The correction and separately labelled production/seeded gates are recorded in
[`pr47-review1-validation.md`](pr47-review1-validation.md).

## Delivered behavior

- Work reads the actual six manager families through the existing named bridge. Structured detail, immutable
  work/run/manager-generation bindings, Unix-second timestamps and settlement/resource-release observations are
  displayed without casting objects into text or turning unknown release into completion.
- Controls remain offered by the core. Agent steering submits the original text to its inbox once; the receipt
  says queued, not consumed. No extra 4,000-character chat-steer cap is imposed on the agent mailbox. No new
  confirmation, model instruction, owner allow-list or generic RPC was introduced.
- Work schedule commands submit the immutable Work ID, with current revision/binding. Their lock is keyed by
  `manager_id`, which is exactly `ScheduleRow.id` returned by `schedules.list`. These are different public surfaces:
  a schedule definition ID is not its immutable Work projection UUID. Shared-lock regressions use unequal IDs
  and prove Settings and Work cannot dispatch twice while the first receipt is unknown.
- Settings exposes actual schedule CRUD, manual run, failure reset and history, recovery-required/missed-run
  observations, inert reasons and last-run settlement. Skipped history is not failed; unknown stays unknown.
  Work events and connection recovery trigger authoritative schedule rereads. Both panels offer explicit Refresh.
- Stored report pages use `reports.page`; reading/copying/paging never invokes `schedules.run`.
- Skills/MCP management and computer use remain plainly unavailable on this base. This is not full P3.1,
  Phase 2 exit, native desktop qualification or release acceptance.

## Real proof and scope

`app/test/services-b-core.py` is test-only and rejects unprivileged/isolation mistakes before admission. It composes
the actual entry point, canonical authenticated owner, WorkService, ControlService, request/background owners,
retained scheduler, command journal, report delivery and Broker. It does not substitute fixture rows into a real
application session from the fixture engine, but it does insert controlled agent/process manager metadata and
replace the two synthetic waiting-tool boundaries. This is a seeded proof, not the production-entry smoke.

A completed task and scheduled two-page report execute harmless real local `run_command` children. Each child
appends an independent effect counter under the disposable HOME. The final smoke reads page two through the
rendered ReportViewer Next button and returns the same task-control receipt through the named preload twice.
Counters stay at `background=1, report=1` through paging/navigation and remain unchanged across tested restart.

The smoke records 22 screen observations, including:

1. A completed real background task, manager-task settlement, and journaled cancellation receipt for another task.
2. A single overdue reminder catch-up notice with due time, lateness and omitted slots. A missed check remains
   recovery-required; no effects were replayed.
3. Two stored report pages, with no producer rerun.
4. All six Work groups and explicitly unproven process release; unavailable services remain honest.

Agent mailbox and restored-process metadata are controlled real-manager seeds, not provider/process-execution
qualification. Waiting tools simulate pending external cleanup. Test bootstrap stops only autonomous ticking to
avoid clock-seeding races, then drives the real scheduler `_tick`, callbacks, admission/history and delivery.
No real account, live profile, live service or active desktop is used. Electron runs under Xvfb and PID isolation.

## Verification and evidence

Source gate head: `6bc0ef5450c4e7547d702264f1ebec5f36b427a1`; the later validation/ledger commit changes no
production or test bytes. Fresh detached checkout: `/home/odin/desktop-p31-slice5-fresh2`.

- `npm run check`: typecheck/build and **658 app tests** passed.
- Fixture smoke passed under the existing PID-isolation runner and Xvfb.
- `npm run test:real-core`: **25 actual Broker/core tests + 6 onboarding tests** passed.
- Real smoke passed: **22 screen observations**, journaled receipt, real task/check counters both one.
- `npm run test:a11y`: **16 tests** passed, including real served Work/schedules and unknown-settlement/steer AX.
- Drift has no errors; ledger review remains pending. Lint has zero new findings; plan and diff checks passed.

Logs, screenshots and JSON: `/home/odin/desktop-p31-slice5-evidence/`. Authoritative successful logs are
`final-check.log`, `final-fixture-smoke.log`, `final-real-core2.log`, `final-real-smoke2.log`, `final-a11y2.log`.
Real smoke detail: `real-core-evidence.json`, `real-core.png`, `real-core-report.png`, `real-core-settings-8.png`.
Accessibility detail: `a11y.json` plus the isolated runner's ignored `app/test-results/`.

Exploratory failures are retained, not omitted: incomplete unit-test Work stubs were made full real-shape rows;
new steer tests were corrected to the retained mailbox's empty-only validation; inherited settings assertions
still expected unserved schedules and disabled turn-state. Those assertions now require the exact composed
state. Adding a serialized third real-core file exceeded the old 120-second whole-suite budget; the bounded
budget is now 300 seconds, with individual timeouts unchanged. No production assertions were relaxed.
The inherited uptime comparison now compares stable startup status fields instead of later wall-clock summary.

No dependency versions changed. Existing lockfile installation reports 11 npm advisories (10 high, 1 critical),
inherited from the base; this slice does not claim a dependency/security or release qualification.

## Maintenance and review

Updating inherited `real-core-settings.test.ts` changes one named evidence digest for
`tests/test_desktop_model_settings.py`. Only that exact digest/reason is refreshed; Python source/test bytes and
pending independent-review state remain unchanged. No safety approval is manufactured.

Read-only audit suggested the schedule locks differed. Inspection of ScheduleService and the unequal-ID
cross-panel regressions shows both lock paths use the scheduler definition ID; the Work UUID is used only for
the command/row identity. The suggested blocker was a conflation of those two IDs, not an observed failure.

Nothing merged into main, rebased, force-pushed, deployed or restarted. No attribution trailers.
