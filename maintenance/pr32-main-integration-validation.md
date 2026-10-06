# PR #32 main integration validation

Validated 2026-10-06 in `/home/odin/desktop-p33-part1`, branch
`app/p33-lifecycle-part1`. The earlier sections below describe historical pins.
The final authorized main30 integration at the end adopts accepted PR #30 through
main, after its actual merge. No rebase, PR merge, deployment or live restart.

## Exact history and integration decisions

- Initial branch: `d1348792d0c1121d6ad5c130433a54d3c64a09be`.
- First fetched main: `d546c44c29388225015f20747c55930413b03f75`.
  Merge `6d8c1e04df396a354def3e0ea83354aba00f4a59` has those branch/main
  commits as its first/second parents.
- Main advanced with controls PR #23 during validation. At the parent's explicit
  direction, merge `240dd3915b991a7394fe0166aaa1a6b14bdd092d` incorporates
  `4ea7aa0f3b423a301854a9f0bdd2a46bc92d9d7b`, with first parent
  `6d8c1e04df396a354def3e0ea83354aba00f4a59`.
- Earlier controls-pin tested source commit: `382f1d54b198f3677073f2bb625a11d9cf8efbad`.
  Its evidence-only commit was `2bcb964b510597bebe9f878664ebe81d8f3ff4dd`.
  The subsequent authorized packaging-pin integration is recorded below.

Preserved main's conversations, requests, transcripts, delivery/publication,
attachments, artifacts, search, control/steer/resume and shared settings/runtime
owners. Preserved PR #32 quiescing, unknown cleanup notices, acknowledgment,
native quarantine/no-replay and exact descendant ownership barriers.

The merged engine now retains original native/process cleanup results exactly
once after request and producer settlement. Management reuses those receipts,
never repeats engine-owned shutdown or invents `not_started` for an uncompleted
barrier. Failed request settlement preserves graph storage and profile ownership.
Failed engine cleanup also attempts durable unknown classification but does not
release graph/profile ownership. Unknown native/process cleanup stops transport
and turn-store teardown. Shared services are not closed beneath live producers.
Eleven added engine/bridge tests plus one core failure test exercise these paths.

Historical negative-control E2E uses the exact pinned historical core together
with its exact historical management, rather than mixing an old compose API with
today's request-enabled core. The dormant native qualification fixture binds the
same original owner into the shared engine dispatcher, not a replacement owner.

## Strict ledger handling

Read `/home/odin/reviews/merge_ledger.py` before use. Each original strict union
refused deliberate double changes. Temporary inputs omit only the named
double-change entries from all three sides; the supplied strict script unions
every remaining key. Existing `inventory.record`/`finalize_records.py` regenerate
the deliberate entries from final bytes, preserving both sides' concrete
contracts, invariants and test witnesses, pending independent review.

- First integration double changes: `src/desktop/core.py`,
  `src/desktop/management.py`, `src/desktop/runtime.py`.
- Controls integration double changes: `src/desktop/core.py`,
  `src/desktop/management.py`, `src/desktop/services.py`,
  `tests/test_desktop_request_core.py`.
- Explicitly refreshed changed evidence-test digests for their named dependent
  records. No blanket source recapture, upstream corpus rewrite or review approval.

Original three inputs, refusal logs, strict union outputs and explicit plans are
retained under the external evidence directory's `ledger/`, `controls-ledger/`
and `final-evidence-plan.json`.

## Final gate results

External evidence root: `/home/odin/pr32-main-integration-evidence/`.

| Gate | Result | Evidence |
| --- | --- | --- |
| Offline drift | `errors: []`, archive verified, byte-drift-clean-review-pending | `short-gates-passed.log` |
| Lint | zero new findings; 7 inherited findings remain | same |
| Phase 2 plan | passed; ownership coverage only, not runtime qualification | same |
| `npm run check` | typecheck/build passed; 664 tests, 72 files | `app-check.log` |
| `npm run smoke` | fixture Electron smoke passed | `app-smoke.log` |
| `npm run test:real-core` | 21/21 passed, 2 files | `app-test-real-core.log` |
| `npm run smoke:real-core` | 39 checkpoints; all 37 prior management checkpoints retained/adapted plus provider-failure and transcript-search checks | `app-smoke-real-core.log`, `fixture-smoke-evidence.json` |
| `npm run test:a11y` | 15/15 passed | `app-test-a11y.log`, `a11y-report.json` |
| `npm run test:e2e` | 29/29 passed, zero retries/skips | `app-test-e2e.log`, `e2e/playwright.json` |
| Core/request/control/resume Python selection | 682 passed in 272.85s; no failures/skips | `core-request-controls.log`, `core-request-controls.xml` |
| Whitespace | working delta and delta against pinned main passed | `git diff --check`, `git diff 4ea7aa0f --check` |

The Python selection covers `test_desktop_core*`, `conversation*`, `request*`,
`management*`, `runtime*`, `*control*`, `*resume*`, resource cleanup, engine
services, delivery, artifacts, attachments, tool details, transcript, native
history binding, persisted outputs, receipt retention, stripped loop,
command/event journals, lifecycle qualification, plan behavior and the actual
retained runner characterization adapter. The exact launcher/arguments and JUnit
case identities are retained externally.

All tests ran as unprivileged uid/gid 1003 (`odin`) behind an isolated PID
namespace. App check/fixture smoke also use the project's namespace launcher.
Graphical tests use private Xvfb and throwaway HOME/XDG, no workstation display,
profile, credentials or bus. Existing project dependencies only. Long runs used
`manage_process`, streamed tee logs, bounded polling and verified process exit.
Accessibility's private bus emitted portal/FUSE/wsdd warnings; its 15 cases passed.
No live install, configuration, account, service or active desktop was changed.

## Transparent earlier failures

- Initial merge: 587 Python passed, 664 app passed, 15 a11y passed; real contracts
  and smoke exposed stale conversation/capability expectations. Lifecycle was
  28/29 because the historical management fixture received new `settings=`.
  Exact historical-core pairing fixed the negative control; focused rerun 1/1.
- Added engine/native regression test had a double-close in its own teardown:
  598 passed, 1 failed. Fix preserves ComputerStore's non-idempotent close contract.
- Short gates exposed unsorted imports and stale named evidence digests; fixed
  with explicit pending records, not waived findings.
- First controls app run exposed `request.resume` versus actual `control.resume`
  and stale capability count 87 versus 90. Corrected the expectations; all final
  app gates reran together successfully. That run's lifecycle also passed 29/29.
- Earlier evidence remains in `initial/`, `controls-first/`, `baseline-fix/`
  and the explicitly named intermediate core/short-gate logs.

## Limits and later integration

This is requested touched-suite/source-build validation, not full engine or
release qualification, native Secret Service, Orca/AT-SPI, Wayland or packaging.
Ledger explanations remain pending independent review.

During the earlier controls-pin app run shared `origin/main` advanced to packaging PR #24
`5ba8d6dfcacce9eff823af2596290bc417897e0e`. That later packaging main is not
included in those earlier results; the subsequent explicit continuation authorized
that exact packaging pin, now integrated as recorded below.

A read-only `git merge-tree` probe with updated PR #30 head
`c605de481e22e84c83e5d0313a75f8e9ae14195e` reports conflicts in Playwright
configuration, real-core smoke, ledger and runtime. Neither branch's ancestry was
changed by that probe. Whichever PR lands second needs another main integration,
retaining #30's off-loop keyring/provider startup together with this lifecycle
cleanup graph. Probe evidence: `pr30-overlap-probe.txt`.

## Evidence SHA-256

```text
9344e8efcae8e69aa17c8ecc894bd5f6c453187179c4cc998e86f8e87a3444cb  short-gates-passed.log
6e71d118381d4c022b299be826a4b0b0e880136a3797df33f8b9c88eb2e60d4b  core-request-controls.log
e87e0a3697c5d617ec0b25718e129f0e49cce635ca1b4a401ea046723b33b4d4  core-request-controls.xml
72d7ec9b6a78399eb66008602aa4da341ceb05d16c7f8f376427854057065ba9  app-check.log
79f4a311e73aaf7da1fb3c7660762d5115e3b74822aab88869e568befc12e7b5  app-smoke.log
ed030a46a4020c874a4742d5020a0550d364b7ca55f45b63145ad9dd81e2fd07  app-test-real-core.log
57d3957693f247fb497a51faf633d7127ae24e545ab6736fe662376bb008e9f6  app-smoke-real-core.log
cfe140f3ad7b9835bca6ba7e85a2196a8937901b3d68cb7651c517ef6f34af77  app-test-a11y.log
423fe93698ad139b164c3bfb3f6fd4b53e91e46f66464b1478ec446f90794240  a11y-report.json
3fe6fb35f726dccf38a157eb732027c7c0db6ccdfacdabb06a0f7de937c7bed3  app-test-e2e.log
e3eb929354c9eb8a9af08c63f6c4f3fcb3cda4a4b542b4bc9811885d3a603b2b  e2e/playwright.json
```

## Authorized packaging-pin continuation

The requested fixed main is `5ba8d6dfcacce9eff823af2596290bc417897e0e`.
Merge commit `21513a9029cbff9a69472116a07f2259c61b2ae3` has first parent
`2bcb964b510597bebe9f878664ebe81d8f3ff4dd` and that exact main as second
parent. This is a proper merge, not a rebase. All pre-existing app scripts remain,
including lifecycle `test:e2e`, alongside the added packaging scripts. No PR #30
ancestry was adopted, and this agent did not merge either PR. Read-only remote
observation during validation showed main at the fixed pin. The post-push check
then observed main advanced to `ddd054fe399fef46dd64b6e8ec95b2676af8f09f`.
That future movement was not adopted or qualified; the requested pin stayed fixed.

Only `app/package.json` and the ledger conflicted. The original supplied strict
ledger union refused the sole double-change record `src/desktop/providers.py`.
The explicit plan removes only that record from the three temporary union inputs,
unions all other records with the supplied strict script, and rerecords providers
from final bytes using `finalize_records.py`. Both sides' reasons, concrete
contracts, invariants and named test witnesses are retained; no approval is
invented. Providers' executable bytes, and all core/runtime/management bytes,
are unchanged by this packaging merge. The prior 682-pass core/request/control
selection therefore remains historical valid evidence, not a claimed fresh rerun.

New external evidence root:
`/home/odin/pr32-main-integration-evidence/packaging-pin/`.
Original ledger inputs, refusal, union and explicit rerecord plan live in `ledger/`.
Both bounded runners and their exact arguments are retained in this root.

| Gate | Final observed result | Evidence |
| --- | --- | --- |
| Offline drift | archive verified, `errors: []`, review pending | `drift.log` |
| Lint | zero new findings, 7 inherited | `lint.log` |
| Phase 2 plan | passed; ownership coverage only | `plan.log` |
| `npm run check` | typecheck/build passed; 666 tests, 72 files | `app-check.log` |
| `npm run smoke` | fixture Electron smoke passed | `app-smoke.log` |
| `npm run test:real-core` | 21/21, 2 files | `app-test-real-core.log` |
| `npm run smoke:real-core` | 39 checkpoints, ready real core | `app-smoke-real-core.log`, `fixture-smoke-evidence.json` |
| `npm run test:a11y` | 15/15 passed | `app-test-a11y.log`, `a11y-report.json` |
| `npm run test:e2e` | 29/29 passed, zero retries/skips | `app-test-e2e.log`, `e2e/playwright.json` |
| New packaging/resource/PDF regressions | 210 passed in 61.65s, zero skips | `packaging-regressions.log`, `packaging-regressions.xml` |
| Packaging behavior unittest | 39 passed, zero skips | `packaging-behavior.log` |
| Whitespace | working delta and fixed-main delta passed | `git diff --check`, `git diff 5ba8d6df --check` |

The 210-case selection covers standalone runtime, models, helper closure, Chromium
runtime/staging, PDF first-use resource/catalog behavior, distribution, retained
history/strip boundaries and core search/entry/lifecycle/providers. The 39 unittest
cases also exercise real disposable namespace masking, first-start SSH keygen,
and real dpkg maintainer-script execution inside a throwaway root, never host
package installation. These are regression proofs, not a new candidate build,
release qualification, full engine qualification or native desktop acceptance.

All engine/process tests used isolated PID namespaces and unprivileged odin
uid/gid 1003. App graphics used private Xvfb and throwaway HOME/XDG, with no live
display, profile, credentials or session bus. `manage_process` started normally;
both runners completed exit 0 with streamed tee evidence and bounded polling.
No arbitrary processes were killed. No live service, desktop or account changed.

Environment sync used only this repository's `.venv` and `app/node_modules`:
`uv sync --locked --extra dev` rebuilt the editable engine, installed locked pip
26.2.1, and removed PyMuPDF as required by the new optional-PDF production boundary.
`npm ci --ignore-scripts` installed the locked graph, followed by pinned Electron
installation. npm reports 11 inherited audit findings (10 high, one critical);
no dependency upgrade or audit fix was attempted. Accessibility's isolated bus
emitted portal/wsdd warnings but all cases passed. The initial drift invocation
used unsupported `--offline`; corrected plain `inventory.py report` is itself
offline and passed. No executable/test fixes were needed for the final gates.

PR #30/#32 overlap still requires integration when whichever PR lands second
encounters the first one's new main. This continuation does not merge them.

### Packaging-pin evidence SHA-256

```text
4e765f6934e04e446c90c7dc38fb4dce7e386edb12e080d8d715c191267a8493  drift.log
9d34ab5bc2efad4fadb7e30a2f0674d4426c54769eed8fb7fe58b6cfe61c4584  lint.log
ee20850a561b355e8240ab57ec1ff604439ca4f5322807e31a00dbd9139f2a48  plan.log
dc31c85f450d281bf3f46fc4461e50e044729fc7c6c4d8451027931777adf3aa  app-check.log
d036b15443a6748a6f1b243f8d929d93b76b77dbf6ac09866b2ec0d55afde781  app-smoke.log
fd4fcdf4d05b84101b912f9724d6c885ccc979d5ddc02a0f4efd105132d99200  app-test-real-core.log
c2a451fcb4cb45bafba98b6b2bd50c90f826a2a7acdf77a08c4f5ee34d5e388c  app-smoke-real-core.log
b4b20fb8c702f76abaf96be7e7e58965e02071b216b3d44bfcfeedc43c083df2  app-test-a11y.log
193b268ec971017bbf3f8c82f2bb4873c56fe054f50a7ef1f6bbdc0277721426  a11y-report.json
acfd6f4a706b4f69bbe5b2384839bad386c347d5b40e57ed2355f36b7d6a4fa8  app-test-e2e.log
af08797ee89fedbebd9d58fcfa069a343208ad594deee7b98d14a4b107bef601  e2e/playwright.json
57cffd7bc1c2997879f42e03b13198fdfa7d4f2c05a09d17eae53b666cc32f43  packaging-regressions.log
13c078f4a9452cbc02ee51d66b8724e21a0024ec1db60425c0e73336566bebb9  packaging-regressions.xml
40b58bf1d50f2527928ef5401a1ecb27cb68263c39ed357d4508ac393e5798a8  packaging-behavior.log
```

## Final authorized main30 integration

After Aaron merged PR #30, the parent explicitly authorized fixed main
`ddd054fe399fef46dd64b6e8ec95b2676af8f09f`. The final proper merge has first
parent `d6b348587fd47c68d91508ef43fb54fe2f9a7655` and that exact main as
second parent. No rebase or stacked unaccepted PR was introduced. Remote main
was still at the fixed pin after all gates; unrelated later changes were not adopted.

### Source and conflict decisions

- Playwright retains the five lifecycle spec lanes and accessibility isolation;
  onboarding remains in its separately owned Vitest/Electron runner, invoked by
  `test:real-core`. All lifecycle and onboarding app scripts survive.
- Runtime publishes both async keyring-backed `first_run` and the original
  `resource_cleanup` journal projection. Unknown native/process receipts remain
  unknown, no effects-undone claim, no replay or replacement cleanup owner.
- Core, management and engine services auto-merged, then were compared critically
  against both parents. Accepted main's off-loop settings hydration, startup vault
  reads/client construction, `engine.initialize_profile_provider`, async readiness
  and initial status-before-listener exposure survive. SQLite remains loop-owned.
- Durable explicit-only `secrets.unlock` keeps prompt-only serialization release,
  cancellation-safe reacquisition and original receipt replay. Lifecycle request
  and producer settlement still gate original-owner cleanup; unknown barriers stop
  transport/turn-store teardown and retain graph/profile ownership.
- Real smoke retains all 39 lifecycle-branch checkpoints, served persisted
  conversations/search and provider-failure assertions. Its expected capability
  union now includes `secrets.unlock` (91 names), plus actual first-run readiness.
- Added one async runtime test proves repeated readiness refresh preserves the
  durable unknown cleanup projection unchanged. The real keyring-core test now
  checks both projections together on the same status route.

The supplied `/home/odin/reviews/merge_ledger.py` refused double changes. Only five
named entries were excluded from temporary strict-union inputs and regenerated
with the existing drift tooling: `src/desktop/{core,management,providers,runtime,
services}.py`. Both parents' contracts, invariants and evidence witnesses survive.
Changed first-run/keyring behavioral evidence digests were refreshed only for
their explicitly dependent records. No blanket recapture or invented approval.
Original three inputs, refusal, strict union and explicit plans are in `ledger/`
under the evidence root below.

### Final fresh gates

External evidence: `/home/odin/pr32-main-integration-evidence/main30/`.

| Gate | Observed result | Evidence |
| --- | --- | --- |
| Offline drift | `errors: []`, archive verified, review pending | `drift.log` |
| Lint | zero new findings; 7 inherited | `lint.log` |
| Phase 2 plan | passed, 122 modules; ownership coverage only | `plan.log` |
| `npm run check` | typecheck/build passed; 693 tests in 75 files | `app-check.log` |
| `npm run smoke` | fixture Electron smoke passed | `app-smoke.log` |
| `npm run test:real-core` | 21 actual core contracts + 6 actual Electron onboarding cases passed | `app-test-real-core.log` |
| `npm run smoke:real-core` | all 39 checkpoints passed | `app-smoke-real-core.log`, `fixture-smoke-evidence.json` |
| `npm run test:a11y` | 15/15, zero skips/flaky/failures | `app-test-a11y.log`, `a11y-report.json` |
| `npm run test:e2e` | 29/29, zero retries/skips/flaky/failures | `app-test-e2e.log`, `e2e/playwright.json` |
| Core/request/control/lifecycle/keyring/first-run Python selection | 769 passed in 232.99s; zero failures/skips | `python.log`, `python.xml`, `python-selection.txt` |
| Secret-domain off-loop regressions | 9 passed in 3.91s; zero failures/skips | `secret-domain.log`, `secret-domain.xml` |
| Journals, IPC, artifacts and retained stripped loop | 164 passed in 8.76s; zero failures/skips | `journals.log`, `journals.xml` |
| Whitespace/conflicts | working and fixed-main delta clean; no unmerged entries | Git diff checks |

Total fresh Python cases: **942** across disjoint selections. Exact bounded
launchers/arguments are retained as `run-{app,python}-gates.sh`,
`run-secret-domain-gate.sh` and `run-journal-gate.sh`. Python/process tests ran as
unprivileged odin uid/gid 1003, isolated PID/mount namespace, disposable HOME/XDG,
no inherited desktop display/bus or profile. App graphics used private Xvfb and
owned session buses. Long jobs streamed tee logs and exited 0 under bounded
`manage_process` polling. Existing project-local dependencies sufficed; no refresh
or system install was needed. Accessibility emitted isolated bus/portal warnings
without failures. One added test initially exceeded the line-length gate by one
character; wrapped it and reran drift/lint/plan before all final gates. No test
weakened, disabled or skipped.

Independent technical source review found no concrete merge blocker in the stable
final executable tree. This remains source/touched-suite integration, not native
prompt acceptance, live provider generation, full engine or packaging/release
qualification. Native platform part-2 rows remain open. No live service, install,
account, workstation desktop or PR merge was changed. Commits have no attribution
trailers; the branch is pushed normally, never force-pushed.

### Main30 evidence SHA-256

```text
f5e6c59e127852b8fc5cf1dee0c2332f6fa634c0c799538c63e17dd66865ce6c  drift.log
9d34ab5bc2efad4fadb7e30a2f0674d4426c54769eed8fb7fe58b6cfe61c4584  lint.log
ee20850a561b355e8240ab57ec1ff604439ca4f5322807e31a00dbd9139f2a48  plan.log
af111b6a8cda4558328c506e8a5a72095b76737200fe0465e179738ced37c50d  app-check.log
52dc786c3a2611b1f75ade60a7c681771821e5edf1b637045f38acc606733131  app-smoke.log
44a54d23a65dc3732b6619cbb313cbdc9430d84ebd309352d0061c70c44687e7  app-test-real-core.log
03d883cd57bd679120ca7067b13bff75aecb9238db5a7d23c3a60dfbf6716650  app-smoke-real-core.log
b48c7d4b36ff474278553fb1410527e34f7e5d3cfd6c21856e4e355dd298763a  fixture-smoke-evidence.json
c2c46e0807fddfd7d70dcd1787f8fbaae7a3f9d68ed3ba38e2639a02c927e9c4  app-test-a11y.log
38e6f3028a5f193bd060406ff65bbc4b6438b772798d5ba578d62fcf70a694d5  a11y-report.json
632a6476810b1e70d45f891cd2a5739b00a81f65cdbbde2a6c843401ce4f2d28  app-test-e2e.log
b2234b5447e08e4197181483de35d212adc0b50750183010b526a3a28477b630  e2e/playwright.json
0416cea35987c772280f8819c22aaca0c45bc569dafa2f2849d19b0fcd21c4f3  python.log
4388fa6832dc64aad72fe8e53bfff431afca0e9a56dc117f4384d23632239fbb  python.xml
d3dae66b5da2c939d2d682dfff41cefa89cf9af9e52e5797adfd468dd13aed6f  secret-domain.log
f28f21b089f8e38bcbbb1d64914df3af8b4cde8275f71ff2d446087cf54d5fa3  secret-domain.xml
459f6523f151ea90eacf65b1e477d1c0e452a4981a3051caa4a64aff2b1b4123  journals.log
7268f1c3e15b0ffc4a0e09de967c4137907379deced04365f13d74ef0fdb286a  journals.xml
```
