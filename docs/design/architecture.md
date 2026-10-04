# Architecture

Owner: Claude. Draft 1, 2026-10-04. It consolidates what Claude and Odin agreed in rounds 1 and 2. Detailed contracts
live in [`core-contracts.md`](core-contracts.md), owned by Odin. The per-file reuse plan is in
[`reuse-map.md`](reuse-map.md), also owned by Odin. Items marked **(round 2)** are being settled now.

## 1. Shape

```
            Odin Desktop (one install, one user profile)

 ┌──────────────────────────────┐        local IPC (owner-only socket / named pipe,
 │ Desktop UI (client)          │◄──────► per-install token, versioned protocol)
 │ chat workspace, management   │                 │
 │ screens, tray, notifications,│                 ▼
 │ quick prompt                 │   ┌───────────────────────────────────────────┐
 └──────────────────────────────┘   │ Odin core (per-user background process)   │
       restartable, any number      │                                           │
       of windows; closing a        │ shared core package (from Odin):          │
       window never stops work      │  tool loop + guards + completion judge,   │
                                    │  providers, tools, agents, scheduler,     │
                                    │  memory, knowledge, skills, MCP, computer │
                                    │  use, audit, turn durability, usage       │
                                    │                                           │
                                    │ desktop surface: conversations, durable   │
                                    │  transcript + artifacts + events,         │
                                    │  background inbox, controls, runtime      │
                                    └───────────────────────────────────────────┘
                                         one core per profile (lock + handshake)
```

## 2. Process model

**Core.** A per-user background process. It owns:
- configuration and secrets;
- providers, the tool executor, and the agent, loop and schedule managers;
- conversations, the durable transcript and artifacts, retained evidence and audit;
- guarded shutdown.

It starts at login when the user opts in. Login-session startup comes first; boot-before-login is a question for
Aaron.

**UI.** A client of the core. It renders the chat and management screens and owns the tray, notifications and the
quick-prompt hotkey. If it crashes, closes or restarts, no work stops and no output is lost: the UI catches up from
durable events.

**One core per profile.** An owner-only lock plus a discovery handshake bind process, profile and protocol generation.
A second launch opens or connects the UI instead of starting a second scheduler. An unrelated Odin server is never
mistaken for this core.

**Lifecycle contract.** The full table is in Odin's
[capabilities round](../discussion/02-odin-capabilities.md#lifecycle-behavior-that-needs-explicit-design).

| Event | Behaviour |
|---|---|
| Close window | Background work continues if the user enabled background operation (disclosed once). |
| Quit UI | Different from Quit Odin. The UI reconnects and catches up later. |
| Quit Odin | Stop admitting work, settle or cancel owned work safely, persist, release supervised input, end owned children. Report unknown effects; never erase them. |
| Sleep or offline | No claim that anything ran while the machine slept. A documented missed-run policy, with last-run and next-run visible. |
| Crash, restart or update | Durable transcript and schedule definitions survive. Interrupted work is shown as interrupted or uncertain, with guarded explicit resume where supported. Nothing is replayed blindly. |

## 3. The shared core and the desktop surface

**Destination.** A versioned core package that both Odin (the server, with its Discord and web surfaces) and Odin
Desktop depend on. The aim is one implementation of:
- the tool loop and guards;
- providers;
- tools and containment;
- durability and audit.

The desktop repo adds its own composition, surface, settings and packaging.

**Not the destination:**
- a permanent copy-and-strip fork, because the two would drift on security and guard fixes;
- the whole `odin` package with features switched off, because feature switches do not isolate dependencies.

**Seams**, defined in `core-contracts.md`:

| Seam | What it does |
|---|---|
| Request envelope | Installation, conversation, branch, request and invocation IDs; content and media references; provenance; explicit scope. Transport IDs never double as authority. |
| Conversation service | Model context, which keeps today's compaction, plus a separate durable user-visible transcript, artifacts and events. |
| Delivery sink | Typed message, artifact, report and notification output bound to a conversation and request. It works with no UI attached. |
| Control service | Stop, steer and resume bound to the exact request, with truthful receipts: queued, consumed or closed; requested or confirmed; unknown. |
| Runtime service | Startup, readiness, feature availability, config apply, shutdown and updates. |
| Tool authority and platform service | The governor, host trust, workspace fences, output authorization, computer consent, and platform-capability boundaries. An unsupported native feature publishes no tools. |

**Extraction sequencing (round 2).** This needs Odin-repository changes that Aaron authorizes separately. It must never
destabilize the server install.

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

## 6. Coexistence and remote mode

- **Standalone.** Its own install identity, XDG data roots, socket, credentials (keyring), known hosts, caches, browser
  profile, audit and lock. It never touches `/opt/odin` or a server's data. Migration is an explicit, validated
  snapshot import; imported schedules stay inert until re-authorized.
- **Remote-server client mode.** Designed as a seam now; its scope is Aaron's decision.
  - Separate, clearly labeled connection profiles.
  - The server keeps its own identity, tier and host policy.
  - No silent fallback from remote to local.
  - Capability negotiation, with unsupported features shown as unavailable.

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
