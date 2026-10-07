# Phase 3 and 4 work order: finish the Linux app and qualify release v1.0

**Status:** reviewed by Claude and approved by Aaron on 2026-10-05, with the decisions in section 6 applied.
This PR remains documentation only, open and unmerged; it performs no implementation or release action.
**Owner:** Odin builds the remaining app and engine integration; Claude reviews each PR and owns the protocol.
**Scope:** remaining roadmap Phases 3 and 4, not a rebuild of app steps 1 to 6.

## 1. Baseline, evidence and boundaries

Based on pulled `main@2cfc64db00e415cfd3773991d9e0f2521e9cde42`, inspected on 2026-10-05, and the settings
continuation at PR #16 head `c5285a9f69d7eac849939dcf32764dccb6104778`. The repository is private.

- App steps 1 to 4 (#6, #7, #9, #10), notifications (#11), and General/Models settings (#12) are merged. #11 and #12
  merged during this plan's reading. Settings PRs #13, #15 and #16 were in review at this watermark. They are built
  work to adopt after review, not instructions to build those screens again.
- Phase 2 transport PR #14 is in review. Its existence does not prove conversations, requests, controls, settings
  or background services are ready. Integrate each reviewed service as it lands; full acceptance requires Phase 2 exit.
- `app/src/main/index.ts` still defaults to the fixture, with `ODIN_DESKTOP_CORE_CMD` as its development override.
  The shell already has a supervisor, broker, private paths, security policy, tray, autostart and Exit routes.
- Models and providers uses `views/Settings.vue`, `settings-form.ts`, `SchemaForm.vue`, `CodexAccounts.vue` and
  `stores/settings.ts`. There is no first-run Desktop flow in the inspected app.
- `app/packaging/odin-desktop.desktop` is a launcher asset, not a `.deb`, AppImage or update system.
- Existing Vitest renderer component tests use a custom object renderer. They do not prove browser focus,
  accessibility trees, Orca speech, native notifications or native input. Xvfb screenshots do not prove those either.

The roadmap, [`app-v1-plan.md`](app-v1-plan.md), [`phase-2-desktop-engine.md`](phase-2-desktop-engine.md),
[`protocol.md`](../design/protocol.md), [`core-contracts.md`](../design/core-contracts.md) and
[`00-brief.md`](../design/00-brief.md) remain authoritative. Paths labeled **Add** are proposed, not existing
implementations or passing evidence. All paths below are relative to this repository.

**Decision precedence:** Aaron's 2026-10-05 choices in section 6 supersede earlier bundled-PDF and Linux signed-update/feed proposals
in the design references. Linux v1 publishes GitHub Releases with `.deb` and AppImage assets, without a signing key,
self-updater or custom feed/manifest. Existing ownership, compatibility, durability and quarantine contracts remain.

### Rules for every implementation PR

1. Pull `main`, branch, send a reviewed PR. Independent steps use separate worktrees; dependent steps name a reviewed
   base and rebase before final gates. No attribution trailers. Do not merge this plan.
2. **D17:** no extra command approvals, consent prompts, owner tool/host allow-lists or governor restrictions.
   Preserve Odin's admin behavior, secret redaction, trust, durability, computer consent and quarantine. Renderer
   isolation and package ownership are product boundaries, not a new owner execution policy.
3. **D19:** Claude approves mechanical interface wording substitutions. Changes to what Odin is told to do go to
   Aaron before implementation. No onboarding, packaging or accessibility step adds a system-prompt instruction.
4. This repository only. Do not edit the Odin repository, `/opt/odin`, live services, profiles or credentials. Do
   not adopt another installation's data/environment. Import, remote-client mode, Windows/macOS and v1+ stay out of
   scope. D10's inbound integration listener is not a remote management API.
5. Follow `CONTRIBUTING.md`: engine/process tests run in an isolated PID namespace; native lifecycle/input tests
   run in hard-isolated graphics. Use disposable HOME/XDG roots, private bus/keyring, scrubbed environment and exact
   owned process identities. Never inherit workstation display, bus, credentials or browser. Use harmless tools/
   receivers and controlled provider responses. No destructive or attack command inputs.
6. All testing stays off Aaron's active desktop until P4.6's final supervised run of the exact build, which he must
   OK first. GNOME/KDE Wayland and Hyprland qualification use VMs on this workstation, one heavy VM at a time
   (decision A). Native receivers cannot reach the active desktop. Xvfb covers ordinary renderer tests, not real
   portal consent, containment or login acceptance. Never lock, suspend, restart or log out the active desktop.
   Check resource headroom before VM setup; host system-package changes need Aaron's OK.
7. Tests exercise behavior, not document wording. After the final change, use a fresh checkout for
   `npm ci --ignore-scripts`, `npm run check`, isolated fixture smoke and relevant real-core/native/package gates.
   Provision Electron's pinned binary through the existing reviewed install procedure; never use `--no-sandbox`
   to fix qualification. Pin new E2E dependencies in `app/package-lock.json`; install only in the project.
8. Each gate records source SHA, artifact hashes, commands/environment, cases/results, logs, cleanup receipts and
   limitations. A skip/missing environment/stubbed native backend is not qualification. Renderer/provider/core
   readiness, OS notification acceptance and human visibility are distinct facts.

## 2. Work graph and Phase 2 handoffs

One reviewed PR per step; desktop/backend-specific proofs may be separate PRs under the same gate. Do not combine
all integration, native tests and packaging into one unreviewable change.

| Step | Work | Dependencies for its final gate | Parallel lane |
|---|---|---|---|
| P3.1 | App step 7: real-core integration | Reviewed app settings; relevant Phase 2 services, then Phase 2 exit | Incremental integration |
| P3.2 | First-run extension of Settings | #12; Phase 2 step 5 and P3.1 runtime/settings slice | Onboarding |
| P3.3 | Native lifecycle and notifications | P3.1; Phase 2 steps 4 to 6; approved isolated sessions | Lifecycle |
| P3.4 | Keyboard and Orca accessibility | Reviewed app steps 1 to 6; P3.2 for complete first-run coverage | Accessibility |
| P4.1 | Bundled runtime and candidate `.deb`/AppImage | Phase 2 runtime/skills boundaries; package layout | Packaging, early |
| P4.2 | Package ownership, migrations and upgrades | P4.1 candidates; P3.1 and P3.3 pre-package lifecycle slice | Packaging acceptance, early |
| P3.5 | Isolated native input and quarantine | Phase 2 step 6; P3.1/P3.3; P4.1 helpers; approved labs | Native backends |
| P3.6 | D11 matrix and Phase 3 closure | P3.1 to P3.5, P4.1/P4.2 candidates, Phase 2 exit | Matrix/closure |
| P4.3 | Release publication and the new-version notice | Decisions C/D settled; P4.1/P4.2 build outputs; P4.5/P4.6 before publication | Releases/notice |
| P4.4 | User and operator docs | Integrated behavior and package/update decisions | Documentation |
| P4.5 | Full R4 on release candidates | Phase 3 closure, P4.1 to P4.4 | Acceptance |
| P4.6 | Aaron's live acceptance and release handoff | P4.5; immediate explicit active-desktop authorization | Owner acceptance |

**Phase boundary:** the roadmap requires package ownership/upgrade tests at Phase 3 exit although packaging is
Phase 4 work. P4.1/P4.2 therefore build/test **unreleased candidates early**, alongside Phase 3. This is not release
authorization. Phase 3 consumes that evidence; Phase 4 qualifies final candidates, release publication and the
new-version notice with R4. No gate is moved or waived, and there is no circular dependency. Aaron's work-order
approval includes this early candidate lane, not permission to publish.

**P3.1 handoffs:** Phase 2 step 1 supplies launch/transport; step 2 conversations/search; step 3 submissions,
attachments/artifacts/delivery; step 4 controls/resume; step 5 runtime/settings/credentials/management; steps 6/7
background work and D10 ingress. Integrate each slice after review. Unavailable services stay honest, never fixture-
backed inside real-core sessions. A slice does not claim app-step-7/R4 completion.

**Lifecycle slices:** P3.3 first proves source-build shutdown/reconciliation/parent loss in isolated sessions. P4.2
can consume that pre-package evidence. P3.5 adds the backend-specific native receiver/loss cases, and P3.3's final
packaged/native matrix is rerun before P3.6. These are partial handoffs, not permission to claim P3.3 passed early.

## 3. Phase 3 steps

### P3.1: app step 7, connect the existing app to the real core

**Change:** `app/src/main/{index,core-supervisor,broker,paths,ipc,schemas}.ts`, `app/src/preload/index.ts`,
`app/src/shared/api.ts`, `app/scripts/smoke.mjs`, `app/README.md`; renderer stores only for concrete integration
defects. **Add:** `app/src/main/core-command.ts`, `app/test/core-command.test.ts`, `app/test/real-core-harness.ts`,
`app/test/real-core-contract.test.ts`, `app/scripts/real-core-smoke.mjs`, `app/test/e2e/real-core.spec.ts` and shared
isolated E2E configuration/helpers under `app/test/e2e/`.

- Extract command selection. Packaged launches use an explicit interpreter/entry point inside candidate resources,
  not PATH `python3`, a developer checkout or `/opt/odin`. Development selects the fixture explicitly; retain it
  for tests, exclude it as a production fallback. Missing/incompatible bundle fails visibly. Validate development
  JSON argv override without shell evaluation or secret-bearing arguments.
- Main owns socket/token/core lifetime. Check installation/profile, protocol features, journal lineage, storage
  readiness and incarnation before writes. Child spawned is not core ready.
- Exercise the existing named bridge against every v1 family, including management/records, attachment/artifact/
  report paths and controls. Contract corrections require Claude's reviewed minor bump; update schemas/API/bridge/
  engine/fixture together. Never add a generic renderer RPC to compensate for a missing method.
- Reconnect/reload uses snapshots, watermarks and cursor catch-up. Lost receipts reconcile the same command identity.
  Expired receipt/cursor and conflicting identity differ from a safe new request.
- Bound restart by existing policy **and ownership/storage reconciliation**, not only the restart timer. Never
  replace a core over surviving execution, unproven input ownership or incompatible state.

**Behavior tests:** actual broker plus temporary real engine: two conversations/child, upload/cancel, committed
reply/tool activity, artifact/evidence/report reads, stale settings revision, write-only secrets, Stop/Steer/resume,
core/renderer restart, lost receipts and expired cursor. Controlled provider responses must enter the original guarded
runner. Independent harmless effect counters prove no replay. Electron smoke asserts transcript/receipt/state, not
only screenshot/`link=ready`. Prove production cannot fall back to the fixture.

**Gate:** fixture regressions and each landed real-core slice pass; app-step-7 completion requires Phase 2 exit
and complete E2E. Preserve logs/effect counters across restarts. **Depends on:** section 2 handoffs; P4.1 layout for
packaged launch. No native desktop qualification claimed here.

### P3.2: first-run onboarding, extend Models and providers

**Decision within this plan:** extend Settings, do not duplicate it. `views/Settings.vue` currently starts at General;
add addressable section navigation and a readiness banner that opens Models and providers. Reuse `SchemaForm.vue`,
`CodexAccounts.vue` and `General.vue`. No second provider wizard or Codex-only screen.

**Change:** `app/src/renderer/src/{App.vue,store.ts,settings-form.ts}`, `views/Settings.vue`,
`views/settings/General.vue`, `components/{SchemaForm,CodexAccounts}.vue`, `stores/{settings,status}.ts`; named
API/IPC/schema/preload layers if the reviewed runtime contract needs a first-run projection.
**Add:** `app/src/renderer/src/components/FirstRunBanner.vue`, `app/test/renderer/first-run.test.ts`,
`app/test/e2e/onboarding.spec.ts`. Compose Phase 2's `src/desktop/{runtime,provisioning,settings,codex_accounts}.py`;
do not create a second bootstrap policy, credential store or engine graph.

- Core state reports fresh/incomplete/saved/effective-ready/degraded. No local completion flag invents provider
  readiness. Complete only after required settings commit; failed save/keyring write stays retryable. Chat and
  settings remain navigable without a provider, without pretending a request can execute.
- Preserve all provider choices. Codex uses device-code login, expiry/cancel/retry/account activation; other providers
  use existing write-only credential routes. Reuse model apply methods and saved/running/pending-restart labels.
- Explain **start at login is opt-in, initially off**, close continues work, Exit stops it. Offer General controls.
  Keep D13 **notification previews on by default**, with immediate preview toggle/mute/quiet-hours access. No new
  privacy-consent gate or mandatory setup checklist.
- Locked/missing Secret Service reports failure and Retry, never successful credential save or plaintext fallback.
  No stored-secret readback, profile/OAuth token, device-login secret or credential-file import reaches renderer,
  log or transcript. Transient user-entered credential fields clear after submission and never enter drafts or
  persisted renderer state. Display the intended short-lived user verification code, not OAuth credentials.
- Open only recognized core provider verification URLs through a narrow named main operation, not arbitrary content
  navigation. Preserve existing auth behavior; no new owner approval. No renderer provider probes/network bridge.

**Upstream boundary:** `ui/js/pages/setup.js`/`src/web/onboarding.py` provide durable completion/retry patterns;
`ui/js/pages/llm-config.js`, `src/web/api/codex_admin.py`, `src/llm/codex_auth.py` supply provider/device login behavior.
Web API/Discord/server setup fields do not come over. Desktop startup/privacy/keyring recovery are Desktop work,
not features already proven by WebUI setup.

**Behavior tests:** section routing/re-entry/no duplicate forms, fresh/second launch, setup-later, save/revision/
connection failures, canceled/expired login, locked/missing keyring/recovery, saved-not-effective model, defaults and
persistence. Isolated auth service for deterministic tests; private real Secret Service in native acceptance. No
production accounts/copied credentials. Include first-run in P3.4 keyboard/Orca.

**Gate:** real app/core first-run-to-ready and incomplete-to-retry pass; no secret readback or false readiness;
defaults match approved decisions. **Depends on:** #12, Phase 2 step 5/P3.1 settings-runtime slice. Parallel with
lifecycle/accessibility.

### P3.3: native lifecycle, tray/no-tray, notifications and login startup

**Change for measured defects:** `app/src/main/{index,lifecycle,tray,autostart,notifications,core-supervisor}.ts`,
`app/packaging/odin-desktop.desktop`, existing lifecycle/supervisor/autostart/notification tests. Phase 2 lifecycle/
runtime/containment changes require drift accounting and unchanged original cases.
**Add:** `app/test/e2e/{lifecycle,notifications}.spec.ts`, `scripts/qualification/lifecycle.py`,
`maintenance/phase3-lifecycle.md` and private-bus/owned-process fixtures under `tests/desktop_fixtures/`.

- Close hides the window; turns/agents/schedules/workflows continue into durable conversations. Relaunch reopens
  the same app/core. Prove the tray actually appears and Open/Exit work, not merely heuristic tray detection.
- With **no tray and no extension**, relaunch, window menu/Ctrl+Q and launcher Exit work. One-time notice explains
  continued work. Notification failure cannot strand the user. `--exit` with no existing instance must not start
  an engine; current first-launch handling needs acceptance here.
- All Exit routes use one bounded shutdown: stop admission, settle/cancel, persist, release resources, exit. Normal
  shutdown and escalation have separate evidence. Unknown effect/input cleanup persists visibly on next start;
  do not label it undone or clear quarantine for a prettier Exit.
- Terminate only the isolated app main process: prove parent-loss containment with real core, harmless owned
  descendants and controlled native receiver. Renderer loss must not stop core. Core loss proves reconciliation/
  no replay and blocks replacement over unproven ownership.
- Notifications exercise request/show/failure/click/ack. Existing preview/focus/mute/quiet-hours/dedupe policy remains.
  Click reaches the right conversation/message; unread state persists. OS acceptance, appearance and read watermark
  are different facts.
- Enable/disable autostart only in the isolated user's XDG directory, then actually log in there: app-only hidden
  startup, one core, no root service/linger, keyring timing and no-tray reopen. Test relocated AppImage/upgraded `.deb`
  paths. VM sleep/wake proves D12 without suspending workstation: reminders coalesce, missed actions wait for owner,
  exited app executes nothing.

**Behavior tests:** routes above, simultaneous second launch, Exit during harmless long call, daemon absence/rejection,
parent EOF/abrupt parent loss, containment deadlines, stale PID/socket occupant and restart budget. Record process
identities/cleanup receipts/receiver observations. PID disappearance does not prove every descendant/input release;
graceful EOF does not qualify abrupt parent loss.

**Gate:** native lifecycle passes on each D11 desktop; no-tray GNOME mandatory. Unknown cleanup is fenced, not
counted as confirmed release. Package-path cases consume P4.1/P4.2. **Depends on:** P3.1, Phase 2 runtime/controls/
background wiring, approved labs. No active-session work.

### P3.4: keyboard-only use and Orca

**Change for measured defects:** `app/src/renderer/src/components/{Composer,ConversationMenu,ConfirmDialog,
CommandPalette,MessageList,Message,FileCard,ReportViewer,SearchPanel,WorkPanel,ResumeBanner,ToolActivity,SchemaForm,
CodexAccounts}.vue`, `views/Settings.vue`, affected `views/settings/*.vue`, `dialog.ts`, `styles.css`.
**Add:** `app/test/e2e/accessibility.spec.ts`, `scripts/qualification/accessibility.py`,
`maintenance/phase3-accessibility.md`; pin an Electron-capable E2E runner and `axe-core` in the app lock if selected.

- Complete chat, attachment selection/cancel, conversation/search/child navigation, results/save/copy/report paging,
  Stop/Steer/resume, all settings/management sections and first-run without a mouse.
- Verify visible focus, tab order, accessible names (including distinct quiet-hour inputs), error associations,
  modal focus containment/restoration and Escape. Existing object-renderer tests cannot prove these.
- Announce busy/completed/queued/consumed/unknown without flooding speech with every event. Never expose rejected
  drafts or secrets to the accessibility tree. Virtualized history/search remains navigable and announces loading/
  context transitions without losing focus/current message.
- Test zoom/reflow, contrast, reduced motion, menus and provider login codes. Confirm **Orca/AT-SPI**, not only ARIA
  attributes, tree snapshots or an automated audit score.

**Behavior tests:** actual Electron DOM focus/accessibility tree, then isolated Orca with a task script and observed
announcements. Automation covers regressions; manual Orca execution records successes/failures. Include native
dialogs/notifications. Screenshots are layout evidence only.

**Gate:** all keyboard tasks complete without traps/lost focus/unnamed essential controls, automated findings are
dispositioned. Orca results are recorded but block nothing (Decision G).
Fixes preserve D9 committed-only replies and D17 behavior. **Depends on:** reviewed app steps 1 to 6; P3.2/P3.3
flows join before final matrix. Can begin in parallel against existing screens.

### P3.5: isolated native input, containment and quarantine

**Compose/change if needed:** `src/desktop/computer_binding.py`, retained `src/computer/` controller/store/runtime
adapters, `src/computer/runtime/dependency_resolver.py`, helpers under `assets/{wayland-scope,kwin-scope}/`, existing
`scripts/computer-feasibility/` X11/portal/Hyprland harnesses. Do not replace the controller.
**Add:** `scripts/qualification/computer.py`, `tests/test_desktop_native_qualification.py`,
`maintenance/phase3-native-input.md`; record exact reused corpus/case mappings in maintenance accounting.

- X11 in isolated Cinnamon, portal capture/input separately in GNOME and KDE Wayland, Hyprland scoped native
  targets in its isolated compositor. Hyprland backend proof does not replace GNOME/KDE app qualification.
- Real owned safe receivers prove targeting/capture/action grounding, focus/geometry/modal changes, stale generation/
  observation rejection, supported text/keys/strokes and postconditions. Safe dialogs require fresh views; batches
  cannot cross unobserved transitions. Portal refusal/absent support stays truthful.
- Exercise pause/cancel/Exit/controller/guardian loss, resource retirement and recovery. Preserve fresh binding/
  consent requirements, release-only recovery, durable quarantine/no-replay. Background/model text cannot create
  foreground authority or revive input.
- Inspect receiver/compositor evidence, not only controller receipts. A drained Hyprland ledger is not proof of
  compositor/receiver release; abrupt sole X11 guardian loss has no universal release guarantee. Unknown release
  stops input/replacement. RELEASE-ALL, later success or another backend cannot erase it. Reconciliation follows
  existing exact-resource/external-cleanup rules, not a Desktop shortcut.
- Prove packaged helper discovery and reject compositor/ABI mismatch. Source-build proofs cannot cover absent/
  incompatible shipped helpers. Unqualified tools stay absent, but that correct absence does not fulfill D11's
  obligation to qualify every promised backend.

**Behavior tests:** real receiver path/hold/release observations and resource identities; loss/recovery corpus;
guarded publication/admission; quarantine across app/core restart. Stubbed backend cases remain headless regressions,
not native evidence. No terminal, security/credential prompt or control-plane targeting. Fault injection/cleanup
are confined to the disposable lab's owned resources.

**Gate:** supported subsets/limitations evidenced from candidates, including unknown-release quarantine/no-replay.
No claimed guarantee without receiver/platform evidence. Do not weaken Odin guards for a pass; unresolved D11 support
blocks release and goes to Aaron. **Depends on:** Phase 2 step 6, P3.1/P3.3 lifecycle slice, P4.1 helpers, approved labs.

### P3.6: D11 matrix and Phase 3 closure

**Add:** `scripts/qualification/desktop.py`, `maintenance/phase3-matrix.json`, `maintenance/phase3-qualification.md`.
**Change:** app behavior tests/maintenance mappings for defects; `app/README.md` qualified environments. No rebuilding
an existing feature simply to create a matrix entry.

Run an immutable candidate in every row, recording distro/kernel, desktop/compositor/session, portal implementation,
GPU/driver, Electron/Chromium/Python/helper versions, package hash and source SHA:

| Environment | Required app evidence | Computer evidence |
|---|---|---|
| Mint 22, Cinnamon/X11, isolated lab | Rendering, keyboard/Orca, renderer security, tray/no-tray, notifications, startup/Exit/parent loss | X11 |
| Ubuntu 24.04, GNOME/Wayland VM, no tray extension | Same app evidence; mandatory no-tray reopen/Exit. Optional extension row separate | GNOME portal |
| Ubuntu 24.04 base, KDE/Wayland VM | Same app evidence; actual SNI tray, KWallet/Secret Service and portal/dialog behavior | KDE portal |
| Ubuntu 24.04 base, isolated Hyprland VM | Safe targets and recovery/containment integration; not substitute desktop coverage | Hyprland |

All v1 rows use x86-64. Record exact desktop/compositor package versions in the VM recipes; only one heavy VM runs
at a time. VM evidence does not claim every physical GPU/driver combination, other distro or architecture. Any
required hardware evidence missing after VM qualification remains a reported blocker, not an active-desktop test.

**Behavior tests:** actual renderer enforcement of sandbox/context isolation/no Node/socket/token, individually named
validated bridge with sender/top-frame/origin checks, CSP/custom origin, inert content fixtures, navigation/pop-up/
permission refusal and file-reference/native-dialog boundaries. No malicious shell dispatch. Long replies/tables/
images/report paging, focus, resize/scaling/recovery on real rendering stacks. Reuse P3.3/P3.4/P3.5 only for identical
candidate hashes/environments; rerun packaged lifecycle after P4.2.

**Gate:** UI parity and P3.1 to P3.5 pass, all D11 rows have real evidence, P4.2 ownership/upgrade cases pass. Phase 2
exit supplies all 326 deferred suites' exact-case results/dispositions, section-4 D19 wording closure and runtime
fresh-host parity. New app/native tests do not replace inherited cases. No unexplained safety drift or unqualified
required row. This is isolated qualification, not Aaron's live acceptance. **Depends on:** section 2 graph; failures/
missing environments block closure, explicitly reported.

## 4. Phase 4 steps

### P4.1: immutable bundled runtime and candidate installers (start early)

**Add:** `app/electron-builder.yml`, `packaging/linux/{bundle-manifest.json,engine.lock,README.md}`,
`scripts/packaging/{build-engine.py,build-linux.mjs,verify-bundle.py}`, `.github/workflows/desktop-package.yml`,
`tests/test_desktop_bundle.py`. **Change:** `app/{package.json,package-lock.json}`, launcher, `pyproject.toml`
package-data/runtime resolution as needed, P3.1 core command. Proposed builder: electron-builder for both formats,
one explicit resource layout and inventory.

- Pin relocatable CPython 3.12, locked engine dependencies and source/assets inside immutable app resources, not
  writable profile data. No system Python/developer tree dependency. Bundle/product, protocol, storage/checkpoint,
  upstream baseline/review watermark are separate versions.
- D14 bundles Playwright Chromium, semantic-search models and computer helpers with provenance/hashes/licenses.
  Offline first run proves these need no feature download. Decision F keeps PDF offered with a pinned automatic
  first-use download into user-writable data, never the immutable runtime. Electron Chromium and tool Chromium
  are separate inventories/security-update obligations.
- User skill dependencies cannot mutate core/another install. Qualify Phase 2's worker/loader and bounded SkillContext
  bridge; a separate venv alone does not make packages visible to an in-core import. Missing loader parity blocks
  bundling, not permission to freeze away skill support.
- Package identity is `odin-desktop`, with independent install/launcher/icon/state/credential namespaces. Exclude
  fixture, developer/test-state/review artifacts and credentials. Retain required provenance/legal material and
  secret-recognition patterns under the narrow reviewed reference allowlist.
- Build `.deb`/AppImage from identical pinned inputs, unprivileged where possible. Preserve Chromium sandbox; qualify
  x86-64 Mint 22/Ubuntu 24.04-base distro/kernel integration, not sandbox-disabling workarounds. Measure actual
  glibc/distro/CPU/compositor ABI floor, download/disk sizes and startup/runtime memory. Other distro/architecture
  targets wait for their own testing. P4.3's release workflow uses these build scripts to produce both attached
  formats; candidate/package inventories and SHA256 records are not an update feed or signing scheme.

**Behavior tests:** extracted/installed candidates, paths with spaces, offline, without checkout/system Python:
real-core conversations/tools/reports, browser launch, semantic search, PDF, skill dependency isolation, native helper
resolution. Scan built distribution/resolved dependencies/actual offered catalog for removed features/secrets, not
only source. Verify manifest closure/digests.

**Gate:** runnable `.deb`/AppImage contain and use all D14 resources, independent runtime, immutable core; no unexplained
asset/dependency drift. Retain SHA256/provenance/licenses/evidence. Unreleased until P4.6. **Depends on:** reviewed
layout, Phase 2 runtime/skill boundaries; may start before final app acceptance.

### P4.2: ownership, alongside isolation, migration and upgrades (Phase 3 gate)

**Add:** `scripts/packaging/acceptance.py`, `tests/test_desktop_package_ownership.py`,
`maintenance/phase4-packaging.md`, disposable VM/container package fixtures. **Change for defects:** packaging,
existing `src/config/migrations.py` and Desktop version/path seams, with migration ownership/drift records. No import.

- Fresh `.deb` install/launch/uninstall distinguishes package-owned resources from per-user data. Maintainer scripts
  do not start services/engine, mutate a logged-in session or erase history/secrets. Test ordinary unprivileged owner,
  not only root. Containers prove ownership/install behavior, not native graphics.
- The user installs a new `.deb` through the package manager, never an in-app installer. Quiesce owned app/core
  before replacement, preserve receipts/quarantine and prevent mixed-version writes. Test interrupted install,
  failed preflight, busy ownership and
  incompatible protocol/storage/checkpoint. Record how package-manager preflight requires/observes stopped app.
- The user replaces the AppImage themselves after safely exiting the owned app/core. Test relocation/spaces/read-only
  mount/non-writable destination/autostart consistency and interrupted user-managed replacement. Neither a version
  check nor opening a release link downloads, stages, writes or replaces an executable. No in-app apply path exists.
- Upgrade from previous candidate with conversations/artifacts/settings/schedules/unknown records. Backup/migration
  commits recover cleanly; failure is not success. Rollback refuses newer incompatible state, never erases fences.
- Alongside proof uses a **disposable second Odin-like installation/service with sentinels**, never `/opt/odin`.
  Run both, upgrade/quit/uninstall Desktop, compare data/credentials/locks/endpoints/processes. Fresh profile cannot
  adopt the other install; package scripts never signal workstation services.

**Behavior tests:** real dpkg install/upgrade/removal in disposable images and user launches; AppImage replacement/
failure performed by the test user; independent state/process comparisons; package-manager versus user-managed
ownership; compatibility refusal before writes. Verify no app-dispatched installer or executable replacement.
Use harmless filesystem/storage failures. Native launch evidence is collected in isolated graphics.

**Gate:** both formats pass ownership/upgrade/alongside/failure/rollback without fabricated cleanup. Required by
**P3.6**, repeated on final P4.5 candidates. **Depends on:** P4.1, P3.1 and P3.3's pre-package lifecycle slice, Phase 2
migrations. No dependency on P3.6, so the early candidate lane is acyclic.

### P4.3: release publication and the new-version notice

**Add:** `.github/workflows/release.yml`, `app/src/main/release-notice.ts`, `app/test/release-notice.test.ts`,
`app/test/e2e/release-notice.spec.ts`, `maintenance/phase4-releases.md`.
**Change:** named main/preload/schema/API operations and General version status/release link, packaging workflow
handoff. This notice needs no core update/apply operation; any actual protocol correction remains Claude-reviewed.

- Match Odin's GitHub Releases model: an authorized version tag drives a release workflow that builds both x86-64
  `.deb` and AppImage using P4.1's pinned build scripts. Validate the tag/product versions, curate release notes,
  retain source SHA/provenance/hashes and attach both formats to the matching GitHub Release. No signing key, pinned
  public key, rotation/revocation process, signing scripts or update manifest is introduced.
- Separate non-publishing candidate builds/rehearsals from publication. P4.5/P4.6 approve exact workflow-built
  artifact hashes before the publication job attaches those same bytes; a rebuild reopens affected gates. Keep
  publication credentials scoped to GitHub Actions, never in app resources, renderer, logs or user profiles.
  Implementing/rehearsing this workflow does not authorize a tag push or release publication.
- The app may report **a new version is available** and link to that release, and nothing more. A named main-process
  operation checks the fixed repository's GitHub Releases metadata without credentials; the renderer has no arbitrary
  network/URL bridge. Compare valid published stable versions, ignore drafts/prereleases for the v1 stable notice,
  and open only a validated release URL for `Calmingstorm/Odin-Desktop`. No custom feed or manifest.
- While the repository is private, unauthenticated checks cannot read its releases. Show **can't check for updates**
  with the private-repo or relevant unavailable reason, not **up to date** or **no releases**. No token is
  bundled, requested, imported from another Odin installation or silently read from a local credential store. Manual
  browser access to a private release uses the user's existing GitHub session, not credentials handled by the app.
- Offline, denied/not-found, rate-limited and malformed responses stay honest and non-blocking. Checking/opening the
  link does not quiesce, stop or restart work, download/stage an artifact, run an installer or replace the AppImage.
  Users upgrade `.deb` through the package manager or replace the AppImage themselves; P4.2 owns those safety tests.

**Behavior tests:** controlled GitHub API responses for private/unauthorized/unavailable, offline/rate-limit,
malformed metadata, no published release, equal/older/newer valid versions, draft/prerelease filtering and rejected
foreign/malformed release URLs. Real Electron notice/link behavior must use the narrow main operation. Scan built
artifacts for credentials; observe that checks/link actions cause no installer, executable write, core restart,
effect replay or quarantine change. Workflow rehearsal builds both formats and checks release notes, version/hash
matching and the publication gate without creating a live release. These are metadata fixtures, not a signed feed.

**Gate:** both formats are publishable through the reviewed workflow; the notice/private-repo can't-check state is
accurate, credential-free and read-only. Publication itself waits for P4.5/P4.6 and explicit owner approval.
**Depends on:** settled decisions C/D, P4.1/P4.2. No in-app quiescence/apply gate. D19 applies to model text.

### P4.4: user docs and operator/recovery notes

**Add:** `docs/user/{install,first-run,chat-and-results,settings,background-work,recovery,updates,accessibility}.md`,
`docs/release/linux-v1-checklist.md`; **Change:** `README.md`, `app/README.md`, maintenance release/port evidence.

Cover formats/requirements, auth/keyring retry, startup/no-tray/Exit, privacy/history, attachment/knowledge choice,
controls/receipt meanings, report/evidence expiry, sleep/exited schedules, unknown/quarantine, compatibility/rollback,
backend limits and uninstall data retention. Managed SSH is supported; phone/server-client/import is not. Document
GitHub Releases, `.deb` package-manager upgrades, user-managed AppImage replacement, the notice-only/private-repo
can't-check state, unsigned release assets and dependency/security maintenance. No in-app download/apply instructions,
feed setup or key custody. State the review watermark, not an 'identical engine' claim from a green aggregate count.

**Behavior validation:** tester follows install/no-tray/login/first-run/keyboard/results/recovery procedures against
candidates in isolation, records outcomes, not Markdown-wording tests. Links/generated metadata can be checked as
data. No screenshots of credentials/private history. **Gate:** docs match shipped behavior/limitations, no misleading
delivery/cleanup or hidden required-feature failure. **Depends on:** behavior/decisions; drafting parallel.

### P4.5: full R4 and final release-candidate qualification

**Add:** `maintenance/r4-acceptance.json`, `maintenance/r4-acceptance.md`, `app/test/e2e/r4.spec.ts`,
`scripts/qualification/release.py`, `.github/workflows/desktop-acceptance.yml`. Machine-readable cases record ID,
dependency, source assertion/corpus mapping, environment, package hash, outcome/evidence/unresolved disposition.
They drive reporting, not turn prose into passing evidence.

**Behavior suite:** section 5 through real Electron/core and both candidate formats. Isolated provider/tool receivers
qualify original-runner integration. An explicitly authorized test account is needed for actual provider sign-in/
network acceptance, evidenced separately. Native rows use actual sessions/backends, not fixture-native substitutes.
Include P4.3's non-publishing release rehearsal and notice/private-repo can't-check cases, plus P4.2's package-manager
and user-managed upgrade paths. No signed-feed or in-app apply acceptance is required or claimed.

**Gate:** applicable Linux R4/contract/D11 cases pass on final hashes; inherited suites/D19/host parity closed;
safety/source drift, dependency/provenance, bundle/reference/catalog scans and current upstream review watermark
reviewed. No missing required case, hidden skip/unqualified backend/unresolved critical port. Reuse evidence only
with identical artifact/environment; rebuilds reopen affected gates. CI does not replace native/Orca evidence.
**Depends on:** Phase 3 closure, P4.1 to P4.4. This step does not publish a release.

### P4.6: explicitly authorized live acceptance, then release handoff

**Add/update:** `maintenance/release-v1.0.md`, `docs/release/linux-v1-checklist.md`: final hashes/watermark/approvals/
evidence, rollback/support. Handoff PR contains no implementation code.

All earlier testing stays isolated. Present Aaron the exact build/hash, actions, paths/session resources, duration,
cleanup/rollback after P4.5. Obtain **immediate explicit authorization** for one final supervised run before any
active-desktop install/run. Limit acceptance to authorized launch/first-run/chat/results/notification/tray/startup/
Exit tasks. Fault injection, parent/guardian killing, lock/sleep/
logout/destructive tests/session teardown remain isolated. Live acceptance does not authorize those on workstation.

**Gate:** Aaron accepts the exact candidate on Mint 22/Cinnamon/X11 after isolated qualification. The release model
is already decided: GitHub Releases with `.deb` and AppImage attached, no signing key. Obtain separate approval for
publication/version/license and release audience; Claude reviews the release PR. Never merge/publish/change visibility
just because tests pass. D16 stays private unless Aaron explicitly chooses otherwise. **Depends on:** P4.5 and the
settled section 6 decisions. This PR performs neither active use nor publication.

## 5. R4 acceptance inventory and contract additions

`docs/discussion/02-odin-capabilities.md` section 8 has ten unnumbered parity bullets. These IDs are new traceability
labels, in original order, not source IDs or passing claims. Phase 2 results are prerequisites; applicable rows also
require the visible app/package behavior listed here.

| ID | Original scenario and required product-level evidence | Main dependency |
|---|---|---|
| R4-01 | Text, image-only, mixed files, PDF, bounded archive, unsupported binary: picker/drop/paste, upload/progress/cancel, original guarded loop, honest type/limit/errors | P3.1/P4.1; Phase 2 step 3 |
| R4-02 | Two conversations/child: serialize same conversation, independent progress, no context/artifact leak, labeled immutable inheritance cutoff | P3.1; Phase 2 steps 2/3 |
| R4-03 | Long harmless call with Steer/Stop: queued/consumed, requested/confirmed, safe cancellation/unknown effect, late controls cannot target successor; exact visible receipts | P3.1/P3.3; Phase 2 step 4 |
| R4-04 | Close/reopen during workflow: progress/results/reports/artifacts catch up; renderer loss continues; core/app loss visibly interrupts without blind replay | P3.1/P3.3; Phase 2 delivery/recovery |
| R4-05 | Compaction/reload/restart: transcript/files/tool outcomes survive independently of compacted context; evidence expiry distinct from durable history | P3.1; Phase 2 transcript/artifacts |
| R4-06 | Window-closed schedule, isolated VM sleep/wake, exited app: conversation/inbox/native notice, D12 policy, no fabricated sleeping execution | P3.3; Phase 2 step 6 |
| R4-07 | Lost-ack repeated submission/reconnect uses same identity and produces one harmless effect; report refresh/paging never reruns check | P3.1; Phase 2 journal/reports |
| R4-08 | Actual install/package-manager `.deb` upgrade/user-managed AppImage replacement/quit/uninstall alongside disposable second install: independent data/credentials/locks/endpoints/processes, untouched sentinels, no import or in-app apply | P4.1/P4.2 |
| R4-09 | Disabled optional feature: absent catalog, stale dispatch/read refusal, no hidden fallback; built-bundle scans; exact approved prompt deltas and original guard/classifier/admin behavior | P3.1/P3.5/P4.1; Phase 2/maintenance closure |
| R4-10 | Future Windows/macOS parity is **deferred to roadmap Phases 6/7 under D15**, not Linux pass or dropped promise. Linux unsupported-capability absence stays tested | Future-platform disposition |

Core-contracts section 7 adds cases not fully specified by those bullets. These CC labels are also new. Record
separate case evidence even when the same execution covers an R4 row:

| ID | Required acceptance beyond scenario list | Gate owner |
|---|---|---|
| CC-01 | Duplicate/conflicting identity, lost/expired receipt reconciliation, no automatic new-ID retry | P3.1 |
| CC-02 | Stale Stop/Steer request/generation fences | P3.1/P3.3 |
| CC-03 | Crash after dispatch preserves unresolved effect; unknown is not retry instruction | P3.1/P3.3 |
| CC-04 | Outbox repair publishes durable result without invoking tool again | P3.1 |
| CC-05 | Resume restores spent budgets/checkpoint/current policy; missing original input/unknown rejects without fresh-run fallback | P3.1 |
| CC-06 | Branch cutoffs/inheritance are snapshots, not live aliases | P3.1 |
| CC-07 | Compaction/restart preserves files and visible history | P3.1 |
| CC-08 | Window-closed schedules use durable destinations, not renderer callbacks | P3.3 |
| CC-09 | Exit/core/app crash/parent loss: exact descendant/input containment evidence | P3.3/P3.5 |
| CC-10 | No-tray reopen/all Exit routes/app-only login startup; `--exit` without running app | P3.3 |
| CC-11 | D12 sleep/offline/exited recovery and deadline/lease re-evaluation | P3.3 |
| CC-12 | Expired cursor/slow client: bounded reset/snapshot, no stale optimistic state or effect replay | P3.1 |
| CC-13 | Revoked evidence/tool/host scope rechecked; alias/cursor is not authority | P3.1/P3.5 |
| CC-14 | Disabled/unconfigured/unqualified tools absent; honest unavailable reason in management | P3.1/P3.5/P4.1 |
| CC-15 | Fresh profile/alongside isolation, independent credentials/default local host, no import | P4.2; Phase 2 step 5 |
| CC-16 | Renderer/core/protocol/storage incompatibility refuses writes before damage; package-manager/user-managed upgrades preserve ownership and compatibility (P4.2); release metadata/private access failures show can't-check, never trigger replacement (P4.3) | P3.1/P4.2/P4.3 |
| CC-17 | Exact approved prompt/request/result deltas; unchanged other prompt bytes, original guard assertions/data/budgets | Phase 2/maintenance closure |
| CC-18 | Native observation/input/release/quarantine/no-replay, rendering, keyboard/Orca and renderer-security evidence | P3.4/P3.5/P3.6 |

**D10 ingress is required, not awaiting a scope decision:** Aaron chose LAN/tailnet option (b). `CC-19` covers
core-contracts section 8: listener off without configured trigger, lifecycle/bind, source auth/signature/replay/body
limits, durable trigger identity/scoped schedule admission, disable/revocation/stale-work fencing, publication/
outbox receipts, and no chat/control API. Phase 2 step 7 supplies headless acceptance; P4.5 proves packaged lifecycle/
settings. Use isolated network namespaces/test peers only, never a live LAN listener.

Storage failure/required-durability refusal, notification loss, corrupt/locked keyring, retained-output expiry,
unavailable attachment/current-policy resume/unresolved cleanup are negative cases in owning rows. Never replace
inherited assertions with screenshots, smoke counts, renamed exclusions or exit codes.

## 6. Aaron's decisions, settled on 2026-10-05

Claude reviewed the work order and Aaron approved it with the update-model change below. A to F (2026-10-05) and G
to I (2026-10-07) are decided, not open options, and do not reopen D1 to D19. Recording approval here performs no setup, test, install or publication.

### Decision A: qualification VMs on this desktop

**Decided:** test GNOME and KDE on Wayland, and Hyprland, in VMs on this workstation, **one heavy VM at a time**
(raised to two by Decision H).
Keep snapshots, exact versions and safe receivers; no active-seat/GPU passthrough or session teardown. Cinnamon/X11
also uses an isolated lab before final acceptance; existing isolated harnesses remain the fast regression lane.

Per active graphical VM, roughly 4 vCPU, 6-8 GiB RAM and 35-50 GiB thin disk are **planning estimates**, not measured
allocations. Setup may take 2-4 hours/image plus 1-2 days for portal/Orca/containment automation; Hyprland/ABI work may
add a day. Check actual available RAM/disk/virtualization before creation. VM evidence records virtual-GPU limits;
it does not claim every physical graphics stack or permit workstation input to fill a missing row.

### Decision B: one final supervised exact-build run

**Decided:** all testing stays off Aaron's active desktop until the end. After P4.5, present the exact build/hash
and proposed tasks/cleanup; Aaron must OK it first, then supervise one final run under P4.6. This is not blanket
permission for live installs, start-at-login, a daily-use trial or earlier native tests. Lock/logout/suspend,
parent/guardian/controller loss and broad cleanup remain isolated, never part of workstation acceptance.

### Decision C: GitHub Releases and manual installation

**Decided:** updates work like Odin's. Publish GitHub Releases with the `.deb` and AppImage attached, built by a
release workflow like Odin's `release.yml`. Users install a new `.deb` through the package manager or replace the
AppImage themselves. P4.2 covers both upgrade/ownership paths. No self-updating app, in-app apply, custom feed or
update manifest. The app may show a new-version notice with a link to the release, and nothing more.

### Decision D: no signing key or bundled release credentials

**Decided:** no signing key, pinned verification key, key-custody scheme, rotation or revocation work. GitHub release
assets are not presented as independently signature-verified. Keep ordinary build hashes/provenance and ownership/
compatibility checks; they are not a substitute signing scheme. While the repo is private, a credential-free app
cannot read releases and says it **can't check**. No token is ever bundled. Workflow publication authorization is
separate from app runtime; no new credential provisioning is part of this documentation PR.

Aaron's reason: "odin (non desktop) updates via github releases and has no key that signs, why does odin desktop
need them".

### Decision E: x86-64, Mint 22 and Ubuntu 24.04 base first

**Decided:** x86-64 first, on Mint 22 and the Ubuntu 24.04 base used by this desktop. Other distros and architectures
come later, each with its own testing. D11 desktop/backend evidence still applies: pin the Cinnamon/GNOME/KDE/
Hyprland lab images and measure the actual glibc/sandbox/helper floor. One green package does not qualify all Debian
derivatives or ARM. The repository stays private under D16; no visibility/license/publication change is implied.
Dependency provenance/licenses are inventoried before distribution.

### Decision F: PDF support downloads automatically on first use

**Decided, 2026-10-05:** "pdf support can download the first time you use it, thats fine".
PyMuPDF remains Odin's optional `[pdf]` extra and is not distributed in either Desktop candidate. Keep the pinned
URL and SHA-256 in `pdf.lock.json`. When no installed module is available, one shared resolver downloads and verifies
the wheel into user-writable data outside the immutable runtime, then imports it. Analyze PDF, PDF attachments and
knowledge PDF imports use that resolver; concurrent first uses share one download. A failed/offline/hash-mismatched
download installs nothing, explains the reason plainly, and the next use retries. No confirmation prompt is added.
`analyze_pdf` stays offered with Odin's unchanged description under D17/D19. Offline PDF use after installation and
honest first-use failure are separate tests; offline first-use PDF success is no longer a bundle requirement.

### Decision G: screen-reader support is not a v1 requirement

**Decided, 2026-10-07:** "i dont care about being usable by blind people... whatever existing work can stay, but...
we're blocking on this?" Orca and screen-reader acceptance is not a v1 release requirement. Existing Orca work,
harnesses and evidence stay. Orca results are recorded but block no step, D11 row (P3.4, P3.6), CC-18 case or
release gate, including the KDE file chooser that exposes no AT-SPI tree. Keyboard-only use remains required.

### Decision H: two lab VMs at once

**Decided, 2026-10-07:** run up to two lab VMs at the same time. This replaces Decision A's one-VM limit. The host has
62 GiB RAM and 24 threads; each lab VM uses 4 vCPU and 8 GiB. Lab work coordinates through two lock slots,
`/run/odq-lab.lock.1` and `/run/odq-lab.lock.2`, with at most two `odq-*` VMs running.

### Decision I: lean v1 release gate

**Decided, 2026-10-07:** "We dont need the insane qualifications, we spend so much time trying to make it work in VM,
which is expensive." Aaron uses Odin's X11 computer use daily, and VMs could not qualify native compositor behaviour
(Odin's Hyprland support needed a real machine). For v1 this decision replaces the D11 VM matrix as the release gate,
along with the native P3.5/P3.6 VM rows, the P4.4 tester walkthroughs and the P4.5 rehearsal and independent-review
items. The [release checklist](../release/linux-v1-checklist.md) is the gate.

- **Scope.** Version 1.0.0. The app is supported on Cinnamon/X11, GNOME/Wayland, KDE/Wayland and Hyprland. Computer
  use is supported on X11 only, at parity with Odin. Wayland computer use (the GNOME Shell extension and the KDE and
  Hyprland plugin builds) moves to 1.1; until then the app refuses it there with guidance.
- **Gate.** CI green on the release commit; every R4/CC acceptance case points to a passing test or a recorded check;
  no known critical or high vulnerability in shipped dependencies; one automated smoke pass of the final build on all
  four desktops (install, first window, tray where present, Exit, logout, upgrade from 0.1.0); Aaron uses the exact
  build on his desktop for a day, including computer use; release notes state the supported scope.
- **Publishing.** A GitHub release on the private repository, unsigned (Decisions C and D), after Aaron's separate
  approval. PDF support stays a first-use download (Decision F): neither Odin's installer nor this package ships
  PyMuPDF.
- **Licence.** MIT, the same as Odin (`LICENSE`).

## 7. Deliverables and authorization summary

Deliverables: implementation PRs, real-core E2E/native proof evidence, exact qualification matrices, unreleased
candidate x86-64 `.deb`/AppImage for Mint 22/Ubuntu 24.04 base, a GitHub release workflow/rehearsal and read-only
new-version/private-repo can't-check tests, manual-upgrade evidence, user docs and final R4/release report. No
Phase 3/4 passing gate is claimed here, and no app/engine implementation, signing system or self-updater is included.

Claude's plan review and Aaron's work-order approval, including the early candidate lane and A to F, are recorded.
Implementation changes each receive review. All testing stays isolated until Aaron OKs one final supervised run
of the exact build. Release publication remains a separate owner approval; PR #17 stays open and unmerged.
