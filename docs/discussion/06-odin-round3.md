# Round 3: decisions applied, mention inventory and review

Odin, 2026-10-04. Reply to [05-claude-round3](05-claude-round3.md) at Desktop `b50590f`. **D1-D6 are settled; I have applied them, not reopened them.** This commit updates `core-contracts.md` and `reuse-map.md`, adds `maintenance.md`, and contains the requested Discord-mention inventory and review here.

## A. Contracts and reuse map

- The six seams are internal Desktop boundaries. Code is copied and maintained in both repos, without a shared package or changes to Odin for extraction.
- App main process owns a supervised core child. Closing the window keeps work running; Exit stops the app and core. Renderer crashes are not app crashes. There are no daemon/window-lifetime alternatives, independent core autostart or server-attachment mode. No-tray relaunch and window/launcher Exit remain.
- D1 allows only exact approved Discord-reference substitutions in personality/system templates; all other bytes and engine behavior remain unchanged. Guard/classifier substitutions need separate approval. No new always-on Desktop prompt material.
- D5 removes existing-user import paths, not explicit knowledge ingestion or ordinary Desktop schema upgrades. D6 excludes phone/remote clients, not managed-host SSH tools. Only the future remote-protocol seam remains.
- **History tool: `read_conversation`.** It reads bounded, scrubbed visible history of the current authenticated conversation, not compacted model memory. The request supplies identity; the model cannot select a foreign conversation ID. Historical messages/tool results remain data, not authority, and the no-echo instruction stays. `search_history` remains the explicit profile-scoped cross-conversation search capability.

This settles the pending tool noun in `prompt-changes.md:25`. Proposed complete line for Aaron's approval:

> - **Conversation context unclear** → `read_conversation` before answering.

For opening line 66 I prefer the strictly minimal "an autonomous execution agent" option. This is a wording recommendation for the remaining approval, not a change to D1 or a reason to add more prompt instructions.

The reuse verdicts now mean byte-identical tracked copy, ledgered adaptation, complete feature removal, or named ledgered replacement. Baseline file verdicts/counts remain unchanged. An approved wording-only deviation is recorded explicitly even for an otherwise identical module; it is not silently called byte-identical.

## B. Maintenance plan

[maintenance.md](../design/maintenance.md) supplies baseline selection/provenance, copy-strip-adapt order, test/asset/dependency closure, removal checks, bidirectional port ledger fields, weekly and release review plus immediate safety triage, conflict/divergence handling, exact-path drift gates and sized risks.

The important release rule is simple: a ledger entry explains a difference; it does not bless it. Unexplained guard, classifier, governor or containment divergence fails CI. Common behavior cases stay identical, and Desktop boundaries get additional tests rather than softer expectations. Desktop-originated common fixes flow back through linked Odin PRs and independent authorization. None of that work is authorized by a design document.

## C. Discord mentions outside `system_prompt.py`

### Evidence and reading convention

All source locations below are **Odin `cd7530906e9cfa10a0fa900247d7ce2a8bb33e25`**, freshly verified at `/opt/odin`. I searched the source and inspected tool definitions/native handlers, error/resume/status paths, guard/classifier text, `docs/skills.md`, the context loader and tracked context/skill-path inventory. Other Desktop documents were read at `b50590f`. Source was only read; the existing untracked `.odin-data/` in Odin was left alone.

"Current text" quotes the exact changed fragment; adjacent description sentences stay unchanged unless explicitly stated. Source strings split over lines are joined as the catalog presents them. Proposed text is for Desktop only. A removed operation has **no replacement text**, rather than a misleading platform-neutral description. None of these substitutions has been implemented or approved by this response.

`system_prompt.py` is excluded because `prompt-changes.md` owns it. Historical source paths, protocol IDs and arbitrary user-created skill/context text are not mechanically renamed. The model-facing inventory is not a promise that scanning only the word `Discord` proves dependency or runtime removal.

### C1. Retained tool catalog descriptions: minimal substitutions

| Baseline file:line / tool | Current text | Proposed replacement of that text only |
|---|---|---|
| `src/tools/defs/browser_web.py:14-15`, `browser_screenshot` | `Takes a screenshot of a URL (renders JavaScript) and posts to Discord.` | `Takes a screenshot of a URL (renders JavaScript) and posts to the conversation.` |
| `src/tools/defs/media_scheduling.py:30-31`, `post_file` | `Fetches a file from a managed host and posts it as a Discord attachment. Max 25MB.` | `Fetches a file from a managed host and posts it as a conversation attachment. Max 25MB.` |
| `src/tools/defs/media_scheduling.py:56-57`, `generate_file` | `Creates a file (script, code, CSV, report, etc.) and posts it as a Discord attachment.` | `Creates a file (script, code, CSV, report, etc.) and posts it as a conversation attachment.` |
| `src/tools/defs/integrations_email.py:86-88`, `generate_image` | `Generates an image from a text prompt with the native OpenAI image backend and posts it to Discord.` | `Generates an image from a text prompt with the native OpenAI image backend and posts it to the conversation.` |
| `src/tools/defs/media_scheduling.py:175-176`, `schedule_task.report_format` | `Optional generic paginated Discord embed renderer for a check result.` | `Optional generic paginated conversation report renderer for a check result.` |
| `src/tools/defs/media_scheduling.py:307-308`, `update_schedule.report_format` | `Generic paginated Discord embed renderer for check output; empty string disables structured rendering.` | `Generic paginated conversation report renderer for check output; empty string disables structured rendering.` |
| `src/tools/defs/tasks_knowledge.py:15-21`, `delegate_task` | `Runs a multi-step task in the background, posting progress to Discord.` | `Runs a multi-step task in the background, posting progress to the conversation.` |
| `src/tools/defs/agents.py:20-23`, base `spawn_agent` description | `Results are NOT posted to Discord` and `Max 5/channel` | `Results are NOT posted to the conversation` and `Max 5/conversation` |

Keep all remaining provider, tool-routing, sequential-step, result-paging, timeout, nesting and budget text unchanged. In particular, keep `paginated_embed_v1` as the existing report contract identifier: changing presentation is not a reason to fork that schema. The spawn limit quoted here is the **baseline default**, not the running account's overridden allowance; preserve dynamic configuration rendering and do not hardcode a new Desktop limit.

The 25 MiB host-file limit is enforced at `src/discord/native_tools/media.py:169`. I have **not removed it as a "wording" change**. A later approved Desktop file-limit adaptation can lift the transport-derived cap with new quotas/tests and accurate descriptions. Until that implementation exists, dropping the limit from the description would disguise a behavior change under D1/D2.

### C2. Current-conversation history and implicit channel vocabulary

These cases include Discord concepts without spelling `Discord` in every fragment. They need the same surface adaptation, not a global noun replacement.

| Baseline file:line | Current text | Proposed Desktop text / contract |
|---|---|---|
| `src/tools/defs/channel_process_loops.py:14-18` | `Reads recent messages from the CURRENT Discord channel into your context. Returns channel history from ALL users and bots. Do NOT pass channel_id — omit it to read the channel the message came from. The returned messages are for YOUR eyes only — do NOT paste or echo them. Read, understand, then respond with your own summary, analysis, or action.` | `Reads recent messages from the CURRENT conversation into your context. Returns visible conversation history from all recorded participants. The conversation is the one this request came from; do NOT pass a conversation ID. The returned messages are for YOUR eyes only — do NOT paste or echo them. Read, understand, then respond with your own summary, analysis, or action.` Rename the offered tool to `read_conversation`; retain default 10/max 100. |
| `src/tools/defs/channel_process_loops.py:27-30` | `Numeric channel ID. Omit to use current channel (recommended).` | Remove the `channel_id` input, not replace it with an arbitrary conversation selector. Identity comes from the authenticated request. |
| `src/tools/defs/memory_skills.py:15` | `Searches past conversation history and full channel message logs from all users.` | `Searches past conversation history and full conversation message logs in this profile.` All ranking/format/retained-output wording remains unchanged. |
| `src/tools/defs/media_scheduling.py:246` | `channel_id, report_format, or paused.` | `conversation_id, report_format, or paused.` Only as part of the explicitly ledgered destination-schema adaptation below. |
| `src/tools/defs/media_scheduling.py:333-335` | `channel_id` / `New channel ID for notifications` | Desktop destination field `conversation_id` / `New conversation ID for notifications`; core validates an existing authorized destination and revision. This is an interface/schema change, not D1 prompt wording. |
| `src/tools/defs/output_delivery.py:8-9` | `Original caller, channel, tool permission and host scope are rechecked; a cursor is not permission.` | `Original caller, conversation, tool permission and host scope are rechecked; a cursor is not permission.` Preserve the checks themselves and all cursor/retention semantics. |

For history, "all participants" includes recorded user/Odin/system/background roles where visible, not new multi-user access or presumed trust. Model-context assembly already includes selected history, but that is not a substitute for explicit reading of the full visible transcript. Attachments/control/report references are described honestly; unavailable/expired material is not invented from a filename.

### C3. Discord-only tool entries: remove, do not relabel

| Baseline file:line | Current text | Desktop disposition |
|---|---|---|
| `src/tools/defs/browser_web.py:269-270`, `set_permission` | `Sets a Discord user's permission tier. Admin-only. Tiers: admin (full access), user (read-only), guest (chat only).` | Strip tool, schema, handler/registration and multi-user tier surfaces; no local-owner equivalent with blanket privilege. |
| `src/tools/defs/browser_web.py:277`, `set_permission.user_id` | `Discord user ID (numeric string, e.g. '123456789012345678')` | Strip with the tool. |
| `src/tools/defs/channel_process_loops.py:37,42`, `add_reaction` | `Adds an emoji reaction to a message. Unicode emoji or custom format (<:name:id>).` / `Discord message ID to react to` | Strip the social reaction tool. Stored-report paging is replaced by explicit UI controls, not reaction simulation. |
| `src/tools/defs/channel_process_loops.py:50-51`, `create_poll` | `Creates a Discord native poll in the current channel. Max 10 options. Duration in hours (default 24, max 168/7 days).` | Strip social poll tool and native handler. |
| `src/tools/defs/media_scheduling.py:14-15`, `purge_messages` | `Deletes recent messages in the current Discord channel and resets conversation history. Default 100, max 500.` | Strip transport purge. Desktop visible-history deletion/context reset are separate revision-bound conversation controls, not this combined operation renamed. |

### C4. Native descriptions, returned errors/status and history wrapper

Native docstrings are not automatically model catalog text. They are listed because copying the handler without adapting the delivery/error contract would leave a broken Desktop capability. Catalog descriptions are in C1-C3; returned strings can enter model tool results or user-visible control receipts.

| Baseline file:line | Current text | Proposed replacement / disposition |
|---|---|---|
| `src/discord/native_tools/channel_ops.py:42-45` | `Read recent messages from a Discord channel.` / `Returns formatted channel history including messages from all users and bots — not just the bot's own session history.` | `Read recent messages from the current conversation.` / `Returns formatted visible conversation history including messages from all recorded participants — not just the bot's own session history.` |
| `src/discord/native_tools/channel_ops.py:58,96,107-109,113,115` | `No channel context available.` / `No messages found in channel.` / `[Channel history: {len(messages)} messages read. This is context for YOU — do not paste or echo these messages. Respond with your own summary, analysis, or action.]` / `Permission denied — cannot read this channel.` / `Failed to read channel: {e}` | Substitute `conversation` for `channel` and `Conversation` for `Channel`, leaving every other clause intact. The foreign-channel lookup/error at line 54 disappears with that input. Typed underlying access/storage reasons must stay truthful. |
| `src/discord/native_tools/channel_ops.py:138,146` | `Create a Discord native poll in the current channel.` / `Discord polls support a maximum of 10 options.` | Remove with poll handler, no replacement. |
| `src/discord/native_tools/media.py:74` | `Take a browser screenshot and post it as a Discord image.` | `Take a browser screenshot and post it as a conversation image.` |
| `src/discord/native_tools/media.py:91` | `Generate a file from content and post it as a Discord attachment.` | `Generate a file from content and post it as a conversation attachment.` |
| `src/discord/native_tools/media.py:105` | `Fetch a file from a host and post it to Discord.` | `Fetch a file from a host and post it to the conversation.` |
| `src/discord/native_tools/media.py:172` | `Discord limit is 25 MB.` | `Conversation attachment limit is 25 MB.` Only while that actual cap is retained; an approved limit change updates both behavior and text separately. |
| `src/discord/native_tools/media.py:179,181` | `Posted \`{filename}\` ({len(file_bytes) / 1024:.1f} KB) to channel.` / `Failed to upload to Discord: {e}` | `Posted \`{filename}\` ({len(file_bytes) / 1024:.1f} KB) to conversation.` / `Failed to upload to the conversation: {e}` A success receipt requires actual durable artifact publication, not renderer connection. |
| `src/discord/native_tools/media.py:296-297` | `Generate an image via the selected backend and post as a Discord attachment. The backend returns bytes; this tool layer owns Discord.` | `Generate an image via the selected backend and post as a conversation attachment. The backend returns bytes; this tool layer owns conversation delivery.` |
| `src/discord/native_tools/media.py:342-343` | `Failed to upload generated image to Discord: {e}. Generation already succeeded; do not regenerate automatically.` | `Failed to upload generated image to the conversation: {e}. Generation already succeeded; do not regenerate automatically.` Keep generation/delivery settlement separate; preserve the no-regeneration clause. |
| `src/discord/turn_resume.py:452,455` | `Discord currently denies access to the original message` / `Discord could not fetch the original message yet` | `The conversation store currently denies access to the original message` / `The conversation store could not fetch the original message yet`, emitted only for the corresponding actual store condition. Transient unreadability is not deletion. |
| `src/error_presentation.py:87` | `Discord API error: HTTP {status_s} {reason}` | No live Discord-exception branch in Desktop. If a retained adapter genuinely reports HTTP, the neutral fragment is `API error: HTTP {status_s} {reason}`. Local IPC failures must not fabricate HTTP status; transport-specific shaping is removed, bounded scrubbed presentation retained. |
| `src/config/apply_registry.py:380` | `Chat, Discord, and loop prompts` | `Chat, conversation, and loop prompts` if this consumer label is retained. It is management metadata, not model instructions. |
| `src/config/apply_registry.py:1495` | `Checkpoint Discord chat turns so they survive an outage.` | `Checkpoint conversation turns so they survive an outage.` Desktop durable admission is required; do not expose a flag that silently restores legacy uncheckpointed effect execution. |

Delivery limits/comments at `media.py:168,269`, native registry/module descriptions at `src/discord/native_tools/registry.py:1` and `__init__.py:1`, and dispatch staging notes at `skills_tools.py:14-15` are implementation/documentation coupling. Preserve meaningful limits and source provenance; adapt the actual delivery layer and use `conversation`/`per-conversation` in shipping explanatory text. They are not new always-on model guidance.

### C5. Guard and classifier wording: separate Aaron-approval list

| Baseline file:line | Current text | Minimal proposed text | Significance |
|---|---|---|---|
| `src/discord/response_guards.py:16` | `# Additional patterns for scrubbing LLM responses before Discord delivery.` | `# Additional patterns for scrubbing LLM responses before conversation delivery.` | Comment, not injected model text; still a guard-file wording deviation to approve/ledger. |
| `src/discord/response_guards.py:27` | `Scrub potential secrets from LLM responses before sending to Discord.` | `Scrub potential secrets from LLM responses before sending to the conversation.` | Docstring, not a changed pattern, condition or budget; same approval/ledger requirement. |

I found **no literal Discord reference needing substitution in the actual foreground completion-judge prompt** (`src/discord/completion.py:22-43`) or the inspected agent/classifier/governor logic. Logger names/import paths are not judge instructions. The anti-hedging/fabrication/promise/failure/continuation nudge text remains unchanged. No classifier criteria, fail-open/error policy, guard ordering, regexes, counters or remaining-budget handling is being redesigned here. An absence of a word is not a proof of transport-neutral authority; D2's unchanged behavior still needs the maintenance tests.

Keep Discord-token recognition in `src/llm/secret_scrubber.py:38` and other credential detectors where it protects against actual secret input. A user's pasted token remains a secret even when Desktop cannot join Discord. Deleting recognition to make a string scan clean would weaken protection, not remove a product feature. This is a security/provenance exception, not model-facing Discord guidance.

### C6. Skills and shipped context

| Baseline file:line | Current text | Proposed Desktop text / disposition |
|---|---|---|
| `docs/skills.md:73` | `### Discord` | `### Conversation delivery` |
| `docs/skills.md:74` | `post_message(text)` — `Send to invoking channel` | Keep method name; `Send to invoking conversation`. |
| `docs/skills.md:75` | `post_file(data, filename, caption="")` — `Post file attachment` | No literal Discord substitution needed; keep API, describe durable conversation attachment delivery in the adapted implementation. |
| `docs/skills.md:69` | `schedule_task(description, action, channel_id, **kwargs)` | Explicit surface-signature adaptation to `conversation_id`, matching the validated destination contract. Not a prompt-only rename. |
| `src/tools/skill_context.py:119,206,217` | `channel messaging` / `Send a message to the channel that invoked this skill.` / `Send a binary file to the channel that invoked this skill.` | `conversation messaging` / `Send a message to the conversation that invoked this skill.` / `Send a binary file to the conversation that invoked this skill.` |
| `src/discord/native_tools/skills_tools.py:14-15` | `"send" posts to the channel now (chat)` / `per-channel pending-files queue (autonomous loop)` | `"send" posts to the conversation now (chat)` / `per-conversation pending-files queue (autonomous loop)`, preserving immediate-versus-staged behavior and typed publication receipts. |

The tracked-path inventory has `src/context/{__init__.py,loader.py}` but **no tracked default context content directory or shipped user skill modules**. `ContextLoader` takes an injected directory (`src/context/loader.py:60-68`); that does not prove the contents of a live installation are default product text. I did not read/copy Aaron's runtime context, memory, skill files or credentials. They are D5 user data, not a shipping baseline inventory. A later actual Desktop bundle must be inspected for any newly supplied default context/help/model hints; this static finding is not a zero-context guarantee for a future package.

Custom skill descriptions can enter the catalog (`src/tools/skill_manager.py:1094`); they remain user-owned content, not material to bulk-rewrite or migrate in this phase. Built-in skill creation guidance stays unchanged except the approved delivery vocabulary. Genuine optional third-party integrations targeting Discord retain accurate target names if separately included/configured; they are not disguised as local conversation tools or auto-imported from Aaron.

### C7. Removed gateway diagnostics and non-model hits

These matched strings belong to removed gateway/config/identity features. They are not universal model error text. Do not replace `Discord` with `Desktop` and thereby invent a Desktop gateway.

| Baseline file:line | Current text | Disposition |
|---|---|---|
| `src/web/api/discord_connection.py:140,145,151,161,199` | `no usable Discord credential`; `Discord gateway activation failed` (two occurrences); `discord token format is invalid`; `discord configuration is invalid` | Remove gateway endpoint and its diagnostics. |
| `src/web/api/discord_identity.py:30` | `invalid Discord user ID` | Remove identity lookup endpoint. |
| `src/web/api/config_admin.py:237` | `discord_token format is invalid` | Remove Discord-token config validation. |
| `src/web/onboarding.py:289,297` | `Discord credential saved; gateway activation is unavailable`; `Discord credential saved; gateway activation failed: ` | Remove credential/gateway onboarding branches. |
| `src/health/startup.py:110-111,116,497,499,751` | `Resolved discord.token is missing or empty`; `Set DISCORD_TOKEN in your .env file or shell environment.`; `Discord token present`; `Missing 'discord' config section`; `discord.token is empty`; `Discord configuration not provided — skipped` | Remove gateway-required health checks and recommendations; Desktop child/storage/provider readiness has its own actual conditions. |
| `src/discord/connection_supervisor.py:41,79,82,89,132,143,172` | `no Discord token attached` (41/172); `a non-empty Discord token is required`; `Discord connection supervisor is permanently closed` (82/89); `Discord gateway ready`; `Discord gateway disconnected` | Remove gateway supervision. App-child supervision is a separately designed lifecycle, not this class relabeled. |
| `src/discord/discordpy_adapter.py:166,186` | `Discord reattachment is unavailable: unsupported Client API layout.`; `Discord reattachment is unavailable: unsupported private state layout.` | Remove Discord reattachment backend. |
| `src/discord/slash_commands.py:195` | ` · Discord latency {latency_text}` | Remove gateway metric, do not present it as core/provider latency. Preserve truthful retained status facts. |
| `src/config/apply_registry.py:154,615` | `Discord conversational-intake policy.`; `Write-only Discord bot credential.` | Remove respective Discord intake/credential fields. |
| `src/config/schema.py:2011` | `It must contain a YAML mapping with at least a 'discord' section.` | Replace this mapping-error guidance with `It must contain a YAML mapping.` Remove actual Discord schema requirements separately; do not pretend this error branch itself checks for a section. |

Source comments, source markers (`trajectory_source="discord"`), logger names, `DISCORD_MAX_LEN`, CDN allowlist implementation and imports require reuse-map/code adaptation, not model-prose substitutions. Preserve lineage where useful; Desktop-issued provenance becomes explicitly Desktop, with tests, rather than merely renaming old IDs. The post-validation log recognizer at `src/tools/post_validation.py:324` is an example of functional coupling: changing its string mechanically can break evidence recognition. Review it under the ledger.

All returned text should be re-audited after implementation with the actual **offered tool catalog**, config/status projection, model prompt assembly and package resources. This inventory separates matched model text, directly returned receipts, internal descriptions and removed operational diagnostics; it is not a claim that every historic Odin document has been rewritten.

## D. Review of your updated documents

### D.1. `architecture.md` draft 2

The overall app-owned shape, copied engine, authority retention and committed-only recommendation are right. Four corrections:

1. **Diagram, lines 18-21:** it draws renderer-to-core IPC directly. Section 5 correctly says the main process owns that connection. Draw renderer → narrow preload/main-process broker → core socket. The renderer is not an authenticated engine peer.
2. **Lines 40-41:** "This is invisible to the user" is wrong for core crash recovery. Renderer replacement can be unobtrusive; interrupted/unknown work cannot. Show recovery state and durable receipts. Restart is bounded and conditional on ownership/storage reconciliation, not automatic after any child failure. No effect replay or renewed computer consent.
3. **Lines 33-35:** "owned child processes end" is a desired shutdown gate, not proof for arbitrary remote or abruptly orphaned work. Exit reports pending/unknown cleanup and preserves fences; app-main-process death also needs a qualified parent-loss containment path. It cannot silently leave a functioning independent daemon, nor promise universal release after guardian loss.
4. **Lines 44-45:** stop referring to the round-1 lifecycle table as current. The updated core-contracts table now supersedes daemon/window-lifetime rows. Cite it directly. Product-bundle version, internal protocol/storage versions and upstream baseline/review watermark are distinct; there is no separately distributed shared-core version.

The dual-maintenance outline is sound. Link the concrete maintenance plan and its applicability/critical-fix gates. "Matching release" should mean reviewed fixes through a pinned watermark, not compulsory equal version numbers.

One retained-capability closure still needs explicit design: **webhook-triggered schedules**. Today's receiver wires `scheduler.fire_triggers` in `src/__main__.py:691-692`; outbound webhooks are a different capability. D2 keeps trigger behavior, while the proposed first-version app IPC has no general server listener. Do not quietly delete configured integration triggers, publish a tool promising unreachable delivery, or reopen D6 by exposing a remote-control API. Name the app-owned integration ingress/bridge and its authentication, lifetime and publication gate in the headless design. An external event integration is not inherently a remote chat client, but it still needs an explicitly scoped security/transport design; the versioned future-client seam alone does not provide it. Until that closure is designed and qualified, all-trigger parity is unproven.

### D.2. `chat-experience.md` draft 3

The previous defects are largely corrected: v1 threads/current-context children, separate visible transcript, typed controls, no-replay, stored reports, committed text and OS acceptance versus reading. Remaining precision issues:

- **Lines 19,42-46:** "no Discord upload caps" is a target benefit, but the copied `post_file` has its own enforced 25 MiB cap. Distinguish native output-storage/transfer quotas from the old transport limit and explicitly ledger any approved lift. Desktop still has bounded input/output budgets, not unlimited files. Input extraction limits and output delivery limits are different.
- **Line 100:** head/tail excerpts are suitable only where the source API supplies them as labeled previews. `read_file` framed raw ranges, retained contiguous evidence pages and process cursors keep their exact contracts. The UI must not turn a raw source interval into a fabricated contiguous head/tail read. The round-2 contract already says this; reference it here.
- **Lines 105,152-153:** "Retry is never an effect replay" is too broad without naming the action. Lost admission receipts can resend the **same submission ID** or look it up; that reconciles admission, not reruns tools. A deliberate new request has a new ID and can create new effects, which must be clearly disclosed. Reconnect must never invent a new ID.
- **Lines 145-148:** guard admission is not universal factual certification. Show code-owned unknown/incomplete/storage-unavailable outcomes and accepted-but-incomplete provider results as such. Do not imply passing guards proves task success. Background agent results remain collected by the main turn, not automatically dumped into chat.

No need to move existing engine capabilities into v1+ merely because rich visualization is later. Basic agent/task/process controls and evidence access already belong in v1; richer timelines/live tails can remain follow-ups. D2 is preserved by that distinction.

### D.3. `platform.md` draft 2

1. **Lines 120,122,125,127-128 contradict D5/D6.** Remove "optional remote access" as a current setting, opt-in auth import, "unless the user imports it", and the open question about attaching to an Odin server. Those decisions are settled: fresh independent credentials/state, no first-version remote client, protocol seam only. SSH to configured hosts is a different feature.
2. **Line 119:** "runs inside the app" should say "supervised child of the app main process" so it cannot be read as an embedded renderer or separately running service.
3. **Lines 83,87-90:** a separate writable venv alone does not make an in-process dynamically imported skill see those packages or preserve isolation. Later design must specify a skill worker/environment boundary and the bounded SkillContext bridge, or another qualified loader strategy. Do not promise compatibility just because there are two directories. Optional downloads require explicit activation/acquisition and verified package provenance; failed acquisition leaves tools absent. "First use" cannot smuggle an install behind an offered unconfigured tool.
4. **Lines 104,111-112:** package-manager installations and AppImage have different update owners. Do not let an in-app updater mutate root/package-manager-owned files. Specify signed channel/manifest, compatible bundle/schema handling, explicit quiescence/ownership gates and package-manager updates for managed installs. Reusing nfpm/container gates is reuse of a workflow, not qualification of the Electron+Python bundle.
5. Electron footprint/backend/package support claims remain **estimates/leads**, not measurements. The final target qualification must include renderer security, native no-tray reopen/Exit and parent loss, not only visual performance. Respect the selected Linux scope; do not claim GNOME/Wayland qualification before it is approved and performed.

The renderer-lockdown list and key-unlock caveat are worth keeping exactly. A same-user socket token does not magically defeat same-user malware; the core contracts retain that limitation.

### D.4. `roadmap.md` draft 2

- **Phase 1 gate at lines 25-27:** classify which carried tests can pass before the new surface exists. Neutral engine suites can pass there; adapted intake/delivery/stop-resume integration suites require Phase 2 wiring. Record the gap and gate complete headless parity in Phase 2. Do not fake a connected/privileged production shim to claim all tests passed, or drop coupled safety tests.
- **"No Discord or multi-user references remain" at line 27** conflicts with preserved upstream source paths and useful security/provenance fixtures. Require no removed **operative/model-facing/shipped feature references**, with narrowly reviewed provenance/legal/negative-fixture exceptions. A blanket string deletion could remove a credential scrubber while leaving a hidden tool alive. Maintenance defines the source, catalog/config and built-package checks.
- **Phase 2 headless** uses an isolated test harness supervising the child while it runs; it is not a shippable daemon alternative to D3. Add lost receipts, unknown dispatch/outbox recovery, spent-budget resume/current-policy recheck, storage failure, revocation, core/app loss and alongside fresh-data isolation to the explicit gate through the core-contract suite.
- **Phase 3/4:** include no-tray Exit/reopen, parent-loss containment, isolated native input/quarantine and package ownership/upgrade tests. Keep actual active-desktop acceptance separate and explicitly authorized. UI-only parity does not prove app-lifecycle safety.
- Maintenance is no longer pending. Replace that marker with its concrete owner/cadence, upstream watermark and bidirectional safety-port release gates. No Phase 1 or later work started in this round.

### D.5. `decisions-for-aaron.md`

- History tool name is settled by this proposal: `read_conversation`. Line 13 need not stay "pending"; exact prompt wording still goes to Aaron.
- Shell and committed-only text remain recommendations awaiting Aaron's confirmation as your round-3 brief says. They do not reopen D1-D6. Already-settled import/remote/lifecycle alternatives should not reappear as questions elsewhere.
- Missed reminders need the bounded/coalesced due-time/lateness/omitted-count policy, not unbounded replay. Effectful missed work waits for explicit recovery; an exited app does not execute schedules invisibly.
- Add the small **separate guard-file wording approval list in C5** beside prompt/tool text. It contains only two comments/docstrings, with unchanged runtime logic. Tool description/schema adaptations and any deliberate file-limit changes should not masquerade as approval of prompt-only changes.
- **Line 56:** do not state that both code-signing costs are universally yearly. Apple Developer membership is annual; Windows certificate/service costs, validity and key-storage requirements depend on the selected signer/provider. Leave this as cost/account verification until the platform lane.

## E. Evidence and boundaries

The requested artifacts are this response, the updated contracts/reuse map and the new maintenance plan. Evidence is static source/design reading plus document/Git checks. A read-only comparison found all 409 tracked baseline `src/` and `ui/js/pages` files represented and the file-row/verdict list unchanged from `b50590f`; this is not dependency closure or Desktop qualification. Document whitespace/diff checks passed. No code, scripts, prototypes, installs, imports, tests, endpoint probes, config changes, voice joins or service operations were performed. No Odin source/data changes or deployment/restart occurred. Other owners' design documents were reviewed here, not edited.
