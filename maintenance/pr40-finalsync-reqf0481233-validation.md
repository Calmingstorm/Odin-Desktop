# PR40 final current-main sync qualification

Request: `/home/odin/reviews/desktop-pr40-merge-main.md`.
Pulled PR40 `dc7a13f8303a00ecaf4ff2c8959bba4f4d9355e4` and merged
`b276b0b34c44c553ed1aa9042e716bf06395694f` with a merge, never a rebase.
This incorporates #71's D17 unknown-file-key restoration without changing
the previously integrated step5 or step6A management/runtime behaviour.
All five source/test paths changed by #71 remain byte-identical to main.
No source or test edits were needed for this sync.

## Ledger union

The ledger has 447 paths: 416 common, 30 PR40-only and one main-only.
All common test sets are unioned. Reasons/contracts/invariants preserve both
side values through superset containment; the sole conflicting settings reason
uses distinct-clause union and retains both exact originals in
`merge_reason_sources`. Seven relevant entries were regenerated with
`inventory.record`, including the changed tests and entries citing them;
their source/test digests were already freshened by Git's automatic merge.
Final `inventory.py report`: zero errors, 447 ledgered entries; review remains
pending, not silently approved. `git diff --check` passes.

## Final-source gates

| Gate | Observed result |
| --- | --- |
| inventory report | 0 errors |
| lint | 0 new findings; 7 inherited findings |
| phase2 ownership plan | passed |
| phase2 suite-map check | valid; 0 errors; 21 step5 restored suites retained |
| D19 disposition report | 0 errors |
| short fixtures/checkers and latest-main regressions, 17 files | 571 passed; 0 failures/errors/skips |
| management/runtime, step6A and PR40 restored suites, 38 files | 1,373 passed; 0 failures/errors/skips; 81 warnings |
| npm run check | typecheck/build passed; 924 tests in 94 files passed |
| npm run test:real-core | 31 tests in 4 files passed; 6 onboarding tests passed |
| real-core smoke | passed; 40 screen checkpoints |
| fixture smoke | passed |

Python tests used the repository's restricted PID namespace launcher as
ordinary user odin, UID 1003, with private HOME/XDG and sanitized environment.
App checks likewise ran as ordinary user odin, with the real-core namespace
launcher and private Xvfb/dbus for graphical checks. These are local requested
integration gates, not full native/package/release qualification.

The optional phase2 closure inventory remains not ready, with inherited parity
hash errors for `src/config/schema.py`, `src/config/sensitivity.py` and
`src/desktop/settings.py`, plus existing deferred obligations. The first and
third stale proof hashes are already present in main after #71; sensitivity
is a previously integrated PR40 change. This historical proof was not recaptured
or represented as fresh qualification. It is distinct from inventory.py report.
Inherited AsyncMock/aiohttp and Fontconfig warnings remain visible.
Keyring unavailable and unconfigured providers are explicit refusal states,
not successful credential/provider/native qualification.

## Evidence and boundaries

Raw logs, JUnit, screenshots and smoke JSON are outside Git at
`/mnt/storage/odin-desktop-evidence/pr40-finalsync-reqf0481233/`.
The adjacent artifact manifest binds every retained file with SHA-256 and path.
Prior evidence remains at `pr40-main-reqf0481233-validation.md` and its manifest.
CI state and the final pushed commit are checked separately after push.
No deployment, service changes, live desktop mutation or PR43 action occurred.
Only the task-owned fresh checkout is deleted after verified push and inactivity.
