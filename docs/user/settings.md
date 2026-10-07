# Settings

Open **Settings** from the left icon rail or press **Ctrl+,**. Choose a section
in the settings navigation, then **Back to chat** to leave. The readiness banner
can open **Models and providers** or **General**.

Read a panel's availability before changing anything. **Unavailable** means it
cannot currently be used, not that it contains zero entries. A visible switch or
saved enabled value cannot create a missing service.

## Saving and running are different

There is no single save-all button:

- Toggles and dropdowns save when changed.
- Ordinary single-line values save on **Enter** or when you leave the field.
  Multiline/list/object fields save when you leave them. Text lists use one item
  per line; other structures use JSON. Follow the field's description.
- A secret has its own **New value → Save** password field. It clears on
  submission, even if saving fails; read the receipt or error.
- Panels such as Personality, Hosts, Memory and Timeouts have named **Save** buttons.
- **Reset to default** removes that ordinary override. It is not a global reset,
  account removal or data wipe. Read-only fields say how to change them elsewhere.

| State | Meaning |
|---|---|
| **Saved …** | Saving was acknowledged; the running value may still differ. |
| **Applied** | The core reports adoption. Read whether it affects live reads or new work. |
| **Applies after a restart** | Saved, but needs an app/core restart. Closing the window is not a restart. |
| **Not in use** | Dormant in the current configuration. |
| **Invalid** | Inspect and correct the error. |
| **Running value differs** | Compare the displayed Saved and Running values. |
| **Running value unknown** | The core cannot establish the effective value. |

For a known rejected change, correct the error. For an **unknown** outcome, use
[Recovery](recovery.md) rather than repeating it. A later read establishes current
state, not proof that an earlier external effect never happened.

For a restart-required setting, finish or stop work, choose **Exit Odin**, wait
for clean shutdown, then relaunch the same installation and profile. Check the
running value again. Resolve unknown cleanup first. See [Updates](updates.md)
when changing versions.

## General

Under **This app**:

- **Theme** offers **System**, **Dark** and **Light**. The rail's theme button
  switches to an explicit light or dark choice; choose System here to follow the
  desktop again. Theme is an app preference, not a core restart setting.
- **Start Odin when you log in** is initially off and optional.
- **Desktop notifications** controls delivery. **Show message previews in
  notifications** is initially on; switch it off for a shared or visible desktop.
- **Quiet hours** and their start/end times control quiet periods. Mute one
  conversation through its **⋯** menu.

These are app preferences, distinct from core settings below them. Closing the
window leaves the app running; use **Exit Odin** or **Ctrl+Q** to stop it. Without
a tray, reopen from the launcher first.

Core groups cover time, learning, sessions, context and attachments. History,
memory and documents may become provider request context. They are not a
model-training job performed by Desktop, nor a local-only privacy guarantee.

## Models and providers

Use [First run](first-run.md#choose-a-model-and-provider) for sign-in, provider
keys and Ollama. The main model reference selects the provider. Use only models
your account or endpoint supports; unrelated provider fields do not make them
valid main-model routes.

**Agents** has separate model and thinking choices. An inherited model, automatic
selection and a concrete override are different. Changes for new agents do not
change an already-running agent's captured configuration.

**Codex accounts** shows **In use**, expiry/limit warnings and reported quota.
**Use this account**, **Refresh sign-in**, **Label…** and **Remove…** are separate
actions. Refresh sign-in refreshes the listed account; it is not the keyring Retry
or a new Add account login. Read its receipt. Removal stops Odin using that
account; it does not delete the provider account. **Quota not reported yet** is
unknown, not unlimited.

Credentials are write-only. **Set** establishes presence, not authentication or
generation success. **Keyring unavailable; saved value unknown** does not mean
Not set. Use the readiness banner's explicit
[keyring Retry](first-run.md#recover-the-keyring), not token import or data deletion.

### Inspect OpenRouter models

In **OpenRouter models**, choose **Reload catalogue** to read the core's models,
profiles, eligibility, fetched/stale state and errors. Missing measurements are
not estimates. Enter **Model ID (author/slug)** and an optional **Provider pin
(blank uses automatic routing)**, then **Read endpoints** to inspect the route.
**Select model** changes compatibility-provider configuration. Read its receipt
and the main-model saved/running state; selecting does not prove generation works.
**Read compatibility diagnostic** can report unhealthy or unavailable state. A
failed read is not an empty catalogue or permission to read back credentials.

### Image models: follow or pin

In **Images**, `image.openai.image_model` and `image.openai.outer_model` can
follow defaults or retain a specific value:

1. Read **Follows Odin's default (…)** or **Pinned to …**.
2. Choose **Pin this value** to retain the current default.
3. Choose **Follow Odin's default** to resume following. Read the returned intent
   and apply state.

The outer model hosts the image tool; it is not the image-generation model.
Their follow/pin choices are independent. Saving does not prove an image was
generated, the backend is enabled or its credentials work.

## Personality

Choose a **Preset**, inspect its identity/voice, then **Save**. **Custom** exposes
**Name**, **Identity** and **Voice**. New requests use saved choices; existing
work may retain its captured prompt.

**Your presets** lets you save a named preset or delete your own with confirmation.
Built-in presets cannot be edited or deleted. Personality does not change host
trust or execution safety.

## Tools

Use **Filter tools**, each tool's switch, and **Parameters** to inspect its inputs.

| Label | Meaning |
|---|---|
| **Available** | Offered under current readiness and policy. |
| **Off** | Switched off and not offered. |
| **Tools are off** | The global tools setting is off. |
| **Hidden: not configured here** | A required runtime/configuration dependency is missing. |

Switching a hidden tool on does not install its dependency. Edit **Default, in
seconds**, optionally **Add a tool's own timeout**, then **Save timeouts**.
Timeouts are positive whole seconds and affect new calls, not calls already running.

Browser/computer/email fields can be visible without a working service. Read the
saved and running values and the returned status, not just an enabled switch.

### Set up browser tools

Under **Tools → Browser**, check the browser settings. Odin uses the configured
CDP endpoint when one is supplied; otherwise it uses bundled Chromium, not your
usual browser profile. Only configure an endpoint you are authorized to use.

Browser settings are saved for the next app/core start. They do not change the
configuration captured when the current core started. Follow the restart steps
above, then check the running values and the next browser tool result. Saving or
seeing a browser tool offered is not proof that its connection works: Odin checks
the browser and its network guards before use. If bundled Chromium is missing,
repair the installation; do not copy a personal browser profile or disable guards.

Read browser failures as unavailable service, not an empty page or successful
click. Each browser call uses a fresh, temporary context; cookies, filled fields
and page state do not carry into a later call. A fresh context is not permission
to repeat a submission whose outcome is unknown.

### Check computer use without granting input

Open **Settings → Records → Computer use → Refresh** to request current status.
Read management availability, any foreground refusal reason, and any reported
session's ID, generation, state and recovery result. **No computer-use session is
reported** is not proof of input release or verified cleanup. A failed refresh
may leave **Showing the last read**; that is not fresh evidence.

For **1.0.0**, the app supports Cinnamon/X11, GNOME/Wayland, KDE/Wayland and
Hyprland, but **computer use is supported on X11 only, at parity with Odin**.
Wayland computer use is planned for **1.1**; until then the app refuses it with
guidance. Read the actual session readiness and any refusal reason. Turning
computer use on does not start a native desktop session, grant consent or make an
unsupported backend usable. Only its enabled flag can be changed through the
current management service; other native configuration
changes are refused. This screen is not a start/resume-input workflow. For a
recovery warning, follow [Computer-input safety](recovery.md#computer-input-safety).

The [Linux release checklist](../release/linux-v1-checklist.md) defines the current
release gate, replacing the earlier Phase 3/native matrix. #97 and #98 are
harness follow-ups for 1.1, not additional v1 release blockers. Neither a release
check nor this management screen grants foreground input consent.

## Skills and MCP servers

These panels manage real skills and server connections. Neither is required for
first-run provider setup. If a panel reports **Unavailable**, read that as a
service problem, not an empty library or a connected server.

### Add or change a skill

Skills are Python code loaded into Odin. Use only code you trust; validation is
not a safety review or a successful execution test. Loading can also install the
skill's declared package dependencies. Read its diagnostics before proceeding.

1. Open **Settings → Skills**. Read each skill's **Loaded**, **Off** or **Failed to
   load** state and diagnostics. Choose **Open** for a loaded/off skill, or **New
   skill** to enter a name and code. Names start with a lowercase letter, use
   lowercase letters, digits or underscores, and are at most 50 characters.
2. Choose **Validate** and correct errors. Validation compiles and inspects code
   without executing it. **Create** or **Save** validates again, then loads the
   code; loading can execute module-level code. Read the returned result and state.
3. If the skill supplies **Its settings**, edit them and choose **Save its settings**.
   This is separate from saving its code and requires the profile's unlocked
   keyring. An unavailable keyring is not an empty saved configuration.
4. Use **Turn off** or **Turn on** to change whether it is offered. **Delete…**
   requires confirmation and removes its code; it does not undo earlier effects.

The **Test** button executes the saved, loaded skill with empty input. It is not
another validation or a sandbox: it can cause real effects through the available
services and permissions. A skill requiring inputs may reject the empty object.
The test has no chat destination, so conversation-dependent operations can fail.
Read its returned output/error; do not assume unsaved edits were loaded or tested.
Never use Test to investigate an uncertain earlier effect.

### Connect an MCP server

MCP servers supply external tools. Starting a local server can run code; connecting
to a URL can make network requests. Use servers and credentials you trust.

1. Open **Settings → MCP servers → Add server**. Enter **Name** and **Transport**.
   For **stdio: a program on this computer**, supply **Executable**, arguments
   (one per line) and the working directory as needed. For **http: a server at a
   URL**, supply **URL**. Set a positive whole-number **Timeout, in seconds**.
2. Use **Only these tools, one per line** to restrict offered tools; blank on a new
   server means all. Add required headers or environment variables through
   **Headers and environment**, then choose **Add**. Read the receipt, server
   state, errors and connected/tool counts. Saving is not connection success.
3. Check **MCP on** and the server's **Turn on/Turn off** state. For an enabled
   server, **Reconnect** requests a new connection and **Refresh tools** refreshes
   its inventory. **Tools** shows offered names and exclusion reasons.
4. Use **Edit → Save** for changes. Blank fields keep existing values; use the
   explicit clear/remove choices to remove arguments, headers or variables, or
   **Offer all its tools again** to clear a tool restriction. Stored header and
   environment values are never read back. A blank password field does not mean
   the credential was lost.

**Maximum tools per server**, **Maximum tools in all** and **Save limits** limit
publication, not permission to perform an effect. Use **1–128** per server and
**1–256** in all; zero is rejected even though the input allows you to enter it.
**Remove…** stops and removes that server and its offered tools, with confirmation.
Turning off, removing, reconnecting or refreshing does not undo or settle earlier
tool calls. For an unknown result, preserve the original record and use
[Recovery](recovery.md).

A connected server and its **Tools** list establish management state, not that
chat can call those tools. The current default core does not connect this managed
MCP inventory to chat requests. Do not treat a working settings panel as a
successful tool execution.

## Hosts and trust

This screen manages command targets over SSH using Odin's own key. It does not
connect the UI to an Odin server. The app does not ask for SSH passwords or import
another installation's private keys.

### Add an SSH host

1. Choose **Add host**. Enter **Alias**, **Address**, **Port**, **SSH user**,
   **System**, optional **Description**, and **Trust its key by**. Use a target
   you are authorized to manage.
2. Choose **Next**. Use **Odin's key → Copy the key** or **Copy the command** to
   install its public key for that account through the target's authorized session.
3. Choose **Next**. For pinning, enter an independently checked host fingerprint
   in **Expected fingerprints**. For a CA, use the signing-CA fingerprint, not the
   host key. Choose **Scan and compare**.
4. For trust on first use, first enable/save **Allow trust on first use** in host
   settings. Inspect the scanned key, choose **Trust exactly this key**, then scan
   again. A scan alone is not independent verification.
5. Choose **Test the connection**. Only a successful test proceeds to activation.
   Use **Activate**, **Save and activate**, or **Save, keeping off** as shown, then
   inspect the resulting host state.

A local/loopback target has a separate **This is this computer: commands run inside
Odin itself** confirmation and does not require SSH key installation.

**Default host** supplies the target when the current policy permits an omitted
host. **None: every command names its host** requires explicit naming. Save with
the panel's **Save**.

Rows show **Ready**, **Not ready**, **Off**, or **Draining**. Off prevents new use;
it does not undo previous effects. **Delete…** may refuse while references remain.
**Force revoke…** attempts to stop existing uses and can leave unknown outcomes.
Key changes marked pending take effect on the next start. Use [Recovery](recovery.md)
before retrying an unknown host change.

## Scheduled and running work

Open the rail's **Work** button for the running-work column beside chat. Open
**Settings → Scheduled and running work** for saved schedules and their **Runs**.
**New schedule**, **Pause/Resume**, **Run now**, **Edit** and **Delete…** have
different effects: Run now executes; Runs only reads history. Unknown runs must
not be replayed through Resume, Run now or Reset failures. Follow
[Background work](background-work.md) for schedule creation, controls and the
sleep/wake missed-run policy. An unavailable read is not an empty work list.

### Incoming integrations

**Webhook ingress** in this section is an opt-in event listener for saved trigger
schedules, not a remote administration API or connection to another Odin install.

1. Save a schedule with webhook timing and a valid reporting conversation first.
2. Under **Inbound listener setup**, supply an explicit numeric LAN, tailnet,
   link-local or loopback **Listen address**, not a wildcard or hostname. Set the
   **Listen port**, opt in with **Enable inbound webhook deliveries**, then choose
   **Save listener setup**. Read the measured status and actual listen address.
3. Choose the **Saved webhook schedule**, matching **Inbound delivery source**
   and a distinct **New per-trigger secret**. **Save trigger source and secret**
   writes the source first and secret separately. The secret draft clears even
   on failure; partial setup can leave the previous secret in use. Refresh and
   inspect the receipt before retrying. **Clear per-trigger secret** removes that
   trigger's authentication setup, not earlier effects.
4. Read the selected schedule's warning, route and authentication instructions.
   Generic, GitHub and Gitea ingress are supported. GitLab schedule matching does
   not mean GitLab ingress is available.

**Accepting deliveries** establishes listener state, not eligibility of every
selected schedule or success of its workflow. Disabled, unconfigured, unbound,
paused and inert states are different. A bind failure does not select a fallback
address. **Refresh** replaces unsaved listener/source drafts and discards the
secret draft. Exit closes the listener.

Incoming payload text is untrusted data, not owner instructions. Use supported
secret fields, not secret-bearing URLs. Check outgoing destinations and event
choices before enabling them; outbound settings are separate from ingress.
Never share signing secrets, raw payloads, headers or private URLs. See
[Integration recovery](recovery.md#incoming-integration-failures) for uncertain
deliveries and the limits of retry/deduplication.

## State: memory, lists and knowledge

**Memory** retains information for requests, not model training. Scopes are
**Yours** and **Everywhere**. Choose **Add**, enter **Key** and **Value**, then
**Save**. **Open** reads entries; **Edit** changes one. **Pick** and **Delete …
picked…** delete selected entries with confirmation. Do not store secrets; saved
memory can become provider context.

**Named lists** offers **Open/Close** and **Delete…**. Deleting a list removes it
and its items, not conversation history or provider-held data.

### Keep document text as knowledge

1. Under **Knowledge → Add a document**, enter a **Source** label and **Text**, or
   use **Load a text file** to fill the text.
2. Choose **Add** and inspect the result/source list. Source is a label, not a path
   Odin automatically reads. Reusing a label affects that source; use a distinct
   label for a distinct document.
3. Use **Search** to read chunks. **Versions** lists recorded history; **Restore**
   applies a stored content version. A deletion version has no content to restore.
4. **Re-ingest** uses the stored full-document snapshot, not a fresh read of a file
   or URL in Source. **Delete…** removes the source and chunks with confirmation.

This is the same profile knowledge store used by the model's knowledge tools.
Successful Add/search establishes retained content, not proof a particular chat
retrieved it. Attachments and knowledge sources remain separate records; an
attachment's **Add to knowledge** requests ingestion rather than guaranteeing it.
Existing local search is not a promise every embedding, provider or tool path
stays offline.

In **Knowledge details**, **Read chunks**, **Find duplicates**, **Read version**
and **Read diff** inspect core-reported records. Use actual listed source/version
identifiers; unavailable or unread does not mean zero duplicates. **Merge
sources…** keeps the named source unchanged and deletes the other with its
chunks, **without copying its content**. This is destructive, not a document union.

**Refresh learned context** reads learned entries and metadata, separate from
explicit Memory and Knowledge. Enter an existing **Learned entry key**, select
**Change content** and/or **Change category**, then **Update learned entry** and
read the receipt. **Delete learned entry…** requires confirmation. An entry count
does not prove reflection success or model training.

**Context → Reload context** reloads context files and displays its result. It is
not a model restart or installation import.

## Records

Use **Health**, **Usage**, **Audit**, **Logs** and **Preserved work** to inspect
reported state. Read errors and timestamps. An unavailable component is not healthy;
usage distinguishes measured, estimated and unknown data. Unavailable/unsigned
audit verification is not a complete verified record.

Records also offers runtime/recovery statistics, recent recovery, capacity-breaker
state, SSH/HTTP pool observations, **Records extras** and **Trajectories**. These
are reported records, not estimates or proof of an external effect. **Close host
pool…** and **Close all pools…** close SSH connections with confirmation; HTTP
pools are unchanged, new work can open new connections, and host trust is not
revoked. See [Recovery](recovery.md#open-the-diagnosis-screens) for safe inspection.

Preserved work records concern checkpoints, not proof an effect was rolled back.
Computer management may report a storage or startup problem; it does not grant
foreground input. Do not use a recovery action merely to remove a warning.
Follow [Recovery](recovery.md).

## Other

This holds fields not assigned to another section; it can be hidden if there are
none. Read their descriptions and apply state. It is not a credential-import page
or general-purpose command runner. Leave unfamiliar defaults alone during setup.
