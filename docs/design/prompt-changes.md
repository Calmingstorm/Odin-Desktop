# Prompt changes for Odin Desktop

Owner: Claude. **Approved by Aaron, D7 (2026-10-04).** This implements decision **D1**: Odin Desktop's prompt, and the rest of its
model-facing text, does not mention Discord.

**The rule.** Only the Discord references change. Every other byte of the personality presets and system templates
stays identical to Odin's. Aaron approves the exact wording below before any build. Parts A and B cover the prompt
templates. Part C covers tool descriptions and other model-facing text, from Odin's round-3 inventory
([`06-odin-round3.md`](../discussion/06-odin-round3.md#c-discord-mentions-outside-system_promptpy), which has full file:line
evidence).

**Source.** Odin `src/llm/system_prompt.py` at `cd753090`. These are the only nine Discord mentions in the file.

## Personality presets

| Line | Today (Odin) | Proposed (Odin Desktop) |
|---|---|---|
| 33 (`odin` preset voice) | `- For Discord: bold for emphasis, code blocks for technical output. Don't format casual conversation with headers and bullets when a sentence would do.` | `- In chat: bold for emphasis, code blocks for technical output. Don't format casual conversation with headers and bullets when a sentence would do.` |
| 47 (`professional` preset voice) | `- For Discord: code blocks for output, bold for emphasis. Keep responses scannable.` | `- In chat: code blocks for output, bold for emphasis. Keep responses scannable.` |
| 61 (`friendly` preset voice) | `- For Discord: use formatting to make responses easy to read. Keep the tone friendly but not over-the-top.` | `- In chat: use formatting to make responses easy to read. Keep the tone friendly but not over-the-top.` |

## Executor system template

| Line | Today (Odin) | Proposed (Odin Desktop) |
|---|---|---|
| 66 (opening) | `You are {bot_name}, an autonomous execution agent on Discord.` | `You are {bot_name}, an autonomous execution agent.` (D7: the strictly minimal option) |
| 95 (Tool Routing) | `- **Code attachments** → \`generate_file\`. Never write code inline in Discord.` | `- **Code attachments** → \`generate_file\`. Never write code inline in chat.` |
| 97 (Tool Routing) | `- **Discord channel context unclear** → \`read_channel\` before answering.` | `- **Conversation context unclear** → \`read_conversation\` before answering.` The desktop history tool is `read_conversation` (Odin, round 3): it reads the current conversation's visible history only. |
| 105 (Rule 2) | ``2. Keep responses concise — this is Discord. Code blocks for output. One update per task, not per tool call. Fenced code blocks (```) MUST start at column 0 — indented fences render as inline code in Discord.`` | ``2. Keep responses concise. Code blocks for output. One update per task, not per tool call. Fenced code blocks (```) MUST start at column 0.`` |

## Chat-routed system template

| Line | Today (Odin) | Proposed (Odin Desktop) |
|---|---|---|
| 116 (opening) | `You are {bot_name}, an AI assistant Discord bot.` | `You are {bot_name}, an AI assistant.` |
| 131 (Rule 2) | `2. Keep responses concise — this is Discord, not a document.` | `2. Keep responses concise — this is a chat, not a document.` |

## Notes for approval

- **Line 66.** Decided (D7): the strictly minimal "…an autonomous execution agent."
- **Line 95.** It keeps today's behaviour: code goes to files rather than inline. On Discord, part of the reason was the
  2,000-character limit, which the desktop doesn't have. Changing the behaviour itself would be a separate decision. D2
  says he works the same, so the proposal keeps it.
- **Line 105.** The column-0 fence rule is kept, because it is harmless and keeps outputs portable. Only its Discord
  justification is dropped.
- **Your own custom personality text** (in your live config) is user data, not shipped text. It is out of scope here
  (D5).

## C. Tool descriptions and other model-facing text

These substitutions change only the Discord wording. Every other sentence in each description stays as it is.

### Tool descriptions (catalog text)

| Tool | Today | Proposed |
|---|---|---|
| `browser_screenshot` | "…and posts to Discord." | "…and posts to the conversation." |
| `post_file` | "…posts it as a Discord attachment. Max 25MB." | "…posts it as a conversation attachment. Max 25MB." The 25 MB cap is real behaviour and stays until a separate approved change. |
| `generate_file` | "…and posts it as a Discord attachment." | "…and posts it as a conversation attachment." |
| `generate_image` | "…and posts it to Discord." | "…and posts it to the conversation." |
| `schedule_task.report_format` | "Optional generic paginated Discord embed renderer for a check result." | "Optional generic paginated conversation report renderer for a check result." |
| `update_schedule.report_format` | "Generic paginated Discord embed renderer for check output; …" | "Generic paginated conversation report renderer for check output; …" |
| `delegate_task` | "…posting progress to Discord." | "…posting progress to the conversation." |
| `spawn_agent` | "Results are NOT posted to Discord" / "Max 5/channel" | "Results are NOT posted to the conversation" / "Max 5/conversation". The number stays as it is configured. |
| `read_channel` → **`read_conversation`** | "Reads recent messages from the CURRENT Discord channel… from ALL users and bots. Do NOT pass channel_id…" | "Reads recent messages from the CURRENT conversation… visible conversation history from all recorded participants. The conversation is the one this request came from; do NOT pass a conversation ID." The rest is unchanged, including the no-echo instruction. |
| `search_history` | "…full channel message logs from all users." | "…full conversation message logs in this profile." |
| `get_tool_output` | "Original caller, channel, tool permission and host scope are rechecked; …" | "Original caller, conversation, tool permission and host scope are rechecked; …" |

**Interface changes, not just wording.** Scheduling's `channel_id` fields become `conversation_id`: a validated
destination, not a free-form ID. `read_conversation` loses its channel-ID input entirely.

**Tools removed with their features,** with no replacement text: `set_permission`, `add_reaction`, `create_poll` and
`purge_messages`. Deleting visible history and resetting context are separate desktop controls.

### Tool results and errors the model sees

Apply only the named retained-receipt substitutions in round-3 sections C2 and C4. Remove the named Discord-only
branches along with their features. Emit adapted store and HTTP diagnostics only for their actual conditions. Never
mechanically rewrite arbitrary tool output, user skill text, source identifiers or historical material.

Examples:
- "Posted `{file}` (…) to channel." becomes "…to conversation."
- "Failed to upload to Discord: {e}" becomes "Failed to upload to the conversation: {e}".
- The no-regeneration clause on image-upload failure stays.
- The resume messages "Discord currently denies access…" and "Discord could not fetch…" become "The conversation store
  …", and are emitted only for the matching store condition.

**The approval inventory.** The tables in part C are abbreviated. The exact retained substitutions and dispositions
are round-3 sections C1 to C7, including retained config and status metadata. Unchanged parts of each description
stay intact. Schema and handler adaptations get their own ledger entries and tests.

### Skill documentation and the skill API

`docs/skills.md`:
- "### Discord" becomes "### Conversation delivery".
- `post_message`: "Send to invoking channel" becomes "Send to invoking conversation".

The SkillContext docstrings change "channel" to "conversation". `schedule_task`'s `channel_id` parameter becomes
`conversation_id`.

### Guard file wording (separate approval)

Only two lines, both non-runtime. No pattern, condition, ordering or budget changes:

| Location | Today | Proposed |
|---|---|---|
| `response_guards.py:16` (comment) | "…before Discord delivery." | "…before conversation delivery." |
| `response_guards.py:27` (docstring) | "…before sending to Discord." | "…before sending to the conversation." |

Odin found no Discord wording in the completion-judge prompt or the classifier, governor or anti-hedging text; those
stay byte-identical.

**One deliberate exception.** The secret scrubber keeps recognizing Discord-token-shaped secrets. A pasted Discord token
is still a secret, so removing that check would weaken protection.

## D. Request preamble (approved 2026-10-05)

Found in the Phase 1 review: the per-request preamble's context line, built in `src/discord/tool_loop.py` and passed to
`build_request_preamble(channel_description=...)`, reaches the model on every request. It was missing from parts A to
C. Aaron approved it on 2026-10-05 ("Yes"):

| Today | Desktop |
|---|---|
| `Channel: #<name>` | `Conversation: <name>` |
| `Channel: #<parent> → thread: <name>` | `Conversation: <name>` |

## E. Tool results and diagnostics (approved 2026-10-05)

Odin's Phase 1 table (`maintenance/pr2-model-facing-string-approvals.md` on the Phase 1 branch) found these
model-visible strings outside parts A to D. Aaron approved them on 2026-10-05 ("yes you can approve"):

| Kind | Today | Desktop |
|---|---|---|
| Inherited context | `[INHERITED FROM #{parent_name}]` / `Parent channel context:` | `[INHERITED FROM {parent_name}]` / `Parent conversation context:` |
| File result | `File {filename} ({size} bytes) attached to channel.` | `… attached to conversation.` |
| Task result | `Progress will be posted to this channel.` | `Progress will be posted to this conversation.` |
| Status label | `Reading the channel` | `Reading the conversation` |
| Schedule diagnostics | `Digest {id} has no channel_id` / `Scheduled task {id} has no channel_id` | `… has no conversation_id` |
| History tool | (it took a channel ID) | `Only 'limit' is accepted; the conversation is the one this request came from.` |
| Steer denial | `Access denied. Only the turn's requester or an admin may steer it.` | `Access denied. Only the turn's requester may steer it.` |
| Tool permission | `Permission denied: tool '{tool_name}' is not available for tier '{tier}'. Contact an admin to upgrade your permissions.` | `Permission denied: tool '{tool_name}' is not available for this authenticated owner request.` |
| File and image caller | (Discord author identity) | `Permission denied: authenticated owner identity is required.` |
| Browser | `playwright is not installed. Run: pip install playwright && playwright install chromium` / `Failed to launch Chromium. Run 'playwright install chromium' to install browser binaries. ({e})` | `Browser unavailable: required bundled Playwright dependency is missing.` / `Failed to launch required bundled Chromium. Repair the desktop installation. ({e})` / `Browser unavailable: required bundled Chromium is not configured.` |
| PDF | `… Install the 'pdf' extra (pip install '.[pdf]') and restart Odin.` | `… The required bundled dependency is unavailable; repair the desktop installation.` |
| Search models | (ambient model cache) | `no bundled embedding model roots configured` / `bundled embedding model unavailable: {details}` |
| Knowledge import | `file/directory not in allowed import roots: {SAFE_IMPORT_ROOTS}` | `{kind} not in allowed import roots: {admitted roots}` |
| Skill API text | "channel" in the SkillContext docstrings and the `search_history` result field `channel_id` | "conversation" and `conversation_id`; `list_hosts`: "List host aliases admitted by the authenticated owner context." |
| Settings text | `See config.yml comments for examples.` / `Let admins proceed past a governor refusal.` | `See the desktop configuration documentation for examples.` / `Let the authorized owner proceed past a governor refusal.` |

**Standing rule (D19).** Claude approves mechanical wording swaps of this kind without asking: "channel" becoming
"conversation", admin or tier wording becoming owner wording, and install hints becoming bundled-app wording. Anything
that changes what Odin is told to do still goes to Aaron.

**Not approved here, and not reachable in Phase 1** (no model request path is wired yet): the temporary "unavailable
until Phase 2" and "not implemented" gates, the readiness backstops, and the results that lost an attachment or URL
because there is no delivery yet. Phase 2 must remove each one and restore Odin's behaviour, or bring it for approval
under the rule above.
