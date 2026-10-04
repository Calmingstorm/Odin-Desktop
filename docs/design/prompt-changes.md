# Prompt changes for Odin Desktop

Owner: Claude. Draft 2, 2026-10-04. This implements decision **D1**: Odin Desktop's prompt, and the rest of its
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
| 66 (opening) | `You are {bot_name}, an autonomous execution agent on Discord.` | `You are {bot_name}, an autonomous execution agent running on the user's computer.` |
| 95 (Tool Routing) | `- **Code attachments** → \`generate_file\`. Never write code inline in Discord.` | `- **Code attachments** → \`generate_file\`. Never write code inline in chat.` |
| 97 (Tool Routing) | `- **Discord channel context unclear** → \`read_channel\` before answering.` | `- **Conversation context unclear** → \`read_conversation\` before answering.` The desktop history tool is `read_conversation` (Odin, round 3): it reads the current conversation's visible history only. |
| 105 (Rule 2) | ``2. Keep responses concise — this is Discord. Code blocks for output. One update per task, not per tool call. Fenced code blocks (```) MUST start at column 0 — indented fences render as inline code in Discord.`` | ``2. Keep responses concise. Code blocks for output. One update per task, not per tool call. Fenced code blocks (```) MUST start at column 0.`` |

## Chat-routed system template

| Line | Today (Odin) | Proposed (Odin Desktop) |
|---|---|---|
| 116 (opening) | `You are {bot_name}, an AI assistant Discord bot.` | `You are {bot_name}, an AI assistant.` |
| 131 (Rule 2) | `2. Keep responses concise — this is Discord, not a document.` | `2. Keep responses concise — this is a chat, not a document.` |

## Notes for approval

- **Line 66.** There are two candidates:
  - Claude's: "…an autonomous execution agent running on the user's computer." It adds an accurate fact.
  - Odin's: "…an autonomous execution agent." It is the strictly minimal change.

  Aaron picks.
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

Every "Discord" or "channel" in delivery receipts and errors becomes "conversation", with every other clause intact.
Examples:
- "Posted `{file}` (…) to channel." becomes "…to conversation."
- "Failed to upload to Discord: {e}" becomes "Failed to upload to the conversation: {e}".
- "…Generation already succeeded; do not regenerate automatically." keeps its no-regeneration clause.
- The resume messages "Discord currently denies access…" and "Discord could not fetch…" become "The conversation store
  …", and are emitted only for the matching store condition.
- "Discord API error: HTTP…" is removed. Where an adapter genuinely reports HTTP, it becomes "API error: HTTP…".

The full list is in Odin's round-3 file (sections C2 and C4).

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
