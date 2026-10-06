# PR28 step 1: merge main without rewriting either ancestry

Scope is workorder step 1 only. Merged main
`4ea7aa0f3b423a301854a9f0bdd2a46bc92d9d7b` into
`a1842227` on `phase-2/services-part-a`. No PR merge, deployment,
live-service write or active-desktop operation was performed.

## Conflict resolution

- Core retains main's shared settings, engine, request/delivery/control stores,
  publication outbox and resume/recovery path. It also retains 6A's early parent
  observation and cancellation-safe qualification before listener publication.
- Management uses the engine's executor, provider, host registry, scheduler,
  context and catalog, not parallel owners. The skill wrapper shares the raw
  manager, with the profile keyring config store installed at construction.
- Profile browser construction uses the qualified 6A runtime, retaining retry
  readiness and restart-only config behavior. Management owns its retirement;
  failed composition still has an engine fallback close. Cleanup aggregation
  and engine-owned provider/SSH exclusions survive the merge.
- MCP management reuses an injected runtime manager where present. Its tools
  enter the request catalog only when that same manager is already bound for
  dispatch. This merge does not implement Part-B dispatch or `skills.test`.
- Receipt tests retain both served-result and served-6A read classification,
  leaving only genuinely unavailable methods in the cheap-refusal selection.
  The 6A transport test now recognizes main's served `submission.send` and
  asserts shared executor/skill/catalog/browser ownership.
- Ledger union used `/home/odin/reviews/merge_ledger.py`. Twelve jointly changed
  paths were regenerated with `inventory.py record`, combining both sides'
  rationale and tests. Additional changed source/test digests were regenerated
  with the same drift tooling. Independent approval remains pending.

## Actual fresh-checkout evidence

Final executable/test/ledger tree was tested at candidate
`c1ab8b42` in
`/home/odin/reviews/pr28-step1-evidence/qualification-parent/final`.
The eventual merge commit adds only this validation document to that tree.
Fresh Python 3.12.3 copied-interpreter venv; `uv sync --locked --extra dev
--link-mode copy`; checkout and parent verified mode 0775. Test launcher uses
isolated PID/mount namespaces and empty environment with disposable HOME/XDG,
no display, session bus or live credentials.

- Drift report: zero errors, 320 pending independent-review entries.
- Lint: zero new findings, seven inherited findings.
- Phase-2 ownership/plan checker: exit 0, honest `planned-not-implemented` state.
- Core transport group: 567 passed on final serial recheck, one inherited
  subprocess event-loop-close warning.
- Profile management group: 303 passed.
- Step-6A qualified local services group: 166 passed.
- Conflict-touched request/resume/delivery/conversation/control/attachment/
  artifact/transcript/tool-detail/notification/phase2-plan suites: 327 passed.

This is targeted merge validation, not the full 31-group qualification.
Initial failed runs are preserved. They caught browser close/shutdown ownership
and an obsolete unavailable-submission assertion. One final overlapping run
hit the existing three-second listener deadline at parameter 509: 566 passed,
one failed. With no code or assertion change, the entire core transport group
was rerun serially and passed 567/567. This is evidence of a timing-sensitive
gate, not proof that its underlying timing risk is eliminated.

Raw logs, ledger merge inputs, short-gate JSON and XML are under
`/home/odin/reviews/pr28-step1-evidence/`. Final logs:
`final-conflict-groups.log`, `final-core-serial-recheck.log`;
XML under `qualification-parent/final/.test-state/`.
Existing untracked `.venv` in the work branch remains unchanged.
