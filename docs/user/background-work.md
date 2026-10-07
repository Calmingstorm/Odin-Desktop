# Background work

## Find the original work

Conversation requests have their own state in chat. Select the original
conversation to inspect its current request, replies and tool activity. Use its
**Stop**, **Steer** or **Queue** controls as described in
[Chat and results](chat-and-results.md#steer-queue-stop-and-resume).

In chat, open **Work**, then select **Refresh** to fetch the current list. Raven's
Work column separates **Running now**, **Scheduled** and **Finished**, with the
kind, state, details and offered controls on each row. Empty sections are hidden.
Schedules stay in **Scheduled**, including paused rules; **Finished** is not a
promise that resources were released or external effects were undone. Read the
row's **Settlement**, especially any warning that release is not confirmed.

**Open conversation …** returns to the work's conversation where that link is
available. Closing the Work column does not stop anything. **Settings → Scheduled
and running work** also lists schedules and work grouped by kind. These screens
now use the real core's work and schedule services. If a particular connection
reports unavailable, that is not an empty list or proof nothing is running.

| Kind | Meaning | Limit |
|---|---|---|
| Task or workflow | A finite chain of steps, possibly depending on earlier results. | Cancel does not undo completed steps. |
| Agent | A separate reasoning worker, possibly with child agents. | Steer can be queued before the agent reads it. |
| Loop | Repeated reasoning cycles with a limit or stopping condition. | Stop prevents future cycles, not past effects. |
| Process | A tracked command on its original host. | A Stop request or missing PID alone does not prove all descendants or effects are gone. |
| Schedule | A saved time, recurring-time or event rule for a supported action. | Pause changes future firing, not an already-running action. |

Use only the controls offered for that exact row. Records are bound to the
original owner, conversation, run and generation, not just a reusable name or PID.
There is no universal Pause, Undo or Restart for every kind of work. A stale
control must not be used to target a similarly named successor.

## Read the receipt, not just the button

| Wording | Meaning |
|---|---|
| **Sent**, or waiting for confirmation | Dispatched and awaiting a receipt, not proof of execution or completion. |
| **Queued** | A follow-up waits for its turn, or steering waits to be read. |
| **Consumed**, or Odin has read it | Steering was read at a safe boundary, not proof of success. |
| **Confirmed** | The particular control was acknowledged. For Stop, the target turn settled; external effects are not undone. |
| **Unknown** | The outcome cannot be established and may already have happened. Not a safe-to-retry failure. |

Read which request and operation a receipt names. A host or helper acknowledgment
does not prove the receiving application made the intended change.

Work controls may first say **requested**, then **done** for that particular
operation, or **no longer offered** when the target no longer applies. Read the
later work state and settlement too. Agent **Steer → Send steer** sends guidance
to its inbox once; **queued** is not **consumed**. A queued chat follow-up is a
separate future request, not steering for the current one.

For **waiting for Odin to confirm** or **outcome unknown**, do not create another
task or repeat the action under a new name. The app can settle the original
command's late receipt without dispatching it again. Refresh or reopen the
existing record, then follow [Recovery](recovery.md#when-a-command-or-effect-is-unknown)
if it remains unresolved.

## Manage a schedule

1. Open **Settings → Scheduled and running work → New schedule**. **Ctrl+,** opens
   Settings.
2. Enter a description, select an existing destination under **Reports in**, and
   choose the action and timing. **Once** uses this computer's local clock and
   must be in the future. **On a schedule** uses a cron expression and time zone.
   Resolve warnings about nonexistent or repeated local times before saving.
   **On a webhook trigger** is event-based, not a timer; configure the inbound
   source separately in the ingress section. An outgoing Webhook action is not
   an inbound listener. Do not put credentials in descriptions, commands or URLs.
3. Select **Create**, then read the returned schedule state and **Next** time.
   Creation is not proof the action ran. A cron preview is not a run receipt.
4. On an existing row, **Pause/Resume** changes future timing. **Run now** requests
   a new execution, even if the rule is paused; it is not a history refresh.
   **Runs** reads existing history. **Edit → Save** changes the rule. An inert
   one-time rule needs **Set a new time** where offered before it can run again.
5. **Reset failures** clears failure/retry bookkeeping, not an unknown effect.
   **Delete…** removes the rule, not completed effects or a running action.

The run history distinguishes **Succeeded**, **Failed**, **Not run** and
**Unknown**. Read the error and recovery text, not just the label. In particular,
**Unknown** may mean the action started but its completion was not recorded.

The current deletion dialog says that history goes with the schedule, but the
core retains schedule history after deleting its definition. Do not use deletion
as an erasure procedure. The deleted row's **Runs** control is no longer available.

## Background recovery

Refresh the original Work record or read **Settings → Scheduled and running work
→ Runs** for the original schedule before using another control. Review its
conversation, errors, missed-run observations and settlement. Runs reads history;
Run now executes. Pause does not stop an already-dispatched effect.

Restart and Reset failures do not settle a previously unknown run. Interrupted
run history retains that uncertainty; effectful one-time rules can become inert
and require new timing. Future recurring slots are separate from the old run,
not retries proving it finished. Do not run the action again until its original
effect has been reconciled. An ordinary missed action after sleep is different:
it was not automatically replayed and waits for an explicit run.

Stopping loops, cancelling workflows or terminating processes does not undo
completed steps. Do not delete locks, receipts, journals or cleanup records to
make an error disappear. Follow [Recovery](recovery.md) for unresolved effects.

## Close, sleep and Exit

**Closing the window is not Exit.** It hides the window while the app and owned
core continue running. Reopen with the launcher or tray's **Open Odin**. Without
a tray, the launcher still works.

To stop the app, choose **Odin → Exit Odin**, press **Ctrl+Q**, or use the tray or
launcher Exit action. Wait for the shutdown outcome. The app does not install an
independent scheduling service; start at login launches the app itself.

Orderly system shutdown, reboot and logout also run Odin's bounded Exit first.
This does not make a crash, power loss or unconfirmed cleanup
an orderly stop. Unknown cleanup remains unknown on the next start and is not
labelled undone. **Exit while the core is still starting is pending: #96**; the
current startup case can leave an unknown cleanup outcome.

Do not expect local work to execute while the computer is asleep or the app is
exited. Remote effects already started may continue independently. A later
connection does not prove interrupted work completed or that an uncertain action
is safe to repeat. Use the original conversation and recovery records.

### Missed runs after wake or restart: D12

- Overdue reminders are coalesced into **one catch-up notice** for the rule, not
  a burst of every missed reminder.
- Missed actions, including checks and workflows, wait for an explicit user run.
  There is no automatic catch-up workflow replay. Recurring rules move past the
  missed slots; missed one-time actions do not secretly execute later.
- A forward clock jump can make a slot overdue like sleep. A backward jump can
  change the wait for a future slot. Read the stored history and missed-run text
  before choosing Run now; wall-clock displays are not proof of execution.
- An uncertain run that may already have started is not an ordinary missed slot.
  Resume, a new launch or Reset failures does not resolve its effects.

Ordinary running ticks have a lateness grace. Missed-slot counting is bounded
after long downtime, so a catch-up notice is not an exact lifetime count.

D12 is shipped. Native observations recorded on 2026-10-07 cover Cinnamon/X11,
GNOME/Wayland and KDE/Wayland: catch-up reminders, missed checks not run, and no
execution while exited. Those observations used earlier composed candidates,
not one package built from current integrated main. The remaining
[native lifecycle gate](../work/phase-3-app-v1.md#p33-native-lifecycle-trayno-tray-notifications-and-login-startup)
is **pending: #59**; the final integrated desktop matrix is **pending: #97**.
Those release gates do not turn an observed D12 result into qualification of
every lifecycle path or native input backend.

## Foreground computer use is not background authority

The merged foreground binding ties computer authority to an admitted live chat
request, not an agent, workflow, schedule or Work row. Background work cannot
acquire it. A resumed request has a new input lineage; it cannot reuse old consent
or observations.

This binding is not a user-facing native-input qualification. **Settings →
Records → Computer use** currently reports management readiness separately from
unavailable foreground input. Its status and reconciliation controls are not a
Start or Resume input procedure, and a configured backend does not grant consent.
Native input qualification is **pending: #98**; the final matrix is
**pending: #97**. Follow
[Computer-input safety](recovery.md#computer-input-safety), especially when release
is unknown. Never use background work or another backend to bypass it.

## Stored results and expiry

A conversation summary, report reference and full tool evidence are different
records. Tool output's **Kept until** time is its deadline. Full retained tool
evidence normally has a **24-hour** lifetime, storage limits and access checks
on each read. Reading does not extend retention, and not every result is kept
in full.

Use the offered reading or file-saving controls before expiry if you need a
private copy. A saved copy is your responsibility. A summary or receipt remaining
in history does not prove the original bytes are available.

Stored report paging is available in the real core. On the named report, use
**Previous**, **Next**, **Copy page** and, after a page-loading error, **Retry**.
These read the saved result and never rerun its check. Copy page copies only the
displayed page. There is no report **Save as…** operation to infer from file cards.
A rendering failure is not permission to repeat the producer.

Report snapshots do not use tool evidence's 24-hour lifetime. They are bounded,
checked against current profile-owner authorization and removed with their
conversation. An unavailable or invalid stored report may leave a reference in
history without readable pages. There is no promised universal 30-day period or
permanent retention.

Expiry, quota or access refusal cannot be repaired by repeatedly paging. Running
the producer again is a new action, not recovery of its old output.
