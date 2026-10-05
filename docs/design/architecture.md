# Architecture

Owner: Claude. Draft 4, 2026-10-04 (Odin's round-3 and round-4 reviews applied). It consolidates what Claude and Odin agreed in rounds 1 and 2, and Aaron's
decisions D1 to D6 ([brief](00-brief.md#aarons-decisions-2026-10-04-after-round-1)). Detailed contracts
live in [`core-contracts.md`](core-contracts.md), owned by Odin. The per-file reuse plan is in
[`reuse-map.md`](reuse-map.md), also owned by Odin. Items marked **(round 2)** are being settled now.

## 1. Shape

```
                    Odin Desktop: one application, one user

  ┌──────────────────────────────────────────────────────────────────────────┐
  │ App main process (Electron): tray + menu, windows, notifications,        │
  │ autostart, single instance. The broker: it alone holds the core socket.  │
  │                                                                          │
  │  ┌────────────────────────┐  narrow preload   ┌────────────────────────┐ │
  │  │ Renderer (sandboxed):  │  bridge (named,   │ main-process broker    │ │
  │  │ chat workspace and     │──schema-checked──►│ (validates sender,     │ │
  │  │ management screens     │  methods only)    │ origin, schema)        │ │
  │  └────────────────────────┘                   └───────────┬────────────┘ │
  │                                                           │ owner-only   │
  │                                                           │ socket       │
  │                                               ┌───────────▼────────────┐ │
  │                                               │ Odin core: supervised  │ │
  │                                               │ Python child. The full │ │
  │                                               │ Odin engine brought    │ │
  │                                               │ over from Odin, plus   │ │
  │                                               │ the desktop surface.   │ │
  │                                               └────────────────────────┘ │
  └──────────────────────────────────────────────────────────────────────────┘
   Close window → app stays in the tray, Odin keeps working.
   Tray → right-click → Exit → Odin shuts down safely, then the app exits.
```

## 2. Lifecycle (D3)

**Odin runs while the application runs (D3).**
- **Closing the window** hides it to the tray. Odin keeps working: turns, agents, schedules, loops and workflows all
  continue, and their results land in the conversation inbox with a notification.
- **Exit from the tray's right-click menu** stops Odin.
  - Admission stops, owned work is settled or cancelled safely, state is persisted and supervised input is released.
  - Ending owned child processes is a shutdown *gate*, not an assumption. Anything that cannot be confirmed (for
    example, remote work) is reported as pending or unknown, and those fences are kept.
  - Unknown effects are shown on the next start and are never erased or replayed.
- **If the app's main process dies**, a qualified parent-loss containment path makes sure the core cannot carry on as an
  unsupervised daemon.
- **Start at login** is opt-in (R2). The app starts minimized to the tray, which starts Odin.

**Internal process split.**
- The core is a supervised child process of the app's main process. The renderer is sandboxed and never talks to the
  core directly.
- **A renderer crash or reload** is unobtrusive: the UI reconnects and catches up from durable events.
- **A core crash is not hidden.** Restart is bounded and conditional on storage and ownership reconciliation.
  Interrupted or uncertain work is shown with its durable receipts. Effects are never replayed, and computer-use
  sessions follow Odin's existing recovery rules.
- **One Odin per user profile:** a second launch focuses the running app.

**When the app is not running,** nothing runs. Schedules due while it was exited, or while the machine slept, follow the
missed-run policy on the next start. The lifecycle table in [`core-contracts.md`](core-contracts.md) (section 5) is the
contract.

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
- **Port ledger.** Every Odin commit after the baseline gets an entry in the Desktop repo: ported, not applicable (with
  the reason), intentionally divergent, conflict-blocked or pending. Odin releases are reviewed weekly and before every
  Desktop release. Critical safety fixes are handled immediately.
- **Release watermark.** A Desktop release states the upstream commit its review covers. "Matching" means the fixes
  were reviewed through that pinned watermark, not that the version numbers are equal.
- **Separate versions.** The product bundle version, internal protocol and storage versions, upstream baseline and
  review watermark are all distinct. No shared core is distributed separately.
- **Dual changes.** A change to shared behaviour lands in both repos. The Desktop PR links the Odin PR, or the reverse.
- **Parity tests.** The behaviour tests that pin how Odin works (guards, classifier, anti-hedging, stop and steer
  receipts, durability, no-replay) are carried into Desktop with byte-identical assertions and data where the code is
  shared.
- **The full plan** (baseline, bring-over order, ledger fields, cadence, drift and safety gates, risks) is
  [`maintenance.md`](maintenance.md), owned by Odin.

**Seams inside Odin Desktop.** Odin's six seams from round 1 still define the boundary between the engine and the
desktop surface, now inside one repository: request envelope, conversation service, delivery sink, control service,
runtime service and tool authority/platform service. See [`core-contracts.md`](core-contracts.md).

## 4. Authority model on a personal desktop

- **What goes:** multi-user machinery. Permission tiers, Discord users and roles, per-user host grants, the API-token
  user inventory and guest routing.
- **What stays: Odin's own behaviour, unchanged (D17).** The owner gets exactly what an admin gets in Odin today,
  never anything stricter. These carry over as they work in Odin:
  - secret redaction;
  - untrusted-source provenance;
  - the command governor, behaving as it does for an Odin admin with override on: it logs and audits risky commands
    and never blocks the owner's;
  - host identity and trust (every host the owner adds is usable; there is no per-user host access);
  - the command-workspace check that keeps the default working directory away from Odin's own data;
  - retained-output access checks;
  - effect-uncertainty semantics;
  - computer use's existing session rules.
- **Other local actors get nothing.** An attachment, renderer content or another local process does not become the
  owner by sharing the machine. IPC authenticates its peer.
- **No root.** The core runs as the logged-in user. Elevated actions stay exact, separately authorized operations.

## 5. IPC, shell and what the user sees

- **Shell: Electron for v1** (Claude and Odin, round 2), conditional on qualifying rendering, accessibility and
  security on Linux. The renderer lockdown requirements are in [`platform.md`](platform.md#2-ui-shell-options).
- **IPC.** An owner-only Unix socket (a named pipe on Windows) held by the app's main process, never the renderer. It
  uses a profile-scoped credential and a versioned, framed protocol with capability negotiation. The core contracts
  (section 7) cover the handshake, command IDs, event cursors and catch-up. App/core and chat/control IPC have no TCP listener. A separately activated, scoped inbound webhook integration listener may exist only under [core-contracts section 8](core-contracts.md#8-inbound-webhook-integration-ingress) and Aaron's selected option; it exposes no general client/control API.
- **Committed text only.** Reply text reaches the UI only after the existing guard and classifier path accepts it.
  Provider deltas and rejected drafts are never shown. Live tool, task and control activity is shown, from code-owned
  facts.
- **No tray?** Relaunching focuses the running app. Exit is also in the window menu and the launcher's actions. See
  [`platform.md`](platform.md#1-process-model-platform-view-d3).

## 6. Coexistence, import and remote access

- **Alongside an existing Odin (R3).** Odin Desktop has its own install identity, per-user data roots, IPC endpoint,
  credentials (keyring), known hosts, caches, browser profile, audit and lock. It never touches `/opt/odin` or a server
  install's data, services or ports.
- **Importing an existing user's data:** out of scope for now (D5).
- **Phone and remote access:** not in the first versions (D6). The IPC protocol is versioned and has capability
  negotiation, so a remote client can be added later without reworking the core.

## 7. Inbound webhook triggers

Today, Odin's web server receives webhooks that fire schedules. D2 keeps that capability. The desktop app has no
general network listener, and D6 excludes remote access, so triggers get their own small, separately activated ingress.
It is **specified in [`core-contracts.md` section 8](core-contracts.md#8-inbound-webhook-integration-ingress)** for both
of Aaron's options: loopback only, or an opt-in LAN or tailnet bind.

The contract covers:
- **Lifecycle:** app-owned, and only while eligible webhook-triggered schedules exist.
- **Bind policy:** exact binds, with no fallback to a wider address.
- **Authentication:** per-trigger credentials scoped to an authorized candidate set. Today's `fire_triggers` scans every
  schedule, so a scope is required.
- **Limits and replay:** bounds, saturation controls and durable replay receipts.
- **Preserved behaviour:** today's matching and no-replay fences.
- **Receipts:** separate receipts for admission, effect and publication.
- **D6 separation:** no chat, control or config surface.

**Still to come:** Aaron's scope decision, then implementation and qualification. Until then, trigger parity is
unproven, and configured triggers are never silently dropped.

## 8. Portability seams (Windows and macOS later)

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
