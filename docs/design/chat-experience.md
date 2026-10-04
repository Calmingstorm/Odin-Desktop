# Chat experience

Owner: Claude. Draft 2, 2026-10-04. The "today" columns now follow Odin's source inventory
([`../discussion/02-odin-capabilities.md`](../discussion/02-odin-capabilities.md), file:line evidence there).

## The bar

Aaron's requirement R4: the chat must be "every bit as capable, or more capable than interfacing with Odin via
Discord". Today's WebUI chat "doesnt really meet that bar".

Three tests follow from that:

1. **Parity.** Anything a user can do with Odin through Discord, they can do in Odin Desktop, without a workaround.
2. **Better where a desktop can be better.** Discord limits Odin in ways a local app does not:
   - 2,000-character messages;
   - 25 MB uploads;
   - no live text;
   - tool work hidden behind one summary;
   - controls that live in slash commands.
3. **Nothing worse.** A user should never prefer Discord for a task. The hard cases are anywhere-access (a phone) and
   notifications. See "Gaps a desktop app must answer" below.

## What Discord gives Odin today

This is a summary; Odin's inventory is the authoritative list.

| Area | Discord today |
|---|---|
| Conversations | One session per channel; channels run in parallel; threads inherit context from their parent; DMs. |
| Input | Text, image attachments for vision, text/code/archive attachments inline (bounded), mentions, replies. |
| Output | Final text chunked at 2,000 characters; code blocks; files (`generate_file`, `post_file`); images; video. |
| Controls | `/stop` (safe stop with a truthful receipt), `/steer` (queues into the running turn), `/status`, `/usage`, `/reload`; reaction paging on scheduled reports. |
| Visibility | A typing indicator while working. Tool activity is mostly invisible; the reply summarizes it. |
| Background | Schedules post to channels; agent results arrive later; loops. |
| Reach | Every device you're logged in on, including phones, with push notifications. |
| History | Discord keeps the visible history. Odin keeps its own sessions and searchable archives. |

## What the WebUI chat has today

Source: `ui/js/pages/chat.js` (503 lines), `src/web/chat.py`, `src/web/websocket.py`. Odin's inventory is the
authoritative list.

- **Has:**
  - the same tool loop as Discord, through a fake channel;
  - sanitized GFM Markdown with a copy button on code;
  - image URL thumbnails, plus image and file attachments produced during the turn;
  - an animated wait indicator;
  - tool *names* listed after the turn completes.
- **Lacks:**
  - **Input.** It submits text only, with no picker, paste, drag and drop or image blocks.
  - **Conversations.** There is one identity-backed history; the page's `channel_id` is ignored and the WebSocket API
    has no session selection.
  - **An authoritative transcript.** A reload rebuilds from model-session data and drops tool cards and files.
  - **Controls.** There is no stop, steer or guarded resume.
  - **Background destinations.** Schedules, loops and workflows still resolve a Discord channel, and a closed or
    disconnected client has no replayable inbox.
  - **Visibility.** It shows no request-specific event sequence and no retained-evidence links.

## Discord limits worth knowing

These are Odin's limits today, not Discord's.

- Images are 5 MiB by default.
- PDFs are 25 MiB, as text extraction only.
- Archives are 50 MiB compressed, 500 entries and 200 MiB extracted.
- Host files are 25 MiB.
- Audio and video attachments are saved but not understood.
- Replies over 8,000 characters fall back to `response.md`.
- DMs are not passively archived.
- Agents are silent workers: the main turn presents their results.

## Odin Desktop target

Legend: **v1** is required for the first Linux release (the parity bar). **v1+** comes in early follow-up releases.
**later** is roadmap.

### Conversations

| Feature | Discord | WebUI | Odin Desktop |
|---|---|---|---|
| Many named conversations, running in parallel (Odin's channel model) | yes (channels) | no | **v1** |
| Threads and branches that inherit context from the parent | yes (threads) | no | **v1**: "branch from here" creates a child conversation seeded the way threads are today |
| Pin, rename, archive and delete conversations | partly | no | **v1** |
| Per-conversation settings: model, effort, personality, default host, working directory | no | no | **v1+** |
| Full-text search across all conversations, jump to the message | partly (`search_history`) | no | **v1**, using the existing FTS index |
| Export a conversation (Markdown, JSON) | no | no | **v1+** |
| Import sessions from an existing Odin server | n/a | n/a | **later**, a migration helper |

### Composing

| Feature | Discord | WebUI | Odin Desktop |
|---|---|---|---|
| Multi-line composer with history recall and draft persistence | partly | partly | **v1** |
| Attach files and images by drag and drop, paste or picker, with previews, progress, cancel and explicit limits, plus a choice to ingest into knowledge | yes (see limits above) | no | **v1**. The core receives references to owned copies, never raw filesystem handles from the UI. |
| Attach a folder or path reference (Odin reads it locally, nothing is uploaded) | no | no | **v1+** |
| Screenshot capture (region or window) into the composer | no | no | **v1+**, reusing computer-use capture |
| Slash commands with a command palette (`/stop`, `/steer`, `/status`, `/usage`, `/model`, `/effort`, `/new`, `/search`) | yes, a fixed set | no | **v1** |
| `@` pickers for hosts, skills, MCP servers, files and conversations | no | no | **later** |
| Voice input | no | no | **later**; see the Odin voice lane |

### While Odin works

| Feature | Discord | WebUI | Odin Desktop |
|---|---|---|---|
| Live reply text as the model streams | no | no | **Open question, round 2.** Showing unguarded draft text may weaken the response guards in practice. See [round 2](../discussion/03-claude-round2.md). |
| Live tool timeline per turn: name, host, arguments, status, duration | no | names only | **v1** |
| Expand a tool call: full arguments, output with head/tail, retained output by cursor, exit codes | no | no | **v1** |
| Live tail of `manage_process` output | no | no | **v1+** |
| `apply_patch` shown as a rendered diff | no | no | **v1** |
| Computer-use and browser screenshots inline | partly (files) | partly | **v1** |
| Agent tree: spawned agents, live progress telemetry, open an agent's transcript | no (results only) | separate Agents page | **v1**; telemetry already exists |
| Stop, with the same truthful requested/confirmed receipt as `/stop` | `/stop` | no | **v1**, as a button plus Esc, bound to the exact request |
| Steer: type while a turn runs and it queues into that turn | `/steer` | no | **v1**. The composer becomes a steer box while a turn runs, with a receipt (queued, consumed, closed). |
| Queue a follow-up for after the current turn | partly | no | **v1** |
| Guarded resume of preserved work after an interruption (today: a bare `resume`/`continue` on Discord) | yes | no | **v1**, as an explicit control; unknown effects are never replayed blindly |
| Context budget meter, model and account in use, quota | `/status`, `/usage` | separate pages | **v1**, in the header |

### Reading results

| Feature | Discord | WebUI | Odin Desktop |
|---|---|---|---|
| Rich Markdown: GFM tables, task lists, syntax highlighting | partial | yes (basic) | **v1** |
| No 2,000-character chunking; long replies render as one message with collapsible sections | no | yes | **v1** |
| Diagrams (Mermaid) and math | no | no | **later** |
| Inline image, video and audio players; file cards with Open, Save as and Reveal in folder | partly | partly | **v1** |
| Copy as Markdown or plain text; copy code blocks | partly | partly | **v1** |
| Retry or regenerate a turn; edit a past message and resend as a branch | no | no | **v1+** |

### Background work and notifications

| Feature | Discord | WebUI | Odin Desktop |
|---|---|---|---|
| Scheduled tasks post into a chosen conversation | yes (channels) | n/a | **v1**, with the delivery destination owned by the core and not dependent on a window being open |
| Structured scheduled reports with page controls (today: embeds plus reaction paging; a refresh never reruns the check) | yes | no | **v1** |
| Desktop notification when a long turn, agent or schedule finishes, or needs attention | phone/desktop push | no | **v1** |
| Unread badges per conversation and on the tray icon | yes | no | **v1** |
| Work continues while the window is closed; results wait for you | yes | n/a | **v1**: the core keeps running when the window closes (see the architecture options) |
| Quick prompt from a global hotkey (a small floating window) | no | no | **v1+** |

### Management surfaces outside the chat

The WebUI management pages carry over as app screens where they apply. Odin's reuse map decides the exact list.
Examples: settings and models, tools, skills, MCP servers, schedules, memory, knowledge, processes, agents, audit,
usage, hosts.

Multi-user pages do not carry over: host access, API tokens, permissions, Discord config.

## Gaps a desktop app must answer

These are design questions, answered in the architecture docs or put to Aaron.

1. **Anywhere access.** Discord reaches Aaron's phone; a desktop app does not. Options:
   - accept the loss;
   - have the core serve an optional remote client over the tailnet;
   - keep Discord as an optional surface of Odin Desktop.
2. **Notifications away from the desk.** This follows from 1.
3. **Shared conversations.** Discord channels can include other people. Odin Desktop is single-user by design (R7), so
   shared rooms are out of scope unless Aaron says otherwise.

## Principles

- **Guards stay authoritative.** Live text, tool cards and previews are views of work in progress. The committed reply
  is the guarded one, the same as on Discord. Nothing shown live is ever presented as a final claim.
- **Truthful controls.** Every control reports what actually happened (requested or confirmed, queued or consumed), the
  same contracts `/stop` and `/steer` have today.
- **Keyboard first, mouse friendly.** Every action has a shortcut. The palette reaches everything.
- **No hidden work.** If Odin is doing something, the UI can show it.
- **The visible record is durable.** The transcript, artifacts and events the user sees are stored separately from
  Odin's compacted model context and survive restarts. Compaction never shortens what the user can scroll back through.
- **Retries never repeat effects.** Every submission carries a client ID, and the event stream has cursors, so a
  reconnect or a re-sent message cannot execute twice.
