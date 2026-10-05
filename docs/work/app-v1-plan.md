# App v1 plan: the interface (Claude)

**Status:** proposed, pending Aaron's OK. Nothing here is built until he says go.
**Owner:** Claude builds; Odin reviews every PR. Built in parallel with Odin's Phase 2 engine work
([`phase-2-desktop-engine.md`](phase-2-desktop-engine.md)), against the development fixture core, then connected to
the real core.

The target is the approved [`chat-experience.md`](../design/chat-experience.md) v1 column: a chat interface at least as
capable as Discord, and a full settings menu (Aaron: "a beyond-flushed out UI, chat interface, settings menu"). Nothing
here limits Odin (D17); the window is a display and control surface for the same engine.

## Rules

- One PR per step, in order. Odin reviews each; nothing merges without that. No attribution trailers.
- Every change ships with tests of real behaviour (store, broker, fixture, main-process policy). Gates run after the
  final change from a fresh checkout: `npm ci --ignore-scripts`, then `npm run check`, plus the xvfb smoke run.
- The window stays a display surface: no Node access, no generic IPC, every bridge method validated
  (`docs/work/app-shell-plan.md`).

## Files every step touches

Each step adds its protocol methods to the shared contract and wires them through the same layers:

| Layer | File |
|---|---|
| Contract | `docs/design/protocol.md` (minor bump), `app/src/shared/api.ts` (types, IPC channel names) |
| Main process | `app/src/main/ipc.ts` (handlers), `app/src/main/schemas.ts` (request validation) |
| Bridge | `app/src/preload/index.ts` (named methods) |
| Window state | `app/src/renderer/src/store.ts`, or a new module under `app/src/renderer/src/stores/` |
| Development core | `app/fixture-core/fixture_core.py` (in-memory implementation) |
| Tests | `app/test/` (broker and fixture), `app/test/renderer/` (window state) |

## Steps

### 0. Protocol minor 3: the v1 surface

Claude drafts, Odin reviews. It is the contract both workstreams build against.

- **Conversations:** delete, reset context, mark read, child conversations.
- **Search:** `search.query`, plus `messages.around` to jump to a hit.
- **Attachments:** a bounded, chunked upload ending in a core-owned reference, with an explicit choice to add an
  attachment to knowledge.
- **Results:** artifact references with bounded reads, tool details and retained output by cursor, report pages.
- **Running work:** listing and controlling agents, tasks, loops, processes and schedules.
- **Usage and status:** values labeled measured, estimated or unknown.
- **Notification events.**
- **Settings:** the settings schema, `settings.set` with a revision check, write-only secrets, and the management
  domains (skills, MCP servers, hosts and trust, memory, lists, knowledge, audit, logs, turn state, computer use, Codex
  accounts with device-code login).

Files: `docs/design/protocol.md` only.

### 1. Conversations and navigation

Rename, archive, safe delete and reset context (distinct operations, each confirmed). A child conversation from any
message, labeled as inherited. Unread badges. A search panel that jumps to the message.

- New: `components/ConversationMenu.vue`, `components/ConfirmDialog.vue`, `components/SearchPanel.vue`.
- Changed: `components/ConversationList.vue`, `components/MessageList.vue`.

### 2. Composer

Drafts persisted per conversation, and attachments by drag and drop, paste or picker. Attachments get previews,
progress, cancel, size limits and honest messages for unsupported types. The main process reads only the files the user
chose (`webUtils.getPathForFile` in the bridge), so the window never reads the disk. A command palette covers `/stop`,
`/steer`, `/status`, `/usage`, `/reload`, `/new`, `/search` and model and effort shortcuts, each showing what it
affects.

- New: `main/attachments.ts`, `main/drafts.ts`, `components/AttachmentTray.vue`, `components/CommandPalette.vue`.
- Changed: `components/Composer.vue`.

### 3. Reading results

- Markdown with tables and syntax highlighting (bundled `highlight.js`), a copy button on code, and virtualized very
  long replies.
- Images inline. Other files as cards with Open, Save as and Reveal, through core references fetched by the main
  process into a private cache. No active previews: no HTML or SVG execution.
- Copy as Markdown or as plain text. A stored-report viewer whose paging never re-runs the check.

- New: `main/artifacts.ts`, `components/Message.vue`, `components/FileCard.vue`, `components/ReportViewer.vue`.
- Changed: `markdown.ts`, `components/MessageList.vue`, `package.json` (`highlight.js`).

### 4. Running work and status

- Tool calls expand to scrubbed arguments, labeled output previews and retained output fetched by cursor (never
  re-run).
- A panel for agents, tasks, loops and processes, with their controls.
- Guarded resume of preserved work, blocked by unknown effects.
- The status bar shows the model, provider and core health, and usage, quota and context as measured, estimated or
  unknown.

- New: `components/WorkPanel.vue`, `components/ResumeBanner.vue`.
- Changed: `components/ToolActivity.vue`, `components/StatusBar.vue`.

### 5. Notifications and the inbox

- Results from closed-window work land in their conversation with unread state.
- Desktop notifications show message previews by default (D13), with per-conversation mute and quiet hours. Clicking
  one opens that conversation. The tray tooltip shows unread counts.

- New: `main/notifications.ts` (pure policy functions, tested).
- Changed: `main/index.ts`, `main/tray.ts`.

### 6. Settings menu

A settings view with these sections:
- **General:** startup, notifications, quiet hours.
- **Models and providers:** main model and effort, auxiliary, agent model policy, Codex accounts with login, activate,
  remove and labels, and the other providers.
- **Personality.**
- **Tools:** built-ins on and off, and timeouts.
- **Skills.**
- **MCP servers.**
- **Hosts and trust:** enroll, test, commit and remove.
- **Scheduled and running work.**
- **State:** memory, lists, knowledge, context reload.
- **Records:** audit, usage, health, logs, turn state, computer use.

Forms are generated from the settings schema; secrets are write-only.

- New: `views/Settings.vue`, `views/settings/*.vue` (one per section), `components/SchemaForm.vue`,
  `stores/settings.ts`, `stores/management.ts`.
- Changed: `App.vue` (navigation between chat and settings).

### 7. Connect to the real core

Once Phase 2's steps land, the app starts the bundled engine instead of the fixture, which stays for tests. Phase 3's
end-to-end acceptance runs in xvfb with a throwaway profile.

- Changed: `main/index.ts` (core command), `scripts/smoke.mjs`.

## Exclusions

- **Packaging and native qualification** (AppImage, tray and autostart acceptance on each desktop): Phase 3's own
  plan.
- **v1+ and later rows** of `chat-experience.md` (pinning, branch from any message, per-conversation model, export,
  `@` pickers, voice): not in this plan.
