# Roadmap

Owner: Claude, reviewed by Odin. Draft 4, 2026-10-04 (Odin's round-3 and round-4 reviews applied), built around D4: bring Odin's code over and maintain both
repositories. There is no shared package and no work in the Odin repository. Every phase has a gate, and nothing starts
without Aaron's go for that phase.

## Phase 0: design approval (now)

- **Work:** this repository's documents, plus Aaron's answers in [`decisions-for-aaron.md`](decisions-for-aaron.md).
- **Gate:** Aaron approves the plan and authorizes Phase 1.

## Phase 1: bring over (this repository)

Follow [`maintenance.md`](maintenance.md) section 3: steps 1 to 3, plus only the profile, path, secret, authority
and capability foundation from step 4. Step 4's request, control and durable-surface wiring, and its coupled
integration gates, complete in Phase 2. Deferred gates are recorded explicitly; none is waived.

- **Work:**
  - Freeze and record the **baseline**: a clean upstream Odin release chosen when this phase is approved.
  - Copy the code and the tests the reuse map keeps, byte-identical at Odin's paths.
  - Strip removed features completely.
  - Adapt the foundation: profile paths, secrets, authority and capability publication.
  - Apply the D1 prompt changes and the other text changes exactly as Aaron approves them.
  - Start the **port ledger** and the safety-path manifest.
- **Gate:**
  - **Carried tests are classified.** Neutral engine suites (guards, classifier, anti-hedging, governor, durability
    stores) pass here. Suites that need the new intake, delivery or control wiring are recorded as Phase 2 gates. No
    fake privileged shim is built to make them pass early.
  - **The drift report** shows shared modules matching the baseline, and every adaptation ledgered.
  - **Removed features leave no references.** No operative, model-facing or shipped references remain in source,
    resolved dependencies or packaging inputs.
    - There is a narrow, reviewed allowlist for provenance, legal notices and negative test fixtures.
    - Credential-recognition patterns may keep the names and shapes of real third-party secrets. That exception permits
      protection only, not a removed feature, transport dependency, registration or model-facing guidance.
    - Scans of the built distribution and the offered runtime catalog are explicit later gates, run once those
      artifacts exist (Phases 3 and 4).

## Phase 2: desktop engine (headless, Linux)

- **Work:**
  - the desktop surface over the engine (the six seams in [`core-contracts.md`](core-contracts.md)): conversations,
    `read_conversation`, the durable transcript, artifacts and events with cursors, the inbox, controls and the runtime;
  - local IPC;
  - per-user paths and keyring secrets;
  - the missed-run policy;
  - the inbound webhook ingress ([`core-contracts.md`](core-contracts.md) section 8), if Aaron includes it.

  A test harness supervises the core during this phase. It is never a shippable daemon alternative to D3.
- **Gate:** the core-contract suite passes headless. It covers:
  - two conversations and a child conversation;
  - stop and steer during a long tool call;
  - a disconnect and catch-up during a workflow;
  - a restart after compaction;
  - lost receipts and a re-sent submission, with no duplicate execution;
  - unknown dispatch and outbox recovery;
  - resume with spent budgets and a current-policy recheck;
  - storage failure;
  - revocation;
  - loss of the core or the app;
  - running alongside a server install with fresh data and no shared state;
  - if Aaron includes webhook triggers, the section-8 ingress acceptance cases.

  **Inherited-suite closure is also a Phase 2 exit criterion.** All **326 Phase-2-deferred suites** listed in
  `maintenance/test-plan.json` must come back in Phase 2, adapted to the Desktop transport and **never dropped**.
  The original assertions, case data and budgets remain the behavior contract; a smoke test, a renamed exclusion
  or an aggregate passing count is not closure. Record each suite's Desktop execution/adapter mapping and results
  in the maintenance accounting, with no unaccounted deferred cases at the exit gate. This includes:
  - `tests/characterization/test_chat_tool_loop.py`: continuation, the completion judge and nudges;
  - the deferred agent suites: nested agents, completion, budgets, lifecycle, transcripts and delivery;
  - `tests/test_recovery.py` and `tests/test_tool_loop_helpers.py`;
  - `tests/test_codex_replay_boundaries.py` and `tests/test_codex_replay_matrix.py`.

  Existing safety/manual gates still apply. "Come back" requires reviewed safe adapters or pure cases where needed,
  not running prohibited inputs, weakening assertions or dispatching against live state. See
  `maintenance/test-plan.md` for the frozen selection and case-by-case acceptance record.

  **Wording/disposition closure is also a Phase 2 exit criterion (D19).** Every remaining
  **NONE row in section 4** of `maintenance/pr2-model-facing-string-approvals.md` must be
  removed with Odin's behavior restored or explicitly dispositioned under D19. Mechanical
  wording swaps go to Claude; any behavior/instruction change, including anything that
  changes what Odin is told to do, goes to Aaron. This explicitly includes:
  - Phase 2 "unavailable" and "not implemented" gates;
  - readiness backstops;
  - results that lost an attachment suffix or image URL;
  - skill dependency installation;
  - the resume empty-read disposition.
  Record each row's disposition, approval where required, and qualified runtime parity
  evidence. D19 is not blanket approval of unwired gates or changed behavior.

  **Fresh-profile host parity is a Phase 2 exit criterion.** A fresh profile must receive
  the same local host and default host as an Odin install. Prove runtime parity using
  disposable profiles and harmless/stubbed execution, including explicit-host and
  omitted-host selection and `http_probe`'s authenticated-owner local fallback, not just
  configuration text or static assertions. The round-3 D17 restoration is baseline
  behavior, not a new approval. No model request path is wired in Phase 1; these gates
  remain deferred and no Phase 2 runtime parity result is claimed here.

## Phase 3: the app v1 (Linux)

- **Work:**
  - the Electron app with the renderer lockdown, the tray lifecycle (D3) and its no-tray fallback, notifications and
    start at login;
  - the chat workspace v1 from [`chat-experience.md`](chat-experience.md);
  - management screens rebuilt from the WebUI workflows the reuse map keeps;
  - first-run onboarding: provider sign-in, startup and privacy choices.
- **Gate:**
  - UI-level parity scenarios pass;
  - keyboard and screen-reader checks pass;
  - no-tray reopen and Exit work;
  - parent-loss containment holds;
  - isolated native-input and quarantine proofs pass;
  - package ownership and upgrade tests pass;
  - rendering, security and accessibility are qualified on Cinnamon/X11 and on GNOME and KDE under Wayland, with computer use on the X11, Wayland portal and Hyprland backends (D11).

  Acceptance on an active desktop is separate and explicitly authorized.

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

The process is defined in [`maintenance.md`](maintenance.md), owned by Odin:
- **The ledger.** Every upstream commit since the baseline is ported, not applicable, intentionally divergent,
  conflict-blocked or pending.
- **Cadence.** Odin releases are reviewed weekly and before every Desktop release, and each Desktop release publishes its
  review watermark. Critical guard, governor, containment or uncertain-effect fixes are triaged immediately and block
  affected releases.
- **Fixes flow back.** Desktop fixes to shared logic go back to Odin through linked PRs, under Odin's own review and
  authorization.
- **CI** fails on any unexplained divergence in safety-critical paths.

## Separate lanes

- **Voice** (the Odin voice lane) is independent. If it lands, the desktop app is a natural host for it.
- **Importing an existing user's data** (D5) is handled separately.
- **Phone and remote access** (D6) comes later. The versioned IPC protocol leaves room for it.
