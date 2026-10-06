# Task1: step8 part6, five frozen step7 suites

Stack: phase-2/webhooks #42 ebf2b083, merged with main ed006967 by parent
at 02f7e622. No repeated merge, deploy, restart, active desktop or LAN input.

Exact case artifact: `phase2-step8-part6-cases.json`. This is **83 definitions,
108 expanded cases**, with each frozen parameter AST, hash and explicit reason.
`phase2-step8-part6-collection.json` binds 33 restored aliases from actual
sanitized PID collection. Existing `case-accounting.json` links its hash;
`phase2_suites.py check/report` runs the additional exact disposition gate.
All five suite-map rows remain deferred. No whole-suite passing claim.

| Frozen suite | Definitions/cases | Restored | Retired | Deferred |
|---|---:|---:|---:|---:|
| Generated API reference | 11/36 | 0 | 4/23 | 7/13 |
| GitHub webhook | 27/27 | 19 | 6 | 2 |
| GitLab webhook | 29/29 | 9 | 6 | 14 |
| Native monitoring removal | 4/4 | 0 | 1 | 3 |
| Self audit fixes | 12/12 | 5 | 1 | 6 |
| Total | 83/108 | 33 | 18/37 | 32/38 |

Retirement authority is Claude's Task1 removed-surface direction, not an
invented Aaron approval or independent review. Independent review is pending.
Exact route/RBAC rows, Discord channel/default/schema rows, removed web setup
HTTP response, and Discord gateway health startup case alone are retired.

## Named blockers

- GitHub's two callback notification obligations require schedule-specific
  durable callback observation, not a synthetic global callback.
- GitLab auth/fail-close, event normalization and dispatch/configuration remain
  retained obligations despite absent ingress. Nine scheduler cases pass unchanged.
- Native migration/catalogue/health cases mix retained contracts with removed
  HTTP/channel setup. Missing exact projections are blockers, not retirements.
- Self-audit matching token literally asserts `correct-secret` against frozen
  `[REDACTED]`. No substitution is permitted. Three other auth cases require
  exact per-trigger projection. Two relative default-path cases differ from
  profile-owned Desktop defaults and stay deferred. Knowledge concurrency and
  explicit YAML path values pass unchanged.
- Generated reference offline/drift/CLI, provenance/docstring/no-execution and
  webhook inventory remain retained. Removed REST/RBAC spellings are not license
  to substitute route counts, recreate the listener or erase generator parity.

## Observed targeted evidence

- Existing webhook adapters and ingress: 161 passed.
- Initial unchanged retained projection: 14 passed, 2 failed (relative defaults).
  Those exact defaults are now named blockers, not changed assertions.
- First part6 retained/accounting plus existing adapter: 136 passed.
- Expanded targeted including suite map before final integration: 215 passed.
- Final integrated targeted: **254 passed in 58.14s**. Drift, lint, Phase2 plan,
  integrated suite/case accounting and diff checks passed.
- Earlier process-capacity rejection cleared on an ordinary later start. Parent
  created a fresh 0775 checkout at `f9d06c2f`. An initial launcher invocation
  errored before pytest ran because plain frozen sync omitted the dev extra.
  That failure remains retained, not counted as test execution. Installed the
  locked dev extra and checked pytest before the single executable full run.
- Final fresh executable full run completed all 30 groups: **14,864 passed,
  1 failed, 3 skipped**. **29/30 groups passed; the full gate is not green.**
  The unchanged `test_schema_write_event_and_stale_binding_over_transport`
  timed out on the 3-second IPC read for `settings.set`. A separate targeted
  execution of that unchanged case passed in 7.15 seconds. The earlier cause
  is not established; that diagnostic does not replace the failed full gate.
  No second executable full run, assertion weakening or deadline change.
- Setup, failure, complete qualification and diagnostic receipts are SHA-256
  pinned in `phase2-step8-part6-artifacts.json`. Actual execution used the
  restricted sanitized non-root PID helper. Disk remained above 60GB free.

No frozen test bytes, assertions, data, parameter decorators or production
features were rewritten. Selected retained bodies are compiled unchanged from
the archive. Their complete projected class AST is independently checked.
Warnings are not suppressed. This is accounting, not Phase2 closure or native
desktop qualification.

Raw evidence is outside Git under
`/mnt/storage/odin-desktop-evidence/lane5-step8p6-s6-20261006/task1/`.
The artifact manifest also pins both parent merge stage ledgers. Shared work is
not cleaned without parent authorization; only this lane's inactive fresh clone
may be removed after push.
