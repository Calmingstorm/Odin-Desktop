# PR28 second main merge: lifecycle and Step 6A

Merged main `0b7d596f7e870d06699722f151c4d9837c5433f1` (accepted PR32)
into PR28 `2d91071a692a646b6d8c466daa5711a37cd8c93f`, without rebase or
force-push. Executable/test/ledger integration target:
`8ab360bf98352c883650fc2acd2f92c2e37c0a6f`.

## Semantic resolution

- Management first obtains the original execution-owner cleanup evidence. The
  `producers_quiesced` barrier refuses shared-service teardown beneath unsettled
  engine producers. It persists services as unknown and uses `ResourceCleanupError`.
- The barrier and journal wrap PR28's reversed lifecycle-service owner list,
  followed by providers and SSH pool only when not engine-owned. Ordinary owner
  failure never skips remaining owners. Services become unknown in the durable
  cleanup journal before an error escapes. Without a journal, unknown cleanup
  raises the unverified error. PR28's async `start()` remains intact.
- Integration inspection found that the automatic services merge would skip
  the early MCP producer barrier for a shared management-owned manager. Composition
  now delegates that barrier through the same MCP wrapper before execution owners,
  providers or persistence close. The wrapper retains the first close success,
  failure or cancellation so later traversal cannot retry the original manager.
- Browser sandboxing, bounded startup, async reload preparation, off-loop keyring
  settlement and management-before-single-listener startup remain preserved.
- The ledger union used `/home/odin/reviews/merge_ledger.py`; ten jointly changed
  entries were re-recorded with both sides' provenance. Final code and changed named
  test evidence were explicitly re-recorded through `inventory.py record` with
  path-specific rationale. No independent-review state was manufactured.
- PR32's new contract assertion exposed a stale main-only smoke capability list.
  Both explicit static lists now agree on 120 served Step 6A names, with actual
  empty skills/MCP reads and no-session/no-input computer status. Later Part B,
  work and schedules still refuse. Real Settings Skills/MCP surfaces are observed,
  not incorrectly described as unavailable.

## Final targeted gates

Workspace: `/home/odin/desktop-pr28-main2-20261006/work`.
Raw evidence: adjacent `evidence/`; isolated Python XML: work `.test-state/`.

- Exact drift: zero errors; 348 pending independent-review entries.
- Lint: zero new findings; seven inherited findings retained.
- Ownership and suite-map checks pass. These remain static accounting, not runtime
  feature qualification or independent approval.
- Maintenance/plan/suite-map regressions: 169 passed.
- Lifecycle, engine graph and cleanup regressions: 69 passed. Includes 17 new
  management-wrapper cases, actual composed shared-MCP success/failure, exact
  early shutdown order, remaining-owner continuation, durable unknown and
  original-owner non-replay.
- Step 6A named group: 173 passed. Profile management named group: 303 passed.
- App `npm run check`: typecheck/build plus 693 tests passed.
- App real-core: 21 contracts plus six actual Electron onboarding tests passed.
- Actual source-build lifecycle: 29/29 passed, without skips or retries.
- Real-core smoke: 40 checkpoints passed. Fixture smoke passed.
- Accessibility: 15/15 passed, without skips or retries.
- Final narrow independent technical inspection found no concrete merge blocker.
  Claude's acceptance is separate and remains pending. Integrated MCP cancellation
  is not separately injected; wrapper cancellation/non-retry has its own behavioral
  regression, while integrated success/failure prove the producer ordering.

All engine execution uses sanitized HOME/XDG and isolated PID/mount namespaces.
Electron lifecycle/onboarding/smoke/accessibility gates use their established
isolated runner/Xvfb/private bus, not the active workstation desktop.

## Diagnostics and limitations

The initial dependency command used an unsupported `uv venv --copies` option.
It failed before provisioning; the corrected command uses Python 3.12's
`venv --copies` followed by locked `uv sync --extra dev --link-mode copy`.
An import-order lint finding in new tests was corrected before final gates.
The initial real-core run had 20 passes and one exact-capability failure;
the explicit Step 6A smoke expectation fix above produced the final passing run.

Locked npm provisioning reports 11 dependency audit findings (10 high, one
critical), plus transitive deprecation warnings. No opportunistic dependency
upgrade or audit suppression was included in a semantic merge. Isolated GTK/portal
tests emit environment warnings for absent PipeWire/wsdd and private-bus teardown;
all corresponding gates pass. These are not native-platform qualification.

The existing Records renderer expects a flat computer-status shape while the
authoritative core returns `{session, readiness}`. Smoke verifies the core shape,
the refresh surface and absence of session controls; it does not claim the
renderer is a qualified native-input surface. MCP manager shutdown drains its
owned producer tasks but suppresses some retirement/disconnect exceptions, so
this merge restores the existing producer barrier rather than claiming independent
proof of every transport release.

## Fresh full qualification

The sole fresh complete qualification passed against the pinned integration target
`8ab360bf98352c883650fc2acd2f92c2e37c0a6f`:

- **31/31 groups passed; 14,622 passed, two skipped, zero failures/errors.**
- Final full core transport: 567 passed; profile management: 303 passed;
  Step 6A: 173 passed.
- Fresh pre/post drift: zero errors, 348 pending independent-review entries.
  Fresh pre/post lint: zero new findings, seven inherited. Fresh ownership and
  suite-map checks pass.
- The two inherited skips, existing mock-coroutine warnings and subprocess
  event-loop-close warning remain recorded, not excluded or silently reclassified.

Fresh checkout:
`/home/odin/desktop-pr28-main2-20261006/qualification-parent/final`.
Parent and checkout verified mode 0775. Python 3.12 copied-interpreter environment
provisioned only through locked declared development extras. The checkout was
explicitly switched to the integration SHA before dependency provisioning or test
execution; no unrelated branch was qualified.

Raw stream: `evidence/fresh-full-qualification.log`. Summary and runner result:
`evidence/fresh-qualification-summary.json`, fresh checkout
`.test-state/qualification-result.json` and `qualification-0.xml` through `-30.xml`.
The qualified group selection is unchanged; newly merged cleanup/lifecycle suites
also have the separate 69-case targeted gate above, rather than an invented claim
that the inherited full plan selected them. Final evidence commit changes only
this Markdown, not executable/test/dependency/ledger bytes. Main and the PR branch
were rechecked after qualification and still matched the requested pins.

No attribution trailers, GitHub PR merge, deployment, live service/data change,
active-desktop input, native keyring acceptance or real external MCP endpoint.
