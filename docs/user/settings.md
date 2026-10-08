# Settings

Open **Settings** from the left icon rail or press **Ctrl+,**. Choose a section
in the settings navigation, then **Back to chat** to leave. A chat setup invitation
or provider-attention notice can open **Models and providers**; the invitation
can also open **General** for startup and notifications.

The nine primary destinations are **General**, **Models and providers**,
**Personality**, **Tools**, **Skills**, **MCP servers**, **Hosts and access**,
**Work**, and **Data and privacy**. These are curated task screens, not a raw
configuration tree. **More options** holds secondary controls within a screen.
**Advanced settings** is a secondary route under **General → Support and advanced**,
not a tenth primary destination.

In **Data and privacy**, choose **Memory and knowledge**, **Conversations**, or
**Usage, logs and audit**. The old separate State and Records destinations are
not navigation entries in this interface.

Read a panel's availability before changing anything. **Unavailable** means it
cannot currently be used, not that it contains zero entries. A visible switch or
saved enabled value cannot create a missing service.

## Saving and running are different

There is no single save-all button:

- Ordinary independent toggles and dropdowns save when changed. Grouped model
  choices are drafts until their **Save**; **Cancel** discards those drafts.
- Independent short fields can save on **Enter** or when you leave them, and
  offer **Save/Cancel** while changed. Long/structured fields require their
  explicit **Save**; leaving them does not save. Follow the actual editor and
  field description rather than assuming every text field behaves alike.
- Provider setup, browser/email setup, image settings and other explicitly
  grouped controls use their named **Save** actions. In provider setup, changing
  a preset or leaving an address does not save. **Configure** is available while
  a provider is off; saving its setup does not enable it.
- Dedicated secret controls are write-only, with **Store key**, **Replace key**
  and confirmed **Remove key** for provider keys. Key storage is separate from
  the provider setup Save. The submitted key draft clears even on failure;
  read errors and do not assume a blank input means the stored key is gone.
- Panels such as Personality, Hosts, Memory and Timeouts have named **Save** buttons.
- Read-only or unavailable controls cannot be edited here. A specific reset or
  follow-default action, where offered, is not a global reset, account removal
  or data wipe.

| State | Meaning |
|---|---|
| **Saved …** | Saving was acknowledged; the running value may still differ. |
| **Applied** | When reported, the core indicates adoption. Read whether it affects live reads or new work. |
| **Applies after a restart** | Saved, but needs an app/core restart. Closing the window is not a restart. |
| **Not in use** | Dormant in the current configuration. |
| **Invalid** | Inspect and correct the error. |
| **Running value differs** | The saved and running choices differ; refresh and inspect before relying on the change. |
| **Running value unknown** | The core cannot establish the effective value. |

For a known rejected change, correct the error. For an **unknown** outcome, use
[Recovery](recovery.md) rather than repeating it. A later read establishes current
state, not proof that an earlier external effect never happened.

For a restart-required setting, finish or stop work, choose **Exit Odin**, wait
for clean shutdown, then relaunch the same installation and profile. Check the
running value again. Resolve unknown cleanup first. See [Updates](updates.md)
when changing versions.

## General

Under **Appearance** and **Startup and notifications**:

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

**Time** provides **Find a time zone** and a named selection, including the system
zone, rather than requiring a raw configuration value. Learning and search live
in **Data and privacy**; detailed policies are in More options or Advanced settings.
History, memory and documents may become provider request context. They are not
a model-training job performed by Desktop, nor a local-only privacy guarantee.

### About and support

**About** distinguishes **Desktop release** from **Engine build**; the engine's
version is not the desktop release number. It also reports **Runtime** and **Build
and licence**. An unavailable read is shown as unavailable, not a guessed build.
**Copy diagnostics** copies version/build and connection information, not account
details, credentials or configuration. Still inspect support material before sharing.

Under **Support and advanced**, **Open settings folder** opens the local settings
location. Exit before manual editing, manage credentials in the app, and leave
app-managed files unchanged. This is not a credential-import workflow.

### Window size and placement

The app owns a best-effort saved normal window size and maximized state. It tries
to keep a usable window after a display or work-area change, without using a
minimized or fullscreen rectangle as the normal size. On X11 it can also restore
and repair placement. On native Wayland it requests size only, plus the saved
maximized state; the compositor owns placement. Exact position restoration is
not promised. This describes the source implementation, not qualification on
every desktop, compositor, scale or monitor setup.

## Models and providers

Use [First run](first-run.md#choose-a-model-and-provider) for sign-in, provider
keys and Ollama. The main model reference selects the provider. Use only models
your account or endpoint supports; unrelated provider fields do not make them
valid main-model routes.

**Main model** keeps **Model** and supported **Reasoning effort** together, with
one **Save/Cancel** group for unsaved changes. **Refresh model choices** reads
the catalogue; unavailable choices or unknown effort support are not fabricated.
Changing the main model does not enable its provider.

**Agents → Agent model** offers **Same as main**, **Choose automatically**, or
**Choose a model**. Automatic candidates are ordered by preference and can have
supported per-model effort/thinking choices. Use the group's **Save/Cancel**;
independent agent reasoning effort and concurrency controls are separate.
Changes for new agents do not change an already-running agent's captured configuration.

**Accounts and quota** shows **In use**, expiry/limit warnings and reported quota.
**Use this account**, **Refresh sign-in**, **Rename** and **Remove…** are separate
actions. Refresh sign-in refreshes the listed account; it is not the keyring Retry
or a new Add account login. Read its receipt. Removal stops Odin using that
account; it does not delete the provider account. **Quota not reported yet** is
unknown, not unlimited.

**Providers** shows **Codex**, **Ollama** and **OpenAI-compatible**, each with an
enable switch and **Configure**. Setup stays available while disabled. For Ollama
or OpenAI-compatible, use **Save … setup** or **Cancel … changes** for the setup
draft, then enable separately. Disabling the provider handling the main model
requires confirmation and keeps its setup; main chat may become unavailable.

Credentials are write-only. **Key stored** establishes presence, not authentication
or generation success. **Saved key status unavailable** does not mean **No key
stored**. Use the chat keyring notice's explicit
[Retry](first-run.md#recover-the-keyring), not token import or data deletion.
Provider summaries distinguish reported setup from unavailable status; neither a
configured summary nor the absence of a readiness banner proves a successful request.

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

Under **Models and providers → More options → Images**, **Image model** and
**Image host model** can follow defaults or retain a specific value. Their typed
edits use explicit **Save/Cancel**, not Enter or blur. The separate policy controls
offer:

1. Read **Following default: …** or **Pinned: …**.
2. Choose **Pin current value** to retain the current default.
3. Choose **Follow default** to resume following. Read the returned intent
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
saved/running warnings and returned status, not just an enabled switch. Under
**Email → Mail account → Configure**, setup remains editable while email tools
are off. Non-secret account fields use explicit **Save/Cancel**. Passwords use
separate write-only **Store**, **Replace** and confirmed **Remove** actions;
**Password stored** is presence, not a tested mail connection. Enable email tools
separately when ready to use them.

### Set up browser tools

Under **Tools → Browser → Configure**, check the browser settings and use their
explicit **Save/Cancel**. **Refresh status** only reads status; it does not open
the browser. An absent status is unavailable/unread, not a fabricated ready state.
Odin uses the configured
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

Open **Settings → Tools → Computer use → Refresh** to request current status.
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

<a id="hosts-and-trust"></a>

## Hosts and access

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
**Settings → Work** for saved schedules and their **Runs**.
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

<a id="state-memory-lists-and-knowledge"></a>

## Memory, lists and knowledge

Open **Settings → Data and privacy → Memory and knowledge** for these records.

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

The current curated screen does not expose the former Knowledge details or
learned-entry management controls. Learned context remains distinct from explicit
Memory and Knowledge; a stored entry count does not prove reflection success or
model training. If using a knowledge tool instead, inspect its actual result and
source/version identifiers. Unavailable or unread does not mean zero duplicates.
A merge operation that deletes another source without copying its content is
destructive, not a document union; do not infer retention from the word "merge".

**Context → Reload context** reloads context files and displays its result. It is
not a model restart or installation import.

<a id="records"></a>

## Usage, logs and audit

Open **Settings → Data and privacy → Usage, logs and audit** for records and
diagnosis. Computer-use availability and recovery controls are in **Tools →
Computer use**, not a separate Records navigation destination.

Use **Health**, **Usage**, **Audit**, **Logs** and **Preserved work** to inspect
reported state. Read errors and timestamps. An unavailable component is not healthy;
usage distinguishes measured, estimated and unknown data. Unavailable/unsigned
audit verification is not a complete verified record.

The curated screen includes a read-only **Computer use report**, with **Refresh**
and **Go to Tools**. Recovery management is in Tools. Former Records extras,
Trajectories and pool-closing controls are not shown here. Reported records are
not estimates or proof of an external effect. Closing a connection pool through
another supported operation is not host-trust revocation or rollback; new work
may open new connections. See [Recovery](recovery.md#open-the-diagnosis-screens)
for safe inspection, using the current Data and privacy route for these records.

Preserved work records concern checkpoints, not proof an effect was rolled back.
In **Tools → Computer use**, management may report a storage or startup problem;
it does not grant foreground input. Do not use a recovery action merely to remove
a warning. Follow [Recovery](recovery.md).

## Advanced settings

Open **General → Support and advanced → Advanced settings**. Use **Search Advanced
settings** to find curated compatibility, execution-limit and retention-policy
controls. **← General** returns to General. This is not an unfiltered schema tree,
credential-import page or general-purpose command runner. Read descriptions,
errors and restart/apply warnings; leave unfamiliar policies alone during setup.
