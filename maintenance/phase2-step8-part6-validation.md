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
- Later final targeted, short gates and single fresh full qualification receipts
  are recorded in the small artifact manifest and final result.

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
