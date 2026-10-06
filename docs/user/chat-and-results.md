# Chat and results

## Start a conversation

1. Open Odin and complete [First run](first-run.md).
2. Choose **+ New** in the sidebar. Type in **Message**, then choose **Send** or
   press **Enter**. **Shift+Enter** inserts a newline.
3. Watch the pending message and task state. Sending is not task completion.
   Replies shown as answers are committed replies, not unfinished model drafts.
4. Choose **+ New** for another topic. Each conversation has its own history and
   draft. Several conversations can progress independently; requests within one
   are serialized.

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

**Add to knowledge** passes a request through attachment processing; it is not an
automatic knowledge write. Actual retention depends on content handling and an
available knowledge tool. That tool is not connected to the default request
engine's knowledge store, so do not rely on the checkbox as a working library
import. To retain document text directly, use
[Settings → State → Knowledge](settings.md#state-memory-lists-and-knowledge) and
inspect its result. That separately stored text is not currently available to
the model's knowledge tools either.

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
- Expand tool activity to read its result. **Load more** reads retained evidence,
  not another execution. Binary evidence is a file, not decoded prose.
- **No longer available** means the original bytes cannot be retrieved. Save an
  important available file before expiry; you protect that saved copy yourself.

Tool evidence and file references have separate availability rules. Retained
full tool evidence normally expires after **24 hours**, has storage limits, and
is checked against current access on each read. Its **Kept until** time is the
deadline; reading does not extend it. A summary can survive after full evidence
is unavailable. Report paging is not available in the current real core; do not
assume a report reference is a working download or has the same expiry.

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
