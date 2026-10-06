# Background work

First draft at the [README review watermark](../../README.md), based on
`main@0b7d596f7e870d06699722f151c4d9837c5433f1` and the pinned review branches cited
below. **pending: #N** describes unmerged implementation, not a shipped feature or
a completed release gate. A fixture demonstration does not prove real execution.

## Where to look

In chat, select **Work → Refresh**. The panel groups work by kind and offers only
the controls supplied for that item. **Open conversation …** returns to its
conversation. Closing this panel does not stop work.

For schedules, open **Settings** or `Ctrl+,`, then **Scheduled and running work**.
The renderer has schedule and running-work sections. At this main watermark the
real-core work-list and schedule routes are not wired to those screens: an
unavailable message is the honest result, not an empty list or proof nothing is
running. Main already supports real conversation requests and their Stop/Steer
controls; those are separate from the pending background owners.

Sources: [Work panel](../../app/src/renderer/src/components/WorkPanel.vue),
[Work list](../../app/src/renderer/src/components/WorkList.vue),
[schedule screen](../../app/src/renderer/src/views/settings/Work.vue), and
[main routing](../../src/desktop/core.py).

## The different kinds of work (pending: #37)

| Kind | Meaning | Limit |
|---|---|---|
| Task or workflow | A finite chain of steps, possibly depending on earlier results. | Cancelling does not undo completed steps. |
| Agent | A separate reasoning worker with its own context and possibly child agents. | A correction sent to it is not necessarily read yet. |
| Loop | Repeated reasoning cycles toward a goal, with a limit or stopping condition. | Stopping future cycles does not undo past cycles. |
| Process | A tracked command under its original host/process ownership. | A kill request or missing PID alone does not prove all descendants or external effects are gone. |
| Schedule | A saved time, recurring-time or event rule that starts a supported action. | Pausing the rule does not cancel an already-running action. |

The branch binds records to their original owner, conversation, run and generation.
Controls must not affect a successor with a similar name. Use only the actions
offered for that record: there is no universal Pause, Undo or Restart for all work.

Source: [PR #37 work service, pinned](https://github.com/Calmingstorm/Odin-Desktop/blob/4ede9e75fb079a0a305c7b24f89700d7fb7c4416/src/desktop/work.py).

## Read the receipt, not just the button

| Wording | Meaning |
|---|---|
| **Sent**, or “sent, waiting for confirmation” | The app dispatched the command and awaits a receipt. This does not establish admission, execution or completion. |
| **Queued** | A follow-up was accepted to wait, or steering guidance entered a mailbox. Steering has not yet been read. A queued follow-up is a separate future request, not guidance to the current one. |
| **Consumed**, or “Odin has read it” | The task read the steering message at a safe boundary. This does not promise the requested outcome. |
| **Confirmed** | The relevant owner confirmed the particular control. For conversation Stop, the target turn settled. It is not an undo or a guarantee that every external effect stopped. |
| **Unknown** | The command or effect's outcome cannot be established. It may already have happened. It is not a safe-to-retry failure. |

Some controls report **requested** before settling, **done** for their particular
operation, or **not available** when the target/action no longer applies. An agent
correction can be queued without consumed; Run now has its own run history. Read
the later work state as well as the initial receipt. Background-specific settlement
is **pending: #37**; conversation receipt handling is present on main.

A host/helper acknowledgment proves something about that layer only. It is not
proof that the receiving application saw a keystroke, released a button, or made
the intended change. See [native recovery limits](recovery.md#native-input-limits-and-quarantine-pending-28-pending-37).

If a change says “waiting for Odin to confirm” or “outcome unknown,” do not click
again, create a replacement task, or request the same action under a new name.
The app retains the original command identity and can settle a late receipt without
dispatching another action. Refresh/read the existing record instead. See
[unknown outcomes](recovery.md#when-a-command-or-effect-is-unknown).

Sources: [conversation controls](../../src/desktop/controls.py),
[receipt wording](../../app/src/renderer/src/components/MessageList.vue),
[work-control locking](../../app/src/renderer/src/stores/work.ts), and the pinned
PR #37 work service above.

## Manage a schedule (pending: #37)

These screen routes exist, with their real execution owner still pending:

1. Open **Settings → Scheduled and running work → New schedule**.
2. Choose a description, destination conversation, action and timing. One-time
   dates must be in the future; recurring timing has a time-zone choice. Resolve
   local-time ambiguity warnings before saving. Do not put credentials in
   descriptions, commands or URLs.
3. Save, then read the returned state and next-run time. Saving is not a run receipt.
4. On an existing row, **Pause/Resume** changes future timing. **Run now** is an
   explicit execution request, not a history refresh. **Runs** reads stored history.
   **Edit** changes the rule; **Set a new time** handles an inert one-time rule
   where offered.
5. **Reset failures** resets bookkeeping, not an unknown-effect fence. **Delete…**
   removes the schedule, not already-completed real-world effects.

The renderer labels run rows “Succeeded” or “Failed”; those broad labels alone do
not distinguish known failure from uncertain effect. Read the error and recovery
record before any retry. The deletion dialog currently says its history goes with
it, but the pinned #37 engine retains schedule history after deletion. Do not
promise erasure based on that dialog.

Sources: [schedule screen](../../app/src/renderer/src/views/settings/Work.vue),
[PR #37 schedule service, pinned](https://github.com/Calmingstorm/Odin-Desktop/blob/4ede9e75fb079a0a305c7b24f89700d7fb7c4416/src/desktop/schedules.py),
and [PR #37 recovery tests, pinned](https://github.com/Calmingstorm/Odin-Desktop/blob/4ede9e75fb079a0a305c7b24f89700d7fb7c4416/tests/test_desktop_schedule_recovery.py).

## Close, sleep, clock changes and Exit (pending: #37)

**Window Close is not Exit.** Main hides the window and retains its owned core;
reopening the launcher returns to the app. Background work continuing through
that hidden core is the pending #37 integration, not a separate service. Use tray
**Open/Exit** where present, **Odin → Exit Odin** or **Ctrl+Q**, or the launcher Exit
route. See [first run](first-run.md) for the no-tray case.

The approved **D12** missed-run policy is:

- An exited app runs nothing. There is no independent daemon, root service or
  lingering scheduler after Exit. Login startup launches the app, not a second
  scheduling service.
- Sleep is not execution. After wake/restart, overdue reminders become one bounded
  catch-up notice, not every missed reminder delivered in a burst.
- Missed actions, including checks and workflows, wait for an explicit user run.
  There is no catch-up workflow replay. Recurring rules move past the missed slot;
  missed one-time actions do not secretly execute later.
- The branch checks due times at startup and while running. A forward clock jump
  can make a slot overdue like sleep; a backward jump can change the wait for a
  future slot. Wall-clock displays are not proof of execution. Read saved run
  history before choosing **Run now**.
- An uncertain reserved run is not an ordinary missed run. Restart, Resume or
  Reset failures must not replay it. Resolve uncertainty first.

Ordinary ticks have a lateness grace; missed-slot counting is bounded and can be
truncated after long downtime. A catch-up notice is not an exact count of all
missed events. Native sleep/wake and packaged lifecycle qualification remain
release gates, not established by unit tests alone.

Sources: [D12](../design/00-brief.md),
[lifecycle work order](../work/phase-3-app-v1.md#p33-native-lifecycle-trayno-tray-notifications-and-login-startup),
[PR #37 due-time recovery, pinned](https://github.com/Calmingstorm/Odin-Desktop/blob/4ede9e75fb079a0a305c7b24f89700d7fb7c4416/src/desktop/schedule_recovery.py),
and [PR #37 scheduler, pinned](https://github.com/Calmingstorm/Odin-Desktop/blob/4ede9e75fb079a0a305c7b24f89700d7fb7c4416/src/scheduler/scheduler.py).

## Stored results and expiry

A conversation summary, saved report and full tool evidence are different records.
The **Kept until** time on tool output is its evidence deadline. Retained tool
evidence has a fixed 24-hour lifetime, per-result/global storage limits, and current
owner/tool/host authorization on each read. Reading does not extend its deadline.
Not every result is retained in full. A surviving summary or receipt does not prove
the original full evidence remains available.

Use offered output-reading/file-save controls before expiry if you need a private
copy. A quota refusal, expiry or scope refusal cannot be repaired by paging harder.
Repeating an effectful command is a new action, not retrieval of old evidence.

**Report paging (pending: #37):** **Previous**, **Next** and **Retry** read stored
pages and never execute the check again. **Copy page** copies only the displayed
page. Report snapshots do not share evidence's 24-hour TTL, but are bounded,
authorization-checked and removed with their conversation. Deletion, invalidation
or scope refusal can make a report unavailable. There is no universal 30-day report
period or promise of permanent retention. A rendering failure does not authorize
repeating its producer. Main has report storage support, but its real
`reports.page` route is not wired at this watermark.

Sources: [tool-output UI](../../app/src/renderer/src/components/ToolActivity.vue),
[evidence storage](../../src/tools/output_retention.py),
[artifact scope/deletion](../../src/desktop/artifacts.py),
[report viewer](../../app/src/renderer/src/components/ReportViewer.vue), and
[PR #37 reports, pinned](https://github.com/Calmingstorm/Odin-Desktop/blob/4ede9e75fb079a0a305c7b24f89700d7fb7c4416/src/desktop/reports.py).

## Incoming integrations (pending: #42; pending: #37)

An incoming webhook delivers an event to an explicitly configured listener and
matching schedule. It is not a phone/server client, remote-management API, import
of another Odin install, or permission for an external sender to operate Desktop.
Managed SSH tools are a separate supported host feature.

The pending listener accepts eligible enabled trigger schedules with required
source authentication. Disabled, unconfigured, unbound and accepting are different
states. Bind failure does not choose a fallback address. Exit closes the listener;
unknown handoff is retained and that internal receipt is fenced against automatic replay. It does not pause
the valid trigger or future authenticated deliveries. Each new delivery has a new identity; identical bodies
and provider retries can execute again. An HTTP delivery
acknowledgment is not proof of a resulting workflow's success at its receiver.

Payloads and outgoing subscriptions can contain private project, conversation or
result information. Check destinations and event choices before enabling them.
Authentication does not make payload text owner instructions. Use supported secret
fields, not secret-bearing listener/destination URLs. Do not share signed URLs,
raw payloads, headers or config exports. Redaction does not remove all private
content. The reviewed outbound code stores credential-bearing URLs privately in
the keyring and returns a public projection; that is not permission to expose
the original URL. No general-purpose remote access setup is documented here.

Sources: [integration boundary](../work/phase-3-app-v1.md),
[PR #42 ingress, pinned](https://github.com/Calmingstorm/Odin-Desktop/blob/50f90306176dd2abd724a1a2d5b97199d294b9c8/src/desktop/webhooks.py),
and [PR #42 outbound privacy, pinned](https://github.com/Calmingstorm/Odin-Desktop/blob/50f90306176dd2abd724a1a2d5b97199d294b9c8/src/desktop/integrations.py).
