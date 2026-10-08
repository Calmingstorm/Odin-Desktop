# First run

Install and launch Odin using [Install](install.md). Setup uses the normal
Settings screens; there is no separate wizard.

## Open Settings

1. Choose **Settings** in the navigation rail or press **Ctrl+,**, then open
   **Models and providers**. A setup invitation in chat can also offer **Open
   Models and providers**.
2. If you are not ready, choose **Set up later** when offered. A successful save
   remembers this dismissal across reopening and restarting the app. It hides
   the setup invitation, not provider, keyring, connection or recovery warnings;
   it does not configure a provider. If saving the preference fails, read the error.
3. If the core is disconnected or setup status has not been reported, no setup
   banner is manufactured. Read the connection state and use [Recovery](recovery.md)
   if it does not recover. Settings remains the setup entry point.

## Choose a model and provider

Open **Settings → Models and providers**. **Main model** is a compact group with
**Model** and, when applicable, **Reasoning effort**. Choose from the core's model
catalogue, then use the group's **Save** or **Cancel** for unsaved changes. Changing
a selection does not save this group; Enter or leaving it is not a save shortcut.
Use **Refresh model choices** if the catalogue could not be read. Missing model
or effort choices are unknown, not permission to invent support.

You can use a Codex account, an OpenAI-compatible endpoint or an existing Ollama
endpoint. Catalogue references identify their provider:

| Main model value | Provider |
|---|---|
| A bare model name supported by your Codex account | Codex device sign-in |
| `compat:` followed by the provider's model ID | OpenAI-compatible endpoint |
| `ollama:` followed by your installed model name | Ollama endpoint |

Use a model supported by your account or endpoint. The saved main model selects
the chat provider; a provider's enable switch is not a main-model selector. Agent
and image models are separate choices. **Providers → Configure** opens setup even
while that provider is disabled. Saving setup and enabling the provider are
separate actions, and disabling keeps its saved setup.

### Sign in to Codex

1. Under **Accounts and quota**, choose **Add account**.
2. Open the displayed verification URL using its button. Use **Copy sign-in code**
   if needed, then enter the temporary code on that sign-in page.
3. Approve the intended account and return to Odin. Wait for the account list to
   update. **In use** identifies the current account; **Use this account** selects
   another listed account.
4. Under **Providers**, turn on **Codex** separately. **Configure** explains the
   account setup; signing in does not require enabling it first.
5. In **Main model → Model**, choose a supported Codex model and any supported
   **Reasoning effort**, then choose **Save**. Read any error or running-value
   warning before sending a request.

**Stop waiting** cancels the wait, not completes the login. Use **Retry login**
when offered after failure. If a code expired or the wait was stopped, start again
with **Add account** when available. **Retry accounts** or **Refresh** reloads the
account list; neither unlocks the keyring.

Do not paste tokens, browser profiles or credential files into Odin. Treat the
temporary sign-in code and account details as private; do not screenshot them.

### Use an OpenAI-compatible endpoint

1. Under **Providers → OpenAI-compatible**, choose **Configure**. Choose the
   **Provider preset**, **Provider address** and **Provider model** for your endpoint.
2. Enter the key in the write-only **Provider access key** field, whose placeholder
   is **New API key**, and choose **Store key** or **Replace key**. This is a
   separate write from saving setup. Read errors; the submitted draft clears even
   when saving fails. **Remove key** is a separate confirmed removal.
3. Choose **Save OpenAI-compatible setup** explicitly, or **Cancel OpenAI-compatible
   changes** to discard unsaved setup edits. Enter and leaving these fields do
   not save them. Then turn on **OpenAI-compatible** separately.
4. Refresh model choices if needed. In **Main model → Model**, choose the matching
   `compat:` reference and a supported effort when offered, then **Save**. Read
   any errors or running-value warnings. A configured summary is not a successful
   endpoint connection or generation test.

Use the credential field for the provider you selected. A key for an unrelated
service does not configure the main model. Never paste a key into chat, an
endpoint URL or an ordinary text field.

### Use an existing Ollama endpoint

1. Under **Providers → Ollama → Configure**, set **Ollama address** and **Local
   model** to your existing endpoint and installed model. This screen does not
   install or start Ollama or download models.
2. If authentication is required, use **Ollama access key → Store key** or
   **Replace key**. Do not invent a key for an endpoint that needs none.
3. Choose **Save Ollama setup**, then enable **Ollama** separately. **Cancel Ollama
   changes** discards unsaved setup edits, not a key already stored.
4. In **Main model → Model**, choose the matching `ollama:` reference, refreshing
   choices if needed, then **Save**. Inspect the receipt and running-value warnings.

A remote Ollama endpoint still sends data to another machine.

## Recover the keyring

Credentials use Linux Secret Service. Provider key controls report **Key stored**,
**No key stored**, or **Saved key status unavailable**. Unknown does not mean no
credential exists; stored does not mean authenticated or tested.

1. Read **Keyring needs attention** in chat when reported by the current core.
2. With the core connected, choose the banner's **Retry**. This explicit action
   may open the system's keyring unlock prompt; opening Settings alone does not.
3. Complete or dismiss that prompt. If Retry timed out with a prompt still open,
   resolve it before trying again.
4. Read the refreshed credential, account and provider states. Retry does not
   replay a failed key write or start a new device login. After a known failed
   save, deliberately enter and save the key again once the keyring works.

If Secret Service or its default collection is missing, Retry can still fail.
Have the desktop's keyring repaired or provisioned, then retry. Odin does not
create a missing collection by pretending it unlocked, or save credentials in a
plaintext fallback. For an unknown command outcome, use [Recovery](recovery.md)
before another write.

<a id="read-the-readiness-result"></a>

## Read setup and operational status

| Chat notice, when reported | Meaning |
|---|---|
| **Not configured** | Provider setup has not been completed. |
| **Setup incomplete** | The selected provider still needs configuration. |
| **Saved, not effective yet** | Saved choices have not been adopted, or the provider is unavailable. |
| **Provider degraded** | The core reports a provider/keyring problem or cannot confirm health. |
| **Keyring needs attention** | The current core reports a locked/unavailable keyring or a keyring read error. |

An effective-ready provider does not produce a persistent success banner. Missing
status does not produce a fake readiness banner either. Absence of a notice alone
is not proof of health. Setup dismissal only suppresses the invitation, not
**Saved, not effective yet**, degraded-provider or keyring attention notices.

Settings distinguishes saving from adoption and warns about invalid, differing,
unknown or restart-required running values. See
[Settings](settings.md#saving-and-running-are-different). Provider status and
credential presence are not generation tests. A harmless request with a completed
reply separately shows that that request worked; it does not guarantee every
future request will work.

## Choose startup and notification privacy

Open **Settings → General**, or choose **Startup and notifications** in the banner.

- **Start Odin when you log in** is initially **off**. Turn it on only if wanted.
- **Show message previews in notifications** is initially **on**. Turn it off on
  a shared or visible desktop. If **Desktop notifications** is off, the preview
  control is disabled.
- Set **Quiet hours** and their times if wanted. Mute one conversation from its
  **⋯** menu.

Notification settings do not remove saved history or prevent provider network
access. A notification accepted by the desktop is not proof someone saw it.

## Closing is not exiting

Closing hides the window and leaves the app/core running. Reopen using the
launcher or tray's **Open Odin**. Without a tray, launch Odin again, then use
**Odin → Exit Odin** or **Ctrl+Q**. The desktop launcher's **Exit Odin** action is
another route when available.

Exit requests orderly shutdown, not rollback of completed actions. Read
[Background work](background-work.md) and [Recovery](recovery.md) for ongoing work
and unresolved cleanup.

## Keep history, attachments and knowledge distinct

History lets you continue and review conversations; Desktop does not use it as
a model-training job. Your provider's retention and training policy is separate.
Online models receive request context, and tools can make their own network
requests. A local model does not make every tool local-only.

- [Attach a file](chat-and-results.md#attach-a-file-or-request-knowledge-retention)
  for the current request. **Add to knowledge** expresses a retention request,
  not guaranteed ingestion.
- **Settings → Data and privacy → Memory and knowledge → Knowledge** stores
  searchable document text separately.
  The model's knowledge tools use that shared store. Adding a document does not
  guarantee it will be retrieved for every request, and attaching a file does
  not automatically store it there. See
  [Memory and knowledge](settings.md#state-memory-lists-and-knowledge).
- Memory is another kind of retained information, distinct from documents and
  conversation history. Do not put secrets in any of them.

Next: [Chat and results](chat-and-results.md), [Settings](settings.md), or
[Keyboard and accessibility](accessibility.md).
