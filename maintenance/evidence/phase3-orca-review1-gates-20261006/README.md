# PR #50 review-round-one merge gates

`main@f597c1af` was merged as `cbf7cdc2`, never rebased. Canonical PR #49
head `5e56015b` was merged as `f20203c8` while its base-branch merge was still
pending. The canonical runner, user-namespace helper, KDE fixtures and their
tests are byte-identical to #49; #50's duplicate ownership model was removed.
Later `main@2e310bc0` was merged as `6a99ee90`. That last merge adds only
ready-for-review/draft CI conditions and does not change tested engine/app
bytes. PR #50 remains draft; hosted CI skips are not passing qualifications.

Ledger conflicts were resolved by path against the final file digests, unioned
with `/home/odin/reviews/merge_ledger.py`, then stale exact bytes/test digests
were refreshed with `inventory.py record`. No hand-built patch chunks. The
small resolution logs and raw gate evidence are externally retained at
`/mnt/storage/odin-desktop-evidence/pr50-r1-merge-gates-20261006/` and mapped by
`artifact-manifest.json`.

Measured gates:

| Gate | Result |
|---|---|
| Exact-byte drift, no-new-lint, phase-two ownership plan | Passed; seven inherited lint findings, zero new |
| Maintenance/plan isolated tests | 56 passed |
| App `npm run check` | 80 files, 758 tests passed; typecheck/build passed |
| Ordinary-user `npm run test:a11y` | 15 passed; zero failed, flaky or skipped; owned PID/Xvfb/private-bus lane |
| Canonical fixed lab fixture corpus | 267 passed, 4 explicit skips |
| Orca/collector/probe/cleanup/CI isolated tests | 294 passed |
| Full engine qualification, once | 30/30 groups; 14,476 passing executions, 3 skips, zero failures/errors |
| Added CI conflict-resolution regressions after last main merge | 3 passed |

The four canonical fixture skips are the real retry cases: subordinate
UID/GID mappings are unavailable under the unchanged no-new-privileges
launcher (`newuidmap: write to uid_map failed: Operation not permitted`).
Single-ID fresh cases execute the real emitter. These are not eight mocked
ownership passes or permission-policy relaxation. Full qualification skips
are retained in the JUnit archive and are separate from those four cases.
The engine run emitted unawaited mock/slow-handler coroutine warnings and a
subprocess transport destructor warning. The complete log retains them;
they are not suppressed or presented as clean warning-free execution.

Full qualification started at `f20203c8`. Engine source, qualification plan and
isolation/qualification runners did not change afterward. The later changes
were evidence/docs, independent CI-selection regression tests and the
draft-CI conditions; the added tests were run separately. This is not a claim
that the final documentation commit existed before the engine run.

No VM matrix rerun. Only the requested single KDE comparison booted a guest;
its cleanup confirms all lab VMs stopped. No active workstation desktop or
`/opt/odin` change, merge of PR #50 into main, rebase or attribution trailer.
