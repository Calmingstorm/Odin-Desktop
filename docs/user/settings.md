# Settings

Open **Settings** in the top bar or press **Ctrl+,**. Choose **Back to chat** to
leave. The readiness banner can open **Models and providers** or **General**.

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
**Use this account**, **Label…** and **Remove…** are separate actions. Removal
stops Odin using that account; it does not delete the provider account. **Quota
not reported yet** is unknown, not unlimited.

Credentials are write-only. **Set** establishes presence, not authentication or
generation success. **Keyring unavailable; saved value unknown** does not mean
Not set. Use the readiness banner's explicit
[keyring Retry](first-run.md#recover-the-keyring), not token import or data deletion.

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
The core retains session and recovery records, but this screen does not currently
display that retained session record. A blank panel is not proof of no session or
verified cleanup; preserve any error and obtain operator help with the record.

The current core provides computer management, but not foreground mouse/keyboard
input authority. Turning computer use on does not start a native desktop session,
grant consent or make an unsupported backend usable. Only its enabled flag can
be changed through the current management service; other native configuration
changes are refused. This screen is not a start/resume-input workflow. For a
recovery warning, follow [Computer-input safety](recovery.md#computer-input-safety).

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

The visible **Test** button requests a real execution with empty input, not another
validation. In the current core, this management test is unavailable. Do not treat
that refusal as a failed skill run or proof the code is harmless: the button does
not run the skill. Do not use Test to investigate an uncertain earlier effect,
and do not assume unsaved edits were loaded or tested.

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

The named work-list, schedule-management and report-management services are not
available in the current real core. The visible panels are not proof a timer runs
or no work exists.
Use a conversation's task state and Stop/Steer controls for its running request.
See [Background work](background-work.md).

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

This store is separate from attachments and is **not connected to the default
request engine's knowledge tools**. Successful Add/search here does not establish
that a model can retrieve the document during chat.

**Context → Reload context** reloads context files and displays its result. It is
not a model restart or installation import.

## Records

Use **Health**, **Usage**, **Audit**, **Logs** and **Preserved work** to inspect
reported state. Read errors and timestamps. An unavailable component is not healthy;
usage distinguishes measured, estimated and unknown data. Unavailable/unsigned
audit verification is not a complete verified record.

Preserved work records concern checkpoints, not proof an effect was rolled back.
Computer management may report a storage or startup problem; it does not grant
foreground input. Do not use a recovery action merely to remove a warning.
Follow [Recovery](recovery.md).

## Other

This holds fields not assigned to another section; it can be hidden if there are
none. Read their descriptions and apply state. It is not a credential-import page
or general-purpose command runner. Leave unfamiliar defaults alone during setup.
