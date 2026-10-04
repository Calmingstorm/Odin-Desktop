# Roadmap

Owner: Claude, reviewed by Odin. Draft 1, 2026-10-04. Sizes and risks for the extraction steps come from Odin's
round 2 **(pending)**. Every phase has a gate, and nothing starts without Aaron's go for that phase.

## Phase 0: design approval (now)

- **Work:** this repository's documents, plus Aaron's answers in [`decisions-for-aaron.md`](decisions-for-aaron.md).
- **Gate:** Aaron approves the plan and authorizes Phase 1.

## Phase 1: characterize (Odin repository)

- **Work:** pin the behaviour the extraction must preserve, as contract tests against today's Odin:
  - guard order and text, the completion classifier, and anti-hedging;
  - stop and steer receipts;
  - durable-turn admission and the no-replay ledger;
  - the scheduler's no-retry of uncertain effects;
  - output authorization, and computer consent and release.

  Much of this is already covered by Odin's ~24.7K tests. This phase adds the seam-level contract scenarios from
  `core-contracts.md`.
- **Gate:** contracts are green on the current master in CI. There are no behaviour changes.

## Phase 2: extract the shared core (Odin repository, its own authorized campaign)

- **Work:** introduce the six seams inside Odin, so that the Discord and web code become adapters over the core.
  Publish a versioned core package. The location is Aaron's decision: a package inside the Odin repo, or a neutral
  repo.
- **Rules:** branch → PR → review, Odin's usual pipeline. Zero behaviour change for server installs, proven by the
  full suite, the Phase 1 contracts, and a branch-deploy gauntlet on the live install before merge.
- **Gate:** the server Odin release runs on the extracted core with no regressions.

## Phase 3: desktop core (this repository, Linux)

- **Work:**
  - a composition root over the core package, the desktop surface and local IPC;
  - per-user paths and keyring secrets;
  - the lifecycle (lock and handshake, quit semantics, missed-run policy).

  The desktop surface covers conversations, the durable transcript, artifacts, events and cursors, the background
  inbox, and controls. A headless test client exercises everything.
- **Gate:** the core-level parity scenarios pass headless, including:
  - two conversations and a branch;
  - stop and steer during a long tool call;
  - closing and reopening the client during a workflow;
  - a restart after compaction;
  - a reconnect with no duplicate execution;
  - running alongside a server install.

## Phase 4: desktop UI v1 (Linux)

- **Work:**
  - the shell;
  - the chat workspace from `chat-experience.md` (v1 items);
  - management screens ported from the WebUI flows the reuse map keeps;
  - tray, notifications and autostart;
  - first-run onboarding (provider sign-in, data location, startup and privacy choices).
- **Gate:** UI-level parity scenarios pass, plus accessibility and keyboard checks.

## Phase 5: release v1.0 (Linux)

- **Work:** the full R4 acceptance suite (Odin's section 8 scenarios), packaging (`.deb`, AppImage), the update
  channel, and docs.
- **Gate:** Aaron's live acceptance on his desktop, then release.

## Phase 6: v1+ (Linux)

- **Work:**
  - quick-prompt hotkey;
  - branches, regenerate and edit-and-resend;
  - per-conversation settings;
  - export;
  - live process tail;
  - remote-server client mode, if Aaron approves it.

## Phase 7: Windows

- **Work:** platform implementations behind the capability seams:
  - shell and governor;
  - supervision with Job Objects;
  - transactional patching;
  - computer use (SendInput and UI Automation);
  - Credential Manager and named pipes;
  - a signed installer.

  Unqualified capabilities publish no tools.

## Phase 8: macOS

- **Work:** the same seams for macOS: Keychain, LaunchAgent, TCC permissions, ScreenCaptureKit and Accessibility,
  signing and notarization.

## Separate lanes

- **Voice** (the Odin voice lane) is independent. If it lands, the desktop app is a natural host for it.
