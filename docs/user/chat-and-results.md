# Chat and results

**First draft, not release acceptance.** Read the [source and review watermark](../../README.md#documentation-watermark)
before relying on this guide. These instructions describe the current app and real core on `main`, with unmerged
services labeled separately. A development fixture demonstration is not a successful real task.

## Start a conversation

1. Open Odin from your application launcher. Complete [first run](first-run.md), or use Settings while setup is
   incomplete. A ready connection alone does not establish provider access or a working model.
2. Choose **+ New** in the conversation sidebar. Type in **Message** and choose **Send**, or press Enter.
   Shift+Enter inserts a newline. Each conversation has its own draft.
3. Watch the pending message and task status. A submitted message is not a completed request. Odin displays
   committed replies, not an unfinished model draft presented as a final answer.
4. For another topic, choose **+ New** again. Conversations have separate histories; work in one does not become
   another's transcript. Several conversations can progress independently; requests within one are serialized.

The conversation's **Actions** menu offers rename, archive, reset context, delete and notification mute controls.
Archive hides a row until **Show archived** is selected; it is not deletion. Read destructive-action dialogs rather
than treating context reset as history deletion. **Thread from here** on a message starts a child with the context
cutoff labeled in its history. It is a snapshot through that point, not a continuously updated copy of its parent.

## Attach a file, or keep it as knowledge

1. Choose **Attach files**, drop a file into the composer, or paste an image. For keyboard steps see
   [Accessibility](accessibility.md).
2. Wait for the upload progress to finish. Check the filename and any failure notice. A failed attachment must be
   removed before sending. Remove an unwanted attachment using its named Remove control.
3. Leave **Add to knowledge** unchecked for an attachment to this request. Check it only if you want extracted
   material retained for later knowledge searches. Sending a file and successfully ingesting it are different
   outcomes; inspect the resulting message/knowledge state rather than assuming the checkbox guarantees ingestion.
4. Send the message. To attach files while another request runs, choose **Queue**, not **Steer**.

**Current limitation:** `main` exposes the checkbox, but its default engine has no attachment-ingestion handler.
An explicit **Add to knowledge** request therefore fails that processing step; it is not a working import path.
Keep it unchecked for ordinary attachments. To retain document text deliberately, use
**Settings → State → Knowledge** and inspect its result. Do not assume that store is available to the model's
knowledge tools at this watermark. [Settings](settings.md) labels the shared-store wiring **pending: #40**;
that wiring alone is not evidence that the separate attachment-ingestion handler has been implemented.

The current real upload service advertises **10 attachments per turn** and **50 MiB per attachment**. Its upload
receipt/bytes expire after **24 hours**; do not leave a prepared upload indefinitely and assume it is still usable.
The app follows the connected core's advertised limits. Passing upload validation does not prove the processor can
understand every MIME type, archive or document. Unsupported content must report its actual processing outcome.
PDF support may need its separate first-use dependency download; see [Installation](install.md).

Knowledge is stored separately from conversation history. Removing a staged file, deleting a message/conversation,
or clearing model context is not an instruction to delete a knowledge source. Use the Knowledge controls in
[Settings](settings.md) when you intend to remove retained knowledge. Provider processing and remote tools can send
content off this computer; neither an ordinary attachment nor knowledge should be treated as a local-only promise.

## Steer, queue, stop and resume

While the selected conversation is running, the composer offers **Steer the current task** and **Queue a follow-up**.
Steer sends text guidance to that request's next safe boundary. Queue submits another request for that conversation;
it does not rewrite the running request. **Stop** or Ctrl+. asks the current request to stop. Effects already completed
remain completed. A process being stopped does not undo an email, file write or remote action.

| Receipt or state | What it establishes | What it does not establish |
|---|---|---|
| Sending / sent | The app dispatched a submission or control, or is waiting for its receipt. | Admission, consumption, task completion or an external effect. |
| Accepted / confirmed | The relevant core operation acknowledged admission or the named control outcome. Read which operation was confirmed. | A final answer or proof that every external receiver adopted the effect. |
| Queued | Guidance or a follow-up was accepted for later processing. | That the running task has read it, or that a queued request has started. |
| Consumed | The running request read the queued guidance at its control boundary. | That the requested change succeeded or all effects were reversed. |
| Unknown / waiting for confirmation | A receipt or effect cannot yet be established. The original identity must be reconciled. | Failure, safe cancellation, or permission to repeat under a new identity. |

The control is tied to the request and generation it names, not whichever task happens to start next. If the window
reconnects, let it reconcile. Do not retype an uncertain action merely because no reply arrived. If uncertainty
persists, use [Recovery](recovery.md) and check actual external state before deciding what is safe.

An interrupted request may offer **Resume**. It uses preserved input, checkpoints and remaining budgets; it is not a
fresh copy of the request. Unknown effects, missing input, incompatible state or expired checkpoints can block it.
A missing/disabled Resume is not an invitation to bypass that refusal.

## Read, copy and save results

- Replies render text, tables and code. **Copy** on a message offers Markdown or plain text; code blocks have
  their own copy control. Copying a result does not ask Odin to run it again.
- File cards offer **Open**, **Save as…** and **Show in folder**. Open uses the default local application; saving
  chooses an independent destination through the file dialog. Opening untrusted output still deserves care.
- Tool activity expands to its result and retained output. **Load more** reads retained evidence, not another
  execution. Text and binary evidence have different presentation; a binary result is a file, not decoded prose.
- Unavailable/expired files remain labeled **No longer available**. A transcript reference does not guarantee
  that its bytes are still retained. Save an important available file before expiry. A previously saved copy is
  independent of the app's retained copy, but must be protected by you.

### Stored report pages (pending: #37)

PR #37 supplies the real stored-report service behind the existing report view. On `main`, the renderer's report
controls do not prove `reports.page` is available in the real core. Once a candidate includes that service, use
**Previous**, **Next**, **Copy page** and **Retry** on the named report. These read the stored run, never rerun its
check. **Copy page** copies only the displayed page. There is no report **Save as…** operation to assume from file cards.

The pending report service does **not** publish a universal report-expiry interval. A report can become unavailable
after deletion, explicit invalidation or changed scope; history may still show the reference. Evidence/tool output and
reports are separate stores, so do not apply evidence expiry to every report. For retained tool evidence,
use its displayed **Kept until** time and unavailable response rather than a universal lifetime claim.
See [Background work](background-work.md) for destinations, run histories and schedules.

## Find earlier messages without rerunning them

Choose **Search** or Ctrl+Shift+F. Open a hit to view its surrounding history. Use **Back to latest** to return to
current messages. Loading older history, navigating a hit and reading retained output are read operations, not a
repeat of the original tool or request. Model context may be compacted or reset without deleting the visible
transcript and its file references. History retention and evidence availability remain separate.

Type `/` for the command suggestions. `/status` and `/usage` are reports; `/reload` reloads context;
`/new` and `/search` navigate; `/model` and `/effort` use the existing settings apply paths. `/stop` and `/steer`
affect the selected conversation. Read the suggestion's stated effect before sending it.

## Source and validation boundary

Main sources: [composer](../../app/src/renderer/src/components/Composer.vue),
[conversation/control store](../../app/src/renderer/src/store.ts),
[attachments](../../src/desktop/attachments.py), [results](../../src/desktop/artifacts.py),
[message/file/report views](../../app/src/renderer/src/components/Message.vue),
[controls](../../src/desktop/controls.py) and [command palette](../../app/src/renderer/src/commands.ts).
Pending reports: [PR #37](https://github.com/Calmingstorm/Odin-Desktop/pull/37) at the README watermark.
These steps still require the exact package, provider and native acceptance gates in the
[release checklist](../release/linux-v1-checklist.md); a fixture or source-build pass does not close them.
