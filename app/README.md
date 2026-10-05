# Odin Desktop app (Electron)

The desktop app: tray lifecycle (D3), the chat window, and the main-process broker that talks to Odin's core over
the protocol in [`../docs/design/protocol.md`](../docs/design/protocol.md). P3.1 slice 3 connects the existing chat
to the real Phase 2 steps 2–4: conversations/transcript/search, guarded replies, tool activity and retained output,
attachments/artifacts, and generation-bound Stop/Steer/Resume. Settings, management and background-work services
not served by this stack still show explicit unavailable states, not fixture records, successful empty datasets,
or endless loading indicators. This is a stacked integration slice, not full P3.1 or release qualification.

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
```

`npm run smoke` never touches the real desktop session, the user's Odin Desktop profile or their autostart entries. Set
`ODIN_SMOKE_MESSAGE` to drive one message through the core before the screenshot. Set `ODIN_SMOKE_OUT` to choose the
screenshot path.

## Core selection and the real-core gates

`src/main/core-command.ts` explicitly selects `fixture-core/fixture_core.py` in development when no override is
set. For a development real-core session, `ODIN_DESKTOP_CORE_CMD` is a JSON array of executable and literal argv,
for example `["/absolute/engine-venv/bin/python", "-B", "-m", "src"]` when the working directory is the repository
root. No shell parsing, interpolation or shell launcher is allowed. The app appends its own socket, token-file,
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

The real gates use a canned HTTP/SSE OpenAI-compatible endpoint on loopback. The real core's
`OpenAICompatibleClient`, guarded runner, original tools, durable delivery and controls execute; neither provider
client nor tool results are mocked. No real account, ambient credential or live profile is used. Steps 2–4 do not
load provider settings from the CLI yet, so the test-only `test/real-core-provider-entry.py` injects a disposable
configuration through the core's existing `config_provider` seam while retaining its real CLI/lifecycle. It is
not a production settings loader. Provider-backed tests stay out of `npm run check` and fail before engine imports
unless the real-core isolation runner owns their PID namespace and throwaway HOME.

`test:real-core` exercises immutable receipts, replay/watermarks, conversation CRUD/child/reset/search/jump,
guarded publication, queueing, Stop/Steer receipts, successful same-request generation-2 Resume after an isolated
core interruption, real tool-detail/output paging, file/image bytes, chunked attachment adoption/cancel and provider
failure/recovery. The real Python domain-service contracts also exercise the renderer's catch-up and output reducers.

`smoke:real-core` uses the rendered Electron app and named preload bridge to send a committed reply, inspect a real
tool card and retained-output pages, upload a multi-chunk attachment, download a posted file and decode a posted
image, observe provider failure, stop an exact request, steer one and queue a follow-up, search/jump, reset context,
and exercise conversation lifecycle. It also checks honest unavailable Work and Settings screens, then exits
through the existing normal shutdown path. Native file/save chooser selections are injected in main only under
the isolated gate; their native UI, default-app launch and folder reveal are not qualified. Successful checkpoint
Resume is covered by the contract gate, not claimed by the no-checkpoint smoke refusal. Set `ODIN_SMOKE_OUT` to
retain a screenshot and adjacent `-evidence.json`; default evidence and profiles are discarded.

At the slice's base, typed `continue` is still an ordinary submission rather than a resume control, and the later
#22 failure-notice fixes have not reached #23. The app retains real failure outcomes and explains the Resume gap;
the evidence identifies missing core failure notices rather than fabricating them. These backend handoffs must be
merged from `phase-2/controls-resume` when they arrive, then the gates rerun.

The fixture smoke gate explicitly clears real-core overrides, so it remains a fixture regression gate rather
than accidentally running whichever core a developer shell last selected.

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
