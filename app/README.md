# Odin Desktop app (Electron)

The desktop app: tray lifecycle (D3), the chat window, and the main-process broker that talks to Odin's core over
the protocol in [`../docs/design/protocol.md`](../docs/design/protocol.md). P3.1 slice 1 connects the app to the real
Phase 2 step-1 core: launch, authentication, status, durable event replay and orderly shutdown. Conversations,
execution and management services are not served by step 1. Their screens show explicit unavailable states,
not fixture records, empty successful datasets, or endless loading indicators.

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

`smoke:real-core` checks real `status.get` version/phase/instance/capabilities and actual rendered status, exercises
chat/search/work and every settings section's own service loads (including tools/timeouts, skills, MCP, hosts,
schedules, personality, memory/lists, knowledge and each records panel), checks on-demand context reload, asserts explicit unavailable states and
absence of fixture rows, raw capability errors, successful-empty claims or duplicate composer usage notices,
then exits through normal `runtime.shutdown` and parent-EOF cleanup. Its evidence is printed as JSON. Set
`ODIN_SMOKE_OUT` to retain screenshots of chat and every settings section plus a JSON evidence file alongside the
named checkpoint; the default screenshots, evidence and profiles are discarded.

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
