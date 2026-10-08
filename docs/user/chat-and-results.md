# Chat and results

## Start a conversation

1. Open Odin and complete [First run](first-run.md).
2. Choose the plus button, **New conversation**, beside **Chats** in the sidebar.
   Type in **Message**, then choose **Send** or press **Enter**. **Shift+Enter**
   inserts a newline.
3. Watch the pending message and task state. Sending is not task completion.
   Replies shown as answers are committed replies, not unfinished model drafts.
4. Choose **New conversation** for another topic. Each conversation has its own
   history and draft. Several conversations can progress independently; requests
   within one are serialized.

**Message** starts at one line and grows with wrapping and inserted newlines up
to eight visible lines, then scrolls internally. At high zoom or in a short window,
the visible height can be capped sooner to leave room for other controls. The
short hint reads **Enter to send · Shift+Enter for a new line · / for commands**.
Resizing changes the draft's layout, not its text or the selected conversation.

The chat header shows the current core's reported model/effort and available usage
facts. It omits context percentage when context measurement is unknown; missing
status is not filled with guesses. Model and usage controls open their full reports.
The bottom **Odin status** bar keeps connection state, **Status/Usage** report
buttons and actionable warnings, including awaiting receipts, unknown effects and
cleanup attention. A connected core is not proof a request or external effect succeeded.

The conversation **Actions** menu offers rename, archive, reset context, delete
and notification mute. **Show archived** reveals archived rows; archiving is not
deletion. Read the confirmation before resetting context or deleting history.
**Thread from here** starts a child conversation with context through that point,
not a continuously updated copy of its parent.

## Attach a file or request knowledge retention

1. Choose **Attach files**, drop a file into the composer, or paste an image.
2. Wait for upload progress to finish. Check the filename and any failure notice.
   Remove a failed or unwanted attachment with its named Remove control.
3. Leave **Add to knowledge** unchecked for ordinary request input. Check it if
   you want that attachment considered for knowledge retention.
4. Send. While another request runs, use **Queue** for attachments, not **Steer**.

**Add to knowledge** selects knowledge-ingestion intent for that attachment during
processing. It is not an automatic knowledge write: the model still needs to use
an available ingestion tool successfully. Inspect the ingestion result and the
source list before relying on retention. To retain document text directly, use
[Settings → Data and privacy → Memory and knowledge → Knowledge](settings.md#state-memory-lists-and-knowledge) and
inspect its result. Settings and the model's knowledge tools share the profile
store; a retained document is not proof every later chat searched it.

The normal upload service allows **10 attachments per turn**, **50 MiB per
attachment**, with prepared upload bytes expiring after **24 hours**. The app
uses the connected core's advertised limits. Upload success does not guarantee
that every MIME type, archive or document can be understood. PDF handling may
need its [first-use download](install.md#choose-a-format).

Deleting a staged attachment or conversation, or resetting model context, does
not delete a retained knowledge source. Use Knowledge controls for that. Providers
and remote tools may receive file content; attachments are not a local-only promise.

## Steer, queue, stop and resume

While a conversation runs:

- **Steer the current task** sends text guidance to its next safe boundary.
- **Queue a follow-up** submits a later request without rewriting the current one.
- **Stop**, or **Ctrl+.** in Message, asks the current request to stop. Completed
  effects remain completed; stopping does not undo a file write or remote action.

| Receipt or state | What it means |
|---|---|
| **Sending / sent** | Dispatched, or waiting for a receipt. Not proof of admission or completion. |
| **Accepted / confirmed** | The core acknowledged the named operation. Read which operation; this is not a final answer or receiver proof. |
| **Queued** | Accepted for later processing. Steering may not yet have been read; a follow-up may not have started. |
| **Consumed** | The task read steering at its control boundary. Not proof the requested change succeeded. |
| **Unknown / waiting for confirmation** | The outcome is unresolved. It may already have happened; this is not permission to repeat it. |

Controls apply to the request they name, not whichever task starts next. After a
reconnect, let the app reconcile its original receipt. Do not repeat an uncertain
action because no reply arrived. See [Recovery](recovery.md).

An interrupted request may offer **Resume** using preserved input, checkpoints
and remaining budgets. Unknown effects, missing input or incompatible/expired
state can block it. A disabled Resume is not permission to start a fresh copy.

## Read, copy and save results

- **Copy** on a message offers Markdown or plain text. Code blocks have their own
  copy control. Copying does not rerun the request.
- File cards offer **Open**, **Save as…** and **Show in folder**. Open uses the
  default local application; take care with untrusted files. Save as creates an
  independent copy at the destination you choose.
- Expand tool activity to read its result. Completed replies show activity beneath
  the reply; receipts remain inspectable even when a stopped/failed request has
  no answer. **Load more** reads retained evidence, not another execution. Binary
  evidence is a file, not decoded prose.
- **No longer available** means the original bytes cannot be retrieved. Save an
  important available file before expiry; you protect that saved copy yourself.

Tool evidence and file references have separate availability rules. Retained
full tool evidence normally expires after **24 hours**, has storage limits, and
is checked against current access on each read. Its **Kept until** time is the
deadline; reading does not extend it. A summary can survive after full evidence
is unavailable.

### Stored reports

A report card is a stored result from its original run. **Previous**, **Next**
and **Retry** read its stored pages; they do not rerun the producing check.
**Copy page** copies only the displayed page. Report cards do not offer the file
card's Save as operation. A rendering or access failure is not permission to
repeat its producer.

Report snapshots do not use tool evidence's 24-hour expiry. They are bounded,
access-checked records removed with their conversation; invalidation or changed
access can also make a reference unavailable. There is no promise of permanent
retention or universal 30-day report lifetime. Preserve an important available
page yourself and protect that private copy. A surviving summary is not proof
the underlying report or full evidence is still available.

## Find earlier messages

Choose **Search** or press **Ctrl+Shift+F**. Open a hit to view its surrounding
history. **Back to latest** returns to current messages. Loading history and
reading retained output are read operations, not a rerun.

Model context can be compacted or reset without deleting the visible transcript.
History retention and evidence availability are separate.

Type `/` for command suggestions. `/status` and `/usage` show reports; `/reload`
reloads context; `/new` and `/search` navigate; `/model` and `/effort` change their
settings; `/stop` and `/steer` affect the selected conversation. Read the
suggestion's stated effect before sending it.
