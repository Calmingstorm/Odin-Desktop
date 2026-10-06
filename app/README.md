# Odin Desktop app (Electron)

The desktop app: tray lifecycle (D3), the chat window, and the main-process broker that talks to Odin's core over
the protocol in [`../docs/design/protocol.md`](../docs/design/protocol.md). P3.1 slice 2 connects settings and
management to the real Phase 2 step-five core: provider/model configuration, device-code accounts, tools/timeouts,
personality, hosts/trust, memory/lists/knowledge, records and profile runtime observations. Conversations, guarded
execution and step-6B background work, schedules and stored reports now use their actual core services. Services
not composed on this slice's base, including skills/MCP management and computer use, remain explicitly unavailable.
Real-core sessions never substitute fixture rows or invented successful reads.
The P3.1 slice-1 launch, authentication, status and durable event replay contracts remain, with P3.3 source-build
lifecycle qualification for bounded shutdown, quiescing, unknown-cleanup journaling and core loss.

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
`CoreCommandContext.resolvePackaged` is the P4.1 seam: packaging supplies immutable resource layout, bundle
verification and interpreter isolation. Until that resolver is integrated, a packaged build fails visibly with
an unavailable-runtime dialog. This slice does not claim packaged launch or full P3.1 completion.

Real-core gates require Linux, Node 22, `xvfb-run` (smoke), `sudo -n unshare --pid --fork --mount-proc`, `setpriv`
and a Python 3.12 environment containing the engine dependencies from the repository's `pyproject.toml`/`uv.lock`.
Provision a repository `.venv` with `uv sync --frozen`, or explicitly set `ODIN_DESKTOP_ENGINE_PYTHON` to a suitable
environment. Imports are checked against **this checkout's real source**, not another installed core.

The gates sanitize the environment, allocate a throwaway HOME/XDG profile, enter a separate PID namespace, drop
back to the caller's uid/gid, and only then import or launch engine code. The whole Electron/core tree is contained
there; it never uses the active desktop or the user's profile. Missing Python, dependencies, engine, namespace
support or required tools fail with an explanation. There are no silent skips or unisolated fallbacks.

`test:real-core` exercises the actual Broker, profile persistence, revisions/receipt identity, model adoption,
management writes, knowledge versions, record filtering and write-only credentials. Device authentication uses
an isolated localhost auth service and an ephemeral injected keyring, never a production account. These tests
do not qualify native Secret Service unlock behavior or successful model generation.

P3.1 slice 5 also qualifies the named Work, schedule and report methods. Work keeps the immutable public ID and
manager/run/generation bindings, offered actions, structured details and settlement observations. Schedule Work
controls and Settings share one lock by manager ID, while the command still names the immutable public work ID.
Agent steering is queued once to the retained inbox; queued does not mean consumed. Unknown receipts remain locked
under the original command identity. D12 recovery-required, missed-run counts, inert reasons and unknown settlement
are shown without pretending the action ran. Report pages read stored output, never implicitly invoke a check.

`smoke:real-core` checks real `status.get` version/phase/instance/capabilities and actual rendered status, exercises
chat/search/work and every settings section's own service loads, and checks on-demand context reload. A test-only
bootstrap admits work through the canonical owner and retained managers. A harmless real local command finishes
one background task and produces a two-page report, with independent child-written effect counters. The rendered
report's Next button reads page two; the counter stays at one. Work displays all six kinds, a journaled task-cancel
receipt and unproven process release. A real scheduler tick coalesces an overdue reminder into a due/lateness/omitted
slots notice and leaves a missed check recovery-required. Agent mailbox/process metadata and waiting-tool cleanup
are controlled seeds, not provider/native execution qualification. Autonomous ticking is stopped only in this
test bootstrap so clock seeding cannot race it; real tick/admission/history/delivery remain intact.
The profile shows its actual local/default host and provisioned public SSH key, empty memory/lists/knowledge,
actual task/check audit/log records, unknown usage and its actual turn-state availability. The slice-6 Electron
bootstrap injects only an ephemeral memory keyring at the external Secret Service boundary; empty accounts and
fresh/provider-not-configured status are genuine reads under that boundary, not native keyring qualification.
The separate real-core contracts retain missing-keyring failure with Retry coverage.
Skills, MCP and computer use remain
unavailable on this slice's base. The gate validates management/readiness projections, rejects fixture rows,
raw capability errors, successful-empty claims for refused reads and duplicate composer usage notices.
It exits through normal `runtime.shutdown` and parent-EOF cleanup. Evidence includes direct core reads and named-bridge observations. Evidence paths
and a compact result are printed as JSON. Set
`ODIN_SMOKE_OUT` to retain screenshots of chat and every settings section plus a JSON evidence file alongside the
named checkpoint; the default screenshots, evidence and profiles are discarded.

The slice-6 smoke creates a trigger reminder through the named preload schedule API, then uses the rendered
Webhook ingress inspector to opt in on `127.0.0.1` with port `0` and store a per-trigger source/secret via the
existing settings and write-only secret APIs. Saved opt-in without a secret remains off. Actual `status.get`
ingress reason/address/eligible/unknown fields and the rendered endpoint prove binding to the ephemeral port.
Real authenticated HTTP delivery exercises source/event filtering, rejects a wrong secret, runs two distinct
matching deliveries exactly once, and verifies schedule history plus the actual conversation publications.
Secret clear closes the listener without replay. Existing child-written task/report counters stay unchanged.
No LAN listener, real account, native keyring or production profile participates; raw screenshots and large
evidence belong outside Git, with small summaries and artifact hashes retained separately.

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

`test:real-core` includes `test:onboarding`: five behavior tests with six actual Electron launches cover fresh
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
AX audits: step five supplies actual settings/management data and step 6B serves background work and schedules.
Uncomposed services retain explicit unavailable views. Fresh usage is unknown with history not enabled, not a missing `usage.get` service.
Neither a fixture pass nor a Chromium AX dump proves Orca/AT-SPI speech or Wayland qualification.

Reports, full Chromium AX dumps, axe violations **and incomplete checks**, sandbox/cleanup receipts and screenshots
are written under ignored `test-results/`. Set `ODIN_APP_A11Y_REPORT` to an absolute JSON path to retain a report
outside the checkout. Review `../maintenance/phase3-accessibility.md` for findings, dispositions and open native rows.

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
acknowledgement service is explicitly a fixture: the current core does not serve real delivery, requests, background work,
notifications or computer input. D11 trays/login, installed package paths, admitted work/descendant cleanup and
full native desktop input grants remain open, not silently qualified by these tests. The continuation also
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
