# Settings

Open **Settings** in the top bar or press **Ctrl+,**. Use **Back to chat** to leave. The readiness banner can open **Models and providers** or **General** directly; see [First run](first-run.md).

**Draft watermark:** Linux candidate source at `main@0b7d596f7e870d06699722f151c4d9837c5433f1`, not a qualified release. [README](../../README.md) records the reviewed upstream baseline and source watermarks; passing tests do not prove an identical engine. Sections labeled **pending: #N** describe only that pinned, unmerged source, not controls guaranteed in a main candidate or a tested composition of all branches. [The release checklist](../release/linux-v1-checklist.md) keeps P4.5, P4.6 and Aaron's approvals explicit.

For an isolated candidate, open a section first and read its availability message before changing anything. **Unavailable** means that feature cannot currently be used, not that it contains zero entries. A saved switch cannot create a missing service. Never replace a real-core unavailable panel with fixture results and call it working.

## Saving and running are different

Core fields show a label, configuration path, explanation and apply state. There is no single “save all Settings” button:

- A toggle or dropdown saves when you change it.
- An ordinary single-line typed value saves on **Enter** or when you leave the field. A multiline/list/object field saves when you leave it; text lists use one item per line, other structures use JSON. Read the description rather than guessing the format.
- A secret uses its own **New value → Save** password field. Its value clears after submission, even if the save fails. Read the receipt/error, not the empty input.
- Management panels such as Personality, Hosts, Memory and Timeouts have their own named **Save** controls.
- **Reset to default**, when offered, removes an ordinary override. It is not a global reset, account removal, or data wipe. Some fields are read-only and say **Changed with the controls above**.

| Label | Meaning |
| --- | --- |
| **Saved …** | That field's save was acknowledged. It does not by itself establish the running value. |
| **Applied** | The core reports that this field has applied. Read whether it affects live reads or only new work. |
| **Applies after a restart** | The saved choice is waiting for a supported app/core restart. Closing the window is not a restart. |
| **Not in use** | The value is dormant for the current configuration. |
| **Invalid** | The value is invalid; inspect the error. |
| **Running value differs** | The saved and running choices differ. The field shows **Saved: … Running: …**. |
| **Running value unknown** | The core cannot establish the effective value. Do not assume it equals the saved one. |

Saving a provider or host may involve adoption/testing and fail separately from storage. On a rejected change, correct the error. On an **unknown** outcome, consult [Recovery](recovery.md) instead of repeating the mutation or restarting to make the warning disappear. A new field read can establish current state without proving an earlier external effect never happened.

For an ordinary setting marked for restart: finish or stop work as described in [Background work](background-work.md), use **Exit Odin**, wait for shutdown, then relaunch the same candidate and profile. Check the running value again. If cleanup is unknown/quarantined, follow [Recovery](recovery.md) first; a blind relaunch is not reconciliation. [Updates](updates.md) covers compatibility when changing builds.

## The eleven sections

The navigation is defined by the app. A section such as **Other** may be hidden when the core supplies no matching fields.

| Section | What belongs there |
| --- | --- |
| **General** | App login startup/notifications; core time, learning, sessions, context and attachment settings. |
| **Models and providers** | Main/agent models, provider configuration, Codex accounts, images and model recovery. |
| **Personality** | Identity/voice presets and custom personality. |
| **Tools** | Built-in switches, parameter details, timeouts; browser, computer-use and email fields. |
| **Skills** | Custom tool management; real-core management composition is pending. |
| **MCP servers** | External tool-server configuration; real-core management composition is pending. |
| **Hosts and trust** | Managed SSH host enrollment, trust, default target and key information. |
| **Scheduled and running work** | Schedule controls and running work; real-core management composition is pending. |
| **State** | Memory, named lists, knowledge and context; search fields. |
| **Records** | Health, usage, audit, logs and turn records; logging/observability settings. |
| **Other** | Core-supplied fields not assigned to the other sections. |

### General

Under **This app**:

- **Start Odin when you log in** is opt-in and initially **off**.
- **Desktop notifications** controls notification delivery. **Show message previews in notifications** is initially **on**; switch previews off for a shared/visible desktop.
- **Quiet hours**, **Quiet hours start** and **Quiet hours end** control quiet times. Muting one conversation uses its **⋯** menu, not a new Settings list editor.

These controls are saved by the app and remain distinct from core settings. Closing the window leaves work running; **Odin → Exit Odin** in the app menu, **Ctrl+Q**, the tray's **Exit Odin**, or the packaged launcher's **Exit Odin** action stops the app through the shutdown path. Without a tray, reopen using the launcher to use the window Exit route. A notification shown/accepted is not proof it was seen. See [First run](first-run.md#6-closing-is-not-exiting).

The core groups below This app cover time, learning, sessions, context and attachments. Follow each field's save/runtime explanation. Conversation history is not a training job performed by Desktop, but saved history, memory and retrieved documents can become provider request context. Provider retention/training rules and network privacy are separate; do not describe this as local-only. See [Chat and results](chat-and-results.md) for attachments and retained results.

### Models and providers

Use [First run](first-run.md#2-choose-a-model-and-its-provider) for the device-sign-in, provider-key and Ollama procedures. The main model reference selects Codex (bare name), compatibility (`compat:`) or Ollama (`ollama:`); `llm_provider.active_provider` is derived, not separately editable. Only use choices supported by your configured endpoint/account. Fields exposed for auxiliary or other configuration are not evidence that those providers are usable as the main-model route.

**Agents** has separate model/thinking/selection settings. An inherited agent model, automatic selection and a concrete override are different choices. Read the field's rules and apply state; a setting affecting new agents does not change an already-running agent's captured configuration.

**Codex accounts** shows account metadata, **In use**, limit/expiry warnings and quota as reported. **Use this account**, **Label…**, and **Remove…** are separate actions. Removal stops Odin using that account; it is not deletion of the provider account. **Quota not reported yet** is unknown data, not unlimited quota. A failed quota check is not a measured remaining allowance.

Keys and account credentials are write-only. **Set** establishes presence, not valid authentication or generation success. **Keyring unavailable; saved value unknown** must not be read as “not configured.” The readiness banner's **Retry** is an explicit owner unlock request, not a silent automatic recovery. See [keyring recovery](first-run.md#3-if-the-keyring-is-locked-or-missing); a missing collection cannot be unlocked into existence. Do not import tokens or reveal them in support output.

#### Image models: follow or pin

The **Images** group's `image.openai.image_model` and `image.openai.outer_model` fields can carry an intent as well as a value:

1. Read **Follows Odin's default (…)** or **Pinned to …** beside the field.
2. While following, choose **Pin this value** if you want the current reported default retained instead of changing with future defaults.
3. While pinned, choose **Follow Odin's default** to resume following. Read the returned state and field apply label.

The outer model hosts the image tool; it is not the same as the image-generation model. Following and pinning are independent for the two fields. Editing a value and a successful save do not establish that an image was generated, that a backend is enabled, or that its credentials work.

#### Account refresh and OpenRouter administration (pending: #40)

**pending: #40** adds **Refresh sign-in** for a listed Codex account and an **OpenRouter models** panel here. Neither is a main feature at this watermark. [Pinned account UI](https://github.com/Calmingstorm/Odin-Desktop/blob/6321eec26e1c87dd5b9682e902723818a5fdda03/app/src/renderer/src/components/CodexAccounts.vue) and [pinned OpenRouter UI](https://github.com/Calmingstorm/Odin-Desktop/blob/6321eec26e1c87dd5b9682e902723818a5fdda03/app/src/renderer/src/components/OpenRouterAdmin.vue) are the sources.

On a candidate containing that reviewed change:

- **Refresh sign-in** requests the account refresh; read its receipt. It is not the first-run keyring Retry or a new **Add account** login.
- **Reload catalogue** reads core-reported models/profiles/eligibility, fetched/stale status and errors. Missing measurements are not estimates.
- Supply the provider's **Model ID (author/slug)** and optional **Provider pin (blank uses automatic routing)**; **Read endpoints** inspects them. **Select model** changes the compatibility-provider configuration. Read the selection receipt and main-model/apply state rather than assuming a reply was generated.
- **Read compatibility diagnostic** can report unhealthy or unavailable results. A diagnostic failure is not a reason to fabricate a catalogue or read keys back.

### Personality

Choose a **Preset**, inspect its identity/voice, and choose **Save**. **Custom** reveals **Name**, **Identity** and **Voice** fields; save those with the panel's **Save**. New requests use the saved personality; existing captured work may retain its previous prompt.

**Your presets** lets you save a named preset or delete one of your own with confirmation. Built-in presets cannot be edited or deleted. This changes presentation/prompt choices, not host trust, containment or execution policy.

### Tools

**Built-in tools** has **Filter tools**, each tool's on/off control, and **Parameters** to inspect its input schema. The state labels differ:

- **Available**: offered under current core readiness/policy.
- **Off**: that tool is switched off and is not offered.
- **Tools are off**: the global tools setting is off.
- **Hidden: not configured here**: the tool lacks its current runtime/configuration dependency. Switching it on does not install that dependency.

For time limits, edit **Default, in seconds**, optionally **Add a tool's own timeout**, then choose **Save timeouts**. Timeouts must be positive whole seconds. They apply to new calls; already-running calls keep their captured limits.

Browser/computer/email fields may be visible even when their real service is missing. Do not equate a visible field or saved “enabled” value with a live backend. Default main composition does not bind browser, MCP or computer-use runtime owners. Computer use still needs supported backend capabilities, explicit consent and qualified native ownership; it is not enabled by writing display identifiers alone. Read [Recovery](recovery.md) and [Accessibility](accessibility.md) for backend/acceptance limits. No new owner command approval or tool/host allowlist is added by these screens.

#### Browser/computer/skills/MCP composition (pending: #28)

**pending: #28** adds real browser runtime/activation, computer bindings, Skills and MCP management adapters, and workspace diagnostics. [Pinned composition](https://github.com/Calmingstorm/Odin-Desktop/blob/2d91071a692a646b6d8c466daa5711a37cd8c93f/src/desktop/management.py), [browser runtime](https://github.com/Calmingstorm/Odin-Desktop/blob/2d91071a692a646b6d8c466daa5711a37cd8c93f/src/desktop/browser_runtime.py), and [computer binding](https://github.com/Calmingstorm/Odin-Desktop/blob/2d91071a692a646b6d8c466daa5711a37cd8c93f/src/desktop/computer_binding.py) describe only that branch. It does not prove the combined app/backend matrix, portal consent, receiver-side input release or active-desktop qualification. Do not treat one pending branch as containing every other branch's services.

### Skills

The app has a Skills management screen, but main does not compose its named real-core management service. An unavailable panel is the expected boundary, not a working empty skill library. Runtime skill support and a management UI are different facts. Do not use a fixture's sample skills as evidence of a real loaded library.

**pending: #28** supplies the [Skills adapter](https://github.com/Calmingstorm/Odin-Desktop/blob/2d91071a692a646b6d8c466daa5711a37cd8c93f/src/desktop/skills.py) and composition. Use the reviewed candidate's actual controls and receipts when that service is integrated; adding code that executes as a tool is not required first-run setup.

### MCP servers

MCP servers supply external tools. Their commands/connections can run code or make network requests. Main's real core does not compose the MCP management adapter, so visible configuration fields and fixture examples are not proof of connected servers or published tools.

**pending: #28** supplies the [MCP adapter](https://github.com/Calmingstorm/Odin-Desktop/blob/2d91071a692a646b6d8c466daa5711a37cd8c93f/src/desktop/mcp.py) and management composition. Follow the actual candidate's per-server state/receipt and field apply labels. A published-tool limit is not a new owner permission allowlist, and saving configuration is not successful server connection evidence.

### Hosts and trust

This screen manages machines on which Odin runs commands over SSH using its own key. It does **not** connect the Desktop UI to an Odin server. The app does not ask for SSH passwords or import another installation's private keys. Host trust protects target identity; it is not a newly added owner command approval system.

To enroll a disposable SSH target in an approved isolated candidate:

1. Choose **Add host**. Enter **Alias**, **Address**, **Port**, **SSH user**, **System**, optional **Description**, and **Trust its key by**. Do not point this test at a production host. A loopback/local target has a separate **This is this computer: commands run inside Odin itself** confirmation and requires no SSH key installation.
2. Choose **Next**. For SSH, use **Odin's key → Copy the key** or the displayed **Copy the command** route to install its public key for the intended account on the test target, using that target's authorized administrator/session. Do not install it onto the workstation merely to test the guide.
3. Choose **Next**. For pinning, supply the independently checked host fingerprint in **Expected fingerprints**. For a CA, supply the independently checked signing-CA fingerprint, not the host key. Choose **Scan and compare**.
4. If you deliberately chose trust on first use, **Allow trust on first use** must have been enabled and saved in the section's host settings. Inspect the scanned key, choose **Trust exactly this key**, then scan again. A scan alone is not independent verification.
5. At the connection step, choose **Test the connection**. Only a successful test proceeds to activation. Choose **Activate**, **Save and activate**, or **Save, keeping off** as actually shown; inspect the resulting host state.

**Default host** chooses the target used when the existing policy allows an omitted host; **None: every command names its host** requires explicit target naming. Save this choice with that panel's **Save**. This is not an extra execution restriction layered onto Odin.

Rows distinguish **Ready**, **Not ready**, **Off**, and **Draining**. Turning a host off prevents new targetability but does not prove old effects were undone. **Delete…** can refuse while references still name the host. **Force revoke…** attempts to stop existing uses and can leave unknown outcomes; it is not “turn off for future work.” Key changes marked pending are used from the next start. See [Recovery](recovery.md) before retrying unknown host mutations.

### Scheduled and running work

The UI contains schedule and running-work panels, but main's named schedule/work management services are not composed. Runtime owner existence, tool availability and the management list are distinct. Saving a webhook or turn-state field is not proof a timer or a running-work list is functional.

**pending: #37** supplies [work management](https://github.com/Calmingstorm/Odin-Desktop/blob/4ede9e75fb079a0a305c7b24f89700d7fb7c4416/src/desktop/work.py), [schedule management](https://github.com/Calmingstorm/Odin-Desktop/blob/4ede9e75fb079a0a305c7b24f89700d7fb7c4416/src/desktop/schedules.py) and their [core composition](https://github.com/Calmingstorm/Odin-Desktop/blob/4ede9e75fb079a0a305c7b24f89700d7fb7c4416/src/desktop/core.py). See [Background work](background-work.md) for those pending procedures, sleep/Exit behavior, receipts and report expiry. It is not an automatic crash-resumption promise.

**pending: #42** adds the [inbound webhook listener/composition](https://github.com/Calmingstorm/Odin-Desktop/blob/50f90306176dd2abd724a1a2d5b97199d294b9c8/src/desktop/webhooks.py) on its branch. This is distinct from #37's work/schedules and main's outbound target settings. It is an integration listener, not a phone or server-client API. See [Background work](background-work.md); do not expose a candidate listener as a remote administration endpoint.

### State: memory, lists and knowledge

**Memory** is retained information for requests, not model training. The panel labels scopes **Yours** and **Everywhere**. To test with non-private disposable content: choose **Add** in the intended scope, enter **Key** and **Value**, then **Save**. **Open** shows entries; **Edit** changes one, while **Pick** plus **Delete … picked…** requests deletion with confirmation. Do not store secrets here. Saved memory can be included in request context sent to a provider.

**Named lists** has **Open/Close** and **Delete…** for stored lists. Deleting a list removes it and its items; it is not a conversation-history deletion or a provider-data erasure request.

**Knowledge** is separately retained searchable document text. Main has real list/search/ingest/version management backed by a profile-local store:

1. Under **Add a document**, enter a short **Source** label and **Text**, or choose **Load a text file** to populate the text. Use a harmless disposable text file for candidate validation.
2. Choose **Add** and inspect the command result/source list. The source is a label, not a path that Odin automatically follows. Adding the same label affects that source; use a distinct label if you intend a distinct document.
3. Use **Search** to inspect returned chunks. **Versions** lists the recorded history. **Restore** applies a stored content version; delete versions cannot be restored as content.
4. **Re-ingest** uses the current full-document snapshot, not a new read of the file or URL named in Source. **Delete…** removes the knowledge source and chunks with confirmation.

An attachment to one chat request is not automatically added here. Conversely, an added knowledge document is not automatically an attachment. At this watermark the management store is **not wired into the default request engine's model-side knowledge tools**; successful Add/search here does not establish retrieval during chat. The composition is pending below. Existing local knowledge search is not a promise that every future embedding/provider/tool path stays offline.

**Context → Reload context** is a separate reload of context files and displays its result; it is not a model restart or installation import.

#### Shared knowledge and learned-context details (pending: #40)

**pending: #40** adds [shared knowledge-store composition](https://github.com/Calmingstorm/Odin-Desktop/blob/6321eec26e1c87dd5b9682e902723818a5fdda03/src/desktop/services.py), [knowledge detail routes](https://github.com/Calmingstorm/Odin-Desktop/blob/6321eec26e1c87dd5b9682e902723818a5fdda03/src/desktop/knowledge.py), and [Knowledge details/Learned context UI](https://github.com/Calmingstorm/Odin-Desktop/blob/6321eec26e1c87dd5b9682e902723818a5fdda03/app/src/renderer/src/components/KnowledgeDetails.vue). This wiring must not be implied for main merely because main's State panel works.

On that candidate, **Read chunks**, **Find duplicates**, **Read version**, and **Read diff** inspect core-reported results. Supply the actual listed source/version identifiers; an unread or unavailable result is not zero duplicates. **Merge sources…** keeps the named source unchanged and deletes the other, **without copying content**. It is destructive, not an automatic union of documents.

**Refresh learned context** reads learned entries/metadata. For an existing **Learned entry key**, select **Change content** and/or **Change category**, enter the intended changes, then **Update learned entry** and inspect the receipt. **Delete learned entry…** requires confirmation. Learned context is separate from explicit Memory and Knowledge entries. Do not infer reflection success or training from a count alone.

### Records

Main supplies **Health**, **Usage**, **Audit**, **Logs** and turn-state record routes. Read each panel's availability/error and timestamp. **Check again** refreshes health; an unconfigured component is not healthy. Usage distinguishes measured, estimated and unknown values. Audit search/verification is scoped to actual available records; “not enabled,” partial/unsigned coverage and failed verification are not a complete verified record. Records can contain private operational context despite secret scrubbing.

Turn state concerns durable checkpoints, not proof an effect was rolled back. Main does not supply every service referenced by the Records screen; a computer-session status/reconcile panel may be unavailable. Do not press a recovery action just to remove a warning. [Recovery](recovery.md) owns the procedure and backend limitations.

#### Extended records and observability (pending: #40)

**pending: #40** adds [record inspection/export routes](https://github.com/Calmingstorm/Odin-Desktop/blob/6321eec26e1c87dd5b9682e902723818a5fdda03/src/desktop/records.py), [observability routes](https://github.com/Calmingstorm/Odin-Desktop/blob/6321eec26e1c87dd5b9682e902723818a5fdda03/src/desktop/observability.py), and [record](https://github.com/Calmingstorm/Odin-Desktop/blob/6321eec26e1c87dd5b9682e902723818a5fdda03/app/src/renderer/src/components/RecordDetails.vue)/[observability](https://github.com/Calmingstorm/Odin-Desktop/blob/6321eec26e1c87dd5b9682e902723818a5fdda03/app/src/renderer/src/components/ObservabilityDetails.vue) UI. Tool trajectory details also come from that branch's [TrajectoryDetails](https://github.com/Calmingstorm/Odin-Desktop/blob/6321eec26e1c87dd5b9682e902723818a5fdda03/app/src/renderer/src/components/TrajectoryDetails.vue), not main.

Those panels expose runtime/recovery statistics, recent recovery, capacity-breaker state and SSH/HTTP pool observations as reported, not fabricated estimates. **Close host pool…** and **Close all pools…** close SSH connections with confirmation; HTTP pools are unchanged, and new work can open new connections. They do not revoke a host's trust or undo commands. Export/inspection output can still be sensitive: share only sanitized material, never credential/history screenshots. [Chat and results](chat-and-results.md) explains evidence availability and expiry.

### Other

This contains fields not assigned to another group by the app. It is not a hidden general-purpose command runner or credential-import page. Read each core-supplied description/apply state; if you cannot explain the effect, leave the default for first-run setup.

## Support and validation limits

Managed SSH targets are supported; importing an Odin installation, phone access, and Desktop-as-server-client mode are not. Desktop profile data and credentials must stay separate from other installs. The [Install](install.md), [Updates](updates.md) and [Recovery](recovery.md) guides explain candidate layout, upgrades and retained data. Use [Accessibility](accessibility.md) for keyboard/screen-reader guidance.

This draft checks source controls and composition, not a native interactive qualification. Pending #28, #37, #40 and #42 are separate branches, not a proven combined runtime. Real provider generation, keyring prompts, SSH enrollment, native input cleanup, notifications/login and accessibility acceptance still need isolated candidate evidence and the [release checklist](../release/linux-v1-checklist.md). Do not run these procedures on the active workstation or live installation to validate the wording.

### Main-source references

- [Navigation and apply labels](../../app/src/renderer/src/settings-form.ts), [Settings view](../../app/src/renderer/src/views/Settings.vue), [schema controls](../../app/src/renderer/src/components/SchemaForm.vue).
- [General](../../app/src/renderer/src/views/settings/General.vue), [Codex accounts](../../app/src/renderer/src/components/CodexAccounts.vue), [Personality](../../app/src/renderer/src/views/settings/Personality.vue), [Tools](../../app/src/renderer/src/views/settings/Tools.vue).
- [Hosts UI](../../app/src/renderer/src/views/settings/Hosts.vue), [State UI](../../app/src/renderer/src/views/settings/State.vue), [Records UI](../../app/src/renderer/src/views/settings/Records.vue).
- [Core composition](../../src/desktop/core.py), [management composition](../../src/desktop/management.py), [actual request-tool readiness](../../src/desktop/services.py), [settings transactions](../../src/desktop/settings.py), [keyring](../../src/desktop/secrets.py), [knowledge management](../../src/desktop/knowledge.py), [records routes](../../src/desktop/records.py).
