# Odin Desktop app (Electron)

The desktop app: tray lifecycle (D3), the chat window, and the main-process broker that talks to Odin's core over
the protocol in [`../docs/design/protocol.md`](../docs/design/protocol.md). Until Phase 2 wires in the real engine, a
development stand-in (`fixture-core/fixture_core.py`) answers with scripted echoes. It never ships.

## Build and test

Use Node 22 (`PATH=/usr/bin:$PATH` on Aaron's desktop, where `~/.local/bin/node` is an old v16).

```bash
npm install            # .npmrc sets legacy-peer-deps: npm 10's peer resolver crashes on this tree; peers are pinned compatibly
npm run typecheck      # main/preload (tsc) and renderer (vue-tsc)
npm test               # unit tests plus integration tests against the fixture core
npm run build          # out/main, out/preload, out/renderer
npm run smoke          # launches the built app on an isolated xvfb display with a throwaway profile
```

`npm run smoke` never touches the real desktop session, the user's Odin Desktop profile or their autostart entries. Set
`ODIN_SMOKE_MESSAGE` to drive one message through the core before the screenshot. Set `ODIN_SMOKE_OUT` to choose the
screenshot path.

## Layout

| Path | What it is |
|---|---|
| `src/main/` | App lifecycle, window hardening, tray, autostart, core supervisor, broker, named IPC methods |
| `src/preload/` | The narrow bridge exposed as `window.odin` |
| `src/renderer/` | The chat window (Vue 3) |
| `src/shared/api.ts` | Types shared across all three |
| `fixture-core/` | Development stand-in for the core (protocol v0) |
| `packaging/` | Launcher entry, with the "Exit Odin" action for desktops without a tray |

Window hardening applies to the display page only. It never limits what Odin itself can do.
