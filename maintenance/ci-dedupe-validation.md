# CI qualification deduplication

PR #60. Tested code head: `840d383adf0e8b35e2bbcdc844cefb1d532e8c87`.
Main watermark: `da2d3d4adbc7864ed78ffb972e3792f8557fbcb2`, integrated by
two-parent merge, not rebase. This final evidence commit changes no code.

## Dependency and scope

**Draft, not merge-ready:** #52 was still OPEN at completion, head
`7e70bd1e6c90b3a3a527469a57a3d58eb7281bcc`. This implementation is available
for review now but the eventual post-#52 plan must be integrated and recollected
before readiness. No unrequested merge of #52 was performed.

The full-suites job runs the additional Desktop files once and the reviewed plan
groups once. The plan itself is byte-unchanged: every selector, reason and
exclusion is preserved. Exact collected node IDs overlapping plan groups are
owned by their first group, after normal pytest selection. Twenty-seven memory
cases were overlapping; they are not executed again in a later group. An earlier
group failure remains a failure, not a retry opportunity. Each group's indexed
JUnit receipt remains; extras now have their own receipt too.

The separately invoked Phase 2 checker was already in Desktop extras. The mocked
Desktop lab orchestration suite was likewise in extras and the fixture container.
Both additional replays are removed. The six test_lab suites still execute in
their non-root, no-network disposable container. Their actual execution was
validated, not moved to the host. CI short-gate fixture selections are unchanged;
exact-once is within each job, not across separate CI jobs.

The long-selection response-file path previously hid explicit `-p` loads from
pytest's early plugin loading. Plugin arguments now stay on argv while the same
remaining arguments go into the response file. Real response-file regressions
and the large collect-only groups validate this path. Isolation helper, privilege
drop, environment scrub, per-test timeouts and cancellation semantics are unchanged.
No concurrency or retries added. Main's 120-minute job bound is preserved.

## Real collect-only differential

Command: `.venv/bin/python scripts/ci-qualification-differential.py`.
This invokes the actual default and qualified scheduling code with real isolated
pytest `--collect-only` children. A collection-finish plugin records all final
selected node IDs, including items without Python function code. Both schedules
use the same candidate test corpus, including the new regressions, so test
additions cannot disguise a scheduling difference.

| Scope | Before occurrences | After occurrences | Unique before | Unique after |
|---|---:|---:|---:|---:|
| Requested pass-now union qualification | 29,720 | 14,979 | 14,979 | 14,979 |
| Whole full-suites Python schedule | 29,976 | 15,097 | 15,097 | 15,097 |

Requested union: removed `[]`, added `[]`.
Whole Python schedule: removed `[]`, added `[]`, after duplicates `{}`.
Before duplicate occurrences: 14,879. After: zero.

After step counts: extras 292, qualification 14,687, standalone checker zero,
container fixtures 118. All 31 qualification groups retain a receipt.
Fixture *collection* used the PID boundary since collection executes no fixture;
fixture *execution* used the unchanged dedicated Docker isolation.

The final differential took 640.137 seconds locally for both schedules combined.
That is collection proof time, **not measured CI job time**. No before/after CI
wall-time claim is made. Draft CI is intentionally skipped.

## Execution gates

- Focused scheduling/runner/maintenance: 131 passed, 7.23 seconds.
- Actual extras-only invocation: 292 passed, 53.34 seconds.
- Actual six-suite disposable fixture container: 118 passed, 2.91 seconds.
- Container and image cleanup verified for this invocation's exact generated IDs.
- `inventory.py record` used for every changed ledgered path and named-test
  digest refresh. Final `inventory.py report`: zero errors, review pending.
- Lint gate: zero new findings, seven inherited findings.
- Ownership checker, lab Ruff, actionlint 1.7.7 with explicit repository runner
  labels, and `git diff --check` passed.
- Static independent review checked ownership ordering, failure preservation,
  response-file plugins and lab ownership. Its requested-union exit-condition
  finding was fixed before the final differential.

Not run: a new full test execution of all plan groups, app gates, or hosted CI.
This scheduling-only request's required real collection and changed behavior
gates are complete. Full-suite runtime is not inferred from collection.

## Artifacts and cleanup

Raw evidence is outside Git at
`/mnt/storage/odin-desktop-evidence/ci-dedupe-req3c08/`.
The external manifest lists every artifact with its exact path, bytes and SHA256.
Small committed index: `maintenance/ci-dedupe-artifacts.json`.
This lane's fresh clone is removed after push. No other lane's checkout, cache,
evidence or running process is cleanup authority.

No attribution trailers, merge, publication, deployment, service restart or
active-desktop changes.
