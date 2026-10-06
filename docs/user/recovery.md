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

Use [First run](first-run.md#recover-the-keyring) for keyring recovery. An
unavailable Work, Schedules, Skills, MCP or computer panel means the service is
absent, not that there are no records or a clean bill of health.

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

The current default core does not provide usable computer-input management.
Visible controls or enabled fields do not authorize input or establish backend
support. Do not press a release/recovery control simply to hide a warning.

If a resource is quarantined or its input release is unknown, stop. Do not inject
another key press or mouse release to test it; that can interfere with a person's
held input. A disappeared helper or receipt alone is not proof that the receiving
application released input. Preserve the exact session/resource identity and
obtain operator help. Do not restart a desktop session or indiscriminately kill
helpers as a diagnosis step.

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
