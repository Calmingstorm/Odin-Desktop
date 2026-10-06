# CI qualification deduplication

PR #60. Latest tested code head: `2239dce0ad265fec31070b429364b2bfe48bf832`.
Main watermark: `f29ffc34900d3d0b4020740cadcc3baa033f668b`, integrated by
two-parent merge, not rebase. This final evidence commit changes no code.

## Dependency and scope

**Ready for review, dependency not yet merged to main:** #52 remains OPEN at
head `7e70bd1e6c90b3a3a527469a57a3d58eb7281bcc`. That exact head is now
integrated into this PR with a two-parent dependency merge. The combined plan
has been recollected and the merged behavior, accounting and app gates passed.
This PR must land after #52. No merge of #52 on GitHub was performed; if its head
changes before landing, integrate that head and repeat the affected proof.

The full-suites job runs the additional Desktop files once and the reviewed plan
groups once. The plan itself is byte-unchanged: every selector, reason and
exclusion is preserved. Exact collected node IDs overlapping plan groups are
owned by their first group, after normal pytest selection. Twenty-seven memory
cases were overlapping; they are not executed again in a later group. An earlier
group failure remains a failure, not a retry opportunity. Each group's indexed
JUnit receipt remains; extras now have their own receipt too.

The separately invoked Phase 2 checker was already in Desktop extras. The mocked
Desktop lab orchestration suite was likewise in extras and the fixture container.
Both additional replays are removed. Current main migrated its fixed fixture
wrapper from Docker to the repository PID launcher and bounded fixture user
namespaces. That reviewed migration is preserved, including its explicit
capability skips. Main's newly added lab-contract step also repeated the Desktop
fixture-wrapper tests; those now run only as extras. Actual fixture and lab
contract execution was validated. CI short-gate fixture selections are unchanged;
exact-once is within each job, not across separate CI jobs.

The long-selection response-file path previously hid explicit `-p` loads from
pytest's early plugin loading. Plugin arguments now stay on argv while the same
remaining arguments go into the response file. Real response-file regressions
and the large collect-only groups validate this path. Isolation helper, privilege
drop, environment scrub, per-test timeouts and cancellation semantics are unchanged.
No concurrency or retries added. Main's 120-minute job bound is preserved.

## Real collect-only differential, after integrating #52

Command: `.venv/bin/python scripts/ci-qualification-differential.py`.
This invokes the actual default and qualified scheduling code with real isolated
pytest `--collect-only` children. A collection-finish plugin records all final
selected node IDs, including items without Python function code. Both schedules
use the same candidate test corpus, including the new regressions, so test
additions cannot disguise a scheduling difference.

| Scope | Before occurrences | After occurrences | Unique before | Unique after |
|---|---:|---:|---:|---:|
| Requested pass-now union qualification | 30,098 | 15,162 | 15,162 | 15,162 |
| Whole full-suites Python schedule | 30,692 | 15,606 | 15,606 | 15,606 |

Requested union: removed `[]`, added `[]`.
Whole Python schedule: removed `[]`, added `[]`, after duplicates `{}`.
Before duplicate occurrences: 15,086. After: zero.

After step counts: extras 280, qualification 14,882, standalone checker zero,
fixed fixtures 163, additional lab contracts 281. All 31 qualification groups
retain a receipt. Collection and execution use main's current PID boundaries.

The final post-#52/current-main differential exited zero after 855.274 seconds locally
for both schedules combined. That is collection proof time, **not measured CI
job time**. No before/after CI wall-time claim is made. Initial draft CI was
intentionally skipped; review-ready CI is not substituted for local proof.

## Execution gates

- Combined scheduling/runner/part5 accounting and original-case adapters:
  425 passed, 135.78 seconds. Async teardown warnings were emitted after the
  passing part5 projection run; they are retained, not presented as clean stderr.
- Actual merged extras-only invocation: 280 passed, 34.44 seconds.
- Combined app `npm run check`: 764 passed, typecheck and build passed.
- Actual current-main fixed fixture wrapper: 159 passed, four capability skips,
  11.10 seconds. The four skips require two distinct subordinate UID/GID maps;
  the unchanged restricted helper's no-new-privileges boundary denies that map.
- Actual additional lab contracts: 281 passed, 7.11 seconds.
- `inventory.py record` used for every changed ledgered path and named-test
  digest refresh. Final `inventory.py report`: zero errors, review pending.
- Lint gate: zero new findings, seven inherited findings.
- Ownership checker, lab Ruff, actionlint 1.7.7 with explicit repository runner
  labels, and `git diff --check` passed.
- Static independent review checked ownership ordering, failure preservation,
  response-file plugins and lab ownership. Its requested-union exit-condition
  finding was fixed before the final differential.

Not run: a new full test execution of all plan groups or completed hosted CI.
This scheduling-only request's required real collection and changed behavior
gates are complete. Full-suite runtime is not inferred from collection.

## Artifacts and cleanup

Raw evidence is outside Git at
`/mnt/storage/odin-desktop-evidence/ci-dedupe-req3c08/`.
Post-#52 raw receipts and exact manifest are under `post52-proof/` there.
Final current-main integrated receipts and manifest are under `post52-main-proof/`.
The external manifest lists every artifact with its exact path, bytes and SHA256.
Small committed index: `maintenance/ci-dedupe-artifacts.json`.
This lane's fresh clone is removed after push. No other lane's checkout, cache,
evidence or running process is cleanup authority.

No attribution trailers, merge, publication, deployment, service restart or
active-desktop changes.
