# PR34 round 4: main merge and bounded harness waits

Request: `/home/odin/reviews/desktop-pr34-round4.md`. Implementation and
execution evidence, not independent approval or whole-product acceptance.

## Two-parent merge, no rebase

Execution commit `e9861a9159f621c4e812780a3ca16f82b1fdf8a5` has parents
`09a6f21cdc8446a2f181afc1f8705bc292816087` and
`0b7d596f7e870d06699722f151c4d9837c5433f1` (main, PR32 lifecycle).

The management conflict keeps quota-observer settlement before main's complete
execution-owner cleanup. Original owner receipts, producer-quiescence refusal,
unknown cleanup journaling and graph/storage retention coexist with PR34's
provider, audit, guard and quota fixes. Providers/settings remain byte-identical
to the prior PR34 versions. Static comparison against both parents found no
lost lifecycle barrier or provider fix on the normal composed-core path.

The supplied key-union ledger helper preserves both histories. Six concurrently
changed paths were re-recorded from merged bytes with both evidence sets;
`phase2-step8-part2-round4-merge.json` records their digests. Those records remain
pending independent review. Evidence hashes referencing the changed Desktop
fixture were explicitly refreshed without changing their product contracts.

## Deadline classification and exact assertion preservation

Both failures were test fixture waits in
`tests/test_desktop_core_lifecycle.py`, not production latency contracts:

- `wait_connected`: 300 connection-availability polls at 0.01s gave approximately
  three seconds for cold engine setup/imports/listener startup. Now one bounded
  **25-second** `asyncio.timeout` covers availability polling and handshake.
  An exited process still fails immediately, and expiry still fails the test.
  This does not relaunch the core or retry a submitted operation.
- `receive`: separate three-second header/body waits bounded test frame reads,
  including `tools.set_enabled`. Now one bounded **15-second** timeout covers the
  complete frame. No command is resent, and a timeout is never a successful or
  known-outcome receipt. Production request/cleanup budgets are untouched.

The fixture precedent is `d5ef03d37a5f65818dc2f8fbfe172417db9cacef` and
`f869d6aed880e57be27c611d0e794f05121bf511`: 25s cold startup and 15s request
receipt waits. Read-only independent inspection confirmed these Python waits
are fixture policy, not product contracts.

AST comparison against the prior PR head proves all **14 existing test
definitions**, including assertions, parameters and decorators, are identical.
Only fixture helpers/budget constants changed. Six added behavioral tests pin
the exact finite budgets, total-frame deadline, timeout failure, immediate exit
failure and single send on receipt expiry.

## One fresh full invocation: clean

Fresh detached checkout:
`/home/odin/desktop-phase2-step8-part2/round4/qualification/fresh`.

- Fresh `uv sync --locked --extra dev`, no dependency repair or lock change.
- Group-writable 2775 parent/checkout, umask 002, odin UID.
- Every group runs through the mount/PID namespace launcher and sanitized
  throwaway HOME/XDG. No owner display, session bus or credentials inherited.
- Exactly one `scripts/run-qualified-tests.py` invocation: **30 groups,
  15,247 passed, 0 failed, 0 errors, 2 skipped; exit 0**.
- No full rerun, failure retry, partial substitution or combined passing count.
- Group29: **581 passed**. Group30: **1,062 passed**. Both formerly failing
  cases passed in this full invocation, not an unchanged diagnostic rerun.
- Newly merged lifecycle driver/resource-cleanup tests and six harness probes
  are included without removing any prior selector or adding a group.

The actual single-invocation result, every group count/JUnit hash, log and lock
hashes, skip reasons and execution commit are in
`phase2-step8-part2-round4-result.json`. Evidence files added after execution
are maintenance-only; engine/app/test/qualification bytes remain exactly those
of the qualified execution commit.

## Short gates

- Isolated Python core/startup/management/cleanup/provider/keyring/first-run/
  audit/health/accounting gate: **356 passed**, zero failures/errors/skips.
- App typecheck, **75 suites / 693 tests**, production build: passed.
- Packaging unit gate: **39 passed**.
- Fresh-checkout byte-drift report: **zero errors**.
- Historical suite-map check: valid, **326 = 28 restored + 42 retired + 256
  deferred**. No round-three disposition changed.
- No-new-lint gate: **zero new findings**, seven inherited findings retained.

The two existing skips are native wire timing without its optional test binary
and the missing-Playwright-import test while Playwright is installed. Inherited
coroutine/collection/subprocess-finalizer warnings remain visible in the log;
clean means no failing/erroring qualification cases, not warning-free.

## Limits and safety

Counts are executions, including overlapping gate selectors, not unique
inherited cases. Retirements are not passing coverage. This does not claim
installed-package acceptance or fresh native lifecycle/Secret Service/provider
qualification. A static review noted an existing injected-guard identity seam;
it is not a merge-loss finding or demonstrated ordinary-path failure, and no
unrequested runtime redesign was added.

No deployment, live service/configuration change, real keyring/provider access,
active-desktop operation, PR merge or attribution trailer. Main was rechecked
after qualification and remained the merged `0b7d596f` pin.
