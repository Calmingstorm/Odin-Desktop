# Odin Desktop app (Electron)

The desktop app: tray lifecycle (D3), the chat window, and the main-process broker that talks to Odin's core over
the protocol in [`../docs/design/protocol.md`](../docs/design/protocol.md). Current `main` composes real conversations,
search, requests, attachments, result delivery and Stop/Steer/Resume, plus provider/model configuration,
device-code accounts, tools/timeouts, personality, hosts/trust, memory/lists/knowledge and records.
P3.1 slice 3 connects the existing chat to them: transcript/search, guarded replies, tool activity and retained
output, attachments/artifacts, and generation-bound Stop/Steer/Resume.
P3.1 slice 4 adds the Skills/MCP screen integration, owner-only Odin-parity skill Test, browser qualification
and separate next-use retry observations, plus retained computer management and exact-generation recovery.
P3.1 slice 5 connects step-6B background work, schedules and stored reports to their actual core services. Foreground owner binding is integrated; native input qualification remains pending #98;
uncomposed services stay explicitly unavailable. Real-core sessions never substitute fixture rows, invented
successful reads or endless loading indicators.
The P3.1 slice-1 launch, authentication, status and durable event replay contracts remain, with P3.3 source-build
lifecycle qualification for bounded shutdown, quiescing, unknown-cleanup journaling and core loss.
This integration slice is not full P3.1 or release qualification.

## Qualified environments (P3.6)

**No final D11 candidate is qualified yet.** The executable
[matrix](../maintenance/phase3-matrix.json) and
[closure report](../maintenance/phase3-qualification.md) distinguish interim
measurements from required acceptance. Cinnamon uses the documented Ubuntu
24.04/X11 VM fallback, not Mint certification. GNOME 46/Wayland has no tray
extension; Plasma 5.27/Wayland must prove its actual SNI tray, Secret Service and
native portals/dialogs. Hyprland 0.53.3 runs in Ubuntu 26.04 and qualifies only its
safe-target/recovery/containment subset, never the GNOME/KDE app rows. All rows
are x86-64 virtual GPU lab scope. Xvfb/security/content regression passes do not
qualify Orca, native input, physical GPUs, other distros or Aaron's desktop.

`node scripts/lifecycle-e2e.mjs desktop-security.spec.ts` exercises real Electron
renderer enforcement/content behavior in the existing isolated source runner.
`scripts/qualification/desktop.py` collects immutable packaged guest probes and
validates per-row versions, hashes and closure. Final acceptance needs one build
after P3.5 and the dependency fixes, plus the packaged lifecycle/ownership rerun.

## User documentation and review status

The [first-draft user guide](../README.md#user-guide-first-draft) covers installation, first run, chat/results,
settings, current work boundaries, recovery, updates and accessibility using merged `main` behavior only.
Source/review watermarks and claim references are in
[P4.4 validation](../maintenance/p44-user-docs-validation.md). The
[documentation status](../docs/release/pending-user-docs.md) records the promotion
of merged #37/#39/#40/#42 and remaining native dependencies. The
guides also cover merged #89 package fencing, #90/#94 session Exit and #95
fresh Wayland launch and #96 bounded Exit during core startup.
The [Linux release checklist](../docs/release/linux-v1-checklist.md) still requires P4.5,
P4.6 and Aaron's explicit approvals. This documentation PR is not package or live acceptance.

## Build and test

Use Node 22 (`PATH=/usr/bin:$PATH` on Aaron's desktop, where `~/.local/bin/node` is an old v16).

```bash
npm ci --ignore-scripts # .npmrc sets legacy-peer-deps; install exactly the lockfile without dependency hooks
node node_modules/electron/install.js # explicit Electron acquisition for graphical smoke gates, if dist is absent
npm run typecheck      # main/preload (tsc) and renderer (vue-tsc)
npm test               # unit tests plus integration tests against the fixture core
npm run build          # out/main, out/preload, out/renderer
npm run smoke          # launches the built app on an isolated xvfb display with a throwaway profile
npm run test:real-core  # separate real engine contract gate; never included in npm run check
npm run smoke:real-core # built Electron app + real engine, isolated PID namespace and xvfb
npm run test:a11y     # real Electron keyboard/axe/Chromium AX gate, fixture + real step-five core
npm run test:e2e       # source lifecycle + private native notification receiver, same isolation
```

`npm run smoke` never touches the real desktop session, the user's Odin Desktop profile or their autostart entries. Set
`ODIN_SMOKE_MESSAGE` to drive one message through the core before the screenshot. Set `ODIN_SMOKE_OUT` to choose the
screenshot path.

## Core selection and the real-core gates

`src/main/core-command.ts` explicitly selects `fixture-core/fixture_core.py` in development when no override is
set. For a development real-core session, `ODIN_DESKTOP_CORE_CMD` is a JSON array of executable and literal argv,
for example `["/absolute/engine-venv/bin/python", "-B", "-P", "-m", "src"]` with the engine installed in that environment
(the repository's editable install is supported). `-P` keeps the working directory off Python's import path, so
launching from `app/` cannot shadow the engine with the TypeScript `app/src` namespace. This override works from
any working directory. No shell parsing, interpolation or shell launcher is allowed. The app appends its own socket, token-file,
profile and data-directory arguments. Overrides cannot replace these paths or supply credential flags/IPC-token
values; the token itself remains exclusively in the profile token file.

Packaged launches ignore the development override and **never fall back to the fixture or PATH Python**.
P4.1's packaged resolver selects the bundled interpreter with isolated flags and the immutable resource layout.
A missing runtime/manifest fails visibly rather than silently selecting a developer environment.
This source integration does not establish final package/native acceptance or full P3.1 completion.

Real-core gates require Linux, Node 22, `xvfb-run` (smoke), a working reviewed restricted isolation helper
or full-sudo `sudo -n unshare --pid --fork --mount-proc` path, `setpriv`, and a Python 3.12 environment
containing the engine dependencies from the repository's `pyproject.toml`/`uv.lock`. The launcher probes both
authorized paths and refuses unisolated execution; see [`CONTRIBUTING.md`](../CONTRIBUTING.md).
Provision a repository `.venv` with `uv sync --frozen`, or explicitly set `ODIN_DESKTOP_ENGINE_PYTHON` to a suitable
environment. Imports are checked against **this checkout's real source**, not another installed core.

The gates sanitize the environment, allocate a throwaway HOME/XDG profile, enter a separate PID namespace, drop
back to the caller's uid/gid, and only then import or launch engine code. The whole Electron/core tree is contained
there; it never uses the active desktop or the user's profile. Missing Python, dependencies, engine, namespace
support or required tools fail with an explanation. There are no silent skips or unisolated fallbacks.

The real gates use a canned HTTP/SSE OpenAI-compatible endpoint on loopback. The real core's
`OpenAICompatibleClient`, guarded runner, original tools, durable delivery and controls execute; neither provider
client nor tool results are mocked. No real account, ambient credential or live profile is used.
The provider-backed lanes use the real revision-bound `providers.compat.set`, `secrets.set`, and `models.main.set`
methods to configure and adopt the endpoint. Only the external vault boundary is replaced with an ephemeral
in-memory keyring. There is no test-only `config_provider` injection or plaintext credential fallback.
Provider-backed tests stay out of `npm run check` and fail before engine imports unless the real-core isolation
runner owns their PID namespace and throwaway HOME.

`test:real-core` exercises immutable receipts, replay/watermarks, conversation CRUD/child/reset/search/jump,
guarded publication, queueing, Stop/Steer receipts, successful same-request generation-2 button and typed Resume after an isolated
core interruption, real tool-detail/output paging, file/image bytes, chunked attachment adoption/cancel and provider
failure/recovery. The real Python domain-service contracts also exercise the renderer's catch-up and output reducers.

The provider-backed chat pass of `smoke:real-core` uses the rendered Electron app and named preload bridge to send a committed reply, inspect a real
tool card and retained-output pages, upload a multi-chunk attachment, download a posted file and decode a posted
image, assert a committed request-bound provider-failure notice, stop an exact request, steer one and queue a follow-up,
search/jump, reset context, and exercise conversation lifecycle. Typing `continue` resumes a genuinely preserved
checkpoint on the same request's generation 2 with one original user message and no stuck optimistic bubble.
Afterward, the same trigger without a resumable request is an ordinary user message. The preserved checkpoint
comes from an owned real core interrupted before Electron's normal startup, not synthetic ledger rows or a bypass
of lifecycle restart restrictions. Native file/save chooser selections are injected in main only under
the isolated gate; their native UI, default-app launch and folder reveal are not qualified. Successful checkpoint
Resume is covered by the contract gate.

The real settings contract also exercises the actual Broker, profile persistence, revisions/receipt identity, model adoption,
management writes, knowledge versions, record filtering and write-only credentials. Slice 4 adds skill CRUD and
validation, failed-module cards, a harmless local stdio MCP fixture, publication/enable/reconnect transitions,
settings revision conflicts without replay, server-local keyring failures, and browser/computer truthfulness.
`skills.test` executes the harmless constant with empty input, returns its real result, and increments the manager's
execution count. Disabled and unknown skills retain their actual error outcomes.
Device authentication uses
an isolated localhost auth service and an ephemeral injected keyring, never a production account. These tests
do not qualify native Secret Service unlock behavior or successful model generation.

P3.1 slice 5 also qualifies the named Work, schedule and report methods. Work keeps the immutable public ID and
manager/run/generation bindings, offered actions, structured details and settlement observations. Schedule Work
controls and Settings share one lock by manager ID, while the command still names the immutable public work ID.
Agent steering is queued once to the retained inbox; queued does not mean consumed. Unknown receipts remain locked
under the original command identity. D12 recovery-required, missed-run counts, inert reasons and unknown settlement
are shown without pretending the action ran. Report pages read stored output, never implicitly invoke a check.

`smoke:real-core` runs three separate, labelled passes without retries, each in its own disposable namespace and
fresh profile: the provider-backed chat pass above and the two below. **Production entry / fresh real profile** launches `python -B -P -m src`, without the test bootstrap.
It checks real `status.get` version/phase/instance/capabilities and actual rendered status, chat/search/empty Work,
every settings section's own service loads, and on-demand context reload. It asserts no fixture messages, an empty
audit and logs, and the rendered audit's “Nothing recorded.” state. Turn state is actually available on this base.

**Seeded work proof** uses the existing `workProof` harness bootstrap entry. Its screenshots carry a visible seeded
proof label and metadata-only limitation; its screen names and evidence JSON are labelled too. The test-only
bootstrap admits work through the canonical owner and retained managers. A harmless real local command finishes
one background task and produces a two-page report, with independent child-written effect counters. The rendered
report's Next button reads page two; the counter stays at one. Work displays all six kinds, a journaled task-cancel
receipt and unproven process release. A real scheduler tick coalesces an overdue reminder into a due/lateness/omitted
slots notice and leaves a missed check recovery-required. Agent mailbox/process metadata and waiting-tool cleanup
are controlled seeds, not provider/native execution qualification. Autonomous ticking is stopped only in this
test bootstrap so clock seeding cannot race it; real tick/admission/history/delivery remain intact.
The profile shows its actual local/default host and provisioned public SSH key, empty memory/lists/knowledge,
actual task/check audit/log records in the seeded pass (empty audit/logs in the production pass), unknown usage and its actual turn-state availability. In the
production pass, missing keyring access is a distinct failure with Retry, not an empty account success. The seeded
bootstrap injects only an ephemeral memory keyring at the external Secret Service boundary; its empty accounts and
fresh/provider-not-configured status are genuine reads under that boundary, not native keyring qualification. Both passes save, validate and
test a harmless constant skill through the named bridge, add a local stdio MCP fixture and render its discovered
tools; browser health distinguishes missing bundle/readiness from next-use retry, and computer status says no
session and no qualified foreground/native input. No remote MCP service or real account is used. The gate exits through normal `runtime.shutdown` and parent-EOF cleanup. Evidence paths
and a compact result are printed as JSON. Set
`ODIN_SMOKE_OUT` to retain screenshots of chat and every settings section plus a JSON evidence file alongside the
named production checkpoint. The seeded checkpoint adds `-seeded-work-proof.png`, with its own screenshots and JSON,
and the provider-backed chat pass adds `-provider-chat.png` with its own JSON.
The default screenshots, evidence and profiles are discarded. `real-core-work.test.ts` additionally checks ordinary
`manage_process` list (with actual authorization filtering) and unrelated `run_command` calls pass through the bootstrap to the real executor via admitted
scheduled workflows. Listing the seeded registry row is not real process admission or process execution qualification.

The seeded pass also creates a trigger reminder through the named preload schedule API, then uses the rendered
Webhook ingress inspector to opt in on `127.0.0.1` with port `0` and store a per-trigger source/secret via the
existing settings and write-only secret APIs. Saved opt-in without a secret remains off. Actual `status.get`
ingress reason/address/eligible/unknown fields and the rendered endpoint prove binding to the ephemeral port.
Real authenticated HTTP delivery exercises source/event filtering, rejects a wrong secret, runs two distinct
matching deliveries exactly once, and verifies schedule history plus the actual conversation publications.
Secret clear closes the listener without replay. Existing child-written task/report counters stay unchanged.
No LAN listener, real account, native keyring or production profile participates.

The fixture smoke gate explicitly clears real-core overrides, so it remains a fixture regression gate rather
than accidentally running whichever core a developer shell last selected.

## First-run Settings extension (P3.2)

Chat and Settings show the core's additive `status.get.first_run` projection, not a renderer completion flag.
Its states are fresh, incomplete, saved, effective-ready and degraded. Effective-ready means required provider
configuration is committed and the actual running owner has adopted the matching client/model/settings. It is
not a successful generation, connectivity, quota or OAuth acceptance claim. Explicit runtime health failures
degrade it; missing optional health instrumentation does not add a new setup or execution gate.

The banner opens the existing Models and providers section. Sections remain addressable across re-entry;
Set up later dismisses only the current window's chat reminder, never core state. Start at login stays opt-in
and off; notification previews remain on by default. General keeps preview and quiet-hours controls available.

Background keyring reads never unlock or display a system prompt. Only an owner's explicit banner Retry may
invoke the named, no-argument `secretsUnlock()` bridge (`secrets.unlock` in the core), with a bounded wait off the
core event loop. After success, Retry rehydrates schema/accounts/status, never replaying credential writes.
Missing/locked collections remain `keyring_unavailable`; a timed-out prompt is not success, and another Retry
cannot duplicate an outstanding prompt. No plaintext fallback exists. Submitted secret fields clear immediately,
even on failure. Native Secret Service prompt acceptance remains the separate VM gate.

Device authorization material stays in main. The renderer sees the intended human verification code and a
random local `login_id`, never the provider's `device_auth_id` or OAuth tokens. Main projects both direct answers
and late receipts. `codexOpenVerification()` takes no URL; it opens only the recognized URL retained from the core
login response. The app does not introduce a generic navigation or renderer provider-network bridge.

`test:real-core` includes `test:onboarding`: six behavior tests with seven actual Electron launches cover fresh
and second launch, navigation, incomplete/saved/effective/degraded states, revision and connection retry, login
cancel/expiry, missing/locked keyring recovery, write-only secrets and preference persistence. The test-only auth
adapter blocks outbound HTTP and substitutes external auth/keyring observations without overriding the real
core transactions, transport or provider adoption. Native Secret Service durability/unlock and production OAuth
remain separate acceptance work.

## Accessibility regression gate (P3.4 part 1)

`npm run test:a11y` builds the app, then runs pinned Playwright Electron support and axe-core on a separate
PID namespace, Xvfb display and private session bus. It uses disposable HOME/XDG profiles, forces Chromium
accessibility on, and retains the renderer sandbox/CSP/context isolation. Direct Playwright invocation outside
the owned isolation runner is rejected. It requires the real-core Python environment described above, plus
`dbus-run-session`, `xdotool` and ImageMagick `import` for native-dialog keyboard input and whole-Xvfb zoom captures.
No workstation display/bus/profile is inherited. Missing prerequisites fail the gate, not silently skip it.

The fixture lane covers chat, native attachment selection/cancel, copying and saving a generated file, report
paging/copy, conversation menus/children, Stop/Steer/Queue/Resume, work controls, all settings sections, validation,
password/code privacy, delayed history/search, command suggestions, retained output and 200/400 percent reflow.
The real-core lane covers keyboard status/usage reports and all eleven Settings sections with axe and Chromium
AX audits: step five supplies actual settings/management data, step 6A supplies Skills/MCP and browser/computer
management observations, and step 6B serves background work and schedules. Chat now has real core owners;
historical accessibility evidence predates that composition and does not qualify it merely by inheritance.
The suspended Resume banner has both typed-trigger wording and an AX/axe checkpoint.
Uncomposed services retain explicit unavailable views. Fresh usage is unknown with history not enabled, not a
missing `usage.get` service.
Neither a fixture pass nor a Chromium AX dump proves Orca/AT-SPI speech or Wayland qualification.

Reports, full Chromium AX dumps, axe violations **and incomplete checks**, sandbox/cleanup receipts and screenshots
are written under ignored `test-results/`. Set `ODIN_APP_A11Y_REPORT` to an absolute JSON path to retain a report
outside the checkout. Review `../maintenance/phase3-accessibility.md` for findings, dispositions and open native rows.

## Manual version notice (P4.3 notice slice)

The release workflow uses only the runner's completed, version-verified cached Python 3.12 and cached or
system Node 22. Missing interpreters fail with a provisioning error, never an interpreter download. All three
jobs select their Python explicitly; build gates also disable uv interpreter downloads. Release and app
launchers probe the restricted namespace helper first and verify isolation before running suites. A failed
suite is not replayed through another launcher. The first actual Actions dry-run remains an owner/reviewer
`workflow_dispatch` on reviewed `main`, not a lane action.

General shows the installed **desktop product** version, separate from the engine version, and a manual
**Check for updates** control. It performs one named `checkReleases` main-process operation against the fixed
`Calmingstorm/Odin-Desktop` GitHub Releases endpoint. It does not ask the core to check or apply an update.
The request uses Node HTTPS, an isolated per-request agent, no Electron session/cookies, authentication,
credential-store lookup, proxy credential import or redirects. It is bounded to ten seconds, one MiB and
100 release rows. A further page means incomplete/unavailable metadata, not an invented up-to-date result.

Anonymous checks cannot read this currently private repository. Not-found/unauthorized means **can't check**,
not **no releases**. Offline, rate-limit, unavailable/incomplete and malformed responses have distinct honest
status text. Only published stable `major.minor.patch` (optional `v`) versions are compared numerically; draft
and prerelease rows are ignored. Build/prerelease-tagged or invalid local versions cannot claim stable currency.
Missing/invalid metadata for a purported stable release fails closed.

The renderer cannot choose a repository, URL or transport. `openRelease` accepts no URL; main revalidates its
last successful result as an exact HTTPS release-tag page for this repository. Rechecking revokes the old target
immediately, including during offline failures. Opening hands only that page to the system browser, whose own
GitHub session is outside the app. Nothing checks automatically, downloads assets, writes/stages executables,
runs an installer, stops/restarts the core, changes quarantine or replays effects. Upgrade `.deb` with your
package manager or replace your AppImage yourself.

Targeted development gates:

```bash
npx vitest run test/release-notice.test.ts test/release-notice-ipc.test.ts test/renderer/release-notice.test.ts
npm run build
node scripts/accessibility.mjs release-notice.spec.ts
```

The last command uses the existing isolated runner and checks actual Electron main/preload/renderer operations
with debugger-injected controlled GitHub HTTPS responses. It records sandbox, anonymous request options,
browser-opener calls, write/process-spawn observations, unchanged core incarnation/children and profile
config/data hashes, axe findings and Chromium AX trees for fixture and real-core sessions. Built `out/` resources
are scanned for credential signatures and ambient test canaries. This is not a scan of `.deb`/AppImage candidates,
which P4.1/P4.2 package qualification and the later release-workflow gate must supply. Pattern scans cannot prove
absence of every possible secret. The IPC unit test additionally supplies a fail-on-use broker and writable
dependencies and proves neither notice action dispatches core replay/quarantine/lifecycle operations. The Electron
profile/core comparison is an idle fresh-profile proof, not an active execution/quarantine recovery test.
Controlled metadata/opener fixtures do not qualify live GitHub access, actual browser launch/login,
native screen-reader speech, existing active execution or package-manager replacement.

## Source-build lifecycle qualification (P3.3 part 1)

`test:e2e` uses the shared pinned Playwright 1.63.0 without downloading or substituting a browser. It launches the pinned
Electron source build inside the real-core isolation runner, on Xvfb and a disposable D-Bus session that has no
service-activation directories. The notification receiver is an explicitly started `dbus-next` fixture using the
project Python environment. No installed app, user tray, login autostart, workstation bus or native input is used.
Run through the wrapper, not `playwright test` directly: the harness rejects an unisolated/root invocation.

Set `ODIN_APP_E2E_OUT` to an external directory to retain Playwright JSON and per-case PID/start-tick/namespace,
socket, acknowledgement and cleanup evidence. For source/artifact hashes plus the streamed gate log, build first,
then run `../.venv/bin/python ../scripts/qualification/lifecycle.py --output /absolute/external/evidence` from
`app/`. The driver reports failed gates unchanged. Default evidence and private profiles are discarded.

Close/relaunch, menu/Ctrl+Q/launcher Exit, no-instance `--exit`, parent EOF/abrupt app loss, renderer recovery,
stale/live/non-socket occupancy and startup restart budgets are exercised against the actual step-one core.
Unexpected loss of an already authenticated core stops automatic replacement: a process exit cannot establish
effect/native-resource release. Exit freezes admission and reconnect reconciliation before persisting state and
requesting one shutdown. Process escalation has a separate unknown receipt, never an "undone" result.
Cleanup evidence is fsynced in an app-only sibling file `config/odin-desktop/default-cleanup-state.json`, not in
the identity-checked engine profile. Previous unknown evidence remains visible in a nonmodal banner on subsequent
starts and is not cleared by a later ordinary Exit. **Acknowledge** durably archives the displayed warning with its
time in that same journal. It is an acknowledgment of uncertainty, never proof of undo or release: core resource
quarantine/reconciliation and no-replay policy are unchanged. The same archived evidence stays quiet on restart;
a new unknown event raises a fresh notice. Hidden login starts never open a cleanup modal.

Notification tests exercise actual Electron D-Bus requests, acceptance/refusal and native `ActionInvoked`, then
inspect the exact older conversation/message in the renderer, including renderer loss. Their conversation and
acknowledgement service is explicitly a fixture: those notification tests do not qualify real delivery or requests,
even though `main` now composes their core services. Background work and foreground computer
binding are composed; backend-specific native qualification is still separate.
Remaining D11/native and final installed-candidate gates are tracked under #59,
#98 and #97, not silently qualified by these fixture tests. The continuation also
qualifies actual admitted credential-free management work across hide/Exit, original execution-owner escaped
descendant cleanup, and real isolated X11 guardian-loss quarantine/no-replay. It does not upgrade missing
native release proof into success. See
[`../maintenance/phase3-lifecycle.md`](../maintenance/phase3-lifecycle.md).

## Layout

| Path | What it is |
|---|---|
| `src/main/` | App lifecycle, window hardening, tray, autostart, core supervisor, broker, named IPC methods |
| `scripts/real-core-isolation.mjs` | Shared unprivileged PID-namespace runner for the real-core contract and Electron gates |
| `src/preload/` | The narrow bridge exposed as `window.odin` |
| `src/renderer/` | The chat window (Vue 3) |
| `src/shared/api.ts` | Types shared across all three |
| `fixture-core/` | Development stand-in for the core (protocol v0) |
| `packaging/` | Launcher entry, with the "Exit Odin" action for desktops without a tray |

Window hardening applies to the display page only. It never limits what Odin itself can do.
