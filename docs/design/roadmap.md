# Roadmap

Owner: Claude, reviewed by Odin. Draft 2, 2026-10-04, rewritten for D4: bring Odin's code over and maintain both
repositories. There is no shared package and no work in the Odin repository. Every phase has a gate, and nothing starts
without Aaron's go for that phase.

## Phase 0: design approval (now)

- **Work:** this repository's documents, plus Aaron's answers in [`decisions-for-aaron.md`](decisions-for-aaron.md).
- **Gate:** Aaron approves the plan and authorizes Phase 1.

## Phase 1: bring over (this repository)

- **Work:**
  - Record the **baseline**: the Odin commit the copy is taken from.
  - Copy Odin's engine and the code the reuse map keeps, keeping Odin's module paths and names wherever the code is
    shared, so later fixes port as the same diff.
  - Strip Discord machinery and multi-user access control. Removed code leaves no references: no registrations, config,
    tools, UI or dependencies.
  - Bring over the behaviour tests that pin how Odin works: guards, classifier, anti-hedging, continuation, stop and
    steer receipts, durability and no-replay.
  - Apply the D1 prompt changes exactly as Aaron approves them.
  - Start the **port ledger**.
- **Gate:**
  - The carried tests pass.
  - A drift report shows which shared modules match the baseline and which were adapted, and why.
  - No Discord or multi-user references remain.

## Phase 2: desktop engine (headless, Linux)

- **Work:**
  - the desktop surface over the engine (the six seams in [`core-contracts.md`](core-contracts.md)): conversations, the
    durable transcript, artifacts and events with cursors, the inbox, controls and the runtime;
  - local IPC;
  - per-user paths and keyring secrets;
  - the missed-run policy;
  - a headless test client exercising all of it.
- **Gate:** the engine-level parity scenarios pass headless, including:
  - two conversations and a child conversation;
  - stop and steer during a long tool call;
  - a disconnect and catch-up during a workflow;
  - a restart after compaction;
  - a re-sent submission with no duplicate execution;
  - running alongside a server install.

## Phase 3: the app v1 (Linux)

- **Work:**
  - the Electron app with the renderer lockdown, the tray lifecycle (D3) and its no-tray fallback, notifications and
    start at login;
  - the chat workspace v1 from [`chat-experience.md`](chat-experience.md);
  - management screens rebuilt from the WebUI workflows the reuse map keeps;
  - first-run onboarding: provider sign-in, startup and privacy choices.
- **Gate:** UI-level parity scenarios pass, plus keyboard and screen-reader checks, and rendering, security and
  accessibility qualification on Cinnamon/X11 (plus whatever else Aaron's Linux scope includes).

## Phase 4: release v1.0 (Linux)

- **Work:** the full R4 acceptance suite (Odin's round-1 section 8 scenarios plus the contract cases), packaging
  (`.deb`, AppImage), the update channel, and docs.
- **Gate:** Aaron's live acceptance on his desktop, then release.

## Phase 5: v1+ (Linux)

- **Work:**
  - pinning;
  - branch from any message, edit-and-resend, regenerate;
  - per-conversation settings;
  - export;
  - quick-prompt hotkey;
  - rendered diffs;
  - rich agent timelines;
  - live process tail;
  - screenshot capture into the composer.

## Phase 6: Windows

- **Work:** platform implementations behind the capability seams:
  - shell and governor;
  - supervision with Job Objects;
  - transactional patching;
  - computer use;
  - Credential Manager and named pipes;
  - a signed installer.

  Unqualified capabilities publish no tools.

## Phase 7: macOS

- **Work:** the same seams for macOS: Keychain, login items, TCC permissions, ScreenCaptureKit and Accessibility,
  signing and notarization.

## Ongoing from Phase 1: maintaining both (D4)

The process is designed in Odin's round 3 [`maintenance.md`](maintenance.md) (pending). Its outline:

- **The ledger.** Every Odin change after the baseline is ported, marked not applicable (with the reason), or pending.
- **Dual changes.** Changes to shared behaviour land in both repositories, with each PR linking the other.
- **Release review.** Each Odin release is checked against the ledger before the matching Desktop release.
- **Identical tests.** Behaviour tests stay identical where the code is shared.

## Separate lanes

- **Voice** (the Odin voice lane) is independent. If it lands, the desktop app is a natural host for it.
- **Importing an existing user's data** (D5) is handled separately.
- **Phone and remote access** (D6) comes later. The versioned IPC protocol leaves room for it.
