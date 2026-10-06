# PR40 current-main merge qualification

Request: `/home/odin/reviews/desktop-pr40-merge-main.md`.
Starting PR40 head was verified and pulled: `c635472a1d3353f0b36774865e83a38016db1cb7`.
Merged main snapshots with merge commits only, never rebase: initial
`85cfb86efa01a6b6010ca293776fe049a4586356`, then
`189bb77769a89a44fe308b65d6ab808f25882952`, finally the tested snapshot
`f14b773e238724f1e7ce253aac50d7a04865ad77`.

## Preserved contracts

- Step5 records, knowledge, learned context, observability, OpenRouter,
  trajectories, tools cost/risk and Codex refresh coexist with step6A
  skills/MCP/computer management and lifecycle ownership.
- Both real-core capability inventories contain 169 unique methods. Both
  smoke/refusal sets and all four real-core contract suites remain selected.
- Qualification groups are unioned, including the 28-file step5 group and
  eight-file step6A group. All 21 PR40 restored original suites retain their
  hash-bound full-corpus adapters. Later main case dispositions and closure
  tests are also retained.
- Ledger union is by path, with combined reasons/contracts/invariants and
  test-set union. `inventory.record` regenerated combined/stale records and
  every changed cited-test digest. Final report: zero errors; review remains
  pending, not silently approved.
- Main explicitly deleted three obsolete lab/ci files; their obsolete ledger
  entries were removed rather than resurrecting orphaned paths.

## Final local gates

All Python runtime tests used the repository's verified non-root PID namespace
runner, UID 1003, fresh HOME/XDG and no active desktop/session environment.
App gates ran as ordinary user odin; graphical gates use isolated Xvfb/dbus.

| Gate | Result |
| --- | --- |
| inventory report | 0 errors |
| lint gate | 0 new findings, 7 inherited findings |
| phase2 ownership plan | passed |
| phase2 suite-map check | valid, 0 errors; 21 step5 restored suites |
| short fixtures plus relevant later-main additions | 497 passed, 0 failures/errors/skips |
| management/runtime, step6A and PR40 restored suites, 38 files | 1,373 passed, 0 failures/errors/skips; 81 warnings |
| npm run check | typecheck/build passed; 924 tests in 94 files passed |
| npm run test:real-core | 31 tests in 4 files passed; 6 onboarding tests passed |
| real-core smoke | passed, 40 screen checkpoints |
| fixture smoke | passed |
| final smoke-edit typecheck | passed |

## First-run failures and limits

The first 38-file run had 1 failure and 1,372 passes: a step6A cleanup test
supplies its knowledge owner through runtime_context, whereas step5 adds a
direct deps owner. Cleanup now prefers the direct owner and falls back only
when absent, preserving early producer barriers and exactly-once closure.
The complete selection was rerun successfully after the fix and later merges.

The final-main smoke initially failed its obsolete disabled-browser assertion.
Main restored D17 enabled fresh-browser defaults and a truthful unavailable
retry seam for this unbundled profile. Smoke now asserts that exact unavailable,
not-ready, retry-available state, and the UI's unavailable panel. No native
success is inferred. The corrected full smoke and typecheck passed.

One local command lost its supervisor receipt after producing complete passing
intermediate logs. No process remained; final snapshot gates were run again.
Inherited aiohttp AppKey and AsyncMock warnings and Fontconfig cache warnings
remain visible. Inherited main evidence contains trailing whitespace; owned
resolutions pass diff-check. No unrelated inherited evidence was rewritten.

This is requested local integration qualification, not full classified/native,
packaging or release qualification. Keyring-unavailable and unconfigured
OpenRouter observations are explicit refusals, not credential/provider success.
No deployment, service mutation, live installation or active desktop mutation.
No action was taken on PR43. CI on push is separate from these local results.

## Evidence

Raw logs, JUnit, screenshots and smoke JSON are retained outside Git at
`/mnt/storage/odin-desktop-evidence/pr40-main-reqf0481233/`.
`pr40-main-reqf0481233-artifacts.json` pins SHA-256 and absolute paths, including
failed first-run evidence. Only this small summary and manifest are new evidence
committed by this task. Fresh clone is removed after a verified PR40-only push,
after confirming this task's exclusive ownership and process inactivity.
