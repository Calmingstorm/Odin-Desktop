# Phase 2 step 8, part 1: deferred-suite ownership and early restoration

## Review #26 update (supersedes current-state counts below)

Rebased onto `main@566b7954911154ed36d9e5e751c2db9029e262e2`. All original
29 qualification groups remain, plus main's `phase2-step5-profile-management`,
for **30 current groups**. The original 29-group historical object and execution
receipt below remain unchanged, not evidence of a clean current invocation.

The five named step-1 suites are now **retired**, with exact citation
`Claude, review of #26`: client, command reconciliation, gateway transition
regressions, rate limiter and WebSocket production stack. Original bytes and
SHA-256 remain. The map records each review-specific reason, including `/api/`
versus unthrottled `/webhook/*`, separate step-6 report paging, and no IPC URL
credential carrier. No replacement equivalence or passing claim is made.
Historical membership remains **326 = 312 deferred + 9 restored + 5 retired**,
with its original fixed digest. Step 1 has 9 restored, 5 retired, zero deferred.

`computer_catalog` remains step 6 deferred. Claude's D17 review note remains open:
if Odin allows a skill to take a disabled builtin's name, Desktop must too.
No source/product behavior changes are made in this review-fix lane.

The dev extra now declares `pip>=26.2`; `uv lock` generated pip 26.2.1 and
`uv sync --locked --extra dev` succeeded without manual venv repair. Targeted
PID-isolated accounting, historical membership, plan and offline wheel tests:
**144 passed**, including maintenance, isolated-runner and distribution checks.
Ruff, exact-byte drift report and suite-map checker returned zero errors.
Parent owns the final clean full invocation; the historical
failed/retried qualification evidence is not overwritten.

## Historical implementation and execution record

Built from freshly pulled `main@7d919f0c32402e28179e019dee948be8ed3f5407`.
One review PR, no merge, deployment, live-service change or active-desktop action.
The concurrent requests/delivery, controls and runtime lanes are not changed.

## Machine-readable artifacts

- `phase2-suite-map.json`: exactly one row for every original deferred suite,
  with immutable inherited SHA-256, last required step, reason, surfaces,
  whole-suite status and explicit blocker or qualification selectors.
- `test-plan.json`: all 869 original paths and hashes remain. `phase2` contains
  317 still-deferred suites; `phase2_restored` preserves the nine transitions.
  Their union is still the original 326-path population and fixed digest.
- `qualification-plan.json`: the existing 29 named groups remain. Restored
  suites and accounting tests join `phase2-core-transport`, not a new group.
- `scripts/maintenance/phase2_suites.py`: offline checker rejects lost,
  duplicated, substituted or changed suites, and the tested forms of partial or
  unqualified restoration association. Its static pattern checks are not a
  general dataflow proof against arbitrary malicious adapter rewrites.
  It verifies pinned pre-restoration Git objects, baseline archive, all current
  classifications and complete group/adapter associations. Static accounting
  is not a runtime parity claim or independent approval.
- `phase2-step8-part1-adaptation-plan.json` and `desktop-deltas.json`: exact
  per-path adaptation contracts and evidence digests, pending review.

## Ownership counts

| Last required surface | Suites | Restored here | Still deferred |
|---|---:|---:|---:|
| Step 1 | 14 | 9 | 5 |
| Step 2 | 8 | 0 | 8 |
| Step 3 | 27 | 0 | 27 |
| Step 4 | 12 | 0 | 12 |
| Step 5 | 85 | 0 | 85 |
| Step 6 | 159 | 0 | 159 |
| Step 7 | 5 | 0 | 5 |
| Phase 3 | 16 | 0 | 16 |
| **Total** | **326** | **9** | **317** |

Eight mixed suites were assigned to Phase 3 after independent inspection
identified actual UI, updater or distribution assertions. Earlier engine
obligations remain named in their rows. Merely using a legacy HTTP route does
not make an engine service an app-only obligation; merely mentioning a webhook
schema does not require step 7's inbound trigger receiver.

## Complete restored suites

| Original suite | Original executed cases | Qualification |
|---|---:|---|
| `test_campaign_execution_risk.py` | 18 | Unchanged original, observational classifier/audit helper only |
| `test_channel_state_recent_action_failure.py` | 2 | Unchanged original, real action registry |
| `test_computer_audit_output_r21.py` | 9 | Unchanged original, temporary audit storage and fanout |
| `test_computer_checkpoint_privacy_r5.py` | 3 | Unchanged original, synthetic private-image codec |
| `test_computer_frame_boundary.py` | 4 | Unchanged original, generated raster binding validation |
| `test_connection_lifecycle_d1.py` | 1 | Unchanged original, once-only cleanup helper |
| `test_local_supervisor_wrapper_r10.py` | 22 | Unchanged original, inert workers and isolated protocol globals |
| `test_process_manager.py` | 162 | Complete frozen-source adapter, authentic owner/profile/workspace |
| `test_restored_process_shutdown.py` | 6 | Unchanged original, temporary manifests and real shutdown veto |
| **Total inherited cases** | **227** | No inherited assertion removed |

The process adapter preserves all **374 assertion nodes, 159 definitions and
three boolean parameter corpora**. Eight exact hash-pinned setup statements
replace two obsolete permissive handler fixtures with the actual
`OwnerAuthority`, `PermissionManager`, `ToolExecutor` dependencies and current
localhost identity. Its registry subclass supplies only a private workspace;
no containment, reaper, signal, scan or settlement method is replaced. Full AST
reverse replay and corpus equality guard every original assertion, signature,
decorator and parameter expression. A fixture-removal probe failed before
spawning, as required; the fixture was restored and retested.

The default isolated runner selects the complete adapter instead of also
executing its obsolete original setup. Directly restored originals remain
selected. Qualification uses explicit group selectors and no new exclusions.

## Honest blockers and validation limits

- `test_rate_limiter.py` and `test_websocket_production_stack.py` remain step-1
  blockers pending exact legacy-transport disposition. Their HTTP status,
  API/path/IP/proxy and bearer/session/query-carrier assertions have no assumed
  IPC equivalent. No rate policy, RBAC or management listener was invented to
  make them pass. They are not qualified and need reviewer disposition.
- `test_client.py`, `test_command_reconciliation.py` and
  `test_gateway_transition_regressions.py` also remain step-1 transport-owner
  disposition blockers. Retired Discord class/intents/extensions, guild slash
  publication and gateway-library backoff are not app-owned Phase 3 surfaces
  and have no invented IPC equivalents. No assertion or suite was dropped.
- `test_subsystem_guard.py`: independent whole-suite run **114 passed,
  2 failed**. The missing real application constructor must preserve thresholds
  7/19 and provider guard registration, so the whole suite belongs to step 5.
  A neutral test-built constructor would fabricate product behavior.
- `test_computer_catalog.py`: exact Config-only frozen adaptation left a real
  assertion failure: the original disabled same-name skill must survive,
  while current builtin-name reservation filters it. Step 6 owns explicit
  reconciliation; the failed candidate adapter was removed, not called passing.
- `test_main_exit_codes.py` and `test_restart.py`: actual gateway/bootstrap and
  app-owned exec/environment contracts, plus interrupt/cancellation differences,
  require exact case dispositions. No fake entry facade or in-process relaunch
  was reintroduced. Original bytes remain available for review.
- Native computer admission, accessibility, input and active-session behavior
  are not qualified by synthetic image/audit helpers. No native backend ran.
- The inherited process corpus emitted an unsuppressed asyncio subprocess
  finalizer warning on a closed event loop during targeted runs. The originating
  transport remains unverified; neither warnings nor assertions were silenced.
- The accounting checker requires the pinned historical Git objects. Exported
  archives without those objects are not supported by this checker.
- Existing maintenance approval records remain pending. No independent reviewer
  identity, approval, whole-engine parity or final Phase 2 closure is claimed.

## Executed targeted evidence

All pytest selections used `USER=odin` and `scripts/run-phase1-tests.py`:
isolated mount/PID namespace, procfs, nonroot owner, `env -i`, repository-local
throwaway HOME/XDG roots, no display/DBus/live credentials. Process tests were
fully inspected for executable commands and helpers before execution. Commands
were harmless and cleanup scoped to namespace-owned descendants.

- Original recent-action plus supervisor: **24 passed**.
- Original restored-process shutdown: **6 passed**.
- Original connection cleanup: **1 passed**.
- Original risk/audit plus three synthetic computer suites: **34 passed**.
- Full process adapter: **163 passed**, including provenance check; one warning.
- Mapping checker including mutation scenarios: **62 passed**.
- Parent combined touched run: **252 passed, 1 failed**. This exposed evidence
  refresh wording that lost the prior named D18 contract, not a product failure.
  The exact prior context-line contract was restored in the ledger plan without
  changing the assertion; follow-up membership/runner selection: **14 passed**.
- Ruff passed for new checker, mutation tests, process adapter and runner tests.
- Mapping checker: **zero errors**; exact-byte drift: **zero errors** before the
  fresh qualification gate. Source code under `src/` is unchanged.

The full 29-group qualification result is recorded below after its single fresh
checkout run. Targeted runs above are not a substitute for that gate.

## Single fresh qualification run and dependency remediation

Fresh detached checkout `9c771e541cd7312f2b7e20025fdecfafb4f14d52` was
created under a **2775 group-writable parent**, with **umask 002 before
`git worktree add`**. Fresh locked dependencies were installed locally and
all 29 groups ran once through the isolated launcher as `odin`.

The full invocation returned **13,728 passed, 9 setup errors, 2 skipped**,
zero assertion failures. The existing private-wheel fixture needs `pip`, which
`uv sync` had not included in the fresh environment. Installed **pip 26.2.1**
only in repository virtual environments, verified access as the isolated owner
and `pip check`, then reran **only the affected distribution group**:
**32 passed**, zero failures/errors/skips.

Across each group's successful execution after this remediation:
**13,737 passed, 2 skipped**, all **29 groups** qualified. This is **not** a
single clean full invocation. Original error evidence remains in
`phase2-step8-part1-result.json`, alongside per-group JUnit hashes and retry
evidence. The restored/transport group returned **540 passed**, including all
227 inherited restored cases and the new accounting/provenance checks.

Final mapping corrections reassigned three retired social-transport suites
from an unsupported app label to step-1 **deferred dispositions**. Only mapping
and documentation changed after the fresh gate; executable source/tests,
qualification selectors and exact delta records remain its tested bytes.
Final accounting is checked separately. Current-main PR #19 adds app-only
changes; the actual three-dot PR diff contains **no app or src edits**. The
historical accounting pin is intentionally separate from the integration base.

Final accounting/membership/runner selection rerun: **76 passed**. Exact-byte
drift returned **zero errors**. Parent independently matched all **29 JUnit
hashes**, the qualification-plan digest, and every ledgered executable file
against the fresh tested checkout; no executable drift followed the full gate.

Logs: `/home/odin/desktop-phase2-step8-part1/qualification-final.log` and
`qualification-distribution-retry.log`. Unsuppressed inherited AsyncMock,
timeout-coroutine and process-finalizer warnings remain visible. The two
inherited skips are the unavailable native wire helper and the missing-import
branch while Playwright is installed. No warning-clean or native qualification
claim is made.
