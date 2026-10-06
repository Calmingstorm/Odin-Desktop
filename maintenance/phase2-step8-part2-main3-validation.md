# PR34 main merge 3: step 6A preservation

Request: `/home/odin/reviews/desktop-pr34-merge-main3.md`, 2026-10-06.

## Merge and behavior

Qualified execution commit: `fe42ea1e81810c32e31efa163f312de34f86c78c`.
Its two parents are PR34 `5135016c3352c665813845d94441c78aa1f8caa3`
and main `da2d3d4adbc7864ed78ffb972e3792f8557fbcb2`, which includes
step 6A, the dedicated short-runner change, and the completed #44 docs.
This is a merge, not a rebase. Main remained at that revision after gates.

- Management retains the runtime guard and quota observer, all step 6A domain
  owners, catalog/diagnostics, service qualification and filtered publication.
- Quota starts only after admission/listener startup and stops before provider
  retirement. The step 6A producer barrier, browser/MCP shared ownership and
  continued cleanup of other owners after individual failure are retained.
- The close conflict preserves both observer settlement and the
  `ResourceCleanupError` import needed by refusal paths.
- Lifecycle retains one bounded 25-second connection budget, including stalled
  connect, and one 15-second complete-frame receipt budget. It also retains
  main's parent-stdin close and bounded communicate on startup timeout, with
  corrected actual-budget diagnostics. No request replay or production deadline
  change. The fixture verifies cleanup and the single attempt.
- The merged real-core capability contract has 121 unique methods: PR34's
  `models.image.intent` plus main's step 6A methods. Equality with the real
  welcome/status and the explicit harness inventory passed.
- The step 6A parent-loss fixture now includes background lifecycle hooks and
  verifies no background start before publication, followed by shutdown. This
  avoids a fixture-only AttributeError without weakening production ordering.
- Qualification preserves `STEP6A_GROUP`, both exact GI adapter associations,
  PR34's full frozen guard replacement, all restored suites and accounting.

## Ledger

Union by path: **401 entries**. Both-parent changes: **23 entries**, with both
reasons, contracts, invariants and the union of cited tests retained.
The official `inventory.py record` command emitted **92 entries**, including
right-parent additions/changes and **41 entries whose cited test hashes needed
refresh**. No handwritten byte patches were used as ledger substitutes.
Independent union verification checked both-parent text preservation and every
current source/cited-test hash. Inventory report: **0 errors**. Review status is
not invented by recording bytes.

Historical accounting remains **326 = 28 restored + 42 retired + 256 deferred**.
No original inherited corpus or retirement disposition changed in this merge.

## Requested gates

Locked Python 3.12 environment installed with `uv sync --locked --extra dev`.
The interpreter is a repository-owned copy; tests run as ordinary `odin`,
UID/GID 1003, through the unchanged restricted PID/mount helper and throwaway
HOME/XDG. No live credentials, session/display sockets or config enter tests.

| Complete selection | Passed | Failed/errors/skips |
|---|---:|---:|
| Short/accounting/runner/cleanup/lab fixtures, 9 suites | 354 | 0 |
| `phase2-core-transport`, 18 suites including lifecycle | 628 | 0 |
| `phase2-step5-profile-management`, 51 suites including restored runtime suites | 1,077 | 0 |
| `phase2-step6a-qualified-local-services`, 8 suites | 173 | 0 |
| App `npm run check` | 760 | 0 |
| Actual Broker/core contracts | 22 | 0 |
| Isolated Xvfb onboarding | 6 | 0 |

All restored selector carriers were covered by these complete groups; no
additional restored selector remained uncovered. Python invocation total is
2,232 passing executions, not a deduplicated unique-test total. Every group ran
once after the evidence directory was made writable; the initial launcher failed
before any test started because that directory lacked permission.

Typecheck and production build passed. Real-core UI smoke passed through private
DBus/Xvfb, observing 40 screen checkpoints and 121 served capabilities. This is
not native foreground-input or real desktop qualification.

Short tooling: inventory 0 errors, no new lint findings, ownership-plan checker
pass, suite-map checker valid. An informational four-check validation bundle
also confirmed the written outputs. Three inherited warnings remain: one closed
event-loop subprocess destructor warning and two `Any` collection warnings.
They did not fail a gate. npm emitted existing dependency/deprecation warnings.

The full classified qualification was deliberately not repeated locally; the
request calls for the above gates and push-triggered CI. CI green and merge
remain the reviewer's decisions. No merge, deploy, running-service change or
active-desktop operation was performed.

## Artifacts and disk hygiene

Raw logs, XML, smoke JSON and screenshots are outside Git at
`/mnt/storage/odin-desktop-evidence/pr34-main3-20261006/`.
The committed artifact manifest records all 39 paths, sizes and SHA-256 values.
Final evidence commit adds only this summary, result and manifest after the
qualified execution commit; product/test bytes remain unchanged.

Root free space was 124 GiB before work and never below 118 GiB during observed
checks, above the 60 GiB floor. Only this request's standalone shared checkout
and scratch generation files are cleanup candidates after consumers exit and
pushed refs/evidence are verified. Other lanes and evidence directories are
untouched.
