# Gates under parallel load, 2026-10-07

Base: `aa3d61b3043ea47805686c185133a53c54b127fc` (latest main before branching).
Scope: real-core test scheduling and containment fixture/readiness observation.
No production behavior, isolation helper, API-lane files, gate ratchets, retries
or test skips changed. No running service, VM or workstation desktop changed.

## Real-core suite

Cold engine starts and first-use imports accumulated in one serialized eight-file
suite. Measured baseline wall times were **597.87s and 471.54s**, both 66/66 passed;
the first left essentially no margin against the existing 600s gate bound.

An initial three-concurrent-shard experiment took 219.15s, 173.12s and 134.18s,
but **one of three failed** on workProof's existing 12s manager-admission deadline.
That design was rejected rather than loosening the deadline or retrying failures.

The final scheduler partitions the same eight files into four isolated shards:
contracts, settings/completion, services/webhooks/skills/renderer run concurrently;
workProof runs after that wave drains. Every file remains internally sequential.
Each shard invokes the unchanged namespace launcher with its own HOME/XDG/profile.
First failure cancels siblings and waits for actual launcher exits; failed work is
never replayed. Explicit selection, file reporter, coverage/cache and watch
overrides are refused, so CLI flags cannot shrink the gate or lose shared output.

Final repeated wall times: **193.85s, 157.48s, 166.41s, 146.44s; 0/4 failures,
66/66 each**. Maximum shard was **134.624s**. Per-shard cancellation bound is 300s;
the original **600s aggregate** spans both waves, including namespace probes.
Individual test/hook/startup deadlines and CI's 120-minute job bound are unchanged.
Bounds initiate cancellation; actual cleanup exit is awaited, not assumed.

Unit/config/unchanged-launcher tests: **92 passed**, including fourth-wave signal
and aggregate-deadline cancellation. A real namespace probe verified
four distinct PID namespaces/HOMEs, non-root identity and sanitized display/session
environment. A real exit-7 probe cancelled two live sibling namespaces, awaited
their exits and did not admit the fourth shard.

## Containment admission

The old 15s poll included cold imports/profile construction, then accepted
descendant effects before registry admission and core startup had completed.
The fixture also created an empty `admitted.json` as its restart fence before
awaiting registry admission. Instrumented runs exposed two empty-JSON races.

Fix: separate exclusive `admission.fence` from atomically published completed
`admitted.json`; retain monotonic startup/admission stages and actual failure
diagnostics. Cold setup through original composition uses the existing harness's
45s cold-start observation budget. Registry admission, completed core start,
live identities and escaped effects retain a separate **15s** observation bound,
anchored to the actual composition timestamp, not delayed poll observation.
Recorded failures, child/spawn failure and supervisor death fail immediately.
The **15s EOF and 12s settlement bounds are unchanged**. Successor tests verify
the receipt still belongs to the original admission, not just an evidence label.

| Batch | Passed | Direct EOF test min / median / max |
|---|---:|---:|
| Unchanged baseline | 18/20 | 8.391 / 9.521 / 24.520s |
| First fixed policy, load approximately 15–21 | 20/20 | 7.315 / 8.661 / 16.251s |
| Final actual-stage deadline | 20/20 | 6.832 / 7.473 / 9.452s |

Baseline failures: one admission timeout and one known EOF-during-startup exit 1.
Diagnostic old-policy runs were 6/10: two empty-marker races and two premature-EOF
failures. They are retained, not folded into successful fixed-policy measurements.
Final anchored setup max was 3.165s, compose-to-ready/effects max 0.594s and actual
registry start max 0.160s. Five complete containment repeats passed; final suite
after all refinements was **11/11**. No #96 production fix was copied into this PR.

## Validation and evidence

- Full app check: **1,096 passed**, typecheck/build passed.
- Engine qualification: **38/38 groups passed, 19,313 passed / 3 existing skips**;
  warnings remain visible.
- Additional Desktop: **470 passed**.
- Hermetic Cinnamon/GNOME fixtures: **38 passed**.
- Offline orchestration: **281 passed**; fixture corpus **159 passed / 4 existing
  capability skips** (subordinate mappings unavailable under unchanged isolation).
- Short drift/lint/ownership/D19/closure gates passed on the final tree.
- Full isolated lifecycle E2E: **41/41 passed**. Onboarding: **6/6 passed**.
- Independent static review found no blockers. Timing-report correction for
  setup preceding observation was fixed and regression-tested.

These are naturally busy-host observations, not controlled identical-load
benchmarks. Baseline timeout had no stage instrumentation, so its exact delay
cannot honestly be assigned retrospectively to a specific import/hydration call.
No claim that production startup itself was accelerated. Final anchored admission
batch had lower load than the first fixed batch; both ran concurrently with work.

Raw logs, reports and traces are outside Git at
`/mnt/storage/odin-desktop-evidence/ci-load-20261007/`.
`gates-under-load-20261007-artifacts.json` records retained artifact paths and SHA-256.
Hosted CI is **BLOCKED**, not passed. On 2026-10-07 at approximately 18:35 UTC,
GitHub reported workflow `374882115` (`phase1-engine.yml`) as `disabled_manually`.
PR #101 has no check runs, and its check watcher exited because there were none.
The workflow was not re-enabled and no runners or another lane's CI were changed.
Local source gates above do not substitute for the task's required hosted pass.
