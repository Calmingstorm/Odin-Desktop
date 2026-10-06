# PR34 round 3: main catch-up and health closure

Authority: **Claude, review of #34, round 3**, supplied by Aaron in
`/home/odin/reviews/desktop-pr34-round3.md`. This is implementation and execution
evidence, not an independent review or whole-product acceptance claim.

## Merge, not rebase

Merged `main@ddd054fe399fef46dd64b6e8ec95b2676af8f09f` into the existing
`phase-2/step8p2-integration` branch. Both histories are retained. Core startup
keeps async secret hydration and ready/event ordering together with quota
observer admission and shutdown. Provider sync/async settings and reload paths
keep the adopted graph for policy-only and boot-bound settings, while actual
credential preparation, Codex pool/configuration reads and persistence settle
off the event loop. Constructors/publication remain loop-owned.

The supplied `merge_ledger.py` performed the key union. Nine entries changed on
both sides were regenerated from the merged files with `inventory.py record`,
unioning both evidence sets. `phase2-step8-part2-round3-merge.json` names each
source and merged digest. These records remain pending independent review,
not automatically approved.

Inspection found round-2 audit signing authority had synchronous keyring reads
in async Records and Hosts paths. Resolution now uses the settled credential
worker without dropping the profile signing key or treating a locked vault as
unsigned. Reader binding and asyncio lock construction stay on the loop.

## Two health suites, case-level dispositions

- `test_health_endpoints.py`: all 22 inherited definitions retired. Four tier
  and bearer-policy cases cite **multi-user tiers removed**. Eighteen HTTP
  health callback-registry/live/ready/detail definitions cite **HTTP health
  endpoints removed with the listener**. No case exercises actual `check_all`
  results with an honest independent `health.get` equivalent. Removed HTTP
  callback registration is not relabeled as Desktop health passing evidence.
- `test_campaign_startup_health.py`: both unchanged knowledge-diagnostic cases
  restored from exact frozen source. One obsolete parameterized Discord/HTTP
  definition, expanding to two cases and including HTTP-only detail, retired
  with **Discord and the HTTP listener removed**. All inherited assertions,
  decorators and parameters remain in the frozen compiled corpus; only the
  reviewed removed definition is withheld from pytest export.

Every retirement records the exact case, source digest, reason and authority
**Claude, review of #34, round 3**. The map checker admits only those identities
and requires the adapter exclusions to equal the case dispositions. Removed
cases are retired, not skipped or counted passing.

Historical suite accounting: **326 = 28 restored + 42 retired + 256 deferred**.
Original population membership, archived bytes and prior retirements remain
intact. `test_image_model_config_api.py`, `test_web_api_llm_admin.py`, and
`test_log_search.py` statistics stay deferred with the exact blocker
**awaiting the step 5 completion PR**. No unrelated lane is promoted.

## Short gates before qualification

- Locked dev installation: `uv sync --locked --extra dev`, no manual repair.
- Merged provider/quota/audit and main #24/#30 regressions: **139 passed**,
  zero failures/errors/skips, under the required PID and sanitized HOME/XDG
  boundary. This overlapping count is not a unique inherited-case total.
- App typechecking, **640 tests** and production build passed. Packaging unit
  gate: **39 passed**. No app source changes were made by this revision.
- Final health/accounting, exact-byte drift and no-new-lint results accompany
  the full qualification receipt.

Parent final accounting/maintenance/health/runtime and audit threading gate:
**234 passed in 164.57s**, zero failures/errors/skips. Drift and map checkers
returned zero errors; lint retained seven inherited findings with none new.

## Qualification and safety boundary

The full qualification is run once from a fresh detached checkout of the
completed merge, under a 2775 group-writable parent, umask 002, a fresh locked
dev installation, isolated PID namespaces and throwaway HOME/XDG directories.
The plan retains its 30 groups and includes newly merged packaging/first-run/
keyring tests plus the round-three health and threading regressions. Its
single invocation and every JUnit digest are recorded separately in
`phase2-step8-part2-round3-result.json` after completion. No combined counts,
partial rerun substitution or clean claim before that receipt exists.

No deployment, installed-package claim, real provider/keyring access, upstream
change, live service/configuration change or active desktop operation. Native
packaging tests use their disposable namespaces; no owner desktop is touched.

## Actual full outcome: not merge-qualified

The single fresh full invocation at `2281b211` returned **15,214 passed,
2 failed, 2 skipped**, zero errors. Group29 failed the 0777-parent socketpair
startup case at the three-second listener wait. Group30 failed the actual
management shell-tools/readiness case at a three-second `tools.set_enabled`
response wait. Exact cases, group counts and JUnit hashes are in the result
JSON. No test assertion or deadline was relaxed.

Both exact failures passed together in a diagnostic-only isolated rerun on the
same unchanged checkout: **2 passed in 8.90s**. This proves intermittence under
the observed schedules, not their cause, harmlessness or full qualification.
It is not combined into a passing total. The once-only full-run instruction
was preserved; there was no second full invocation.

The health closure and requested #24/#30 catch-up are implemented, but the
requested clean full merge gate **was not achieved**. Main also advanced to
`0b7d596f` when PR32 lifecycle landed during qualification. That later main is
not merged or covered by this receipt. This handoff is not merge-ready.
