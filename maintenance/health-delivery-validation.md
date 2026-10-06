# D17 durable delivery health restoration

Request: `/home/odin/reviews/desktop-health-delivery.md`.
All observations below are local development evidence, not independent approval,
full qualification, native desktop qualification or a release claim.

## Source and scope

- Waited for PR #38 to merge, then fetched latest main before branching:
  `edbbdfbf72984bcde080a7fbcb9985b1033ac2c0`.
- Implementation commit: `34155da9`.
- Later main `198c0cea` (#67 package qualification) integrated with an ordinary
  two-parent merge. Exact final exercised engine head:
  `191825c09f9ec0b28ccbdbcb51c8d162608af0ae`.
- Branch: `fix/health-delivery-readiness`. No rebase or force-push.
- Engine and new test bytes recorded explicitly through `inventory.py record`.
  Entries remain pending independent Claude review.

## Restored behavior

`CoreService` observes the actual `DurableDelivery`, shared durable journal/events,
request-service identity, engine binding, and their close state. Readiness is not
inferred from provider configuration or optional external sink presence. Desktop
IPC consumes the committed journal without an external sink.

Management samples these live properties on every `health.get`; it does not cache
startup readiness. The retained checker reports `Delivery ready` / `ok` for ready
delivery and `Delivery not ready` / `down` with a safe reason for missing,
mismatched or closed owners. A caller with no readiness observation still receives
the strict unavailable fallback; that is not the composed Desktop health path.

Delivery readiness is not admission authority. During non-admitting quiescence,
the still-bound delivery service remains usable to finish existing requests.
Readiness becomes false when its actual owners begin closing or are closed.
The focused read-only review suggested conflating quiescing admission with delivery
closure; that suggestion was not adopted, and an actual `runtime.shutdown` test
pins the distinction. No authorization or shutdown behavior was changed.

## Executed proofs

The new suite has **12 cases**, including parameterized broken bindings:

- Before composition, even with a provider-enabled configuration: not ready,
  reason `delivery_not_composed`.
- Fresh composed real profile via authenticated IPC: ready at startup.
- Real retained guarded runner with a harmless deterministic provider: exactly
  one provider call, `Guarded answer 1.` in the durable transcript, request-bound
  outbox records, and delivery still ready afterward.
- Summary count verified against every component: ready delivery contributes
  nothing to `unavailable_count`.
- Missing delivery, wrong store/events, unbound request/engine, and engine close
  attempt: not ready with the appropriate current reason; restoring bindings
  restores readiness on a new read.
- Requests closed: authenticated `health.get` reports not ready.
- Durable store closed: real journal/delivery unit proof, without background
  consumers. The request/engine handles in this one unit case are diagnostic
  fixtures, not a claim of a running composed profile.
- Core closed: retained real health callback reports `core_closed`; its IPC
  listener is correctly gone, so this is explicitly not a post-close IPC claim.
- Real accepted shutdown: admission stops while still-open delivery stays ready.

All pytest invocations used the reviewed launcher, restricted root-owned isolation
helper, separate PID/mount namespaces, UID 1003, sanitized HOME/XDG environment,
temporary profiles and keyring fixtures. The new composed fixture explicitly
refuses network client creation. No active graphical session was used.

## Gates

Final post-main-merge run: **410 passed**, no skips or failures, 175.46 seconds.
Includes all twelve new cases and these complete suites:

- Desktop web-strip/health observation, durable delivery, real request core,
  request failures, composed 6A services, management core, core lifecycle,
  engine services and records.
- Maintenance and maintenance-review, Phase 2 ownership/suite-map behavior,
  isolated runner, hermetic Cinnamon and GNOME fixtures.

Final offline checks:

- Inventory archive verified, **zero drift errors**; review remains pending.
- Lint: **zero new findings**, seven inherited findings.
- Phase 2 planned ownership check passed; this is coverage accounting, not
  implementation qualification.
- Suite-map check valid, **zero errors**; no inherited suite or retirement
  disposition was changed by this narrow fix.
- `git diff --check` passed.

Earlier runs are disclosed rather than relabeled as success:

1. Initial five proofs passed, but closing a live fixture's persistence before
   its teardown produced one teardown error. Replaced that extra closure probe
   with a standalone real-journal unit case; all five then passed.
2. First broad run: **147 passed, two failures**, both existing management IPC
   three-second timeouts (`models.main.set`, `tools.timeouts.set`). Those unchanged
   cases subsequently passed in the focused run and the final complete suite.
   This does not erase the original failures or prove a general load fix.
3. Expanded focused run: **13 passed, one failure** from the new shutdown proof
   omitting the required `reason` parameter. Corrected the test request; final
   broad run before merging newer main: **156 passed**, 154.92 seconds.
4. Task runner capacity was full (20 managed processes), so no new background
   watcher was started. Bounded foreground tools were used instead; no other
   lane's process was terminated. The disposable copied venv was replaced with
   a repository-owned `--copies` Python 3.12 environment and `uv sync --locked
   --extra dev`. No dependency or lockfile changes were committed.

Full classified qualification and Electron/UI tests were **not** run for this
engine-only fix. CI is triggered by the new PR; local counts above are not CI
results. No deploy, live-service restart/config write, production state access
or active-desktop operation occurred.

## D19 coordination

PR #63 remains **OPEN**, unmerged, at
`c5b7d23682879e0f6ac69fc324595471ae1ba0cb` when checked after final gates.
Its D19-049 record and pinning test are therefore not present on this main-based
branch and were not edited. The bridge lane should set D19-049 to
`removed_by_restored_behaviour` and replace the broken-behavior expectation, citing
`tests/test_desktop_health_delivery.py::test_health_delivery_ready_after_startup_and_real_guarded_turn`.

## Evidence and hygiene

External evidence with SHA-256 hashes is listed in
`maintenance/health-delivery-artifacts.json`. Raw output stays outside Git under
`/mnt/storage/odin-desktop-evidence/health-delivery-req7ebb92cd/`.

Root filesystem had 124 GB available initially, 120 GB before the first broad
run, and 118 GB after final gates, above the 60 GB floor. Only this task's
`/home/odin/desktop-health-delivery-req7ebb92cd` worktree and disposable venv are
cleanup candidates, after committed evidence, push and inactivity checks.
Protected caches, other lanes and evidence directories are not cleanup targets.
