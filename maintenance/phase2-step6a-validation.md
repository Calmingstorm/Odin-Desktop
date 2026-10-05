# Phase 2 step 6A validation

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
