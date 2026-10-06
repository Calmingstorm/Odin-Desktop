# Background work

## Check the work you actually started

Conversation requests have their own state in chat. Select the original
conversation to inspect its current request, replies and tool activity. Use its
**Stop**, **Steer** or **Queue** controls as described in
[Chat and results](chat-and-results.md#steer-queue-stop-and-resume).

The **Work** panel and **Settings → Scheduled and running work** are visible, but
their named real-core work-list and schedule-management services are not yet
available. An unavailable message does not mean nothing is running. Do not rely
on those panels to create a working timer or inspect every background owner.

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

For **waiting for Odin to confirm** or **outcome unknown**, do not create another
task or repeat the action under a new name. The app can settle the original
command's late receipt without dispatching it again. Refresh or reopen the
existing record, then follow [Recovery](recovery.md#when-a-command-or-effect-is-unknown)
if it remains unresolved.

## Close, sleep and Exit

**Closing the window is not Exit.** It hides the window while the app and owned
core continue running. Reopen with the launcher or tray's **Open Odin**. Without
a tray, the launcher still works.

To stop the app, choose **Odin → Exit Odin**, press **Ctrl+Q**, or use the tray or
launcher Exit action. Wait for the shutdown outcome. The app does not install an
independent scheduling service; start at login launches the app itself.

Do not expect local work to execute while the computer is asleep or the app is
exited. Remote effects already started may continue independently. A later
connection does not prove interrupted work completed or that an uncertain action
is safe to repeat. Use the original conversation and recovery records.

## Stored results and expiry

A conversation summary, report reference and full tool evidence are different
records. Tool output's **Kept until** time is its deadline. Full retained tool
evidence normally has a **24-hour** lifetime, storage limits and access checks
on each read. Reading does not extend retention, and not every result is kept
in full.

Use the offered reading or file-saving controls before expiry if you need a
private copy. A saved copy is your responsibility. A summary or receipt remaining
in history does not prove the original bytes are available.

Report paging is not available in the current real core. Do not infer that a
report reference has the same expiry as tool evidence or supports file saving.
A refusal due to expiry, quota or access cannot be repaired by repeatedly paging.
Running the producer again is a new action, not recovery of its old output.
