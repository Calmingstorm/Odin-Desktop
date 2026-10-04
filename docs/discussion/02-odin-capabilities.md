# Odin Desktop: capabilities and round-1 position

Round 1, 2026-10-04. Discussion only, not implementation approval.

## Evidence boundary

Inspected baseline: Odin `cd7530906e9cfa10a0fa900247d7ce2a8bb33e25`, v4.13.0. Citations are paths and one-based lines at that commit, not promises about future desktop behavior. This is a static source inventory, not live acceptance testing. No code, prototypes, scripts, installations, endpoint probes, voice joins, configuration changes, Odin repository changes or restarts were performed. The accompanying deliverable is [`../design/reuse-map.md`](../design/reuse-map.md).

**The gap is the conversation product, not merely access to the tool loop.** The WebUI already runs the same loop, but it does not provide Discord's intake, long-lived delivery destination, conversation navigation or interaction controls. Wrapping today's chat page in a desktop window would preserve those gaps.

## 1. Discord capabilities today

### Inputs, admission and conversation structure

| User capability | Observed implementation and limitation | Source evidence |
|---|---|---|
| Send text, multiline text and code blocks | Messages enter a secret-scrubbing, allowlist, enablement, mention and duplicate gate before the conversation pipeline. No legacy prefix command surface: the prefix resolver explicitly disables it. | `src/discord/intake_pipeline.py:162-211,237-282,370-386`; `src/discord/client.py:241-243` |
| Send a message without mentioning Odin, or summon it by mention | Global/guild/channel mention policy applies; DMs bypass the mention requirement. Own messages are ignored. Replies from other bots and permitted webhooks have distinct admission and buffering rules, not human authority. | `src/discord/intake_pipeline.py:170-172,213-270,284-367` |
| DMs | Supported by message intake and slash-command contexts, subject to user admission. DMs are **not** passively archived by the channel logger. A DM is not automatically the same session as a guild channel. | `src/discord/intake_pipeline.py:238-269,465`; `src/discord/slash_commands.py:393-399`; `src/discord/channel_logger.py:51-64` |
| Image attachments | PNG, JPEG/JPG, GIF and WebP are recognized and converted to native image blocks; default image limit is 5 MiB. Image-only turns get a textual placeholder. Actual interpretation depends on provider vision support; format admission does not imply animation understanding. | `src/discord/attachments.py:31-32,164,214-220,252-274`; `src/discord/intake_pipeline.py:376-386` |
| Text/source/config/log/CSV attachments | Extension/MIME recognition, UTF-8 decoding, bounded preview and saved full files for large inputs. Original large text is retained for cursor retrieval. A request to ingest is a hint to use the knowledge tool, **not** automatic permanent ingestion. | `src/discord/attachments.py:34-42,83-96,119-138,319-363`; `src/discord/intake_pipeline.py:145-159` |
| PDF attachments | Text extraction through optional PyMuPDF, default 25 MiB limit, page labels, bounded preview and retained original/extraction when large. This path is text extraction, not a guarantee of understanding scanned/image-only PDF pages. | `src/discord/attachments.py:165,276-317` |
| Archives | ZIP, TAR, TAR.GZ and TGZ dispatch to bounded listing/extraction and small text previews. Defaults: 50 MiB compressed, 500 entries, 200 MiB extracted. Path escape and TAR link checks are present. Do not advertise arbitrary archive-format support. | `src/discord/attachments.py:44,159-163,227-230,365-461,463-499,501-523` |
| Other binary attachments, including audio/video | Saved with path, size and hash. There is no audio transcription or video comprehension in this attachment intake. Being able to upload a clip is not the same as Odin understanding it. | `src/discord/attachments.py:245-246,525-546` |
| Several attachments in one turn | Iterated into text and image collections; bot-message buffering also preserves each original message's attachments. Temporary workspaces are separated by conversation/message identifiers and exclusive filenames. | `src/discord/attachments.py:181-205,210-250`; `src/discord/intake_pipeline.py:294-301,351-363` |
| Channels in parallel | Per-channel locks serialize turns within one channel; different channels can progress independently. Cancellation, active requests, pending files and steering are separately owned. This is conversation concurrency, not unconstrained parallel access to the same target files or GUI. | `src/discord/intake_pipeline.py:465-470`; `src/discord/channel_state.py:82-115,133-170` |
| Threads with inherited context | On the first turn in an empty thread, seed from the parent's summary and last six messages, clipped to 300 characters each and marked inherited. It is a snapshot, not permanent live context synchronization. | `src/discord/intake_pipeline.py:471-508`; `src/discord/tool_loop.py:1149-1168` |
| Persistent conversation context | Sessions store user/assistant messages, summaries, archives and continuity. The working model history is compacted/budgeted; it is not the full Discord-visible transcript. | `src/discord/intake_pipeline.py:529-533`; `src/sessions/manager.py:523-533,1095-1116,1797-1826` |
| Read current channel history | `read_channel` reads up to 100 recent platform messages, including other users/bots, attachment names and embed text. Results are context, not instructions to replay old work. Can select another accessible numeric channel. | `src/discord/native_tools/channel_ops.py:41-115`; `src/tools/defs/channel_process_loops.py:12-32` |
| Search history | Searches sessions, archives and, for logged guild messages, passive channel history, with keyword/semantic/FTS infrastructure. Ranking/whole matches are retained for continuation instead of rerunning the search. Logger skips DMs. | `src/tools/defs/memory_skills.py:12-20`; `src/sessions/manager.py:1509-1525,1628-1655`; `src/discord/native_tools/knowledge.py:32-64`; `src/discord/channel_logger.py:51-64` |
| Resume preserved work | Bare `resume`/`continue` is checked before fresh prompt/history assembly by the Discord pipeline. It is a guarded durable-turn operation, not merely sending the previous prompt again. Unknown effects still require resolution rather than automatic replay. | `src/discord/intake_pipeline.py:619-629`; `src/discord/tool_loop.py:820-846` |

### Outputs and controls

| User capability | Observed implementation and limitation | Source evidence |
|---|---|---|
| Markdown text, replies and long output | Delivery has retries and a fence-aware 2,000-character splitter. Responses over 8,000 characters fall back to `response.md`. Attachment stream identity is preserved for safe fallback when a reply target disappears. Desktop should remove the platform length restriction, not the delivery truthfulness. | `src/discord/delivery.py:28-33,65-110,270-332,381-497` |
| Receive files, images and video | `generate_file`, host-backed `post_file`, browser screenshots and skill file callbacks deliver attachments. Host files have a 25 MiB Discord limit. Video/audio can be delivered as files; native player behavior is Discord's, not a media-understanding feature of Odin. | `src/discord/native_tools/media.py:73-102,104-181`; `src/discord/native_tools/skills_tools.py:205-220` |
| Native tool images enter reasoning | Tool-image envelopes are attributed to the tool invocation, preserving image blocks rather than stuffing bytes into text/audit. MCP/native evidence is distinct from authority. | `src/tools/media_result.py:21-85` |
| Optional output streaming and progress | Tool streaming is opt-in and off by default; delivery can update an existing progress message. Background workflows post/edit progress and final summaries. It is not evidence that every model token streams to chat. | `src/tools/output_streamer.py:1-17,44-63,197-259`; `src/discord/background_task.py:717-802,808-855`; `src/web/chat.py:45-55,299-304` |
| Embeds and reaction pagination | Scheduled structured reports render embeds, persist projections and add paging reactions. Refresh/paging edits the saved projection and **does not rerun the check**. Desktop equivalent is a structured report/table viewer with explicit page controls. | `src/discord/scheduled_report.py:514-588`; `src/discord/cogs/scheduled_report_pagination.py:27-32` |
| Add reactions and create polls | Tools can react to a message or create a native Discord poll, up to ten choices. These are social/platform capabilities, not necessary personal-desktop parity features. | `src/discord/native_tools/channel_ops.py:117-163` |
| Buttons/dropdowns | Confirmation and role-selector classes exist. Static references inspected show class definitions but no active call sites importing them outside those files. Do **not** claim a general active chat approval-button workflow from these leftovers. Desktop does need grounded controls for stop, consent and management operations, designed separately. | `src/discord/views/confirm.py:9-53`; `src/discord/views/role_select.py:13-43`; current `src/` reference search |
| `/status` | Runtime/config/health report, with user admission. Desktop equivalent: runtime status plus command-palette action, not a guild slash registry. | `src/discord/slash_commands.py:401-406` |
| `/reload` | Reloads context files and invalidates/rebuilds prompt/tool caches. It is **not** a service restart or general code/config reload. | `src/discord/slash_commands.py:408-419` |
| `/usage` | Usage range totals and quota report. Uses the rollup store off-thread and private interaction response. | `src/discord/slash_commands.py:421-445` |
| `/steer` | Secret-checked, bounded correction to the active request's FIFO inbox. Receipt distinguishes queued, consumed and turn-ended-unconsumed. Consumption occurs at safe boundaries, not during an in-flight tool; admission does not change the original execution authority. | `src/discord/slash_commands.py:447-501`; `src/discord/channel_state.py:35-36,50-65,196-218`; `src/discord/tool_loop.py:477-488` |
| `/stop` | Requests cancellation of the request currently owned by that channel. Waits up to ten seconds for a truthful settlement receipt; otherwise reports that in-flight work could not yet be safely interrupted. Not an undo button. | `src/discord/slash_commands.py:503-539`; `src/discord/channel_state.py:133-155` |
| Clear chat/reset session and change permissions | `purge_messages` deletes recent platform messages and resets session; `set_permission` changes tiers only for admins. The latter is removed for standalone desktop; the former becomes explicit local-history/reset operations, with precise deletion semantics. | `src/discord/native_tools/channel_ops.py:29-39,165-177` |
| Typing/presence | Presence/status strings and active-task updates are Discord delivery concerns. Desktop can show request-specific task state rather than one global presence label. | `src/discord/delivery.py:160-225,239-270` |

### Full execution capabilities available through conversation

These are static capabilities, **not** a claim that every feature is configured on every install. The same definitions/handlers are used by a full-authority web turn. Preserve tool-result validation, effect uncertainty, post-action validation and all guard/classifier behavior. Do not turn a settings-page toggle into an alternative execution path that bypasses the core.

| Capability family | Inventory | Source evidence |
|---|---|---|
| Managed systems and files | Commands, multiline scripts, multiple hosts, contiguous/raw file reads and strict transactional patches. Local execution and SSH remote management both remain relevant to a desktop. | `src/tools/defs/system_files.py:12,39,75,101,146`; `src/discord/native_tools/media.py:119-163` |
| Processes | Start/poll/write/kill/list, retained output, bounded waits and truthful lifecycle ownership. | `src/tools/defs/channel_process_loops.py:75-160`; `src/tools/process_manager.py:1676` |
| Browser and web | Screenshot, rendered page/table reads, click, fill, evaluate, web search and static fetch. Existing browser tool calls own fresh browser sessions; do not imply they automate the user's already-open browser with inherited credentials. | `src/tools/defs/browser_web.py:12,39,86,112,150,194,227,248` |
| HTTP and validation | HTTP probing plus validation bundles for deployments/restarts/configuration/network changes. Desktop does not remove infrastructure tools simply because the application is local. | `src/tools/defs/integrations_email.py:12-82,103-213` |
| Media | Image generation when available, image/PDF analysis, attachment generation/delivery. Model/backend availability still gates publication. No built-in Discord voice receive/send in this inspected baseline. | `src/tools/defs/integrations_email.py:84-101`; `src/tools/defs/channel_process_loops.py:213-231`; `src/tools/defs/browser_web.py:290`; `src/discord/tool_catalog.py:160-174`; `src/discord/client.py:64-71` |
| Personal state | Memory CRUD, named lists with done/undone markers and history/audit search. Simplify multi-user scopes deliberately, preserving imported data rather than silently dropping formerly global/shared entries. | `src/tools/defs/memory_skills.py:12-121`; `src/tools/defs/channel_process_loops.py:162-209` |
| Knowledge | Search, ingest, bulk import, list and delete. Attachments remain task context until explicit ingestion; indexed knowledge is not a substitute for visible chat history. | `src/tools/defs/tasks_knowledge.py:96,121,149,187,198`; `src/discord/attachments.py:3-8,329-354` |
| Skills | Create/edit/delete, list/status, enable/disable, install/export/invoke, plus configured custom tools and sanctioned callback services. Skill APIs must retain a desktop delivery destination even when no UI window exists. | `src/tools/defs/memory_skills.py:125,165,183,197,207,221,235,252,266,283`; `src/tools/skill_context.py:205-225,376-434` |
| MCP | Configured external tools enter the merged catalog; tools/media/outcomes must keep attribution and uncertainty. Stdio/HTTP integrations are optional, not implicit desktop dependencies. | `src/discord/tool_catalog.py:64-72,129-135`; `src/tools/mcp/protocol.py:1`; `src/tools/media_result.py:21-85` |
| Email | Send/search/read/recent tools, only when configured. Sending still executes a real external action, not merely previewing a draft. | `src/tools/defs/integrations_email.py:215,252,273,289`; `src/discord/tool_catalog.py:146-148` |
| Supervised computer interaction | Session/observation/action tools when enabled and runtime-available. Desktop transport must renew target consent/binding; local ownership is not a reason to discard input guards or support unqualified platforms. | `src/tools/defs/computer.py:5,31,119,167`; `src/discord/tool_catalog.py:155-159` |
| Retained evidence | `get_tool_output` reads retained text/binary evidence rather than rerunning effect-capable tools. Cursors are scoped, bounded evidence access, not permissions or permanent artifact URLs. | `src/tools/defs/output_delivery.py:1-26`; `src/discord/intake_pipeline.py:145-159` |

### Background behavior and unsolicited delivery

| Capability | Observed implementation and limitation | Source evidence |
|---|---|---|
| Schedules | Recurring cron with timezone, one-time and webhook-triggered tasks; reminder, check, digest and workflow actions; list/update/pause/delete. Originating conversation/requester is stored. | `src/tools/defs/media_scheduling.py:82-227,229-361`; `src/discord/native_tools/scheduling.py:103-169` |
| Schedule delivery | Callback resolves a numeric Discord channel, posts reminders/check results/workflows, validates stored nested payload at fire time and refuses automatic retry of uncertain effect outcomes. Current connection admission is Discord-owned; replace it with core/destination readiness, not UI-window-open state. | `src/discord/scheduled_events.py:490-611`; `src/scheduler/scheduler.py:374-418` |
| Delegated workflows | Sequential tool chain with conditions, variable substitution, failure policy, progress edits, terminal summary and optional conversational follow-up; list/cancel supported. Needs destination ownership independent of the starting foreground turn. | `src/tools/defs/tasks_knowledge.py:12-94`; `src/discord/background_task.py:147-160,410-431,688-706,717-916` |
| Autonomous loops | Periodic full reasoning cycles with notify/act/silent modes, interval, stop condition and iteration cap; stop/list. `asyncio` tasks and channel objects are process-local. Their durable iteration history does not itself make execution automatically restart-resumable. | `src/tools/defs/channel_process_loops.py:233-310`; `src/tools/autonomous_loop.py:125-187`; `src/web/api/agents_loops.py:82-155` |
| Agents | Spawn with model/effort controls, nested agents, bounded lifetime, send instructions, wait/list/kill and retained results. Agents are **silent workers**, not automatic Discord speakers; the main turn explicitly collects and presents results. They retain originating conversation/request authority and native computer vision remains restricted. | `src/tools/defs/agents.py:158-280`; `src/discord/native_tools/agents_tasks.py:1404-1445,1466-1525,1527-1566`; `src/agents/manager.py:444` |
| Proactive posts | Schedules, loops, workflow updates, permitted skill callbacks and configured incoming webhooks can post without a new human text message. This source inventory found no generic always-on ambient companion/chatter capability to promise as parity. | `src/discord/scheduled_events.py:515-522`; `src/tools/autonomous_loop.py:479-481,578-605`; `src/discord/native_tools/skills_tools.py:199-218`; `src/health/server.py:936-939,1368-1389` |

## 2. WebUI, REST and WebSocket inventory

### What is genuinely shared

- `_WebChannel`, `_WebAuthor` and `WebMessage` duck-type enough Discord objects to call the actual tool loop. Prompt construction, task history, tools and result persistence are real, not a second weaker chat engine. However, the adapter still requires the `OdinBot` composition root (`src/web/chat.py:62-169,181-219,253-308`).
- Successful and failed turns are persisted to session history with different error sanitization. Captured in-turn files are returned as base64 objects with MIME/name/size (`src/web/chat.py:81-126,306-342`). Current capture is up to 25 MiB **per file**, not an independently verified aggregate admission budget.
- Backend tool availability filtering exists for email, browser, knowledge, computer, image generation and PDF dependencies. A desktop capability model must apply the carried requirement to every optional feature, not merely display disabled tools (`src/discord/tool_catalog.py:139-180`).

### Per-surface capabilities

| Dimension | WebUI chat | REST API | WebSocket API | Evidence |
|---|---|---|---|---|
| Text input | Textarea, Enter/Shift+Enter, one pending send | `/api/chat`: required text, max 32,000 characters | `type: chat`: same text limit | `ui/js/pages/chat.js:194-224,245,409-431`; `src/web/api/sessions_chat.py:59-72`; `src/web/websocket.py:816-827` |
| Attachments as input | No picker, paste/drop attachment route or structured attachment composer | Inspected chat/execute handlers consume text only | Inspected chat handler consumes text only | `ui/js/pages/chat.js:194-224,393-425`; `src/web/api/sessions_chat.py:59-109,128-179`; `src/web/chat.py:167`; `src/web/websocket.py:816-867` |
| Model tools | Same loop through web adapter, subject to identity/policy | Same loop; caller tool/host scope comes from authenticated identity | Same loop; equivalent identity scope | `src/web/chat.py:212-250,278-295`; `src/web/api/sessions_chat.py:74-108`; `src/web/websocket.py:829-867` |
| Conversation IDs | One identity-backed history; the page sends `channel_id`, which the backend does not use to select arbitrary chats | Optional validated `session_id`, namespaced under identity; overlapping turns serialized by conversation | Always identity-backed channel in the inspected handler; no equivalent `session_id` selection | `ui/js/pages/chat.js:393-398,423,433-440`; `src/web/api/sessions_chat.py:86-114`; `src/web/chat.py:23-26,196-224`; `src/web/websocket.py:829-832` |
| Stateless automation | Not a page feature | `/api/execute` uses UUID ephemeral channel and does not retain chat session continuity | No separate stateless execution message branch | `src/web/api/sessions_chat.py:128-179`; `src/web/websocket.py:753-780` |
| Final output | Sanitized Markdown, code-copy, image URL thumbnails, image attachments and non-image download links | Final response/tools/error/files in JSON | Final `chat_response`/`chat_error`, tools/error/files | `ui/js/pages/chat.js:17-25,119-165,288-329,377-406`; `src/web/api/sessions_chat.py:115-126,182-194`; `src/web/websocket.py:868-890` |
| Progress/streaming | Generic animated wait; cards list tool names **after** completion; subscribes to `chat`, not the tool-stream event feed | Request returns after loop completion | Separate `logs`/`events` subscriptions carry audit and optional tool streams; chat response is still terminal, not a token/durable-message stream | `ui/js/pages/chat.js:119-133,261-270,377-389,481-492`; `src/health/server.py:1023-1040`; `src/web/websocket.py:753-780,868-896` |
| Disconnect behavior | Socket loss is reported; REST fallback is for a send not accepted over WS, not a proven exactly-once replay protocol | Long request bounded by loop/tool/provider guards, not a documented durable client command ID | Chat tasks outlive disconnect; terminal text enters history, but closed socket cannot receive the files/result | `ui/js/pages/chat.js:420-428`; `src/web/websocket.py:183-186,844-850`; `src/web/chat.py:306-332` |
| Reopening history | Loads role/content/timestamps from working sessions; reload constructs `files: []`, `tools_used: []` and maps every non-user role to bot | Session list/get/search/export/delete and trajectory APIs available | No complete transcript catch-up/replay protocol in socket command dispatch | `ui/js/pages/chat.js:433-477`; `src/web/api/sessions_chat.py:205,253,320-400,402,439-484`; `src/web/websocket.py:753-780` |
| Controls | No chat stop/steer/reload/status/usage controls or conversation sidebar | Turn-state endpoints are observational, not stop/steer/resume; management endpoints provide separate feature controls | No stop/steer/resume command branches | `ui/js/pages/chat.js:194-224,495-503`; `src/web/api/turn_state.py:1-5,55-87`; `src/web/websocket.py:753-780` |
| Durable turn checkpoint/resume | Session persistence exists, but full turn checkpoints are not admitted for web source | Same exclusion for API web-message shims | Same exclusion | `src/discord/tool_loop.py:1254-1272`; `src/web/chat.py:156,262-295` |
| Background destinations | A page request's fake channel captures outputs in that turn; it is not a persistent subscription destination | Loop start still resolves a numeric Discord channel; schedule records still name a destination | Events exist, but no desktop-style durable per-conversation background inbox | `src/web/chat.py:69-126`; `src/web/api/agents_loops.py:167-205`; `src/discord/scheduled_events.py:503-509` |
| Channel history operations | No Discord history through fake channel | Fake history returns an empty list and fetch raises; thread inheritance pipeline is not used | Same fake-channel limitation | `src/web/chat.py:128-132,262-295`; `src/discord/intake_pipeline.py:471-508` |
| Supervised computer binding | A separate management surface/binding exists, not automatic authority from text | Managed browser binding is attached for authenticated chat requests | Managed admin session may attach a binding, revoked when socket closes/policy changes | `src/web/api/sessions_chat.py:42-50`; `src/web/websocket.py:861-866` |

### Management is stronger than chat

The existing WebUI/API already offers useful management that Discord conversation exposes only indirectly: session search/export, schedules/history/manual run, agent trees and termination, loop history/restart, process inspection/kill, knowledge versions/diffs/restore, memory/learned entries, provider/configuration/integration controls and execution observability. Preserve those workflows as desktop management surfaces, not as justification for shipping the current chat UX unchanged (`src/web/api/sessions_chat.py:205-550`; `src/web/api/schedules_api.py:39-204`; `src/web/api/agents_loops.py:52-517`; `src/web/api/knowledge_mem.py:95-538`; per-page evidence in the reuse map).

### Exactly where today's WebUI falls short

1. **Input parity is absent.** It submits strings, not attachments or image blocks. URL-based analysis tools are not a substitute for selecting a local image/PDF/archive.
2. **Conversation parity is absent.** There is one chat view, no workspace/thread navigation or explicit branch inheritance. REST has scoped sessions; WS and the page do not exercise the same conversation-selection contract.
3. **The visible transcript is not authoritative.** Reload uses model-session data, losing tool cards and in-turn files. Compaction is a model-budget operation, not permission to erase the user's visible chat history.
4. **In-turn control and recovery parity is absent.** No first-class stop, steering receipts or explicit guarded resume. The shared runner explicitly excludes web/API sources from durable-turn checkpoint admission. Typing a natural-language request into a locked chat is not an equivalent control plane, and session persistence is not checkpoint recovery.
5. **Delivery parity is absent.** In-turn capture is transient. Background workflows still target Discord, while closed/disconnected UI delivery has no replayable inbox.
6. **Rich interaction parity is incomplete.** Images/download links are supported, but no embedded video/audio player, report pagination, persistent attachments or actionable per-turn execution view in the chat page.
7. **Stream truthfulness is not a product contract.** Separate optional event streams are useful infrastructure, but the page shows an animated wait and terminal tool-name cards. It does not expose request-specific event sequencing, retained-evidence links or tool outcome distinctions.

Evidence for these judgments is the corresponding table row above. These are static product gaps, not untested allegations about live endpoint failures.

## 3. What Discord supplies that desktop must replace

The following are platform properties and design obligations, not implementations found inside Odin. The cited code identifies the dependency boundary.

| Platform benefit | Desktop responsibility | Boundary evidence |
|---|---|---|
| Persistent human-visible messages and attachment hosting | Durable transcript separate from model history; stable message/artifact IDs, owned file storage, retention/export/delete behavior and restart-safe delivery | `src/discord/native_tools/media.py:97-100,175-179`; `src/web/chat.py:73-76,111-126`; `ui/js/pages/chat.js:433-461` |
| Channel/thread navigation and independent histories | Conversations/workspaces, optional branches, inherited context snapshot and clear target binding | `src/discord/intake_pipeline.py:465-508` |
| Notifications, unread state and background delivery | OS notifications with privacy/redaction controls, unread inbox, open-specific-conversation actions and quiet hours; persist first, notify second | `src/discord/scheduled_events.py:503-522`; `src/tools/skill_context.py:205-225` |
| Phone/remote access and multiple devices | Local-only loses this convenience. Optional authenticated server-client mode is the sane path; arbitrary LAN exposure or cloud sync is a separate owner decision, not a free property of desktop | `src/web/api/sessions_chat.py:74-108`; `src/web/websocket.py:39-43,245-251` |
| Shared channels and other people speaking | Standalone desktop is one local owner. Do not promise collaborative guild/DM semantics or retain their permission UI. Remote client continues respecting the server's identity and scope | `src/discord/intake_pipeline.py:83-91,213-241`; `src/discord/native_tools/channel_ops.py:165-177` |
| Markdown/media rendering, downloads and report controls | Accessible renderer, safe link handling, constrained media viewer, virtualized long messages and native save/open actions. Never load remote content with core authority or execute a generated file on preview | `src/discord/delivery.py:381-497`; `src/discord/scheduled_report.py:514-588`; `ui/js/pages/chat.js:17-25,145-165` |
| Connectivity/session recovery | Durable event cursor/catch-up and client submission identity, duplicate suppression, explicit delivery receipts and reconnection state. Retrying a UI request must not repeat a real tool effect | `src/discord/intake_pipeline.py:279-282`; `src/web/websocket.py:183-186,844-850`; `src/discord/delivery.py:36-62` |
| Bot online status | Separate window/core/provider/destination/platform capability status. UI closed is not core stopped; core running is not machine awake or tool available | `src/discord/delivery.py:248-270`; `src/scheduler/scheduler.py:386-418`; `src/discord/tool_catalog.py:139-180` |

**Parity is equivalence of relevant capabilities, not a counterfeit Discord.** Polls, reactions, roles and guild administration can go. Reliable history, attachments, independent conversations, stop/steer, asynchronous delivery and remote-access tradeoffs cannot disappear behind that argument.

## 4. My views: process model

### Recommendation: a per-user background core plus an independently restartable UI

One application install, two primary responsibilities:

- **Core process:** owns configuration/secrets, providers, conversations, durable transcript/artifacts, tool executor, scheduler, agent/loop managers, retained evidence, audit and guarded shutdown.
- **UI process:** presents chat and management, connects over private authenticated local IPC, and receives structured events. Renderer failure/closure must not terminate tool execution or erase output. A graphical helper for supervised computer input may have a separate lifetime/consent contract; background core persistence does not authorize input on a locked or absent session.
- **Single core per profile:** an owner-only lock and discovery handshake bind process, profile and protocol generation. A second launch opens/connects the UI rather than starting a second scheduler against the same databases. An unrelated Odin server is not mistaken for this core.

Existing composition is already partly separated, but not truly transport-independent: `build_services` returns `BotServices`; startup/shutdown and late-bound callback wiring still reach the bot (`src/discord/wiring.py:1-17,99-153,156-190,1175-1355`). The web shim proves reuse is possible, not that the bot singleton can be removed by renaming a class.

### Lifecycle behavior that needs explicit design

| Event | Proposed contract |
|---|---|
| Close window | Keep core/background work alive when the user enabled background operation; disclose this once and expose status without relying on a tray existing. Do not silently keep running if the user chose window-lifetime operation. |
| Quit UI | Different from Quit Odin. The UI can reconnect and catch up from durable events. |
| Quit Odin | Stop admission, settle/cancel owned work safely, persist state/results, release supervised input and terminate owned children. Unknown release/effects are reported, not erased by a fresh process. |
| Login/startup | User opt-in, per-user session startup. On Linux a user service is one packaging option, not an API assumption. Boot-before-login service operation is not implied by 'run at startup'. |
| Sleep/offline | No claim of running schedules while asleep or powered off. Define missed-run policy, timezone/DST and reconnect/backoff behavior; show last-run/next-run and failures. |
| Core crash/restart/update | Durable transcript and schedule definitions survive. Active agents/loops/workflows do not magically survive because their history did. Show interrupted/uncertain state and guarded explicit resume where supported; never blindly rerun effects. |
| Update | Independently verify/package UI and core compatibility; drain work and snapshot storage before a controlled update. Rollback must account for storage migrations and owned subprocess/input cleanup. |

**Why not embedded-only?** Simpler packaging and no IPC, but it couples background work to the GUI toolkit/event loop and window lifetime. It is acceptable only as an explicit reduced operating mode, not our primary parity architecture.

**Why not a system/root daemon?** A personal app should not inherit Aaron's root-operated deployment as its default authority. Login-session GUI consent, keychains and notifications are per-user. Optional elevated actions remain exact, separately authorized operations, not a permanently privileged renderer.

**Why not just keep the HTTP server?** A loopback aiohttp transport can be an interim adapter, but serving a privileged API locally still needs authentication, origin/CSRF protection, capability binding and careful port discovery. Owner-only sockets/named pipes may reduce exposure; they do not remove the threat from untrusted renderer content or other local processes. This decision belongs with platform design, not a declaration that 'localhost is trusted'.

## 5. My views: sharing the core

### Compare the three real choices

| Choice | Benefit | Maintenance/risk | Position |
|---|---|---|---|
| Copy-and-strip into this repo | Fastest initial ownership; desktop can release independently and remove irrelevant dependencies | Two tool loops, guard stacks, providers and containment implementations drift. Bug/security fixes must be hand-portable, and provenance/tests must track every copied change | Not the long-term design. If Aaron chooses a temporary fork, specify baseline, upstream diff tracking and exit criteria before implementation |
| Shared versioned core package plus surface packages | One executor/provider/durability/guard implementation with explicit lifecycle and delivery contracts; Discord/server and desktop have separate composition/settings/packaging | Up-front extraction is real work and requires separately authorized Odin changes. Need contract tests and coordinated release/version policy, not a vague 'core' directory | **Recommended destination** |
| Depend on today's entire `odin` package with features off | Lowest immediate duplication; can reuse existing management flows | Discord imports and `OdinBot` construction remain, server routes/config leak into desktop, feature switches are not dependency isolation, and unused capabilities are easier to accidentally publish | Reasonable research/bootstrap reference, not acceptable final stripping boundary |

### Proposed extraction seam

The shared core should accept explicit services, not pretend messages/channels. Names here describe contracts, not code to implement in this round:

1. **Request envelope:** stable local owner, conversation/message/request IDs, text/media references, source/provenance, explicit target/tool scope and parent/branch metadata. Transport IDs never double as authority.
2. **Conversation service:** model-session context plus a distinct durable user-visible transcript. Existing session compaction remains reuse; transcript/artifact/event ownership is new product infrastructure.
3. **Delivery sink:** typed message creation/edit, artifact publication, report projection and notification intent, bound to conversation/request, usable while no UI is attached. No `discord.File`, `channel.send` or base64-in-final-response as the universal domain API.
4. **Control service:** request-owned stop/steer and guarded resume, preserving queued/consumed/closed and confirmed/unknown distinctions. UI buttons/slash commands are adapters.
5. **Runtime service:** startup, readiness, feature availability, config apply, shutdown, updates and durable task ownership. Distinguish core/destination readiness from Discord gateway attachment.
6. **Tool authority/platform service:** execution governor, host registry/trust, result capture/authorization, native supervision and computer consent. Remove user-tier routing but preserve target and effect safety.

Evidence for why these seams matter: `src/web/chat.py:62-169,278-332`; `src/discord/channel_state.py:82-115,133-218`; `src/discord/tool_loop.py:1100-1181`; `src/discord/scheduled_events.py:503-509`; `src/tools/skill_context.py:205-225`; `src/scheduler/scheduler.py:374-418`.

The literal number of Discord-library touchpoints in the loop is a useful lead, not an effort estimate. Channel/guild policy, native handlers, the bot-root shutdown path, output callbacks, scheduler connection epochs and process-global/module caches are equally important coupling. I agree with extracting the loop; I disagree with describing the complete extraction as light.

### Non-negotiable sharing contract

- **Preserve existing personality and system-prompt text byte-for-byte.** Extraction is not permission to rewrite it, append desktop etiquette or inject an always-on UI manual. New tool guidance belongs in tool descriptions. Transport metadata can supply accurate conversation facts without inventing new instructions.
- **There is an owner-level tension to settle, not an excuse to edit the prompt.** Existing preset voice and system templates literally mention Discord (`src/llm/system_prompt.py:16-34,66-114,116-134`). The brief simultaneously requires unchanged personality/system text and no references to removed features. My default is preserve those text bytes and remove Discord runtime/config/tool/UI dependencies; ask Aaron in design convergence whether the wording is an explicit exception or whether he is changing that standing decision. No prompt rewrite is authorized here.
- **Same anti-hedging guards, completion classifier and response guards.** No weaker desktop path, no 'chat-only shortcut' that loses execution policy, no parity definition that compares only final prose.
- **Unconfigured features publish no tools.** Strip unused registrations/config/help/UI/dependencies, with boundary tests at eventual implementation time.
- Version core releases with explicit UI/protocol compatibility and storage migration ownership. Pin released versions, not a floating git dependency or live `/opt/odin` imports.
- Eventual tests must cover Discord and desktop adapters against the same contract scenarios plus platform-specific native proofs. This round does not run or author those tests.

Repository ownership/location of the shared package is an Aaron decision: an Odin-built core distribution consumed by this repo, or a neutral shared repository consumed by both. A Python package inside Odin Desktop that Odin imports opportunistically is not a stable ownership policy.

## 6. My views: 'instead of or alongside'

### Standalone desktop

- Its own install identifier, launcher/update channel and version metadata. No runtime dependency on `/opt/odin`, the current Python environment, Discord credentials or Aaron's source checkout.
- Distinct per-user config/data/cache/log/runtime roots and profile namespace. Linux should follow XDG conventions; Windows/macOS use their native app locations. Immutable application resources are not writable state or execution workspaces.
- Distinct core lock/IPC endpoint and optional listener port. Prefer no network listener unless a feature needs it; if used, discover a profile-bound authenticated endpoint rather than guessing the server's existing port.
- Distinct credential namespace/keychain entries, known-hosts store, context/memory/knowledge/schedule stores, skill/MCP caches, retained output, audit, browser profile and supervised computer resources. Do not share a live SQLite/JSON store between installations.
- Default local actions execute as the logged-in owner, not root. OS privilege prompts require an explicit approved operation and do not become GUI automation targets.
- Data migration is explicit import/snapshot with provenance and schema validation, never point desktop at a running server's data directory. Ask how owner identity, global/personal memory, shared lists, channel/thread IDs and channel-targeted schedules map. Imported effects/schedules start inert until destinations and credentials are validated.

Source demonstrates why this is more than paths: runtime install root derives from code location (`src/runtime_paths.py:8-10`), session persistence is channel-named (`src/sessions/manager.py:1797-1826`), schedules bind requester/destination (`src/discord/native_tools/scheduling.py:112-126`), and current self-update/restart assumes a Python process install (`src/restart.py:1-11,80-85`; `src/web/api/self_update.py:83,264-267`). All need explicit packaging/ownership decisions.

### Optional client to an existing Odin server

**Recommend architecting for it, not silently bundling it as a parity-complete feature.** It preserves phone/remote/server value and avoids forcing users to duplicate providers, knowledge and automation. Existing REST/WS are a starting point, not a sufficient remote-desktop protocol.

- Distinct local-core and server-client connection profiles, plainly labeled in every conversation and action. Target defaults must never switch silently with connection loss.
- Server mode keeps server credentials, permission tiers and host/tool restrictions **on the server**. Removing standalone user access administration does not grant a remote client unrestricted server authority.
- A remote conversation uses server-owned state/destinations. Reconnecting must not start duplicate local schedules/agents or merge remote messages into an unrelated local model session.
- Explicit capability negotiation for attachments, typed delivery/events, controls, history/artifacts, supervised computer binding and API version. Unsupported capability is unavailable, not an invisible degraded substitute.
- No automatic 'remote failed, execute locally' fallback. Local paths/browser/computer/SSH credentials belong to the machine owning execution; sending a local file to the server is an explicit transfer with visibility and limits.
- The UI may connect remotely before the server has every new capability, but must display the gaps. 'Client connects' is not 'R4 parity met'.

Evidence for present compatibility limits: REST scoped sessions versus WS identity channel (`src/web/api/sessions_chat.py:86-114`; `src/web/websocket.py:829-832`), text-only submission (`src/web/chat.py:167`), terminal capture (`src/web/chat.py:328-332`) and Discord-bound background destinations (`src/web/api/agents_loops.py:167-205`).

## 7. What I would cut and add

### Cut from the standalone product

Discord gateway/client/command registration, guild/channel allowlists and mention configuration, other-bot buffering, role/poll/reaction/platform moderation features, multi-user tiers/host ACL administration, public API-token administration, server static-web hosting by default, systemd/root/container-specific onboarding assumptions and git-in-place self-update. Remove their references and dependencies, not merely hide nav entries.

Keep **remote host management**, health/diagnostics, audit, tools, providers, MCP, skills, knowledge/memory/lists, schedules/workflows/loops/agents and supervised computer interaction when configured/qualified. A desktop is not a reason to amputate the executor or pretend a server task is irrelevant.

### Add to meet the bar

1. Durable full transcript, artifact shelf and replayable structured events, separated from compacted model context.
2. Real attachment composer: drag/drop, paste image, file picker, progress/cancel, previews, explicit supported types/limits and ingestion choice. Send references to owned copied snapshots, not unrestricted filesystem handles from a renderer.
3. Conversation/workspace sidebar, search, branches, rename/archive/export/delete, unread state and visible active-target binding.
4. First-class Stop, Steer and Resume controls with truthful per-request receipts and blocked/uncertain states. Optional command palette aliases for `/status`, `/reload` and `/usage`.
5. Per-call execution view with IDs, tool outcomes, retained-evidence links, output stream and final artifact, distinct from optional hidden model reasoning. No default dump of secrets or raw internal prompts.
6. Durable background inbox/notifications and task dashboard, with schedule/agent/loop ownership and window/core status kept separate.
7. Safe media/report viewer, accessible keyboard/screen-reader navigation, virtualized long messages, file save/open and explicit external link handling.
8. Per-user startup/background controls, recoverable provider setup and credential storage, core/UI version/health status and controlled updates.
9. Explicit local/server connection profiles with capability negotiation if Aaron approves remote-client scope.

These additions are proposed desktop equivalents for the observed gaps, not new always-on personality/system-prompt instructions. Voice is a separate concurrent design effort; it is not an already-shipped baseline feature or an implied requirement of this brief.

## 8. Proposed parity acceptance scenarios for later approval

No scenarios were executed or implemented in this round. They make R4 measurable before implementation:

- Text, image-only, mixed multiple files, PDF, safely bounded archive and unsupported binary all enter the same guarded tool loop with honest capability/error messages.
- Open two conversations and a branch: same-conversation work serializes, independent conversations progress, context/artifacts never leak, inheritance is labeled.
- During a long tool call, queue steering and request stop. Distinguish queued from consumed, requested from confirmed, and unknown effect from safe cancellation. Late controls cannot hit a replacement turn.
- Close/reopen UI while a workflow runs. Progress, results, reports and artifacts remain readable after catch-up; restarting the core marks interrupted work rather than replaying it blindly.
- Reload after compaction and after restart: visible transcript/files/tool outcomes remain intact even when model context shrinks.
- Schedule with UI closed, then sleep past due time: show documented missed-run policy and outcomes without pretending the sleeping machine executed anything.
- Repeated submission/reconnect after uncertain delivery cannot duplicate execution. Refreshing a report never reruns its underlying check.
- Install alongside Odin: independent data/credentials/locks/endpoints/processes; no migrations, updates or quits affect the existing installation.
- Disable an optional feature: no tool publication, stale references or hidden fallback execution remains. Same guards/classifier/personality evidence across both adapters.
- Future Windows/macOS builds either retain proven platform safety contracts or explicitly omit those tool capabilities. A launchable shell is not native execution/containment parity.

## 9. Decisions for Aaron and round 2

My preferred architecture is **versioned shared core + per-user background runtime + separate desktop UI**, with local/server profiles as an explicit additional scope. The shell toolkit is not decided here; Claude's platform work should compare lifecycle, packaging, safe IPC/renderer isolation, accessibility, updates and native integrations before selection.

Owner decisions needed:

1. Is run-at-startup login-session background operation, or is boot-before-login also required? I recommend login first.
2. Is remote-server client mode part of Linux v1, or a designed seam for a later phase? No silent substitution for standalone parity.
3. Where does the shared core live, and what coordinated Odin changes/extraction phase will Aaron authorize after design approval?
4. What migration data and identity mapping must v1 support? Existing server stores stay untouched.
5. Which optional capabilities ship in the default distribution versus separately configured packs? Preserve tools-absent-when-unconfigured behavior.
6. What visible history/artifact retention and notification privacy policy is desired? Bounded model history and 24-hour tool evidence are not adequate default chat-history definitions.
7. How broad is Linux support, especially X11/Wayland supervised input? Existing qualification boundaries must remain honest.
8. Is literal Discord wording in the protected personality/system templates an exception to 'removed features leave no references', or is Aaron explicitly changing the prompt-preservation rule? Preserve it unchanged until that decision is made.

The plan should be approved on these contracts, not on an attractive window around the current chat page. The window is the easy part. The background work still needs somewhere truthful to live.
