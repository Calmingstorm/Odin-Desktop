# Recovery and safe diagnosis

## Preserve the unresolved state

**Unknown** means an action may have happened without a reliable final record.
It is not the same as paused, cancelled, failed or undone. Pausing prevents
future activity; stopping work does not undo completed external effects.
**Quarantine** prevents unsafe reuse when ownership or release is unproven.

Do not delete locks, receipts, journals, cleanup files or profiles to make an
error disappear. Do not downgrade or start another copy over uncertain ownership,
or issue the same action under a new identity. That destroys recovery evidence.

## When a command or effect is unknown

1. Open the original conversation and read its task status and tool activity.
   [Receipt meanings](background-work.md#read-the-receipt-not-just-the-button)
   distinguish sent, queued, consumed and confirmed.
2. Leave the original action alone while a late receipt can settle it. Refresh
   or reopen that record instead of resubmitting.
3. If it stays unresolved, inspect the actual destination through a read-only
   view, such as its file, service status or existing remote job record. A
   vanished process or host acknowledgment alone does not prove the effect.
4. Ask for help with the original request identity, time, error and sanitized
   observations. Do not ask to repeat it until the original outcome is reconciled.

**Resume last task** can explain that unknown effects block continuation; it is
not force-resume. Resume's own unknown outcome waits for its original receipt.
Historical unknown counts are diagnostic, not necessarily current fences. Read
the current **Needs attention** or manual-resolution state.

## Open the diagnosis screens

Open **Settings → Records**. Where the service is available:

- **Health → Check again** reads a new snapshot. **Showing the last check** after
  a failure means the displayed result is older, not freshly verified.
- **Audit → Search the audit**, **Tool**, **Errors only**, then **Show** narrows
  recorded calls. Expand **Input** only when needed; it can contain private data.
- **Verify the record** checks available audit integrity, not whether an action
  was correct. An unavailable verifier is not a verified record.
- **Logs → Level / Search the logs** reads logs. No entries does not prove no
  action occurred.
- **Preserved work → Refresh** reads checkpoints. **Needs attention** or **need
  manual resolution** differs from historical unknown diagnostics. It is not a
  general editor for resolving real-world effects.

In chat, `/status` reads runtime/configuration state. `/reload` reloads context,
not the core or cleanup state. A ready core, saved setting or usable keyring
does not itself prove provider or endpoint health.

Use [First run](first-run.md#recover-the-keyring) for keyring recovery. Skills and
MCP management and retained computer status are supported; see
[Settings](settings.md#skills-and-mcp-servers) for their controls. **Unavailable**
still means a service cannot currently be used, not that there are no records or
a clean bill of health. Work, Schedules and report management remain unavailable
in the current core.

## A skill or server will not work

- In **Settings → Skills**, read the load state and diagnostics first. **Validate**
  checks code without execution; **Create/Save** loads it and can execute
  module-level code. Saving successfully is not proof the skill's external
  operation works. The current core refuses the visible **Test** request because
  management test execution is unavailable. Do not retry it to settle an unknown
  earlier effect.
- In **Settings → MCP servers**, read the server state, error and offered-tool
  counts. Check **MCP on** and the server's on/off state. For a known connection
  failure, correct the configuration and use **Reconnect**; use **Refresh tools**
  when the inventory needs updating. Neither verifies a previous call's outcome.
  Stored header/environment values are never shown again; blank fields are not
  evidence of missing credentials. If the error requires an unlocked keyring,
  recover that first, then reconnect. For an older imported server, **Reconnect**
  can also migrate its stored credentials into the profile keyring. Read the
  migration error or returned state; do not copy credentials into ordinary fields.
  A connected server still does not establish that chat can call its tools.
- For browser failures, check the saved versus running browser settings. Changes
  require a clean app/core restart; they do not alter the current start's captured
  configuration. A CDP connection error calls for checking the configured endpoint;
  a missing or unusable bundled Chromium calls for installation repair. There is
  no generic browser-repair button in Records. Do not change PATH, copy personal
  browser profiles or weaken network guards as a repair. A fresh browser session
  does not authorize replaying an uncertain click, submission or navigation.

### Workspace diagnosis

There is no dedicated workspace-diagnostics screen in the current UI. **Health →
Check again** collects a local workspace snapshot, but the panel does not display
its workspace details. Do not interpret a healthy component list as a workspace
size check, clean repository or up-to-date remote branch.

If support supplies the core's workspace snapshot, read its unavailable/partial
state before its counts. Collection is bounded, local and read-only: partial
counts are incomplete and local Git references do not establish remote freshness.
It does not fetch, prune, repair the workspace or clear safety blocks.

## Window or core loss

Reopen from the launcher after hiding the window. Use **Exit Odin** or **Ctrl+Q**
to stop the app, not window Close. Exit attempts bounded shutdown; it may report
unknown cleanup.

Losing the window is not permission to replay submissions or restart the core.
Core crashes have a limited restart budget, and replacement can refuse when
ownership or cleanup is unproven. A new core process or recovered connection
does not settle old effects. Inspect existing records before continuation.

On the next start, **Cleanup unknown** shows retained reason/time and shutdown
observations. Preserve those first. **Acknowledge** only archives the notice:
it does not prove cleanup, undo effects, clear quarantine or replay work.

If startup refuses ownership or compatibility, keep the error and state for
support. Do not remove sockets/locks, kill every similarly named process, or
repeatedly start copies. Forced termination is not a clean shutdown receipt.

## Computer-input safety

### Read the retained session

1. Open **Settings → Records → Computer use → Refresh**. This requests status,
   not mouse/keyboard input. The core retains session and recovery records, but
   the current panel does not display that retained session record. A blank panel
   or absent Release button therefore does not establish that there is no session
   or that cleanup succeeded. Preserve any error and ask an operator to inspect
   the retained record, including its exact session ID, generation and recovery
   reason. A failed refresh may leave **Showing the last read**; that is not fresh
   evidence.
2. The current core has retained-session management but no foreground input
   authority. An enabled value or a status read does not establish native backend
   support, consent or permission to start/resume input. No session shown is not
   proof that a previous application released input.
3. If a quarantined row offers **Release…**, its confirmation asks you to check
   the computer first and says cleanup remains unverified. **Cancel** leaves the
   session unchanged. The current screen sends a release request the core rejects;
   it does not release or reconcile the session. Do not use it to dismiss
   quarantine or establish cleanup. Preserve the record and obtain operator help.
   If a recovery result is already recorded, read it: a refused, unknown,
   incomplete or still-quarantined result is not permission to continue.

This screen is not a complete native recovery wizard. It does not provide a
fresh-target/renewed-consent input workflow or permission to replay partial work.
An acknowledgment made by an operator is not proof that the receiving application
released input, even if a retained session is closed.

If a resource is quarantined or its input release is unknown, stop. Do not inject
another key press or mouse release to test it; that can interfere with a person's
held input. A disappeared helper or receipt alone is not proof that the receiving
application released input. Preserve the exact session/resource identity and
obtain operator help. Do not restart a desktop session or indiscriminately kill
helpers as a diagnosis step.

### Native backend limits

- **Shared X11:** cleanup depends on a surviving guardian and acknowledged release
  of its owned input. Abrupt loss of the sole guardian can lose that record. There
  is no universal server-side release guarantee; a vanished helper is not proof
  that the mouse or keyboard released.
- **Hyprland:** a confirmed release may mean only that the guardian's input record
  was drained and local resources closed, without compositor acknowledgment. That
  is not compositor or receiving-application proof. Native scoped targets and
  safe same-process dialogs need fresh observations; XWayland and ambiguous
  surfaces are not made safe by a recovery action.
- **Unknown release:** a release-all request, later success, switching backends or
  restarting the app cannot erase uncertainty. Exact-resource cleanup may require
  a qualified operator's external verification and explicit reconciliation. Any
  release-only recovery does not resume input. Never automatically replay an action.

Status and recovery do not authorize terminals, credential/security prompts or
Odin's own controls.

## Compatibility and rollback

Follow [Updates](updates.md#compatibility-and-failed-migrations) before changing
versions. Startup checks can refuse incompatible state before opening it for
writes. An arbitrary older executable is not a recovery tool.

A backup does not justify discarding later unknown effects. Do not overwrite the
profile, erase fences or weaken checks to force a downgrade. If a compatible
recovery path cannot be established, preserve state and ask for help.

## What to include in a support request

Include app version, package format, desktop/session, timestamp and time zone,
exact error, original request identity, receipt state and recovery reason.
Separate observations from assumptions. Copy only necessary sanitized output.

The app has no general full-profile recovery-export wizard. Result copies and
file saves are not backups of the keyring, checkpoints or quarantine. Tool
evidence can expire while a summary survives; do not rerun a command to recover
expired output.

Review material before sharing. Scrubbing does not remove every private path,
hostname, conversation detail or URL. Never share credentials, raw configuration
or environment, token files, private-history screenshots or whole database/profile
archives. Even private support needs only the minimum relevant evidence.
