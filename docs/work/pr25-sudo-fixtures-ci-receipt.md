# PR25 sudo fixture follow-up: stable CI receipt

The requested eight KDE ownership fixtures were implemented by Odin in PR49,
commit `20f885b81c7c698b1f009f4397823e90d1a7def2`, and merged externally in
`28642294d4f3dc079e525d5e9f2df16adeb756be`.

The fixed offline corpus passed locally with 265 passes and four explicit
capability skips. Four fresh ownership cases passed. Four ownership-retry
cases require distinct subordinate UID/GID mappings; the unchanged restricted
PID helper denies `newuidmap` under no-new-privileges. No fixture requires host
root, and no ownership-retry success is inferred from a second fresh emission.
All emitter and assertion failures remain failures, not capability skips.

Both short CI gates passed, but the original PR full-suite run hit its old
60-minute job deadline. Main now has a reviewed 120-minute bound. A single
`control.resume` response-header timeout at the fixture's three-second bound
did not reproduce in three isolated focused runs (15 tests passed).

Repeated main-branch merges cancelled subsequent full-suite runs before
completion. This documentation-only branch freezes main `efc5e20c` for one
complete CI receipt without changing production code, fixtures, test selection,
deadlines, runner configuration or isolation guards. Its PR must not be merged
while the receipt is being collected. CI results are recorded separately only
after all jobs have finished; queued or cancelled runs are not green evidence.
