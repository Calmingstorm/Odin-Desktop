# PR38 prerequisite-base merge

PR38 source parent: `089da3c4` on `app/p31-real-core-slice4`.
Merged prerequisite: PR28 `phase-2/services-part-a` at
`2d91071a692a646b6d8c466daa5711a37cd8c93f`.
This is a two-parent local merge, not a rebase or GitHub PR merge. No branch push
is part of this operation.

## Resolution contracts

- `app/src/main/real-core-smoke.ts`: keep main's real conversation creation,
  empty transcript and served-search checks; keep PR38 genuine skill Test,
  MCP, browser health and computer-management checkpoints. Refusals are only
  methods genuinely withheld by this core.
- `app/test/real-core-harness.ts`: preserve main's service capabilities and
  PR38's `skills.test` admission, owner scope, bounded durable receipt wait.
- `app/test/real-core-settings.test.ts`: preserve main's empty real skills/MCP
  and honest computer readiness checks; do not incorrectly require
  `skills.test` to be unavailable.
- No core source conflict required choosing one side. Main onboarding,
  keyring, browser/package readiness changes coexist with PR38 skill Test.
- `maintenance/desktop-deltas.json`: key union through
  `/home/odin/reviews/merge_ledger.py`. Joint metadata records were regenerated
  through `inventory.py record`, preserving both rationales, contracts,
  invariants and the union of named tests. Joint paths: `pyproject.toml`,
  `src/desktop/commands.py`, `src/desktop/core.py`,
  `src/desktop/management.py`, `src/desktop/mcp.py`,
  `src/discord/tool_catalog.py`, `src/tools/browser.py`, `uv.lock`.
  Three settings/model records additionally refresh the named merged app-test
  digest without changing their existing contracts or source-byte records.
- The uncommitted historical note in `p31-slice4-validation.md` is retained.

## Evidence boundary

Inventory refresh and short merge gates are not fresh full qualification.
Merge short gates passed: exact-byte drift has zero errors (review pending),
lint has zero new findings (seven inherited), phase-2 ownership plan passes,
app TypeScript/Vue typecheck passes, and `git diff --check` is clean.
All 330 independent record reviews remain pending, not manufactured approvals.
Parent-owned fresh post-merge gates and corrected skill-Test smoke evidence will
be recorded separately under `pr38-review1-validation.md`, backed by
`/home/odin/desktop-pr38-review1-evidence/`.

No lane7 checkout edits, live deployment, service restart or active desktop work.
