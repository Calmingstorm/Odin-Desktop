# PR 2 item A: changed model-facing strings and approval coverage

Compared **Phase 1 `phase-1/bring-over` after merge `6862c257b3c7fc75b40f3767d18b195e68a54582`**
with immutable Odin v4.13.0 `cd7530906e9cfa10a0fa900247d7ce2a8bb33e25`.
Approval documents are from main **`ae8aaebb`**, including Aaron's **D18**.
Main contains the app/design, not the engine; the audited engine is on the Phase 1 branch.

This is the requested **string-to-approval table**, not a new approval. The implementation
and its per-path ledger remain independently reviewable. **Items with no exact approved
entry are listed below, not silently declared approved by D1, D2, D17, a passing test,
or a generic adaptation ledger.** This completes the inventory requested by item A;
it does not claim every discovered wording change has been approved.

## Scope and evidence convention

- Includes personality/system templates, request/history context, tool names, parameter
  names/descriptions, tool results/errors and changed skill API text. Retained Phase 2
  bodies count even when currently unavailable. Removal is a disposition, not neutral
  replacement prose. Each removed catalog entry includes its entire schema.
- Compared source diffs and string-bearing ASTs, not only matches for `Discord`.
  Checked adapted engine paths, ordered definition slices, catalog/prompt assembly,
  native handlers, executor/retention, skills, resume and config/status projections.
- Tables quote the **changed fragment** where surrounding text is unchanged. `{...}`
  denotes the existing interpolation, not a new literal. Paths use current source;
  approval links contain the original pinned source locations. Repeated identical
  messages are listed together with their consuming functions.
- Arbitrary host output, user prompts/memory/context, user-authored skill definitions,
  historical source names and logger/import identifiers are not shipped replacement
  instructions. They are not rewritten or falsely given wording approval.
- App-only UI/fixture/protocol error strings imported by the main merge are not model
  prompts or engine tool results. No app-to-real-engine wiring is claimed in Phase 1.

Approval keys:

| Key | Approved entry |
|---|---|
| D7-A | [prompt-changes, Personality presets](../docs/design/prompt-changes.md#personality-presets) |
| D7-B executor | [prompt-changes, Executor system template](../docs/design/prompt-changes.md#executor-system-template) |
| D7-B chat | [prompt-changes, Chat-routed system template](../docs/design/prompt-changes.md#chat-routed-system-template) |
| D7-C / C1-C7 | [prompt-changes part C](../docs/design/prompt-changes.md#c-tool-descriptions-and-other-model-facing-text), incorporating the exact [round-3 C1-C7 inventory](../docs/discussion/06-odin-round3.md#c-discord-mentions-outside-system_promptpy) |
| D18 / part D | [prompt-changes part D](../docs/design/prompt-changes.md#d-request-preamble-approved-2026-10-05) |
| NONE | No exact entry in those approved wording inventories. Requires disposition/review, not presumed approval. |

## 1. Personality, system prompt and request preamble

All system-template rows are in `src/llm/system_prompt.py`. The nine replacements
are exact; the maintenance gate still protects every surrounding byte.

| Source selector | Odin fragment | Desktop fragment | Approved entry |
|---|---|---|---|
| `odin` personality | `For Discord: bold for emphasis` | `In chat: bold for emphasis` | D7-A, Odin row |
| `professional` personality | `For Discord: code blocks for output` | `In chat: code blocks for output` | D7-A, professional row |
| `friendly` personality | `For Discord: use formatting` | `In chat: use formatting` | D7-A, friendly row |
| Executor opening | `You are {bot_name}, an autonomous execution agent on Discord.` | `You are {bot_name}, an autonomous execution agent.` | D7-B executor, opening |
| Executor code-attachment routing | `Never write code inline in Discord.` | `Never write code inline in chat.` | D7-B executor, Code attachments |
| Executor history routing | `**Discord channel context unclear**` / `read_channel` | `**Conversation context unclear**` / `read_conversation` | D7-B executor, context routing |
| Executor Rule 2 | `2. Keep responses concise — this is Discord. Code blocks for output. One update per task, not per tool call. Fenced code blocks (` + three backticks + `) MUST start at column 0 — indented fences render as inline code in Discord.` | `2. Keep responses concise. Code blocks for output. One update per task, not per tool call. Fenced code blocks (` + three backticks + `) MUST start at column 0.` | D7-B executor, Rule 2 |
| Chat opening | `You are {bot_name}, an AI assistant Discord bot.` | `You are {bot_name}, an AI assistant.` | D7-B chat, opening |
| Chat Rule 2 | `2. Keep responses concise — this is Discord, not a document.` | `2. Keep responses concise — this is a chat, not a document.` | D7-B chat, Rule 2 |
| `src/discord/tool_loop.py`, `_prepare_chat_turn`, ordinary conversation | `Channel: #<name>` | `Conversation: <name>` | **D18 / part D**, ordinary row |
| Same selector, child/thread context | `Channel: #<parent> → thread: <name>` | `Conversation: <name>` | **D18 / part D**, thread row |

The preamble still passes `channel_description=channel_ctx` to
`build_request_preamble`; renaming an internal parameter is unnecessary. This named
change is now explicitly recorded in the `src/discord/tool_loop.py` delta reason and
contract. D18 does not approve the other inherited-context wrapper in section 4.

## 2. Offered/documentation tool catalog, names and parameter descriptions

The schema corpus is also inspected before readiness filtering: an unwired tool's
documentation definition is not forgotten because it is hidden from Phase 1 runtime.
Unchanged provider/model/effort descriptions, limits, ordering, timeout and cursor
instructions are not new wording. The spawn limit remains dynamically rendered from
configuration; its pinned base is 5, not a newly hardcoded Desktop allowance.

| Source / selector | Odin fragment | Desktop fragment or removal | Approved entry |
|---|---|---|---|
| `src/tools/defs/browser_web.py`, `browser_screenshot.description` | `posts to Discord.` | `posts to the conversation.` | D7-C, round-3 C1 browser_screenshot |
| `src/tools/defs/media_scheduling.py`, `post_file.description` | `posts it as a Discord attachment. Max 25MB.` | `posts it as a conversation attachment. Max 25MB.` | D7-C, C1 post_file; cap unchanged |
| Same file, `generate_file.description` | `posts it as a Discord attachment.` | `posts it as a conversation attachment.` | D7-C, C1 generate_file |
| `src/tools/defs/integrations_email.py`, `generate_image.description` | `posts it to Discord.` | `posts it to the conversation.` | D7-C, C1 generate_image |
| `media_scheduling.py`, `schedule_task.report_format.description` | `Optional generic paginated Discord embed renderer for a check result.` | `Optional generic paginated conversation report renderer for a check result.` | D7-C, C1 schedule_task.report_format |
| Same file, `update_schedule.report_format.description` | `Generic paginated Discord embed renderer for check output; empty string disables structured rendering.` | `Generic paginated conversation report renderer for check output; empty string disables structured rendering.` | D7-C, C1 update_schedule.report_format |
| `src/tools/defs/tasks_knowledge.py`, `delegate_task.description` | `posting progress to Discord.` | `posting progress to the conversation.` | D7-C, C1 delegate_task |
| `src/tools/defs/agents.py`, `SPAWN_AGENT_BASE_DESC` results clause | `Results are NOT posted to Discord` | `Results are NOT posted to the conversation` | D7-C, C1 spawn_agent |
| Same selector, limit noun | `Max 5/channel` | `Max 5/conversation` | D7-C, C1 spawn_agent; dynamic configured limit preserved |
| `src/tools/defs/channel_process_loops.py`, history tool name | `read_channel` | `read_conversation` | D7-C, C2 current-conversation history |
| Same tool, description | `Reads recent messages from the CURRENT Discord channel into your context. Returns channel history from ALL users and bots. Do NOT pass channel_id — omit it to read the channel the message came from.` | `Reads recent messages from the CURRENT conversation into your context. Returns visible conversation history from all recorded participants. The conversation is the one this request came from; do NOT pass a conversation ID.` | D7-C, C2; entire no-echo tail unchanged |
| Same tool, `channel_id` name and description | `channel_id`; `Numeric channel ID. Omit to use current channel (recommended).` | Removed input and description. `limit` description unchanged. | D7-C, C2; no foreign selector replacement |
| `src/tools/defs/memory_skills.py`, `search_history.description` | `full channel message logs from all users.` | `full conversation message logs in this profile.` | D7-C, C2 search_history |
| `media_scheduling.py`, `update_schedule.description` destination name | `steps, channel_id, report_format, or paused.` | `steps, conversation_id, report_format, or paused.` | D7-C, C2 destination-schema adaptation |
| Same tool, destination parameter | `channel_id`; `New channel ID for notifications` | `conversation_id`; `New conversation ID for notifications` | D7-C, C2; real destination authorization remains a Phase 2 obligation |
| `src/tools/defs/output_delivery.py`, `get_tool_output.description` | `Original caller, channel, tool permission and host scope are rechecked; a cursor is not permission.` | `Original caller, conversation, tool permission and host scope are rechecked; a cursor is not permission.` | D7-C, C2 get_tool_output |
| `browser_web.py`, `set_permission` name/description | `set_permission`; `Sets a Discord user's permission tier. Admin-only. Tiers: admin (full access), user (read-only), guest (chat only).` | Entire tool removed, no replacement text | D7-C, C3 set_permission |
| Same removed schema, `user_id` / `tier` | `Discord user ID (numeric string, e.g. '123456789012345678')`; `Permission tier` | Names, descriptions and enum removed with tool | D7-C, C3 whole schema removal |
| `channel_process_loops.py`, `add_reaction` name/description | `add_reaction`; `Adds an emoji reaction to a message. Unicode emoji or custom format (<:name:id>).` | Entire tool removed | D7-C, C3 add_reaction |
| Same removed schema, `message_id` / `emoji` | `Discord message ID to react to`; `Emoji to react with` | Names and descriptions removed | D7-C, C3 whole schema removal |
| Same file, `create_poll` name/description | `create_poll`; `Creates a Discord native poll in the current channel. Max 10 options. Duration in hours (default 24, max 168/7 days).` | Entire tool removed | D7-C, C3 create_poll |
| Same removed schema, `question` / `options` / `duration_hours` / `multiple` | `The poll question`; `List of answer options (max 10)`; `Poll duration in hours (default 24)`; `Allow multiple selections (default false)` | Names, descriptions and item schema removed | D7-C, C3 whole schema removal |
| `media_scheduling.py`, `purge_messages` name/description | `purge_messages`; `Deletes recent messages in the current Discord channel and resets conversation history. Default 100, max 500.` | Entire tool removed | D7-C, C3 purge_messages |
| Same removed schema, `count` | `Number of messages to delete (default 100, max 500)` | Name and description removed | D7-C, C3 whole schema removal |

`paginated_embed_v1` remains unchanged, as C1 requires. `src/discord/tool_catalog.py`
and `src/tools/agent_tool_policy.py` change composition/readiness/name matching, not
additional emitted instruction sentences. Dynamic custom skill `name`, `description`
and `input_schema` remain user-provided (C6), not rewritten bundled defaults.

## 3. Retained result/error wording covered by the inventory

| Current source / selector | Odin text | Desktop text | Approved entry |
|---|---|---|---|
| `src/discord/native_tools/channel_ops.py`, missing request | `No channel context available.` | `No conversation context available.` | D7-C, C4 history receipts |
| Same handler, empty transcript | `No messages found in channel.` | `No messages found in conversation.` | D7-C, C4 |
| Same handler, history wrapper | `[Channel history: {len(messages)} messages read. This is context for YOU — do not paste or echo these messages. Respond with your own summary, analysis, or action.]` | Same wrapper with `Conversation history` | D7-C, C4; no-echo clauses unchanged |
| Same handler, denied transcript | `Permission denied — cannot read this channel.` | `Permission denied — cannot read this conversation.` | D7-C, C4 |
| Same handler, failed transcript | `Failed to read channel: {e}` | `Failed to read conversation: {e}` | D7-C, C4; inserted exception is scrubbed |
| `src/discord/native_tools/media.py`, oversized post_file | `Discord limit is 25 MB.` | `Conversation attachment limit is 25 MB.` | D7-C, C4 media cap receipt |
| Same file, post_file success | `Posted {filename} ({size} KB) to channel.` | `Posted {filename} ({size} KB) to conversation.` | D7-C, C4; filename backticks and size formatting retained |
| Same file, post_file upload failure | `Failed to upload to Discord: {e}` | `Failed to upload to the conversation: {e}` | D7-C, C4 |
| Same file, generated-image delivery failure | `Failed to upload generated image to Discord: {e}. Generation already succeeded; do not regenerate automatically.` | `Failed to upload generated image to the conversation: {e}. Generation already succeeded; do not regenerate automatically.` | D7-C, C4; no-regeneration clause unchanged |
| `src/discord/turn_resume.py`, ConversationAccessDenied | `Discord currently denies access to the original message` | `The conversation store currently denies access to the original message` | D7-C, C4; typed store denial only |
| Same file, ConversationFetchUnavailable | `Discord could not fetch the original message yet` | `The conversation store could not fetch the original message yet` | D7-C, C4; typed transient condition only |
| `src/error_presentation.py`, Discord HTTP exception special case | `Discord API error: HTTP {status_s} {reason}` | Branch removed; no fabricated Desktop HTTP replacement | D7-C, C4 explicit removal |
| `src/discord/native_tools/channel_ops.py`, foreign-channel lookup/poll errors | `Channel {channel_id} not found or not accessible.`; `Discord polls support a maximum of 10 options.` and poll receipts | Removed along with foreign input/poll handler | D7-C, C2/C3/C4 removal dispositions |

Success bodies behind unavailable publishers are retained code, **not observed durable
publication**. Phase 1 does not publish files or claim those success receipts were emitted.

## 4. Changed/new model-facing strings WITHOUT an exact approval entry

**NONE means none in D7 A-C, round-3 C1-C7 or part D.** Many are truthful implementation
diagnostics, but truthfulness and functional adaptation approval are not exact wording
approval. This table deliberately does not retroactively extend D18 or hide them as logs.
Some are currently gated/hidden; they remain in scope for eventual engine wiring.

| Source / selector | Baseline or previous behavior | Current changed string | Approved entry / disposition |
|---|---|---|---|
| `src/discord/intake_pipeline.py`, inherited context tag | `[INHERITED FROM #{parent_name}]` | `[INHERITED FROM {parent_name}]` | **NONE**; actual model-context wrapper, not D18's preamble |
| Same function, context block | `Parent channel context:\n{parent_context}` | `Parent conversation context:\n{parent_context}` | **NONE** |
| `channel_ops.py`, unexpected history arguments | Foreign-channel lookup accepted | `Only 'limit' is accepted; the conversation is the one this request came from.` | **NONE** for this new error; C2 approves selector removal, not exact sentence |
| Same handler, absent history reader | No Phase 2-specific diagnostic | `Conversation history is unavailable: Phase 2 admission and transcript wiring is not implemented.` | **NONE** |
| `media.py`, publisher missing (`_DELIVERY_UNAVAILABLE`) | Gateway attachment send | `Conversation artifact publication is unavailable until Phase 2.` | **NONE**; can enter existing caught tool-error wrappers |
| Same file, generate_file success | `File {filename} ({len(file_bytes)} bytes) attached to channel.` | `File {filename} ({len(file_bytes)} bytes) attached to conversation.` | **NONE**; C4 names post_file receipt, not this separate success string; backticks retained |
| Same file, post_file/analyze_image caller denial | Gateway author identity | `Permission denied: authenticated owner identity is required.` | **NONE**; both consuming handlers |
| `src/discord/native_tools/agents_tasks.py`, delegate_task admission | Prior background admission | `Phase 2 background request admission and delivery is not implemented.` | **NONE** |
| Same file, delegate_task success | `Progress will be posted to this channel.` | `Progress will be posted to this conversation.` | **NONE**; C1 approves catalog progress text, not this separate result |
| Same file, start_loop admission | Prior loop admission | `Phase 2 autonomous request admission and delivery is not implemented.` | **NONE** |
| Same file, spawn_agent admission | Prior agent admission | `Phase 2 agent request admission and invocation context is not implemented.` | **NONE** |
| Same file, collect/agent invocation context | Prior invocation context | `Phase 2 agent invocation context is not implemented.` | **NONE** |
| `src/discord/native_tools/scheduling.py`, schedule admission | Original destination inferred from gateway | `Phase 2 scheduled destination admission is not implemented.` | **NONE** |
| Same file, update destination | Original channel destination authorization | `Phase 2 scheduled destination authorization is not implemented.` | **NONE** |
| `src/discord/native_tools/skills_tools.py`, skill delivery | Immediate/staged gateway delivery | `Conversation skill delivery is unavailable until Phase 2.` | **NONE** |
| Same file, export_skill unstaged result | `Skill '{name}' exported as {filename}.` | `Skill '{name}' export prepared as {filename} ({len(file_bytes)} bytes), but not staged. {staging_error}` | **NONE**; explicit prepared-versus-published diagnostic |
| `src/tools/executor.py`, unavailable owner capability | Tier permission wording | `Permission denied: tool '{tool_name}' is not available for this authenticated owner request.` | **NONE** |
| Same file, newly propagated permission codes | Existing denial prose, now an additional admission result path | `permission_denied` | **NONE** for new result path; `Permission denied: a requester identity is required.` itself is **unchanged**, not a wording delta |
| Same file, retention live capability check | No equivalent capability sentence | `Output capability unavailable.` | **NONE** |
| `src/tools/builtin_policy.py`, unavailable_rejection | New rejection distinct from unchanged disabled_rejection | `Tool unavailable: '{name}' has no ready handler for this installation and was not executed.`; `tool_unavailable` | **NONE** |
| `src/tools/runtime_delivery.py`, no authenticated retention consumer | Ownerless fallback path | `Output retention unavailable: no authenticated executor consumer is configured. Do not replay the tool.` | **NONE**; output/result paths both use it |
| Same file, missing output authority | No equivalent readiness diagnostic | `Output authority unavailable. Do not replay the tool.` | **NONE** |
| Same file, denied output capability | No equivalent readiness diagnostic | `Output capability unavailable.` plus ` Do not replay the tool.` | **NONE**; dynamically prefixes an existing denial where present |
| `src/tools/output_authorization.py`, owner_output_scope | Prior gateway scope | `Conversation output scope unavailable until Phase 2 admission.` | **NONE** |
| `src/tools/autonomous_loop.py`, start | Original loop start path | `Error: Autonomous loops unavailable: Phase 2 durable admission and conversation delivery are not configured. No loop was started.` | **NONE** |
| Same file, loop delivery | Gateway response posting | `Autonomous loop conversation delivery unavailable. Do not replay the iteration.` | **NONE** |
| `src/tools/skill_context.py`, post_message missing callback | Log-only `post_message called but no channel callback available` | `Conversation delivery is unavailable until Phase 2 wiring.` | **NONE**; now raised, potentially returned by skill execution |
| Same file, post_file missing callback | Log-only `post_file called but no channel callback available` | `Conversation attachment delivery is unavailable until Phase 2 wiring.` | **NONE** |
| Same file, search_history | Session-manager result or empty list | `Owner-scoped conversation history is unavailable until Phase 2 wiring.` | **NONE** |
| Same file, schedule_task/update_schedule/delete_schedule | Scheduler result or unavailable defaults | `Validated conversation scheduling is unavailable until Phase 2 wiring.` | **NONE**; three consumers |
| `src/tools/skill_manager.py`, dependency installer | pip output / `pip install timed out after {timeout}s` | `Approved isolated skill dependency installation is unavailable in Phase 1.` | **NONE**; named D14 functionality is not wording approval |
| Same file, failed dependency diagnostic | Previous dependency setup path | `DependencyError: skill dependencies unavailable` | **NONE**; skill-status failure reason can expose it |
| `src/tools/browser.py`, missing browser path | Ambient browser discovery | `Browser unavailable: required bundled Chromium is not configured.` | **NONE** |
| Same file, missing Playwright | `playwright is not installed. Run: pip install playwright && playwright install chromium` | `Browser unavailable: required bundled Playwright dependency is missing.` | **NONE** |
| Same file, failed launch | `Failed to launch Chromium. Run 'playwright install chromium' to install browser binaries. ({e})` | `Failed to launch required bundled Chromium. Repair the desktop installation. ({e})` | **NONE** |
| `src/tools/handlers/browser_web.py`, http_probe without target host | Implicit local host path | `http_probe unavailable: an authorized managed host is required.` | **NONE** |
| `src/tools/handlers/files_docs.py`, PDF dependency failure tail | `Install the 'pdf' extra (pip install '.[pdf]') and restart Odin.` | `The required bundled dependency is unavailable; repair the desktop installation.` | **NONE**; original error prefix/type retained |
| `src/knowledge/importer.py`, file/directory root denial | `file/directory not in allowed import roots: {SAFE_IMPORT_ROOTS}` | `{kind} not in allowed import roots: {actual admitted roots}`, or `none admitted` | **NONE** for changed dynamic diagnostic; original prefix remains |
| `src/discord/turn_resume.py`, empty adapter read | A returned `None` previously led to `the original message is gone` | `the original message could not be fetched yet` | **NONE** for changed disposition on an empty read; this sentence itself is unchanged on generic/transient exception paths |
| `src/discord/tool_loop.py`, shared Phase 2 gate (also used by resume) | No Phase 2 entrypoint guard | `Desktop tool-loop intake, durable admission and delivery require Phase 2 wiring` | **NONE**; retained engine entrypoint error, not D18's context line |
| `src/discord/delivery.py`, DeliveryService construction | Gateway delivery service | `Durable conversation delivery is deferred to Phase 2` | **NONE**; control/startup error, not successful model delivery |
| `src/computer/integration.py`, request admission | Original request context construction | `Desktop computer request admission is unavailable until Phase 2` | **NONE**; foreground/control bridge, currently unavailable |
| Same file, stop_channel/operator context | Original stop/operator context construction | `Desktop computer control admission is unavailable until Phase 2` | **NONE**; both consumers |
| `media.py`, generated-image URL suffix and status metadata | Conditional ` Attachment URL: {attachment_url}` and detected URL metadata | Suffix removed; `attachment_url_available` remains present but false | **NONE** for changed result/metadata shape; no renderer URL or durable publication fabricated |
| `src/discord/intake_pipeline.py`, shared intake gate | Original gateway admission path | `Phase 2 authenticated owner/conversation admission, secret rejection, revision-bound request ownership and durable delivery are not wired` | **NONE** |
| `src/discord/channel_state.py`, steer denial | `Access denied. Only the turn's requester or an admin may steer it.` | `Access denied. Only the turn's requester may steer it.` | **NONE**; control receipt |
| `src/discord/delivery.py`, history status label | `Reading the channel` | `Reading the conversation` | **NONE** exact, retained presentation/status text |
| `src/discord/scheduled_events.py`, execution gate | Operational scheduled work | `Scheduled execution requires Phase 2 durable admission, conversation authority and delivery.` | **NONE** |
| Same module, publication gate | Gateway publication | `Conversation publication is unavailable until Phase 2; do not replay the producer.` | **NONE** |
| Same module, scheduled report recovery | No corresponding fixed exception | `Scheduled report publication unavailable; preserve producer output and recover delivery without rerunning the check` | **NONE** |
| Same module, digest destination diagnostic | `Digest {schedule['id']} has no channel_id` | `Digest {schedule['id']} has no conversation_id` | **NONE** exact; diagnostic destination noun |
| Same module, scheduled task diagnostic | `Scheduled task {schedule['id']} has no channel_id` | `Scheduled task {schedule['id']} has no conversation_id` | **NONE** exact |
| `src/discord/scheduled_report.py`, post gate | Operational gateway report post | `Scheduled report conversation publication is unavailable until Phase 2.` | **NONE** |
| `src/discord/slash_commands.py`, command registration gate | Gateway command registration | `Native command registration and owner-bound stop/steer/reload controls require Phase 2 admission, control and durable delivery wiring` | **NONE** |
| `src/discord/wiring.py`, build_services | Original service composition | `Phase 2 core service composition is not implemented.` | **NONE** |
| Same module, build_components | Original component composition | `Phase 2 request/control/durable-surface wiring is not implemented.` | **NONE** |
| Same module, start_mcp | Original configured service startup | `Phase 2 supervised capability startup is not implemented.` | **NONE** |
| `src/discord/background_task.py`, progress projection | `Full report attached ({len(task.results)} steps).` suffix | Suffix removed; full scrubbed text assigned to `task.progress_text` | **NONE** for changed result shape; no attachment claimed |
| Same module, summary projection | `Full summary attached.` suffix | Suffix removed; scrubbed text assigned to `task.summary_text` | **NONE** for changed result shape |

`Permission denied: tool scope revoked or unavailable.` and `Permission denied:
restricted tool authority.` in executor admission, and `Permission denied: selected
skill scope revoked or unavailable.` in skill invocation, are unchanged baseline sentences
with adapted authority paths, not new wording. `permission_denied`,
`conversation_delivery_unavailable` and `tool_unavailable` are machine-readable
status/error strings, not prose approval; the new consumer paths are explicitly
included above. C4 authorizes the history error's noun replacement, not new
exception-scrubbing or broadened catch behavior. Those remain implementation
review obligations rather than exact-wording approval.

### Adjacent changed config/status strings, separately visible through inspection

These are management metadata, not new always-on model instructions. They are included
because a model can inspect configuration/status via tools. The actual implementation
is not silently equated with the specific C4 wording.

| Source / selector | Odin text | Actual Desktop text | Approved entry |
|---|---|---|---|
| `src/config/apply_registry.py`, prompt consumer label | `Chat, Discord, and loop prompts` | `Conversational turns and loop prompts` | **NONE for actual text**; C4 instead proposes `Chat, conversation, and loop prompts` |
| Same file, checkpoint description | `Checkpoint Discord chat turns so they survive an outage.` | `Checkpoint conversational turns so they survive an outage.` | **NONE for actual text**; C4 instead proposes `Checkpoint conversation turns so they survive an outage.` |
| Same file, owner override description | `Let admins proceed past a governor refusal.` | `Let the authorized owner proceed past a governor refusal.` | **NONE in wording inventory**; D17 governs behavior, not this exact description |
| `src/config/schema.py`, invalid mapping guidance | `It must contain a YAML mapping with at least a 'discord' section.` | `It must contain a YAML mapping.` | D7-C, C7 schema guidance |
| Same diagnostic, documentation pointer | `See config.yml comments for examples.` | `See the desktop configuration documentation for examples.` | **NONE** |
| Same module, unknown top-level fields | Baseline unknown-field compatibility path | `Config validation failed: unsupported top-level configuration fields` | **NONE**; startup diagnostic, not prompt policy |
| `src/search/embedder.py`, missing configured/bundled model | Ambient/cached-model selection | `no bundled embedding model roots configured`; `bundled embedding model unavailable: {details}` | **NONE**; may be surfaced through knowledge/search failure wrappers |

### Internal control/storage and lifecycle diagnostics, not established model prose

These are separately inventoried rather than claiming every construction exception is
an offered-tool result. Each has **NONE** for exact wording approval; future Phase 2
projection must not silently turn them into an approved model contract.

| Current source / selector | Baseline disposition | Current string(s) without an entry |
|---|---|---|
| `src/discord/scheduled_report.py`, store/record/control validation | New stored-report operations | `stored report_id must be a non-empty string`; `stored conversation_id must be a non-empty string`; `report_id must be a non-empty string`; `conversation_id must be a non-empty string`; `report_id already exists; do not replay the producer`; `unsupported report control`; `report belongs to a different conversation` |
| `src/__main__.py`, main | Server composition removed | `Desktop core composition is deferred to Phase 2` |
| `src/cli.py`, main | Server API CLI removed | `Desktop local control client is deferred to Phase 2` |
| `src/restart.py`, relaunch | Server reexec removed | `Relaunch blocked by unproven teardown`; `Desktop supervised relaunch is deferred to Phase 2` |
| `src/setup_wizard.py`, setup | Gateway onboarding removed | `Desktop onboarding is deferred to Phase 2` |
| `src/health/checker.py`, delivery readiness | Gateway readiness facts removed | `Authenticated delivery readiness is not wired (Phase 2)`; `Delivery ready`; `Delivery not ready` |
| `src/web/api/__init__.py`, shared stub | App-management service boundary replaced | `{operation} requires authenticated Desktop service wiring (Phase 2)`; operation names include `Autonomous loop commands`, `Agent commands`, `Owned process commands`, `Conversation execution`, `Conversation management`, `Private trajectory inspection`, `Private agent trajectory inspection`, `Fresh-profile setup`, `Effective runtime status`, `Supervised lifecycle actions`, `Personality settings`, `Startup report delivery`, `Skill management and execution`, `Durable scheduling commands`, `Conversation event delivery` |

## 5. API documentation and non-runtime coupling

Native/API docstrings are not automatically injected model text. They are recorded so
source-reading and generated documentation do not conceal wording changes. New internal
docstrings describing authenticated ownership/readiness are implementation documentation,
not catalog instructions; no approval is manufactured for those paragraphs.

| Source / selector | Before | After / disposition | Entry |
|---|---|---|---|
| `src/discord/native_tools/channel_ops.py`, reader docstring | `Read recent messages from a Discord channel.` / `Returns formatted channel history including messages from all users and bots` | `Read recent messages from the current conversation.` / `Returns formatted visible conversation history including messages from all recorded participants` | D7-C, C4 |
| `media.py`, screenshot/generate_file/post_file docstrings | `Discord image`; `Discord attachment`; `post it to Discord` | `conversation image`; `conversation attachment`; `post it to the conversation` | D7-C, C4 |
| Same file, generate_image docstring | `Discord attachment`; `this tool layer owns Discord.` | `conversation attachment`; `this tool layer owns conversation delivery.` | D7-C, C4 |
| `src/discord/response_guards.py`, comment | `before Discord delivery.` | `before conversation delivery.` | D7-C, C5; non-runtime only |
| Same file, scrubber docstring | `before sending to Discord.` | `before sending to the conversation.` | D7-C, C5; non-runtime only |
| `docs/skills.md`, heading | `### Discord` | `### Conversation delivery` | D7-C, C6 |
| Same document, post_message | `Send to invoking channel` | `Send to invoking conversation` | D7-C, C6 |
| Same document, schedule_task signature | `channel_id` | `conversation_id` | D7-C, C6 explicit signature adaptation |
| Same document, skill configuration help | `Set via web UI or skill_status API.` | `Desktop settings and delivery wiring are Phase 2 work; skill_status remains the tool-side inspection contract.` | **NONE** for new documentation sentence |
| `src/tools/skill_context.py`, class/post_message/post_file docstrings | `channel messaging`; `channel that invoked this skill` | `conversation messaging`; `conversation that invoked this skill` | D7-C, C6 |
| Same file, schedule_task parameter | `channel_id` | `conversation_id` | D7-C, C6 |
| Same file, search_history result field docstring | `channel_id` | `conversation_id` | **NONE exact**; C2/C6 destination semantics explain the adaptation but do not quote this API result field |
| Same file, schedule_task docstring | `Add a scheduled task. Returns the schedule dict, or None if scheduler unavailable. Keyword args are passed to Scheduler.add() ...` | `Add a task to an authenticated, validated conversation destination. Phase 1 has no destination authority. No caller-supplied ID is admitted or forwarded to the upstream scheduler. Phase 2 must bind the owner, profile and conversation before this surface can schedule delivery.` | **NONE exact**, non-runtime API documentation |
| Same file, list_schedules docstring | Prior scheduler list documentation | `List schedules when owner/conversation intake is available.` | **NONE exact**, non-runtime API documentation |
| `src/discord/native_tools/skills_tools.py`, staging notes | `posts to the channel now`; `per-channel pending-files queue` | `posts to the conversation now`; `per-conversation pending-files queue` | D7-C, C6 |

The completion-judge prompt, classifier/governor criteria and anti-hedging/fabrication/
promise/failure/continuation nudges have **no wording adaptation**. The failure wrapper
copied into `runtime_delivery.ensure_failure_visible` retains the original
`Error (tool reported failure):\n{result_text}` sentence; moving it is not a new instruction.
Secret scrubbers retain Discord-token detection as explicitly required by C5.

## 6. Removed gateway/social diagnostics and other exclusions

These complete the **removal disposition** audit, rather than pretending gateway errors
became Desktop model prose. Any new Phase 1 entrypoint guard says the actual capability
is unwired, not that a Desktop gateway exists.

| Baseline source / surface | Removed wording or feature | Entry / boundary |
|---|---|---|
| `src/web/api/discord_connection.py` | `no usable Discord credential`; gateway activation failure (both cases); invalid token/configuration | D7-C, C7; whole endpoint absent |
| `src/web/api/discord_identity.py` | `invalid Discord user ID` | D7-C, C7; identity endpoint absent |
| `src/web/api/config_admin.py` | `discord_token format is invalid` | D7-C, C7; credential-validation branch removed |
| `src/web/onboarding.py` | credential saved / gateway unavailable / gateway activation failed | D7-C, C7; gateway onboarding removed |
| `src/health/startup.py` | missing/empty token; `Set DISCORD_TOKEN ...`; token present; missing discord section; gateway-check skipped | D7-C, C7; gateway readiness removed |
| `src/discord/connection_supervisor.py` | no/empty token; permanently closed; gateway ready/disconnected | D7-C, C7; supervisor absent |
| `src/discord/discordpy_adapter.py` | reattachment unavailable, unsupported Client/private-state layouts | D7-C, C7; adapter absent |
| `src/discord/slash_commands.py` | ` · Discord latency {latency_text}` | D7-C, C7; gateway metric removed |
| `src/config/apply_registry.py` | `Discord conversational-intake policy.`; `Write-only Discord bot credential.` | D7-C, C7; associated schema consumers removed |
| `src/discord/intake_pipeline.py`, gateway bot-secret/mention/intake notices | Gateway message-deletion notices, bot buffering/mention and transport admission paths | Removed gateway implementation; **not an individually quoted C7 wording entry**; no replacement model guidance |
| `src/discord/background_task.py`, `scheduled_events.py`, `scheduled_report.py` | Gateway send/edit/paging/attachment transport and its transport-only formatting | Removal/adapted internal formatting, **not blanket wording approval**; no claimed durable publication |
| `src/tools/handlers/state.py`, list owner denial | `You don't have access to the '{list_name}' list.` | Removed per-user list ownership branch; **not an exact C1-C7 wording entry**, no replacement sentence |
| Owner/profile/host/startup modules and removed web stubs | Construction/configuration errors for actual private paths, UUIDs, secrets, host trust, runtime ownership and unwired controls | Not catalog/prompt/tool receipt text; inspection can expose source as data, not turn it into always-on guidance. No exact wording approval asserted. |
| `app/` added by main merge | UI labels, fixture-core errors, broker/control receipts | App/fixture-only, not injected into the real model in Phase 1. Future core wiring must audit any new projection. |

## Validation and remaining disposition

`tests/test_desktop_round2_acceptance.py` statically checks the merged D18 record,
exact request context construction and table coverage, compares every retained catalog
schema/string with the frozen baseline plus only the named C1-C3 transformations,
and protects the explicit uncovered list. No Phase 2 loop, model endpoint, native helper
or active desktop is exercised by those checks.

Observed local validation on 2026-10-05:

- Focused acceptance/maintenance/catalog/strip-loop selection: **43 passed** in the
  sanitized non-root PID/mount namespace. The new missing-D18-ledger regression first
  failed against the old generic delta reason, then passed with the explicit entry.
- Complete approved qualification: **28/28 groups**, **13,131 passed executions,
  2 skipped, 0 failures/errors**. Counts are executions, not unique cases or full
  inherited-suite/Phase 2 parity. Existing AsyncMock/timeout warnings remain visible.
- Qualification plan remains unchanged at SHA-256
  `6b05c2e8552a7ef302f6840cf88edb5072ece464906fddb14293d9060bcfe447`.
- Offline byte drift: **1,236 shared paths, 197 exact ledgered paths, 202 pending
  independent reviews, zero unexplained errors**. Refreshed only the D18 approval-document
  digest in the manifest, not baseline, selection, case accounting or safety policy.
- Lint: **zero new findings**, seven named inherited findings. `git diff --check` clean.
- Local receipts: `.test-state/pr2-item-a-qualified.log`,
  `.test-state/pr2-item-a-drift.json`, and `.test-state/qualification-{0..27}.xml`.
  Hosted CI is a separate result, never inferred from those local receipts.

**Outstanding wording entries are explicitly NONE above.** They must be reviewed,
approved separately, restored or otherwise dispositioned before an assertion of complete
wording approval. This change does not rewrite them, relax any safety policy, claim
native qualification, deploy an engine, restart a service or merge PR 2 into main.
