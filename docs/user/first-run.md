# First run

Install and launch Odin using [Install](install.md). Setup uses the normal
Settings screens; there is no separate wizard.

## Open Settings

1. Read the **Provider readiness** banner and choose **Open Models and providers**.
   You can also choose **Settings** in the navigation rail or press **Ctrl+,**.
2. If you are not ready, choose **Set up later** on the chat banner. This hides the
   reminder; it does not configure a provider.
3. If it says **Readiness unavailable**, wait for the core connection. If it does
   not recover, use [Recovery](recovery.md).

## Choose a model and provider

Open **Settings → Models and providers**. You can use a Codex account, an
OpenAI-compatible endpoint or an existing Ollama endpoint.

| Main model value | Provider |
|---|---|
| A bare model name supported by your Codex account | Codex device sign-in |
| `compat:` followed by the provider's model ID | OpenAI-compatible endpoint |
| `ollama:` followed by your installed model name | Ollama endpoint |

Use a model name supported by your account or endpoint. Enter this reference in
the **Main model** field `llm_provider.model`. It selects the provider; the
read-only `llm_provider.active_provider` is not a separate provider selector.
Agent and image models are separate choices.

### Sign in to Codex

1. Under **Codex accounts**, choose **Add account**.
2. Open the displayed verification URL using its button. Use **Copy sign-in code**
   if needed, then enter the temporary code on that sign-in page.
3. Approve the intended account and return to Odin. Wait for the account list to
   update. **In use** identifies the current account; **Use this account** selects
   another listed account.
4. In the **Codex** group, check `openai_codex.enabled`. In **Main model**, enter
   the concrete model name in `llm_provider.model`.
5. Press **Enter** or leave the field to save. Read any error and its saved/running
   state before sending a request.

**Stop waiting** cancels the wait, not completes the login. Use **Retry login**
when offered after failure. If a code expired or the wait was stopped, start again
with **Add account** when available. **Retry accounts** or **Refresh** reloads the
account list; neither unlocks the keyring.

Do not paste tokens, browser profiles or credential files into Odin. Treat the
temporary sign-in code and account details as private; do not screenshot them.

### Use an OpenAI-compatible endpoint

1. In **OpenAI-compatible provider**, set `openai_compatible.base_url` to the
   provider's API base URL.
2. Enter its key in the write-only `openai_compatible.api_key` **New value** field
   and choose its **Save** button. Read the receipt or error. The input clears
   after submission even if saving fails.
3. Check `openai_compatible.enabled` and set `openai_compatible.model` to the
   provider's model ID. Ordinary typed fields save on **Enter** or when you leave
   them; toggles save immediately.
4. Set `llm_provider.model` in **Main model** to `compat:` plus that model ID.
   Read its apply state and the readiness banner.

Use the credential field for the provider you selected. A key for an unrelated
service does not configure the main model. Never paste a key into chat, an
endpoint URL or an ordinary text field.

### Use an existing Ollama endpoint

1. In **Ollama**, set `ollama.base_url` and `ollama.model` to your existing endpoint
   and installed model. This screen does not install or start Ollama or download
   models.
2. If authentication is required, save its key through `ollama.api_key` using
   **New value → Save**. Do not invent a key for an endpoint that needs none.
3. Check `ollama.enabled`. Set **Main model** `llm_provider.model` to `ollama:`
   plus that model's name, save and inspect the readiness state.

A remote Ollama endpoint still sends data to another machine.

## Recover the keyring

Credentials use Linux Secret Service. A secret field can report **Set**, **Not
set**, or **Keyring unavailable; saved value unknown**. Unknown does not mean no
credential exists.

1. Read the keyring notice in **Provider readiness**.
2. With the core connected, choose the banner's **Retry**. This explicit action
   may open the system's keyring unlock prompt; opening Settings alone does not.
3. Complete or dismiss that prompt. If Retry timed out with a prompt still open,
   resolve it before trying again.
4. Read the refreshed credential, account and readiness states. Retry does not
   replay a failed key write or start a new device login. After a known failed
   save, deliberately enter and save the key again once the keyring works.

If Secret Service or its default collection is missing, Retry can still fail.
Have the desktop's keyring repaired or provisioned, then retry. Odin does not
create a missing collection by pretending it unlocked, or save credentials in a
plaintext fallback. For an unknown command outcome, use [Recovery](recovery.md)
before another write.

## Read the readiness result

| Banner | Meaning |
|---|---|
| **Not configured** | Provider setup has not been completed. |
| **Setup incomplete** | The selected provider still needs configuration. |
| **Saved, not effective yet** | Saved choices have not been adopted, or the provider is unavailable. |
| **Ready** | The core adopted the saved model and provider. This is not a connection or generation test. |
| **Provider degraded** | The core reports a provider/keyring problem or cannot confirm health. |
| **Readiness unavailable** | No current readiness information is available. |

Fields also distinguish **Saved**, **Running**, and **Applies after a restart**.
See [Settings](settings.md#saving-and-running-are-different). A harmless request
with a completed reply separately shows that that request worked; it does not
guarantee every future request will work.

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
- **Settings → State → Knowledge** stores searchable document text separately.
  The model's knowledge tools use that shared store. Adding a document does not
  guarantee it will be retrieved for every request, and attaching a file does
  not automatically store it there. See [State](settings.md#state-memory-lists-and-knowledge).
- Memory is another kind of retained information, distinct from documents and
  conversation history. Do not put secrets in any of them.

Next: [Chat and results](chat-and-results.md), [Settings](settings.md), or
[Keyboard and accessibility](accessibility.md).
