# Prompt changes for Odin Desktop

Owner: Claude. Draft 1, 2026-10-04. This implements decision **D1**: Odin Desktop's prompt does not mention Discord.

**The rule.** Only the Discord references change. Every other byte of the personality presets and system templates
stays identical to Odin's. Aaron approves the exact wording below before any build. Tool descriptions that mention
Discord are covered separately: Odin inventories them in round 3.

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
| 97 (Tool Routing) | `- **Discord channel context unclear** → \`read_channel\` before answering.` | **Depends on the tool decision.** If the desktop keeps a history-read tool, the line becomes `- **Conversation context unclear** → \`<tool>\` before answering.` with that tool's name. If no such tool exists, the line is removed. |
| 105 (Rule 2) | ``2. Keep responses concise — this is Discord. Code blocks for output. One update per task, not per tool call. Fenced code blocks (```) MUST start at column 0 — indented fences render as inline code in Discord.`` | ``2. Keep responses concise. Code blocks for output. One update per task, not per tool call. Fenced code blocks (```) MUST start at column 0.`` |

## Chat-routed system template

| Line | Today (Odin) | Proposed (Odin Desktop) |
|---|---|---|
| 116 (opening) | `You are {bot_name}, an AI assistant Discord bot.` | `You are {bot_name}, an AI assistant.` |
| 131 (Rule 2) | `2. Keep responses concise — this is Discord, not a document.` | `2. Keep responses concise — this is a chat, not a document.` |

## Notes for approval

- **Line 66.** The proposal adds the fact that Odin runs on the user's own computer. That is accurate and useful
  context for an executor. The strictly minimal alternative is `You are {bot_name}, an autonomous execution agent.`
- **Line 95.** It keeps today's behaviour: code goes to files rather than inline. On Discord, part of the reason was the
  2,000-character limit, which the desktop doesn't have. Changing the behaviour itself would be a separate decision. D2
  says he works the same, so the proposal keeps it.
- **Line 105.** The column-0 fence rule is kept, because it is harmless and keeps outputs portable. Only its Discord
  justification is dropped.
- **Your own custom personality text** (in your live config) is user data, not shipped text. It is out of scope here
  (D5).
