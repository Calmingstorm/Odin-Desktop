# Chat experience

Owner: Claude. Draft 4, 2026-10-04 (Odin's round-3 precision fixes applied). The "today" columns follow Odin's source inventory
([`../discussion/02-odin-capabilities.md`](../discussion/02-odin-capabilities.md), file:line evidence there). The v1
scope follows Odin's review ([round 2, section E](../discussion/04-odin-round2.md#e-chat-spec-review)) and Aaron's
decisions D2 to D6.

## The bar

Aaron's requirement R4: the chat must be "every bit as capable, or more capable than interfacing with Odin via
Discord". Today's WebUI chat "doesnt really meet that bar". D2 adds that he works exactly the same; only the interface is
new.

What parity means here:

1. **Personal execution and chat parity.** Everything a user does with Odin through Discord in their own conversations
   works in Odin Desktop without a workaround: conversations, attachments, controls, background results and management.
2. **Better where a desktop can be better:**
   - no 2,000-character chunking;
   - limits that are Odin's own rather than Discord's. Inputs and outputs are still bounded: input extraction limits and
     output delivery quotas are separate. The copied `post_file` keeps its 25 MiB cap until an approved change replaces
     it with new quotas, tests and descriptions;
   - visible tool activity instead of one summary;
   - first-class controls;
   - a durable, searchable record.
3. **Honest limits.** Two things are deliberately left out:
   - **Social and guild features:** polls, reactions, roles and moderation. Odin Desktop is single-user.
   - **Phone and remote access** is not in the first versions (D6). A local-only v1 does not claim reach parity with
     Discord, and the plan says so plainly.

## What Discord gives Odin today

This is a summary; Odin's inventory is the authoritative list.

| Area | Discord today |
|---|---|
| Conversations | One session per channel; channels run in parallel; a new thread is seeded once from its parent (summary plus six recent messages); DMs. |
| Input | Text, images (vision), text, code, PDF and archive attachments (bounded), mentions, replies. |
| Output | Final text chunked at 2,000 characters (over 8,000 falls back to `response.md`); code blocks; files; images; video. |
| Controls | `/stop`, `/steer`, `/status`, `/usage`, `/reload` (context and caches, not a restart); a bare `resume`/`continue`; reaction paging on stored reports. |
| Visibility | A typing indicator. Tool work is mostly invisible; the reply summarizes it. |
| Background | Schedules, workflows, loops and permitted skills post to channels. Agents are silent workers: the main turn presents their results. |
| Reach | Phones and other devices, with push notifications. |

**Odin's own input limits today:**
- images 5 MiB by default;
- PDFs 25 MiB, as text extraction only;
- archives 50 MiB compressed, 500 entries and 200 MiB extracted;
- host files 25 MiB;
- audio and video are saved but not understood.

## What the WebUI chat has today

- **Has:**
  - the same tool loop, through a fake channel;
  - sanitized Markdown and code copy;
  - image thumbnails and files produced during the turn;
  - tool *names* after the turn ends.
- **Lacks:**
  - attachments as input;
  - more than one conversation;
  - an authoritative transcript: a reload drops tool cards and files;
  - stop, steer and resume;
  - a background destination: results still go to Discord channels;
  - any request-specific activity.

## Odin Desktop target

Legend: **v1** is the first Linux release (the R4 parity bar). **v1+** comes in early follow-ups. **later** is
roadmap.

### Conversations

| Feature | Odin Desktop |
|---|---|
| Named conversations running in parallel. Same-conversation turns serialize, as on Discord today. | **v1** |
| A child conversation seeded from the current context, the equivalent of a Discord thread, labeled as inherited | **v1** |
| Rename, archive, safe delete, reset context. Deletion, context reset and artifact expiry are distinct operations. | **v1** |
| Search across the visible transcript and artifacts, jump to a message. The existing FTS engine is reused, but the new transcript records need their own deletion-aware indexing. | **v1** |
| Pin conversations | v1+ |
| Branch from any past message, edit-and-resend, regenerate. These need new cutoff, provenance and no-replay rules. | v1+ |
| Per-conversation model, effort, personality and default host. Global defaults stay in v1 settings. | v1+ |
| Export a conversation | v1+ |

### Composing

| Feature | Odin Desktop |
|---|---|
| Multi-line composer with persisted drafts | **v1** |
| Attach files and images by drag and drop, paste or picker. Includes previews, progress, cancel, per-file and per-turn limits, and honest messages for unsupported types. The core receives owned copies, never raw filesystem handles from the UI. | **v1** |
| An explicit choice to ingest an attachment into knowledge. Never automatic. | **v1** |
| Command palette:<ul><li>`/stop`, `/steer`, `/status`, `/usage` and `/reload` (Discord equivalents);</li><li>`/new` and `/search`;</li><li>model and effort shortcuts, which are new management aliases.</li></ul>Each shows what it affects. | **v1** |
| Attach a folder or path reference; screenshot capture into the composer, which needs native consent | v1+ |
| `@` pickers for hosts, skills, MCP servers and files | later |
| Voice input (the separate voice lane) | later |

### While Odin works

| Feature | Odin Desktop |
|---|---|
| **No reply text until it is committed.** Reply text appears only after the existing guard and classifier path accepts it, as on Discord. Provider deltas and discarded drafts are never shown. (Recommended by Claude and Odin: showing unguarded drafts weakens the guards in practice.) | **v1** |
| Activity per tool call: name, target host, scrubbed input summary, lifecycle and outcome (success, failure or unknown), duration, and a link to evidence and result | **v1** |
| Expand a call: scrubbed arguments; the output previews the source API actually supplies, labeled as previews; retained output fetched by cursor without re-running anything, with expiry shown. Raw file ranges, retained evidence pages and process cursors keep their exact contracts. The UI never stitches them into a fake contiguous read. | **v1** |
| Inline computer-use and browser screenshots; generated files | **v1** |
| Agents, tasks, loops and processes: identity, state, corrections, controls and results | **v1** |
| Stop: a button plus a dedicated shortcut, bound to the exact request and generation, with a requested or confirmed receipt. Never Esc on its own, which also closes dialogs. Stop is not rollback, and the UI lists anything that keeps running. | **v1** |
| Steer and Queue follow-up, as two explicit modes with a visible target and receipts (queued, consumed or closed). A draft is never reinterpreted because another window started a turn. Rejected text is kept. | **v1** |
| Guarded resume of preserved work. It binds the exact preserved request, and unknown effects block it. | **v1** |
| Status: target endpoint and host, model, core and provider health. Usage, quota and context are shown as measured, estimated or unknown, never invented. | **v1** |
| Rendered diff view for `apply_patch` | v1+ |
| A rich per-agent activity timeline, with no model drafts or reasoning | v1+ |
| Live process output tail | v1+ |

### Reading results

| Feature | Odin Desktop |
|---|---|
| Committed Markdown with tables and syntax highlighting; code copy; full-length replies with no chunking, virtualized for very long content | **v1** |
| Media and file cards with Open, Save as and Reveal through core-issued references. No active previews (no HTML or SVG execution). Playback is not comprehension. If a codec fails, the file itself is still offered. | **v1** |
| Stored report viewer with page controls. Paging never re-runs the check; re-running is a separate, explicit action. | **v1** |
| Copy as Markdown or plain text | **v1** |
| Diagrams and math rendering | later |

### Background work and notifications (D3)

| Feature | Odin Desktop |
|---|---|
| Closing the window keeps Odin working. Results from turns, schedules, workflows, loops and skills land in the conversation inbox. | **v1** |
| Unread state per conversation; desktop notifications with privacy controls (minimal previews by default, quiet hours). A notification the OS accepted is not proof that the user saw it. | **v1** |
| Tray icon with a right-click menu: Open, status, Exit. Exit stops Odin (D3). On desktops without a tray, reopening goes through the launcher, and Exit is also in the window's menu and the launcher's actions. | **v1** |
| Start at login (opt-in), minimized | **v1** |
| Quick prompt from a global hotkey | v1+ |

### Management screens

These carry over as app screens: the workflows Odin's reuse map keeps, not the old pages unchanged.

- **Configuration:** settings, providers and models, personality.
- **Tools and integrations:** tools, skills, MCP servers, hosts and trust.
- **Scheduled and running work:** schedules, workflows, loops, processes, agents.
- **State:** memory, named lists, knowledge, context reload.
- **Records:** audit, usage, health, logs, turn state, computer use.

Multi-user pages do not carry over: host access, API tokens, permissions, Discord config.

## Principles

- **Committed text only.** The user only ever reads reply text that passed the guards.
- **Truthful controls and results.** Each receipt says what actually happened: requested or confirmed, queued or
  consumed. Invocation completed, exit code zero, validation passed and task done are different facts, and the UI never
  merges them.
- **No hidden work.** Effects and state are visible. Model internals (reasoning, prompts, drafts) are not part of that.
- **A durable visible record.** The transcript, artifacts and events are stored separately from Odin's compacted model
  context and survive restarts. Compaction never shortens what the user can scroll back through.
- **Safe retries, named precisely.**
  - A lost receipt is resolved by re-sending, or looking up, the **same submission ID**. That reconciles admission and
    reruns nothing.
  - A deliberate new request gets a new ID and can cause new effects. The UI says so.
  - Reconnecting catches up from a cursor and never invents a new submission ID.
  - Odin never replays effects whose outcome is unknown.
- **Honest outcomes.** Passing the guards is not proof that a task succeeded. Code-owned outcomes are shown as they
  are: unknown, incomplete, storage unavailable, and accepted-but-incomplete provider results. Agents stay silent
  workers: their results are collected and presented by the main turn, not posted into the chat on their own.
- **Keyboard and screen-reader first.** Focus, structure and announcements are qualified on Linux. Activity must not
  flood screen-reader announcements.
