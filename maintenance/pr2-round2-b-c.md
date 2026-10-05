# PR 2 round 2: B and C

Scope: Claudia's review at
https://github.com/Calmingstorm/Odin-Desktop/pull/2#issuecomment-5987058604.
**A remains pending Aaron's exact wording decision.** No model-facing string, approved wording inventory,
prompt approval or safety policy was changed by this follow-up. Its required complete string-to-approval table
is still outstanding with A; this document does not claim that blocker is closed.

## B: Phase 2 corpus acceptance

`docs/design/roadmap.md` and `maintenance/test-plan.md` now require all **326 Phase-2-deferred suites** to return
in Phase 2, adapted to Desktop transport and never dropped. This includes the chat tool-loop characterization
(continuation, completion judge and nudges), deferred agent suites, recovery, tool-loop helpers and both Codex
replay suites. Every original case needs an execution/adapter mapping and qualified result; aggregate pass
counts, smoke substitutes and exclusion relabeling do not close the requirement. Existing safety/manual gates
and isolated-execution rules are preserved.

The exact sorted frozen deferred path set is SHA-256
`a4bcf41b3ee1660c991df903cccbda1583497c2ec01cea6bb2be6425ba43888f`.
`tests/test_desktop_round2_acceptance.py` checks its identity, count and matching classifications, as well as
both acceptance documents. No inherited suite, case, assertion or classification was changed.

## C: Governor suites and upstream evidence

`docs/design/maintenance.md` records the four governor suites' existing safety/manual gates, successful
upstream CI evidence against byte-identical baseline governor/imports, and the obligation to attach upstream
CI evidence when porting a governor change. A divergent governor import requires reviewed requalification of
only pure classification cases, not execution of mixed suites with destructive literals or a full-parity claim.

Observed upstream evidence: https://github.com/Calmingstorm/Odin/actions/runs/36951324132 reports completed,
success, at `cd7530906e9cfa10a0fa900247d7ce2a8bb33e25`. New static tests verify that
`risk_classifier.py`, `command_shapes.py` and `command_authority.py` retain the frozen archive's exact bytes.
They do not import or execute the gated governor suites.

## Validation

- Focused touched/maintenance/plan tests: **29 passed**, isolated PID namespace.
- Complete approved local qualification: **28/28 groups**, **13,127 passing executions, 2 skipped, 0 failures/errors**.
  Counts include duplicate direct/adapter executions, not unique cases or full Phase 2 parity.
- Qualification plan SHA-256: `6b05c2e8552a7ef302f6840cf88edb5072ece464906fddb14293d9060bcfe447`.
- Runner: `scripts/run-qualified-tests.py`, through `scripts/run-phase1-tests.py`; sanitized non-root PID/mount
  namespace, repository Python 3.12 environment, disposable HOME/XDG roots, no desktop/session/credential environment.
- Local logs: `.test-state/pr2-round2-focused.log` and `.test-state/pr2-round2-qualified.log`.
  JUnit receipts: `.test-state/qualification-{0..27}.xml`.
- Offline drift: **1,236 shared paths, 197 exact ledgered paths, 202 pending independent reviews, zero unexplained errors**.
  New test ledger entry is pending review, not self-approved. Seven inherited lint findings; zero new findings.
- Existing native-helper and missing-dependency-branch skips, plus inherited AsyncMock/timeout warnings, remain visible.

Design documents were committed on main, then merged into `phase-1/bring-over`. The new static acceptance tests
are included in the existing Desktop-boundary qualification group. No source/runtime behavior changes, live
install writes, services/restarts, active-desktop input, implementation merge to main or deployment.
Hosted CI for the follow-up is a separate result, not assumed from the local pass.
