# PR 2 round 4: code tests, not document wording

Scope: [review comment 5994319842](https://github.com/Calmingstorm/Odin-Desktop/pull/2#issuecomment-5994319842).
Merged main `0c9f9cffa43690eda1b177fb4cc5dce2d0113a84` first, including Aaron's
standing test rule in `CONTRIBUTING.md`.

## Removed and retained

- Deleted `tests/test_desktop_round3_approval_docs.py`, all **44 collected cases**.
- Deleted the round-2 approval-table-only test, **one collected case**.
- Removed Markdown reads and wording assertions from the mixed round-2 tests.
  Retained their actual request-preamble construction, frozen catalog schema/string
  comparison, exact C4 code labels, upstream governor/probe module byte checks,
  and machine-readable plan/ledger assertions. The two plan checks were renamed
  to describe their remaining scope; **eight cases remain in this file**.
- Kept inventory-tool tests consuming copied documents as real input, knowledge
  import/search tests, generated-output checks and machine-readable plan tests.
- Human approval/disposition tables and Phase 2 exit criteria remain review
  artifacts. Removing their wording tests does not approve or erase any NONE row
  or close a deferred runtime gate.

## Qualification selection and accounting

- Removed the deleted file from the existing Desktop-boundary qualification
  group. The plan still has **28 groups**; no inherited selection or safety/manual
  gate changes. Plan SHA-256:
  `6b05c2e8552a7ef302f6840cf88edb5072ece464906fddb14293d9060bcfe447`.
- Recollected all groups through the sanitized non-root PID/mount namespace:
  **28/28 groups**, **13,099 unique executable identities**. This is collection,
  not passing or full inherited-suite evidence.
- Refreshed `case-accounting.json`'s collection identities only. Its previous
  snapshot predated the round-2/3 acceptance and round-3 probe cases; the refreshed
  snapshot records the eight surviving acceptance cases and current owner/probe
  cases, and contains neither the removed file nor approval-table-only case.
  Every original historical/foundation disposition, mapping, digest and reason
  remains unchanged: **259 historical rows and 38 foundation suites**.
- Removed the deleted Desktop-only addition and its evidence reference from
  `desktop-deltas.json`; explicitly recorded the surviving code-test bytes and
  refreshed their named evidence hashes. Source patches remain unchanged and
  independent review remains pending.

## Observed validation, 2026-10-05

- Focused acceptance/owner/maintenance/qualification/collection/plan tests:
  **69 passed** in the sanitized namespace. The initial acceptance/owner run
  passed **39 cases** before collection/accounting refresh.
- Complete selected qualification: **28/28 groups**, **13,145 passed executions,
  two skips, zero failures/errors**. This is exactly **45 fewer executions** than
  round 3's 13,190 passing count, corresponding to the 44 documentation-only
  cases and one approval-table-only case removed. Counts include duplicate
  direct/adapter executions, not full inherited-suite or Phase 2 runtime parity.
- Offline drift: **1,237 shared paths, 196 exact ledgered paths, 201 pending
  independent reviews, zero unexplained errors**.
- Lint: **zero new findings**, seven inherited findings; `git diff --check` clean.
- Engine source, frozen inherited `test-plan.json`, baseline archive, manifest
  and safety manifest are unchanged. Existing warnings/skips remain visible.

Local receipts: `.test-state/pr2-round4-collection.log`,
`.test-logs-pr2-round4-qualified.txt`, `.test-state/pr2-round4-drift.json`, and
`.test-state/qualification-{0..27}.xml`. Hosted CI is a separate result.
No deployment, restart, live-profile operation, active-desktop input or PR merge.
