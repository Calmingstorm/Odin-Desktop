# Recovery and safe diagnosis

First draft at the [README review watermark](../../README.md), based on
`main@0b7d596f7e870d06699722f151c4d9837c5433f1`. **pending: #N** sections describe
pinned unmerged implementation, not released features. Screen labels below are
source-verified, not a claim that all real services/native backends behind those
screens are available or release-qualified.

## First, preserve the uncertainty

**Unknown** means an action may have happened without a reliable final record.
It differs from **paused**, **cancelled**, **failed**, or **undone**. Pause changes
future activity; cancellation settles/stops owned work where possible; neither
rolls back external effects. **Quarantine** prevents unsafe reuse of a resource
whose ownership or release is unproven. It is not a warning to dismiss for a retry.

Do not delete locks, receipts, journals, cleanup files or profiles to make an error
disappear. Do not switch backends, downgrade, start another copy over unproven
ownership, or issue the same action under a new command identity. Those shortcuts
lose the evidence needed for safe recovery.

## When a command or effect is unknown

1. Read the original conversation's status and tool activity. Sent means waiting
   for a receipt; queued steering waits to be read; consumed means read, not a
   successful change. See [receipt meanings](background-work.md#read-the-receipt-not-just-the-button).
2. Leave the original action alone while a late receipt can settle it. The app
   retains the original identity and says it will not be sent twice. Refresh or
   reopen the existing record instead of resubmitting.
3. If uncertainty remains, inspect the actual destination through a **read-only**
   view: its existing file/document, service status or remote job record. Record
   observations separately from assumptions. A host acknowledgment or vanished
   process is not receiver proof.
4. Request help with the original request/run identity, time, error and sanitized
   observations. Do not ask “try it again” until the responsible owner has
   reconciled the original effect.

The conversation **Resume last task** banner can explain that unknown effects
block continuation. It is not force-resume. Resume's own unknown outcome also
waits for its original receipt. Historical unknown counts are diagnostic, not
automatically active fences; read current Needs attention/manual-resolution state.

Sources: [receipt state](../../app/src/renderer/src/store.ts),
[Resume banner](../../app/src/renderer/src/components/ResumeBanner.vue),
[controls](../../src/desktop/controls.py), and
[Records screen](../../app/src/renderer/src/views/settings/Records.vue).

## Open the diagnosis screens

Use **Settings** or `Ctrl+,`, then **Records**. Where the running core supports
the service:

- **Health → Check again** reads another snapshot. “Showing the last check” after
  a failure means the displayed snapshot is older, not freshly verified.
- **Audit → Search the audit**, **Tool**, **Errors only**, then **Show**, narrows
  recorded calls. Expand **Input** only when needed; do not share private input.
- **Verify the record** checks available audit integrity, not correctness of an
  action or receiver behavior. An unavailable verifier is neither verified nor
  known to be broken.
- **Logs → Level / Search the logs** reads log records. No entries is not proof
  that no action happened.
- **Preserved work → Refresh** reads request/checkpoint state. **Needs attention**
  and “need manual resolution” differ from “historical unknown (diagnostic only).”
  This panel is not a general effect-resolution editor.

In chat, `/status` is read-only runtime/configuration observation. `/reload`
reloads context, **not** the core or cleanup state. Saved settings, a usable
keyring, and a ready core do not alone prove provider/browser/endpoint health.
For credential/keyring recovery use [first run](first-run.md), not data deletion.

An **unavailable** panel means a missing service, not a clean bill of health.
Main's real Work/Schedules/report-paging routes and skills/MCP/computer management
are not fully composed at this watermark. Do not substitute fixture results.
The [background guide](background-work.md) marks those owners separately;
conversation requests and their controls are real main paths.

Sources: [Records](../../app/src/renderer/src/views/settings/Records.vue),
[read-only turn observer](../../src/desktop/records.py),
[slash commands](../../app/src/renderer/src/commands.ts), and
[main routing](../../src/desktop/core.py).

## Renderer loss, core loss and cleanup notices

Reopen the launcher to return after hiding the window. With no tray, use
**Odin → Exit Odin** or **Ctrl+Q** for Exit, not window Close. Exit performs bounded
owned-work shutdown; escalation and unknown cleanup are possible.

Renderer loss is not permission to restart the core or replay submissions. Core
crashes have a bounded restart budget; replacement is blocked where ownership or
cleanup conditions cannot be proved. A recovered connection or new core process
does not resolve all old effects. Interrupted work must be reconciled from existing
records, not automatically replayed.

On next start, **Cleanup unknown** shows the retained reason/time and any
process/shutdown/unsaved-state observations. Preserve them first. **Acknowledge**
only archives that notice. It does **not** prove cleanup, mark effects undone,
clear resource quarantine or replay work. A newer notice stays authoritative even
when an older acknowledgment finishes later.

If startup refuses ownership/compatibility, preserve the state and collect the
message for operator diagnosis. Do not remove socket/lock files, kill all similarly
named processes or repeatedly start copies. Normal Exit is preferable to forced
termination; forced exit is not a cleanup receipt.

Sources: [Cleanup notice](../../app/src/renderer/src/components/CleanupNotice.vue),
[supervisor](../../app/src/main/core-supervisor.ts),
[shutdown](../../app/src/main/shutdown.ts), and
[lifecycle work order](../work/phase-3-app-v1.md#p33-native-lifecycle-trayno-tray-notifications-and-login-startup).

## Background recovery (pending: #37)

Open **Work → Refresh**, or **Settings → Scheduled and running work → Runs** for
the original schedule. Read its existing conversation, work state and error before
using a control. Runs reads history; **Run now** executes. Pause prevents future
schedule firing, not already-dispatched effects. Reset failures does not resolve
an unknown run.

The branch preserves uncertain runs across restart and refuses replay even after
failure-counter reset. An ordinary missed action after sleep/clock jump differs:
D12 waits for an explicit run, while reminders coalesce. See
[sleep/exited-app policy](background-work.md#close-sleep-clock-changes-and-exit-pending-37).
Paused alone does not tell you whether a retry is safe.

Agent corrections can be queued without consumed. Stopping loops, cancelling
workflows or terminating processes does not undo completed steps. Control the
original record only; a stale target must not affect a successor.

Sources: [PR #37 controls, pinned](https://github.com/Calmingstorm/Odin-Desktop/blob/4ede9e75fb079a0a305c7b24f89700d7fb7c4416/src/desktop/work.py),
and [PR #37 uncertain-run tests, pinned](https://github.com/Calmingstorm/Odin-Desktop/blob/4ede9e75fb079a0a305c7b24f89700d7fb7c4416/tests/test_desktop_schedule_recovery.py).

## Optional tools and their recovery (pending: #28)

These existing screen controls need their pending real service owners. Use them
only when the core reports support:

- **Settings → Skills**: read diagnostics before **Open**, editing and **Validate**.
  Validation compiles without executing; saving loads code, and **Test** executes.
  Do not test an uncertain effect as a harmless recovery check.
- **Settings → MCP servers**: read state/error. **Reconnect** requests reconnection;
  **Refresh tools** refreshes inventory. Neither proves a previous tool call had
  no effect. Header/environment values are stored but never read back; a blank
  secret field does not prove a lost credential.
- **Browser tools**: the branch qualifies configured CDP or bundled Chromium
  before exposing a usable generation. Saved browser settings require restart
  and do not change the boot snapshot. Missing bundled Chromium requires install
  repair, not changing PATH, copying workstation profiles or disabling guards.
  Records has no generic browser repair button. A new session does not replay an
  old click/submission/navigation.
- **Workspace diagnosis**: bounded status observations are read-only and local.
  A partial count is not complete; local Git refs do not establish remote freshness.
  Observation does not fetch, prune, run repairs or clear fences.

Sources: [Skills](../../app/src/renderer/src/views/settings/Skills.vue),
[MCP screen](../../app/src/renderer/src/views/settings/Mcp.vue),
[PR #28 MCP, pinned](https://github.com/Calmingstorm/Odin-Desktop/blob/2d91071a692a646b6d8c466daa5711a37cd8c93f/src/desktop/mcp.py),
[PR #28 browser, pinned](https://github.com/Calmingstorm/Odin-Desktop/blob/2d91071a692a646b6d8c466daa5711a37cd8c93f/src/desktop/browser_runtime.py), and
[PR #28 workspace diagnosis, pinned](https://github.com/Calmingstorm/Odin-Desktop/blob/2d91071a692a646b6d8c466daa5711a37cd8c93f/src/desktop/workspace_diagnostics.py).

## Native-input limits and quarantine (pending: #28; pending: #37)

These branches do not qualify all promised native backends. #28 exposes management
without foreground input authority; #37 adds foreground binding, not final native
qualification. Enabling a backend, headless tests, a receipt or a status read is
not proof of native input support. Status/background requests never authorize
terminals, credential/security prompts or Odin's control plane.

- **Shared X11:** release depends on a surviving guardian and acknowledged owned
  input cleanup. Abrupt sole-guardian loss can lose its ledger. There is no proven
  universal server-side release guarantee. A missing process does not prove the
  mouse/keyboard released. Stop after unknown release.
- **Hyprland:** release_confirmed may mean only a drained guardian ledger and
  closed local resources, without compositor acknowledgment. This is not compositor
  or receiver proof. Scoped native targets/safe same-process dialogs require fresh
  observations; XWayland or ambiguous surfaces do not become supported by recovery.
- **Quarantine:** RELEASE-ALL, later success, another backend or app restart cannot
  erase unknown release. Hyprland may require retirement of the **exact** recorded
  resources, operator-verified external cleanup and explicit reconciliation before
  a fresh session with renewed consent/observation. Release-only recovery never
  resumes input; partial work must not be replayed.

### Inspect Computer use (pending: #28; pending: #37)

1. Open **Settings → Records → Computer use → Refresh**. This is read-only status.
   Note exact session ID, generation, state and recovery reason. On main the backing
   computer service is unavailable; do not infer a safe empty desktop.
2. When the core supplies a quarantined session, the screen may offer **Release…**.
   **Release this session?** asks you to check the computer first and says cleanup
   stays unverified. **Cancel** leaves it unchanged.
3. Do not press Release to dismiss a warning. The renderer sends the exact
   session/generation and `ACKNOWLEDGE UNVERIFIED CLEANUP …`. The returned recovery
   record, not RPC success, determines the outcome. “Closed on your word” is
   attestation, not receiver proof. This is not a universal Hyprland exact-resource
   cleanup/fresh-target wizard. If required steps are not supported by the screen,
   stop and obtain operator help instead of improvising a reset.
4. If cleanup stays unverified or quarantine remains, do not start input. Even a
   released session does not authorize old bindings: obtain newly observed targets
   and required renewed consent, never replay the old action.

Never diagnose a stuck key by injecting another press/release; it can interfere
with a human's actual hold. Safe manual diagnosis uses the affected application's
visible state and platform/resource evidence without new Odin input. Exact cleanup
belongs to a qualified operator. Do not terminate a desktop session, restart a
compositor or indiscriminately kill helpers as a test.

Sources: [Computer use UI](../../app/src/renderer/src/views/settings/Records.vue),
[Release payload/outcomes](../../app/src/renderer/src/stores/records.ts),
[PR #28 management boundary, pinned](https://github.com/Calmingstorm/Odin-Desktop/blob/2d91071a692a646b6d8c466daa5711a37cd8c93f/src/desktop/computer_binding.py),
[native controller](../../src/computer/controller.py), and
[qualification work order](../work/phase-3-app-v1.md#p35-isolated-native-input-containment-and-quarantine).

## Incoming integration failure (pending: #42; pending: #37)

Distinguish an unavailable/unbound listener from an accepted event whose handoff
is unknown. Do not redeliver a payload to diagnose uncertain acceptance. The branch
retains the unknown internal receipt without replaying it, but does not pause the valid trigger or future
authenticated deliveries. Identical bodies and provider retries are new deliveries and may execute again;
receipt recovery is not body deduplication or exactly-once external effects. Interrupted scheduled runs follow
their separate one-time/recurring recovery rule. Inspect the existing conversation/schedule instead. This listener is for
integrations, not remote management; do not publish/open an endpoint as a repair.

Share sanitized source type, delivery time, status and record IDs only, not raw
payloads, signing secrets, authentication headers or secret-bearing URLs. See
[integration privacy](background-work.md#incoming-integrations-pending-42-pending-37).

Source: [PR #42 listener/recovery, pinned](https://github.com/Calmingstorm/Odin-Desktop/blob/50f90306176dd2abd724a1a2d5b97199d294b9c8/src/desktop/webhooks.py).

## What to save and what not to export

Collect build version, package format, desktop/backend, timestamp/time zone, exact
error, original request/run identity, receipt state and recovery reason. Separate
facts from guesses. Copy only necessary sanitized output. Report **Copy page**
copies one page when the pending report route is available. Tool evidence can
expire while its summary survives; [expiry rules](background-work.md#stored-results-and-expiry)
apply. Do not rerun a command to recover expired output.

The inspected UI has no general diagnostic-bundle/full-profile recovery export
wizard. Do not invent Export logs/Export recovery buttons. Result copies/file
saves are not restorable backups of the installation, keyring, checkpoint ledger,
native resources or quarantine.

Review material before sharing. Scrubbing does not remove all private conversation
text, hostnames, paths, identifiers or URLs. Never share credentials, keyring/token
files, raw config/environment, private-history screenshots or whole profile/database
archives in public reports. Private support still needs minimum relevant evidence.

## Compatibility and rollback (pending: #36)

See [Updates](updates.md) for replacement/rollback details rather than a second
installation recipe. Safely Exit the owned app/core and preserve original state
and cleanup receipts before replacement. Pending package checks refuse incompatible
protocol/storage/checkpoints or unproven ownership before admitting writes.
Interrupted upgrades require the compatible candidate, not an arbitrary older
executable.

A backup does not authorize discarding later unknown effects. Do not overwrite
the live profile, erase fences or weaken schema checks to force a downgrade. If a
compatible recovery path cannot be established, preserve state and ask for operator
help. No in-app download/apply or import of another Odin install is supported.

Sources: [package work order](../work/phase-3-app-v1.md#p42-ownership-alongside-isolation-migration-and-upgrades-phase-3-gate),
[PR #36 state checks, pinned](https://github.com/Calmingstorm/Odin-Desktop/blob/30402eb95154d9a4d3076fb5cae165771d4aee36/src/desktop/package_state.py), and
[PR #36 ownership, pinned](https://github.com/Calmingstorm/Odin-Desktop/blob/30402eb95154d9a4d3076fb5cae165771d4aee36/src/desktop/package_ownership.py).
