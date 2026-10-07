# Issue 93: Exit during core startup

Implementation base: `aa3d61b` (main with #89, #94 and #95). No sub-agents,
skills, lab VMs, deployments, service restarts or active-desktop input.

## Core half

`CoreService.run` races its real startup task against the lifetime stop edge.
Interrupted startup gets bounded cancellation/settlement. Startup native secret
workers have an explicitly scoped tracker; cancellation retires only the await,
not the daemon or its observed outcome. Unsettled workers produce `unknown`
cleanup and retain profile ownership for entry containment/finalization.
A cancellation-resistant startup producer retains its store as well.
Ordinary transactional secret operations still settle before cancellation reaches
rollback. IPC callbacks do not inherit the startup-only exception. Settled failed
reads retain inert error types but are not falsely recorded as outstanding workers.

## App half

Exit retains initial connection-establishment retries during a bounded readiness
wait, then asks the ready core for `runtime.shutdown`. The original five-second
request budget includes both waiting and request receipt; expiration aborts the
wait and prevents late dispatch. Admission, ordinary command reconciliation and
replacement-core reconnect remain frozen. Never-ready startup still records
`unknown`, without a tool/input-release claim.

## Regressions and evidence

- Actual `CoreService.run`, withheld first and second hydration, SIGTERM with a
  real lifetime signal watcher: all four exact regression cases fail on main.
- Electron with real entry/core/transport and a harmless startup read withheld:
  ready-within-bound fails on main (`shutdownAccepted: false`), succeeds on the
  branch; never-ready remains `unknown`.
- EOF during asynchronous startup, cancellation-resistant producer ownership,
  late native read errors, inactive-scope transactional cancellation, app wait
  expiry/close/replacement fencing are covered.
- Final touched core/cleanup tests: 70 passed. Fresh-profile parity included in
  the separate 27-pass touched run. New tracker executable lines are covered;
  the narrower probe is not whole-project coverage (core 72%, secrets 51%).
- App: 1,054 unit tests; typecheck/build; 66 real-core contract cases and 6
  onboarding cases passed. Final source lifecycle E2E: 36/36 passed, including
  both new startup cases. Packaging: 109 passed, 30 prerequisite skips.
- A prior full lifecycle run had one direct-EOF containment failure. Its workers
  did settle. Investigation exposed incorrect accounting of a completed failed
  startup read as outstanding. Corrected that distinction; the four containment
  cases and the entire 36-case lifecycle corpus then passed. Earlier failed
  qualification evidence is retained, not presented as green.
- Final engine qualification: 38/38 groups, 19,313 passed / 3 skipped;
  additional Desktop 477 passed; offline lab orchestration 319 passed;
  fixture corpus 159 passed / 4 subordinate-user-namespace capability skips.
  Drift, lint, Phase 2 plan, D19 and closure inventories passed. Static closure
  readiness is an inventory result, not native acceptance or approval of the
  named suite deferrals. Ledgers remain pending independent review.

Artifacts: `/mnt/storage/odin-desktop-evidence/issue93-20261007/`.
`exit-during-startup-artifacts.sha256` binds retained files by exact digest/path.
Native logout timing in Cinnamon/GNOME/KDE is not requalified by this source
Xvfb/private-bus regression run. No native acceptance is claimed here.
