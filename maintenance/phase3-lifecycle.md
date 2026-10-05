# P3.3 part 1: source-build lifecycle evidence

## Scope and baseline

Branch `app/p33-lifecycle-part1` starts from pulled `origin/main`
`2acdbc70212b93d1603c532a150d0eb812bf009e` on 2026-10-05. No unmerged Phase 2, qualification-lab or packaging PR
is adopted. This is a source-build lifecycle slice, **not completed P3.3 or full Phase 2 execution qualification**.
`src/` is unchanged. D9/D12/D13/D17 policy is not replaced or tightened by an owner execution approval layer.

The actual core advertises only `status.get`, `events.subscribe` and `runtime.shutdown`. It admits no tools,
turns, agents, schedules, workflows, conversations, real notification delivery or computer sessions. Tests must
not convert that missing graph into successful work/descendant/native-release claims.

## Isolation and reproducibility

- Node 22, project Python 3.12 from `uv sync --frozen --all-extras`, pinned Electron 44.5.1 and Playwright 1.58.2.
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
in 1.7 minutes. Final fresh-checkout results are recorded below after completion.

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

## Open handoffs, not passing rows

1. **Actual work during hide/Exit, harmless admitted descendants, settle/cancel and durable work reconciliation:**
   blocked on the reviewed Phase 2 graph. No ProcessManager/tool call can be submitted to this step-one core.
   Retained original command-journal/entry/lifetime tests protect unknown outcomes and receipt identity, but are
   not proof of a launched app shutting down real turns, escaped descendants or active computer input.
2. **Unknown effect/native-input cleanup:** the app preserves and displays its own unknown lifetime receipt;
   no core resource-enumeration/reconciliation service is present. It never labels effects undone or clears core
   quarantine. Full resource release and safe successor admission require later Phase 2/P3.5 evidence.
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
passed and the complete integrated E2E run passed 17/17. Final counts, source commit and artifact hashes are in
the external evidence and final verification appendix. Neither a clean lineage report nor these passing cases
constitutes independent Claude review or release/native-matrix qualification.
