# Architecture

Owner: Claude. Draft 2, 2026-10-04. It consolidates what Claude and Odin agreed in rounds 1 and 2, and Aaron's
decisions D1 to D6 ([brief](00-brief.md#aarons-decisions-2026-10-04-after-round-1)). Detailed contracts
live in [`core-contracts.md`](core-contracts.md), owned by Odin. The per-file reuse plan is in
[`reuse-map.md`](reuse-map.md), also owned by Odin. Items marked **(round 2)** are being settled now.

## 1. Shape

```
                 Odin Desktop: one application, one user

  ┌────────────────────────────────────────────────────────────────────┐
  │ App process (shell): tray icon + menu, windows, notifications,     │
  │ autostart, quick prompt. Owns the lifetime of everything below.    │
  │                                                                    │
  │   ┌───────────────────────────┐     ┌───────────────────────────┐  │
  │   │ UI (renderer): chat       │◄───►│ Odin core (child process, │  │
  │   │ workspace, management     │ IPC │ Python): the full Odin    │  │
  │   │ screens. Restartable.     │     │ engine brought over from  │  │
  │   └───────────────────────────┘     │ Odin + desktop surface.   │  │
  │                                     └───────────────────────────┘  │
  └────────────────────────────────────────────────────────────────────┘
   Close window → app stays in the tray and Odin keeps working.
   Tray → right-click → Exit → Odin shuts down safely, then the app exits.
```

## 2. Lifecycle (D3)

**Odin runs while the application runs (D3).**
- **Closing the window** hides it to the tray. Odin keeps working: turns, agents, schedules, loops and workflows all
  continue, and their results land in the conversation inbox with a notification.
- **Exit from the tray's right-click menu** stops Odin. Admission stops, owned work is settled or cancelled safely, state
  is persisted, supervised input is released and owned child processes end. Unknown effects are reported on the next
  start; they are never erased or replayed.
- **Start at login** is opt-in (R2). The app starts minimized to the tray, which starts Odin.

**Internal process split.** The core runs as a child process of the app, rather than inside the renderer. A renderer
crash or reload then cannot stop work or lose output: the UI reconnects and catches up from durable events. The app
supervises the core, and if the core crashes it reports interrupted work and restarts the core. This is invisible to
the user. There is still one Odin per user profile: a second launch focuses the running app.

**When the app is not running,** nothing runs. Schedules due while it was exited, or while the machine slept, follow a
documented missed-run policy on the next start. Last-run and next-run times are shown. Odin's round-1 lifecycle table
still applies, with the background-daemon rows replaced by the app-owned model above.

## 3. Code: bring Odin's code over, maintain both (D4)

**Approach.** Odin Desktop starts from a copy of Odin's code at a recorded **baseline commit**. Then:
- strip what doesn't apply (Discord machinery, multi-user access control), following Odin's
  [`reuse-map.md`](reuse-map.md) verdicts;
- adapt the surfaces to the desktop.

There is no shared package and no Odin-repo extraction. Both repositories are maintained.

**Keeping the two in step.** This is the cost of D4, so it's designed in from the start:
- **Keep the layout.** Shared engine code (tool loop, guards, completion judge, providers, tools, agents, scheduler,
  memory, knowledge, skills, MCP, computer use, audit, turn state) keeps Odin's module paths and names where possible,
  so a fix ports as the same diff.
- **Port ledger.** Every Odin commit after the baseline gets an entry in the Desktop repo: ported (with the Desktop
  commit), not applicable (with the reason), or pending. Every Odin release is reviewed against the ledger before the
  matching Desktop release.
- **Dual changes.** A change to shared behaviour lands in both repos. The Desktop PR links the Odin PR, or the reverse.
- **Parity tests.** The behaviour tests that pin how Odin works (guards, classifier, anti-hedging, stop and steer
  receipts, durability, no-replay) are carried into Desktop and kept identical where the code is shared.

**Seams inside Odin Desktop.** Odin's six seams from round 1 still define the boundary between the engine and the
desktop surface, now inside one repository: request envelope, conversation service, delivery sink, control service,
runtime service and tool authority/platform service. See [`core-contracts.md`](core-contracts.md).

## 4. Authority model on a personal desktop

- **What goes:** multi-user machinery. Permission tiers, Discord users and roles, per-user host grants, the API-token
  user inventory and guest routing.
- **What stays.** Local-owner authority still has limits. These all remain:
  - secret redaction;
  - untrusted-source provenance;
  - the command governor;
  - host identity and trust;
  - workspace fences;
  - retained-output access checks;
  - effect-uncertainty semantics;
  - explicit consent for supervised computer input.
- **Other local actors get nothing.** An attachment, renderer content or another local process does not become the
  owner by sharing the machine. IPC authenticates its peer.
- **No root.** The core runs as the logged-in user. Elevated actions stay exact, separately authorized operations.

## 5. IPC and the UI shell (round 2)

- **IPC.** An owner-only Unix socket (a named pipe with an ACL on Windows), a per-install token, and a versioned
  protocol with capability negotiation. No TCP listener by default.
- **Shell.** The leaning is Electron for v1 because of Linux rendering reliability. Tauri is the alternative. See
  [`platform.md`](platform.md).
- **Renderer lockdown:** a preload bridge only, no Node in the renderer, a strict CSP, and file access only through
  references the core issues.

## 6. Coexistence, import and remote access

- **Alongside an existing Odin (R3).** Odin Desktop has its own install identity, per-user data roots, IPC endpoint,
  credentials (keyring), known hosts, caches, browser profile, audit and lock. It never touches `/opt/odin` or a server
  install's data, services or ports.
- **Importing an existing user's data:** out of scope for now (D5).
- **Phone and remote access:** not in the first versions (D6). The IPC protocol is versioned and has capability
  negotiation, so a remote client can be added later without reworking the core.

## 7. Portability seams (Windows and macOS later)

These are Linux and POSIX primitives in today's core, each to be put behind a platform-capability interface. Each one
needs its own design and qualification on Windows and macOS:
- `renameat2` in `apply_patch`;
- `/proc`, `prctl` subreapers and pidfds in the local supervisor;
- POSIX signal handlers;
- shell and governor parsing that assumes bash or sh;
- the X11, Wayland portal and Hyprland computer-use backends;
- systemd and bubblewrap containment;
- 0600 file secrets.

Porting command syntax alone is not safety parity. If a platform lacks a qualified implementation, that capability
publishes no tools.
