# App shell plan (Claude)

Assignee: **Claude**. Reviewer: **Odin**. This is the per-file change list for the Electron app's first PR, presented
for Aaron's OK before any code is written.

**What it is.** Groundwork for Phase 3, built in parallel with Phase 1. The app talks to a small **fixture core** that
speaks the real protocol, so it does not wait on Phase 2. The real engine replaces the fixture in Phase 2.

**Stack.** Electron with Vite, Vue 3 (the same framework as Odin's WebUI) and TypeScript. Built with Node 22. All
dependencies stay in `app/node_modules`.

## Files

| Path | What it does |
|---|---|
| `docs/design/protocol.md` | **Protocol v0** between the app and the core: length-prefixed JSON frames over the owner-only Unix socket; handshake (versions, profile, capabilities); request/response with command IDs; event stream with cursors and catch-up. It is the concrete encoding of core-contracts sections 3, 4 and 7. Claude drafts it and Odin reviews it, because his core implements it in Phase 2. |
| `app/package.json`, `app/package-lock.json` | Dependencies: electron, electron-vite, vue, typescript, zod (IPC schema validation), vitest. |
| `app/electron.vite.config.ts`, `app/tsconfig*.json` | Build config for the main, preload and renderer bundles. |
| `app/src/main/index.ts` | App lifecycle (D3):<ul><li>single-instance lock; a second launch focuses the window;</li><li>close hides the window to the tray;</li><li>Exit runs an orderly shutdown;</li><li>the `--exit` flag (used by the launcher action) stops a running instance.</li></ul> |
| `app/src/main/security.ts` | Window hardening. **This never limits Odin**, whose engine keeps exactly the access it has today. It only stops the window's web page from running things on its own when it displays content (links, HTML, images) from sites and files Odin reads:<ul><li>a custom `app://` origin serving only packaged files;</li><li>a strict CSP;</li><li>sandbox, context isolation and no Node in the renderer;</li><li>navigation and pop-ups blocked;</li><li>permission requests denied;</li><li>external links validated before handing them to the OS.</li></ul> |
| `app/src/main/tray.ts` | Tray icon and menu (Open, status, Exit). If the desktop has no tray, a one-time notice explains how to reopen and exit. |
| `app/src/main/core-supervisor.ts` | Starts the core as a child process, watches it, and restarts it with a bounded policy that never replays work. Exit runs the shutdown handshake. |
| `app/src/main/broker.ts` | The only holder of the core socket: framing, handshake, command IDs, event cursors and reconnect catch-up. |
| `app/src/main/ipc.ts` | Individually named IPC methods, each with a zod schema and sender/origin validation. There is no generic passthrough to the core. |
| `app/src/main/autostart.ts` | Start-at-login toggle: writes or removes the XDG autostart entry, which starts the app minimized. |
| `app/src/preload/index.ts` | The narrow bridge: exposes those named methods and an event subscription, nothing else. |
| `app/src/renderer/…` (`index.html`, `main.ts`, `App.vue`, a few components) | A first chat workspace shell: conversation list, message list, composer, status bar. It renders committed messages and tool activity from the fixture. |
| `app/fixture-core/fixture_core.py` | A tiny development core (Python asyncio) that speaks protocol v0: handshake, status, scripted chat and tool events. Development and tests only; it never ships. |
| `app/packaging/odin-desktop.desktop`, `app/packaging/icons/` | Launcher entry, including an **Exit Odin** action for desktops without a tray. |
| `app/test/…` | Vitest unit tests: lifecycle state machine, IPC schema rejection, framing and handshake, broker catch-up against the fixture. |

## Not in this PR

- The real engine (Phase 1 and 2, Odin).
- Packaging and installers (Phase 4).
- The management screens.
- Autostart and tray behaviour on a live desktop. These are checked later in isolated graphical sessions, not on Aaron's
  active desktop.
