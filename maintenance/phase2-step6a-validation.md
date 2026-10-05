# Phase 2 step 6A validation

## PR #28 review round 1 fixes and current qualification

All seven findings in `/home/odin/reviews/desktop-pr28-review.md` are addressed on
`phase-2/services-part-a`. Main was merged without rebase or force-push, including
the subsequently merged PRs #26, #27 and #29. Final integrated main is
`caa871cdee8017015eef1b994af2c0453f09d5f2`.

Executable/test/accounting qualification target:
`9b29bbbb5f920ab662f218a1c7fc0ac30a956ff9`.
The later validation-record commit changes only this Markdown and the receipt JSON.

### Corrected behavior

- Dependency metadata errors no longer reject otherwise importable skills.
  Unsafe install specs remain refused; diagnostics remain visible. Defined names
  may differ from filenames, and optional blank/zero/null calls reach the skill.
- Failed pip installations retain useful stdout/stderr and timeout partial output
  through the copied scrubber, URL-userinfo masking and inherited credential-value
  masking. No actual skill dependency installation is performed by these tests.
- Credential presence is recorded per MCP server without secret values. Fresh
  credential-free startup performs no keyring reads. Marked unreadable credentials
  make only their server unavailable, with a reason; unrelated servers publish.
  Marker durability and secret/config rollback are tested. Older unmarked keyring
  credentials remain untouched until explicit existing `mcp.reconnect` after
  unlock. No new protocol method was retained.
- Browser resource resolution follows PR #24's `ODIN_DESKTOP_BUNDLE_ROOT` and
  `browser/chromium/chrome-headless-shell-linux64/chrome-headless-shell`, rejecting
  resolved escapes. Configured CDP is honored; absent CDP uses the bundled binary.
  Failed startup leaves a qualify-before-use retry seam available without health
  claiming readiness. Each generation has one 30-second qualification budget;
  copied bounded failure cleanup follows separately. Terminal close, context
  isolation and copied HTTP/WebSocket guards remain intact.
- PR #26 accounting recognizes only the exact new service group and two hash-pinned
  immutable GI/accessibility placement adapters. Corruption, lost selectors,
  unknown groups and incomplete membership remain refused. Original tests are
  unchanged. The PR #26 pip dev duplicate was removed, retaining product pip.

### Fresh gate evidence

- Fresh checkout:
  `/home/odin/desktop-pr28-review1/qualification-parent/final-corrected`.
- `umask 002`; parent and checkout verified `0775`. New copied-interpreter Python
  3.12.3 venv, locked dev sync with copy link mode, pip 26.2.1 from the lock, no
  manual environment repair. Engine suites use the isolated PID/mount namespace
  launcher, sanitized throwaway HOME/XDG and no desktop/DBus/live credentials.
- **One complete full qualification: 31/31 groups passed, 14,244 passes, 2 skips,
  zero failures/errors.** Step-6A group: **166 passed**. Core transport including
  merged process/accounting coverage: **581 passed**. Profile management: **300 passed**.
- Separate phase-2 plan behavior suite: **30 passed**.
- Exact drift: **zero errors**, **268 pending independent-review records**.
  Lint: **zero new findings**, seven inherited findings. Ownership checker passed;
  suite map valid with 326 mapped, nine restored, 312 deferred, five retired.
- Integrated skills/MCP/browser/GI targeted tests: **218 passed** before this gate.
  Additional checker regression selection: **125 passed**.

The first fresh preflight at `f4fae9dce73d90bcc27408d7f9b6bdf9ef4bf75d`
stopped at an import-formatting lint finding inherited from the final PR #27 merge,
before any full-suite group began. Its evidence is preserved. A formatting-only
fix was committed, then the entire gate ran from a second fresh checkout. Earlier
collection/checker integration failures are also retained, not relabeled as passes.

Artifacts under `/home/odin/desktop-pr28-review1/`:

- `final-corrected-qualification.log`, `final-corrected-plan-tests.log`.
- `fresh-corrected-locked-sync.log`, `fresh-corrected-drift.json`,
  `fresh-corrected-lint.json`, `fresh-corrected-suite-map.json`,
  `fresh-corrected-ownership.json`, `fresh-qualification-receipt.json`.
- `qualification-parent/final-corrected/.test-state/qualification-result.json`,
  `qualification-0.xml` through `qualification-30.xml`, and `phase2-plan.xml`.
- Earlier preflight: `fresh-locked-sync.log`, `fresh-drift.json`, `fresh-lint.json`.
  Collection and reconciliation logs remain alongside them.

Inherited mock-coroutine warnings and one process-transport event-loop-close warning
remain visible. Tests use inert browser/CDP/MCP/native/installer boundaries, not
real bundled-browser, endpoint, keyring or native-platform qualification. No
`/opt/odin`, live service/data, active desktop, upstream Odin or deployment changes.
Independent acceptance remains pending.

## Original pre-review qualification, retained historical evidence

## Artifact, stack and gate target

This artifact implements skills lifecycle/schema/publication/dependency installation,
configured supervised MCP, bundled Chromium startup, bounded workspace diagnostics,
worker-only GI discovery and the computer management/recovery side. Request delivery,
work/reports/schedules and foreground-turn computer binding remain outside part A.

The branch began at PR #21 `982477643adaa7652a74199198110981fe2fdfa0`. Its review-1
fixes were integrated bottom-up by rebasing onto
`b3f533e1ce26b41f3b7176478e34dda78154cfb1` before final gates. PR #21 merged into
main while qualification ran. This branch does not merge anything; its PR can now
target main. The tested engine stack includes all of #21's final review fixes.

Final executable/accounting gate target:
`2a2cd4eefabfac7216df2ee1b9803d7f1923f355`.
This validation record is committed afterward without executable/test/dependency changes.

## Corrected fresh-checkout qualification

- Checkout: `/home/odin/desktop-phase2-step6a/qualification-corrected-parent/final`.
- `umask 002` before creation; parent and fresh checkout verified mode `0775`.
- New copied-interpreter Python 3.12.3 venv, populated by `uv sync --locked --extra dev
  --link-mode copy`. Engine-local declared pip 26.2.1 was verified there.
- All engine suites ran through the isolated PID/mount namespace launcher, with
  throwaway HOME/XDG roots and no active desktop/bus/session environment.
- **31/31 qualification groups passed; 13,836 passes, 2 skips, zero failures/errors.**
- Step-6A service group: **118 passed**. Computer/GI adapters also execute in the
  retained original-corpus groups, not inflated into this new-service count.
- Core transport: **228 passed**. Step-5 profile management: **294 passed**.
- Phase-2 plan behavior suite separately: **30 passed**.
- Exact drift report: **zero errors**, **264 pending independent-review records**.
- Lint gate: **zero new findings**, seven inherited findings.
- Ownership checker passed: 409 source rows, 30 replacement rows, 122 planned modules.
  This is inventory coverage, not a claim of full Phase-2 runtime closure.
- Inherited mock-coroutine warnings remain in agent-lifecycle/tool-timeout cases. No
  warning was converted into an exclusion or a fabricated qualification result.
- Existing unresolved case-accounting boundaries remain honest: eight historical
  and 22 foundation blockers are not waived by this part-A gate.

Raw artifacts:

- `/home/odin/desktop-phase2-step6a/final-corrected-qualification.log`
- `/home/odin/desktop-phase2-step6a/final-corrected-plan-tests.log`
- `/home/odin/desktop-phase2-step6a/fresh-corrected-inventory.json`
- `/home/odin/desktop-phase2-step6a/fresh-corrected-phase2-plan.json`
- `qualification-corrected-parent/final/.test-state/qualification-result.json`
- `qualification-corrected-parent/final/.test-state/qualification-0.xml` through
  `qualification-30.xml`.

## Initial full-gate failures, retained rather than relabeled

The first fresh checkout against `06c23b7a403dd9849c937480323e1fff1515c717` completed
all 31 groups: **28/31 groups passed; 13,821 passes, 2 skips, 13 failures, no errors**.
That run remains at `/home/odin/desktop-phase2-step6a/final-qualification.log` and
`qualification-parent/final/.test-state/qualification-*.xml`.

The failures exposed four boundaries:

1. One immutable mocked accessibility case still ran in the main-process placement.
   The new worker-only resolver correctly refused it. A fixture adapter now runs the
   entire unchanged original suite at its worker seam, preserving original assertions,
   parameters and no-native-effects fixture. No original corpus bytes changed.
2. One Desktop-origin byte-parity test lacked the three exact optional-provider
   substitutions introduced in the retained catalog. Its byte assertion remains;
   only those concrete substitutions were added, with runtime merge tests separately.
3. Four real core entry cases exposed the copied native store's stricter ancestor/
   symlink fence. That optional subsystem must not crash otherwise usable IPC. The
   fence remains unchanged: status reports unavailable private storage while native
   management effects are withheld. No unrelated ancestor is chmodded, unsafe alias
   adopted or second native store created. Existing entry assertions now pass unchanged.
4. Seven step-1 unavailable-method cases now addressed genuinely served skills/MCP/
   computer reads. They moved into equally strict valid/invalid/quiescing no-reservation
   tests; deferred methods and `skills.test` remain unavailable. No receipt protections
   or assertions were discarded.

Correction verification: **162 targeted cases passed** before corrected collection and
a second complete fresh-checkout run. The earlier green step-6A-only group did not hide
the failed integration gate.

## Verified behavior and limits

- Actual local transport dispatch uses existing authenticated `OwnerContext` and durable
  keyed receipts. Skill source/config and MCP instructions/credentials do not manufacture
  authority. Parent EOF during qualification settles startup before publication.
- Skills use real retained lifecycle/schema/dependency handling and profile-specific
  module identities. Pip execution and vault boundaries are stubbed in tests. No real
  dependency was installed by a skill. Trusted skills are in-process Python, not a sandbox.
- MCP uses retained manager/transport/era/publication behavior with controlled connections.
  Locked keyring, credential rollback, invalid schemas, name reservations, limits,
  cancellation and reload/reconnect no-replay behavior were exercised. No real MCP endpoint
  or authentication credential was used.
- Browser resolves only packaging-owned Chromium, qualifies disposable context/page and
  copied HTTP/WebSocket guards, withdraws on disconnect/close and prevents stale-owner
  resurrection. Playwright, DNS and browser execution are stubbed. Actual bundle/native
  ABI qualification remains a packaging/Phase-3 requirement.
- Computer private store startup is inert. Management binds owner/runtime/request task
  without a fabricated conversation/turn; exact generations, quarantine, uncertainty and
  release-only recovery retain the controller/store rules. No pixels, input, native
  helper or active graphics session was accessed. Foreground tools remain unpublished.
- GI loads only in retained worker entrypoints without changing core search paths or
  environment. Original GI/accessibility assertions run through explicit placement
  adapters. Importability is not native-backend qualification.
- Workspace diagnostics use the actual executor resolver, bounded non-following walk,
  literal local Git argv and single-flight timeout behavior. Remote freshness is always
  unproven. Filesystem syscall deadlines are cooperative, not hard OS interruption.

No `/opt/odin`, live configuration/data, service, operator browser or active-desktop
changes. No deployment, independent acceptance or merge is claimed. Claude's review
remains required.
