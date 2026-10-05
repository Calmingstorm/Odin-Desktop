# Phase 3 and 4 work order: finish the Linux app and qualify release v1.0

**Status:** proposed work order for Claude's review and Aaron's phase approval. This PR is documentation only.
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

### Rules for every implementation PR

1. Pull `main`, branch, send a reviewed PR. Independent steps use separate worktrees; dependent steps name a reviewed
   base and rebase before final gates. No attribution trailers. Do not merge this plan.
2. **D17:** no extra command approvals, consent prompts, owner tool/host allow-lists or governor restrictions.
   Preserve Odin's admin behavior, secret redaction, trust, durability, computer consent and quarantine. Renderer
   isolation/release authenticity are approved product boundaries, not a new owner execution policy.
3. **D19:** Claude approves mechanical interface wording substitutions. Changes to what Odin is told to do go to
   Aaron before implementation. No onboarding, packaging or accessibility step adds a system-prompt instruction.
4. This repository only. Do not edit the Odin repository, `/opt/odin`, live services, profiles or credentials. Do
   not adopt another installation's data/environment. Import, remote-client mode, Windows/macOS and v1+ stay out of
   scope. D10's inbound integration listener is not a remote management API.
5. Follow `CONTRIBUTING.md`: engine/process tests run in an isolated PID namespace; native lifecycle/input tests
   run in hard-isolated graphics. Use disposable HOME/XDG roots, private bus/keyring, scrubbed environment and exact
   owned process identities. Never inherit workstation display, bus, credentials or browser. Use harmless tools/
   receivers and controlled provider responses. No destructive or attack command inputs.
6. Native input needs an isolated VM/session whose receiver cannot reach Aaron's desktop. Xvfb suffices for ordinary
   renderer tests, not GNOME/KDE Wayland, real portal consent, containment or login acceptance. Never lock, suspend,
   restart or log out the active desktop. System packages and VM/seat setup need Aaron's OK.
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
| P4.3 | Signed update channel | Hosting/key decisions; P4.1/P4.2; P3.3 quiescence | Updates |
| P4.4 | User and operator docs | Integrated behavior and package/update decisions | Documentation |
| P4.5 | Full R4 on release candidates | Phase 3 closure, P4.1 to P4.4 | Acceptance |
| P4.6 | Aaron's live acceptance and release handoff | P4.5; immediate explicit active-desktop authorization | Owner acceptance |

**Phase boundary:** the roadmap requires package ownership/upgrade tests at Phase 3 exit although packaging is
Phase 4 work. P4.1/P4.2 therefore build/test **unreleased candidates early**, alongside Phase 3. This is not release
authorization. Phase 3 consumes that evidence; Phase 4 later signs/qualifies final candidates with updates and R4.
No gate is moved or waived, and there is no circular dependency. Aaron's work-order approval must include this lane.

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
dispositioned, Orca tasks pass on Cinnamon/X11, GNOME/Wayland and KDE/Wayland. Missing AT-SPI/Orca blocks that row.
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
| Cinnamon/X11 | Rendering, keyboard/Orca, renderer security, tray/no-tray, notifications, startup/Exit/parent loss | X11 |
| GNOME/Wayland, no tray extension | Same app evidence; mandatory no-tray reopen/Exit. Optional extension row separate | GNOME portal |
| KDE/Wayland | Same app evidence; actual SNI tray, KWallet/Secret Service and portal/dialog behavior | KDE portal |
| Isolated Hyprland native session | Safe targets and recovery/containment integration; not substitute desktop coverage | Hyprland |

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
- D14 bundles Playwright Chromium, semantic-search models, PDF support and computer helpers with provenance/hashes/
  licenses. Offline first run proves no feature download-on-demand. Electron Chromium and tool Chromium are separate
  inventories/security-update obligations.
- User skill dependencies cannot mutate core/another install. Qualify Phase 2's worker/loader and bounded SkillContext
  bridge; a separate venv alone does not make packages visible to an in-core import. Missing loader parity blocks
  bundling, not permission to freeze away skill support.
- Package identity is `odin-desktop`, with independent install/launcher/icon/state/credential namespaces. Exclude
  fixture, developer/test-state/review artifacts and credentials. Retain required provenance/legal material and
  secret-recognition patterns under the narrow reviewed reference allowlist.
- Build `.deb`/AppImage from identical pinned inputs, unprivileged where possible. Preserve Chromium sandbox; qualify
  required distro/kernel integration, not sandbox-disabling workarounds. Measure actual glibc/distro/CPU/compositor
  ABI floor, download/disk sizes and startup/runtime memory.

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
- `.deb` upgrade uses package manager, never in-app writes. Quiesce owned app/core before replacement, preserve
  receipts/quarantine, prevent mixed-version writes. Test interrupted install, failed preflight, busy ownership and
  incompatible protocol/storage/checkpoint. Record how package-manager preflight requires/observes stopped app.
- AppImage relocation/spaces/read-only mount/non-writable destination/autostart consistency and owned atomic
  replacement. AppImage update cannot write `.deb` files or unrelated executables.
- Upgrade from previous candidate with conversations/artifacts/settings/schedules/unknown records. Backup/migration
  commits recover cleanly; failure is not success. Rollback refuses newer incompatible state, never erases fences.
- Alongside proof uses a **disposable second Odin-like installation/service with sentinels**, never `/opt/odin`.
  Run both, upgrade/quit/uninstall Desktop, compare data/credentials/locks/endpoints/processes. Fresh profile cannot
  adopt the other install; package scripts never signal workstation services.

**Behavior tests:** real dpkg install/upgrade/removal in disposable images and user launches; AppImage replacement/
failure; independent state/process comparisons; package/app updater dispatch; compatibility refusal before writes.
Use harmless filesystem/storage failures. Native launch evidence is collected in isolated graphics.

**Gate:** both formats pass ownership/upgrade/alongside/failure/rollback without fabricated cleanup. Required by
**P3.6**, repeated on final P4.5 candidates. **Depends on:** P4.1, P3.1 and P3.3's pre-package lifecycle slice, Phase 2
migrations. No dependency on P3.6, so the early candidate lane is acyclic.

### P4.3: update channel, authenticity and quiescent replacement

**Add:** `app/src/main/{updates,update-policy}.ts`, `app/test/update-policy.test.ts`,
`app/test/e2e/updates.spec.ts`, `scripts/packaging/{sign-update.py,verify-update.py}`,
`packaging/linux/update-manifest.schema.json`, `maintenance/phase4-updates.md`.
**Change:** named bridge/schema/API, General update status/actions, packaging workflow. Needed protocol corrections
remain Claude-reviewed, not generic renderer update RPC.

- `.deb` reports version/channel and package-manager path; no self-write or implicit root installer. AppImage verifies
  signed manifest/digest via pinned public key; author credentials/private signing key are never bundled/renderer-visible.
- Manifest names product/version/format/architecture/digest/compatibility/provenance. Bad signature, wrong target,
  truncated artifact, incompatible state or unknown channel fails before replacement. Test rotation/revocation and
  version replay/downgrade policy; no unsigned fallback when feed is absent.
- Checking/downloading need not stop work. **Apply is explicit**, uses bounded P3.3 quiescence/ownership evidence.
  Never auto-kill working core, replay effects, clear unknowns or renew computer consent. Verify/stage/atomically
  replace only owned AppImage, relaunch and verify health, preserve compatible recovery. Failure retains old working
  image or truthfully recoverable stopped state.
- Private repo access is not permission to ship an author token. Aaron chooses hosting/access/key custody in section 6.
  No feed/DNS deployment, visibility change or credential creation in this plan.

**Behavior tests:** controlled local signed feed with real images; tamper/missing/offline/wrong ownership/busy or
unknown resource/interrupted download/apply/schema incompatibility/compatible rollback. Effect counters cannot rise
merely from relaunch. Retain post-replacement native/package health checks; successful rename is not healthy update.

**Gate:** install owners respected; only verified compatible updates apply; failures preserve state/fences. Chosen
hosting/key rotation also has evidence. **Depends on:** Aaron's choices, P4.1/P4.2, P3.3. D19 applies to model text.

### P4.4: user docs and operator/recovery notes

**Add:** `docs/user/{install,first-run,chat-and-results,settings,background-work,recovery,updates,accessibility}.md`,
`docs/release/linux-v1-checklist.md`; **Change:** `README.md`, `app/README.md`, maintenance release/port evidence.

Cover formats/requirements, auth/keyring retry, startup/no-tray/Exit, privacy/history, attachment/knowledge choice,
controls/receipt meanings, report/evidence expiry, sleep/exited schedules, unknown/quarantine, compatibility/rollback,
backend limits and uninstall data retention. Managed SSH is supported; phone/server-client/import is not. Document
update/key/security maintenance and review watermark, not an 'identical engine' claim from a green aggregate count.

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

**Gate:** applicable Linux R4/contract/D11 cases pass on final hashes; inherited suites/D19/host parity closed;
safety/source drift, dependency/provenance, bundle/reference/catalog scans and current upstream review watermark
reviewed. No missing required case, hidden skip/unqualified backend/unresolved critical port. Reuse evidence only
with identical artifact/environment; rebuilds reopen affected gates. CI does not replace native/Orca evidence.
**Depends on:** Phase 3 closure, P4.1 to P4.4. This step does not publish a release.

### P4.6: explicitly authorized live acceptance, then release handoff

**Add/update:** `maintenance/release-v1.0.md`, `docs/release/linux-v1-checklist.md`: final hashes/watermark/approvals/
evidence, rollback/support. Handoff PR contains no implementation code.

Present Aaron exact candidate, actions, paths/session resources, duration, cleanup/rollback after P4.5. Obtain
**immediate explicit authorization** before any active-desktop install/run. Limit acceptance to authorized launch/
first-run/chat/results/notification/tray/startup/Exit tasks. Fault injection, parent/guardian killing, lock/sleep/
logout/destructive tests/session teardown remain isolated. Live acceptance does not authorize those on workstation.

**Gate:** Aaron accepts candidate on Cinnamon/X11 after isolated qualification. Obtain separate publication,
destination/access/version/license/signing decisions. Claude reviews release PR. Never merge/publish/change visibility
just because tests pass. D16 stays private until Aaron chooses otherwise. **Depends on:** P4.5 and section 6 choices.
This plan authorizes neither active use nor publication.

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
| R4-08 | Actual install/upgrade/quit/uninstall alongside disposable second install: independent data/credentials/locks/endpoints/processes, untouched sentinels, no import | P4.1/P4.2/P4.3 |
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
| CC-16 | Renderer/core/protocol/storage/update incompatibility refuses writes/replacement before damage | P3.1/P4.2/P4.3 |
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

## 6. Decisions for Aaron, separate from implementation steps

These are execution/release choices, not a reopening of D1 to D19. This PR activates none of them.

### Decision A: where GNOME/KDE Wayland and Hyprland qualification run

| Option | Planning resource/setup cost | Advantages and limits |
|---|---|---|
| Disposable VMs on this workstation | Per active VM: roughly 4 vCPU, 6-8 GiB RAM, 35-50 GiB thin disk. Cinnamon may fit 4-6 GiB; compositor builds may need 8 GiB. Estimate 2-4 hours/image plus 1-2 days for reproducible portal/Orca/containment automation; Hyprland/ABI work may add a day | Snapshots, actual isolated login/lock/sleep. Virtual GPU does not qualify every real graphics stack; no passthrough of active seat/GPU |
| Aaron's spare machines/dedicated test boot | Roughly 8 GiB available RAM/machine; no workstation guest RAM. Estimate half a day/clean OS/session plus harness maintenance | Real graphics/portals. Only explicitly dedicated sessions with known ownership; another person's desktop is not a disposable seat |
| Hosted graphical VMs/dedicated lab host | Roughly 6-8 GiB/session, storage and recurring charges to quote before use; half a day/image plus automation | Moves load away; remote GPU/display/portal limits remain. No purchase/private-code upload without approval |
| Isolated test user with headless/nested session | Roughly 2-4 GiB/session for Xvfb smoke, 4-8 GiB native Wayland/compositor work. Existing harness adaptation hours; full containment qualification longer | Fast regression lane, shared kernel. Nested/headless is not automatically full login/portal/lock/notification/Orca qualification |

Figures are **planning estimates, not measurements or promises**. Four simultaneous 8 GiB guests reserve roughly
32 GiB before host/model/app load. Check actual available RAM/disk/virtualization before creation; installed 64 GiB
does not mean 64 GiB spare.

**Recommendation:** disposable Cinnamon/GNOME/Plasma VM images plus dedicated Hyprland image, one heavy graphical
guest at a time initially, with snapshots/exact versions. Existing isolated harnesses handle fast regressions. Use
spare hardware for a specifically missing real-GPU proof. Aaron approves topology/resource cap/system dependencies
before setup. No active seat/session restart/GPU reassignment.

### Decision B: what may run on Aaron's active desktop

**Options:** (1) isolated qualification only; (2) bounded supervised acceptance of exact candidate after P4.5;
(3) broader daily-use trial with separate time/data/startup boundaries.

**Recommendation:** option 1 during implementation, then option 2 under fresh authorization naming candidate/path/
actions/cleanup. Tray/notifications/chat/first-run/Exit may be accepted; start-at-login needs explicit choice. No
lock/logout/suspend/guardian-controller fault injection/broad cleanup. Daily-use trial is separate, never implied
by permission to write/build this plan.

### Decision C: update feed and artifact hosting

**Options:** private GitHub Releases with owner-authenticated distribution; owner-controlled HTTPS signed manifest/
artifact feed independent of source visibility; static/manual downloads while hosting is selected. Manual candidate
distribution does **not** satisfy the signed AppImage update-channel release gate. `.deb` stays package-manager-owned;
an apt repository is an additional distribution choice, not an in-app overwrite path.

**Recommendation:** owner-controlled HTTPS feed, signed versioned manifests/hash-named artifacts, source visibility
separate, plus chosen `.deb` package-manager distribution. If private, define user access without bundling author
token. Do not make artifacts public by default. Aaron chooses hostname/audience/budget/access/apt repository. P4.3
can use a local signed fixture feed meanwhile; production hosting remains unprovisioned.

### Decision D: signing key custody, rotation and release authority

**Options:** offline owner-held signing/manual approval; protected CI release environment with dedicated restricted
signing credential; owner-operated signing service with audited requests.

**Recommendation:** owner-held first-release signing, pinned public verification key and tested rotation/revocation.
Automate later only with approved custody/CI controls. Never store private key in Git/app/renderer/logs/this plan.
Aaron chooses authority/publication approvers. No key generation or secret migration in this lane.

### Decision E: distro/architecture baseline, private delivery and license

**Options:** x86-64 `.deb` on selected supported Mint/Ubuntu/Debian images and x86-64 AppImage with explicit runtime
floor; broader architectures/distro versions with separate qualification; extras delayed to later release. D11
desktop/backend coverage is mandatory in every option.

**Recommendation:** x86-64 first, matching workstation, pinned Cinnamon/GNOME/Plasma/Hyprland images and measured
glibc/sandbox/helper floor. Aaron selects supported distro versions before build-image freeze. One green package
does not qualify all Debian derivatives or ARM. Keep repo/delivery private while testing. Aaron chooses release
version/audience/visibility/license under D16; dependency provenance/licenses are inventoried before distribution.

## 7. Deliverables and authorization summary

Deliverables: implementation PRs, real-core E2E/native proof evidence, exact qualification matrices, unreleased
candidate `.deb`/AppImage, update-channel tests, user docs and final R4/release report. No Phase 3/4 passing gate
is claimed here, and no app/engine implementation is included.

Claude reviews this plan. Aaron approves phases, early candidate lane and decision choices. Code changes each
receive review; active-desktop acceptance and release publication remain separate owner approvals.
