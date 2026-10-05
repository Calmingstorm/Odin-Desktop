# P3.3 part 1: source-build lifecycle evidence

## Scope and baseline

Branch `app/p33-lifecycle-part1` started from pulled `origin/main`
`2acdbc70212b93d1603c532a150d0eb812bf009e` on 2026-10-05, then rebased onto reviewed
`cbda9ba316c5f3460bed79ec311b55a5c8032bbd` before fresh final gates. Main advanced during this task with merged
runtime management #21, keyboard/accessibility #29 and qualification accounting #26; their reviewed behavior is retained. No unmerged Phase 2,
qualification-lab or packaging PR is adopted. This is a source-build lifecycle slice, **not completed P3.3 or full
Phase 2 execution qualification**. The continuation adds one documented resource-cleanup bridge to the reviewed
Desktop composition, reusing original execution and native owners without editing their containment/input code.
D9/D12/D13/D17 policy is not replaced or tightened by an owner execution approval layer.

The initial step-one core advertised only `status.get`, `events.subscribe` and `runtime.shutdown`. The final base
also composes reviewed runtime/settings/management methods from #21. It still admits no tool execution,
turns, agents, schedules, workflows, conversations, real notification delivery or computer sessions. Tests must
not convert that missing graph into successful work/descendant/native-release claims.

## Isolation and reproducibility

- Node 22, project Python 3.12 from `uv sync --frozen --all-extras`, pinned Electron 44.5.1 and shared Playwright 1.63.0.
  `npm ci --ignore-scripts`; explicit `node node_modules/electron/install.js`. No system package installation.
- `app/scripts/lifecycle-e2e.mjs` enters a separate PID namespace using the existing privileged namespace
  launcher, drops to uid/gid 1003, clears supplementary groups, and sanitizes the environment before imports.
  Electron retains Chromium's sandbox; no `--no-sandbox` workaround.
- Throwaway `odrc-*` HOME/XDG roots, private Xvfb with TCP disabled, private authorization file and a private
  D-Bus configuration with no service activation directories. Only explicit owned receivers are started.
  Workstation display/bus/credentials/keyring/autostart are never inherited.
- Fixture helpers fail closed outside this environment. Per-case evidence records PID, start ticks, namespace,
  incarnation/socket identities and native receiver requests/actions. Chromium may add a nested PID namespace;
  actual renderer-loss tests verify its UID and ancestry instead of disabling the sandbox.
- Namespace PID 1 teardown removes the isolated process tree. This is a containment backstop, **not evidence of
  native input release or cleanup by an admitted execution service**.
- `scripts/qualification/lifecycle.py --output <external-path>` streams logs and records source SHA, dirty state,
  built main/preload/renderer and lockfile SHA256 values, command, exit status and explicit native/package limits.
  The final fresh-checkout evidence is retained outside Git under `/home/odin/desktop-p33-final-evidence/`.

## Measured routes

The integrated source-tree run passed **17 E2E cases** (12 lifecycle, 5 notification), without retries/skips,
in 1.7 minutes, and passed again after the reviewed runtime/accessibility rebase. The final fresh-checkout gate
report pins its exact source commit and artifact hashes outside Git.

| Route | Observed evidence | Status / limit |
|---|---|---|
| Close, two simultaneous relaunches | Hidden window, successful real status call while hidden, unchanged main PID, core PID/incarnation, reopened same window | Pass; no admitted turns/background work claim |
| No-tray notice | Actual private native receiver accepts the explanation once; a full app restart does not show it again | Pass; native tray/extension not claimed |
| Window menu, Ctrl+Q, launcher `--exit` | Shared accepted shutdown, process gone, persisted process receipt | Pass; Ctrl+Q uses Electron's actual input-event path, not physical/native keyboard qualification |
| `--exit` with no instance | Invalid core override is never evaluated and no Odin profile/core is constructed | Pass |
| Shutdown admission | Local IPC writes/pickers and core dispatch rejected after quiescing; broker reconnect/reconciliation frozen; in-flight identities retained as unknown | Unit and integration pass |
| Normal shutdown | Accepted real runtime shutdown, parent-link close, socket removed and profile can be acquired again | Pass; receipt says process exit, never tool/input release |
| Escalation | Exact owned real core SIGSTOP, request acceptance times out, EOF/TERM/KILL bounded, `processOutcome=killed`, persisted unknown | Pass, separate from normal receipt |
| Graceful parent EOF | Actual core with stream stdin exits zero and releases its socket | Pass; not substituted for abrupt parent loss |
| Abrupt app main loss | Exact main SIGKILL, actual core observes EOF and exits; subsequent start shows persistent unknown warning | Pass for core lifetime only |
| Renderer loss | Exact owned renderer SIGKILL, core remains ready/incarnation unchanged, relaunch recovers display | Pass |
| Ready core loss | Exact core SIGKILL fences automatic replacement, visible failed state, unknown persisted | Pass; no blind replay or unproven resource replacement |
| Stale PID text / dead socket | PID text is not authority; owned dead socket replaced safely | Pass |
| Live / regular-file socket occupant | Owned listener survives untouched; regular file preserved; initial plus three retries exhaust budget and never claim ready | Pass |
| Native notification request/show/ack | Real Electron request accepted by private server and fixture ack settles; acceptance does not advance read watermark | Pass; fixture service, not real core delivery |
| Failure / absent daemon | Native rejection or missing bus name yields failed ack, dedupe remains; app can reopen | Pass |
| Native click / renderer recovery | Server emits received `default` ActionInvoked; exact older message highlighted and in viewport, correct conversation selected | Pass; no direct navigation injected in recovery case |
| Policy regression | Default preview, preview-off, focus, mute, quiet hours, stale and dedupe all exercised before OS request | Pass; existing behavior retained |

## Defects found and repaired

- First-launch `--exit` previously reached app/core construction. It now quits before profile/token/core setup.
- Exit previously waited indefinitely for the final child exit and could admit local writes/reconnect replay
  after draft flush. Shared shutdown now quiesces local/core admission and reconciliation immediately; TERM/KILL
  has a final unknown deadline, and explicit broker close preserves pending identities/settles them honestly.
- Cleanup state was initially placed inside the profile before identity bootstrap. Real smoke exposed the
  unchanged ownership refusal. The receipt moved to an app-only sibling, without changing the core allowlist.
- OS clicks previously selected only a conversation. They now identify a committed message and use existing
  generation-fenced history navigation. Preload readiness queues clicks across renderer loss without granting
  renderer-controlled command/target authority.
- Native notification failure/timeout retires handlers; late acceptance/click cannot masquerade as delivery.
- An initial notification-recovery assertion used Playwright's dead renderer CDP page. Its failure remains in
  earlier evidence. The final test observes the recreated renderer through the surviving main process and still
  requires the native action to drive exact-message navigation; it does not inject a navigation shortcut.
- The shared Playwright update from 1.58.2 to 1.63.0 changed its Electron sandbox default. Process identities
  exposed an implicit `--no-sandbox` in the first post-rebase runs. Those runs do **not** qualify this gate.
  The harness now explicitly requests `chromiumSandbox: true` and refuses disabled sandbox/context isolation
  or Node integration at launch. Only the subsequent clean fresh rerun is final qualification evidence.

## Continued admitted-work, descendant and native-resource qualification

The continuation adds `admitted-work.spec.ts`, `execution-containment.spec.ts` and
`native-reconciliation.spec.ts`. These source-only lanes need no VM or installed package.

- **Actual admitted management work, 3 cases:** a harmless local HTTP receiver counts one `webhooks.outbound.test`
  effect. Work completes while hidden; same app/core relaunches, durable original response replays without another
  HTTP request, conflicting parameters refuse. Exit with a short pending call settles durably before shutdown.
  Exit with a withheld response retains a pending reservation/outcome-unknown; a fresh core does not rerun it.
  The test-only credential-free keyring seam returns no secrets and forbids credential writes. No fake core method.
- **Original escaped execution descendants, 4 cases:** actual source core/entry/management compose the original
  ProcessRegistry in a qualification seam, not a new production chat capability. A TERM-immune leader and a
  double-fork/setsid descendant have independent effect counters and native PID/start-tick/session identities.
  Graceful parent EOF, ordinary Electron Exit and abrupt main loss retire the leader, escaped descendant and
  original local supervisor; counters stop. A pinned pre-bridge baseline exposes missing registry settlement
  while its original independent supervisor still kills descendants. No survivor leak is invented.
- **Real X11 native resource loss, 3 cases:** original Guardian, InjectionHelper and native adapter press a harmless
  Control key in a dedicated private Xvfb receiver. Controller, guardian and actual Electron parent SIGKILL are
  separate cases. Surviving guardian release is confirmed by receiver KeyRelease and XQueryKeymap. Sole guardian
  SIGKILL has no manufactured release receipt or blanket key-up. Original controller/store restart preserve
  quarantine and unknown action identity; repeated action lookup never replays, and fresh session admission stays
  fenced. The real replacement core binds original ComputerIntegration through an explicit qualification seam;
  Exit records computer cleanup unknown and the next app shows core reconciliation-required state.

`src/desktop/resource_cleanup.py` persists current/prior cleanup after identity bootstrap. Management teardown
closes only existing original native and process owners, never instantiates an execution owner just to clean it.
Original process shutdown establishes whole-session absence. Original native close is read back against the
same durable store through a pre-opened read-only connection: a dormant quarantine remains unknown even if
`_live` is empty, while an integration closing its own clean DB is not falsely declared unknown. Cancellation
propagates; an interrupted running marker remains unknown. Core runtime status reports the receipt and the app
shows its warning. Prior ambiguity is never cleared by a later clean ordinary Exit or called undone.

## Remaining handoffs, not passing rows

1. **Turns/agents/schedules/workflows:** actual admitted management and original descendant owners now have
   measured evidence. Full chat/background execution remains absent on reviewed main; those future routes are
   not fabricated by the composition fixtures.
2. **Production graphical grant/release-only reconciliation:** source qualification preserves actual X11 unknown
   cleanup and original durable quarantine, with receiver evidence and no replay. Desktop still intentionally
   denies the original operator reconciliation surface; the tests assert that denial, then explicitly compose
   original read-only absence verification/store CAS for the qualification seam. No new foreground authority,
   automatic native replay, force-released human input or quarantine clearing is added. Full grant/production
   release-only recovery is a reviewed Phase 2/P3.5 handoff, not a test-server/mock release claim.
3. **D11 native desktops/trays/login autostart:** Cinnamon/X11, GNOME/Wayland no-tray, KDE/Wayland and Hyprland
   remain open for part 2. No actual tray painting, login, real keyring timing, sleep/wake or D12 schedule recovery
   is counted here. No active desktop operation was performed.
4. **Package paths:** `.deb`/AppImage relocation/upgrade/autostart are open for P4.1/P4.2 and part 2.
5. **Notification visibility:** OS/test-server acceptance, an emitted action and rendered message are measured.
   Human notification visibility, real delivery/unread persistence and native desktop notification appearance
   remain separate. Fixture acknowledgements cannot qualify a nonexistent real core service.

## Gate record

Before final fresh gates: initial app check 526 tests passed; real-core contract 8 passed; retained core
entry/lifetime/journal/durability/IPC selection 169 passed; driver behavior 3 passed. Focused post-change checks
passed and the complete integrated E2E run passed 17/17. After the reviewed main handoff, app check passed 601,
core/driver regression passed 172, real-core contract passed 8 and management-aware real smoke passed 37 screen
checkpoints. Final counts, source commit and artifact hashes are in the external fresh-checkout evidence.
Neither a clean lineage report nor these passing cases
constitutes independent Claude review or release/native-matrix qualification.
