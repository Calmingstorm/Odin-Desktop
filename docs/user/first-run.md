# First run

Start with [Install](install.md). This is a first-draft guide to a **Linux candidate**, not an announcement of a released or fully qualified app. The source watermark is `main@0b7d596f7e870d06699722f151c4d9837c5433f1`; [README](../../README.md) records the reviewed upstream baseline and pending branches. A reviewed baseline or passing source tests do not establish an identical engine or release acceptance. [The Linux release checklist](../release/linux-v1-checklist.md) still requires P4.5, P4.6 and Aaron's approvals.

The instructions below use the app's actual Settings screens. There is no separate setup wizard. For candidate validation, use only the isolated profile/session described in [Install](install.md), with disposable test data and approved test accounts or controlled provider responses. Do not open a live installation's profile, inherit its credentials, or test on the active workstation desktop. No credential or private-history screenshots are needed.

## 1. Open Settings, even if you are not ready to choose a provider

1. Launch the installed candidate from its app launcher.
2. Read the **Provider readiness** banner. Choose **Open Models and providers** to go directly to that Settings section. You can also use **Settings** in the top bar or **Ctrl+,**.
3. If you need more time, choose **Set up later** on the chat banner. Settings and chat remain navigable. Hiding the reminder does not configure a provider or make a request executable.
4. If the banner says **Readiness unavailable**, wait for the current core connection. A window appearing is not the same as a ready core. See [Recovery](recovery.md) if the connection does not recover.

Main composes real conversations, requests and provider/settings owners. It does not substitute the demonstration fixture for missing real services. Some Settings panels still have no real-core service, including Skills/MCP management and scheduled/running-work management at this watermark. An unavailable message is not an empty, working service. See [Settings](settings.md) for the boundaries and individually marked pending work.

## 2. Choose a model and its provider

Open **Settings → Models and providers**. Settings are grouped under **Main model**, **Codex**, **OpenAI-compatible provider**, **Ollama**, **Agents**, **Images** and other groups reported by the core. Each ordinary field shows its configuration path beneath its label; this helps identify the exact field if a provider's labels differ.

Choose one of these routes. You do not have to use Codex:

| Main model reference | Provider route |
| --- | --- |
| A bare model name supported by your Codex account | Codex device sign-in below. |
| `compat:` followed by your provider's model ID | An OpenAI-compatible endpoint and its API key. |
| `ollama:` followed by your installed model's name | An existing Ollama endpoint. A remote endpoint may need a bearer key. |

Use the model name supplied by the provider or your test environment, not an example copied from another account. The **Main model** field `llm_provider.model` selects the serving provider from this reference. The `llm_provider.active_provider` field is read-only: there is no separate provider dropdown to override it. Agent and image choices are separate; changing them is not main-model setup.

### Codex device sign-in

1. In **Codex accounts**, choose **Add account**.
2. When the panel shows a verification URL and temporary **Sign-in code**, choose that URL button to open the recognized sign-in page in your browser. **Copy sign-in code** is available if needed.
3. Enter the code on that page and approve sign-in for the intended account. Do not paste account tokens, browser profiles or credential files into Odin.
4. Return to Odin and wait for the account list to update. **In use** identifies the current account. For another listed account, choose **Use this account**. Adding an account and selecting a main model are different steps.
5. In the **Codex** group, check that `openai_codex.enabled` is on. In **Main model**, enter a concrete Codex model name in `llm_provider.model`, then press **Enter** or move focus out of the field to save. Read any error and the saved/running labels before continuing.

**Stop waiting** cancels Odin's wait; it is not a completed sign-in. For a failed login, use **Retry login** when offered. If a code expires or a wait has been stopped, start again with **Add account** when available. **Retry accounts** or **Refresh** reloads an account list; it is not the keyring unlock operation. A stale list is explicitly marked and is not proof your last account change succeeded.

Only the short-lived verification code is intended to be visible. Treat it as private too. Do not screenshot it, account details or credentials for support.

### OpenAI-compatible provider key

1. In **OpenAI-compatible provider**, find the endpoint field `openai_compatible.base_url` and the write-only key field `openai_compatible.api_key`. Use the endpoint and key supplied by the provider or isolated test environment. Do not paste the key into the endpoint, chat or an ordinary text field.
2. Enter the key in its password field marked **New value**, and choose that field's **Save** button. Wait for its receipt or error. The entered value clears after submission, including a failed submission; an empty input does not prove a save succeeded.
3. Set the endpoint to the intended provider's API base URL. Ordinary typed fields save on **Enter** or when focus leaves them. Check `openai_compatible.enabled` and the group's model field `openai_compatible.model` for that endpoint. Toggles save immediately.
4. Set `llm_provider.model` in **Main model** to `compat:` plus that model ID. Read its apply state and the readiness banner. Provider adoption can fail on configuration, authentication or network errors; a failed change is not a reason to keep sending the same request.

There is no universal “enter any provider key” dialog. Use the specific credential field for the provider actually selected. A field such as an auxiliary-provider key does not configure the main provider.

### Existing Ollama endpoint

1. In **Ollama**, set `ollama.base_url` to your existing endpoint and `ollama.model` to the model installed there. This screen does not install or start Ollama, download a model, or create an endpoint.
2. If the endpoint requires authentication, save its key through `ollama.api_key` using the same write-only **New value → Save** route. For a local endpoint that does not require a key, do not invent one.
3. Check `ollama.enabled`, then set the **Main model** field `llm_provider.model` to `ollama:` plus that model's name. Save and inspect the apply state/readiness banner.

An endpoint on another machine or an external provider is network access, even though Odin Desktop runs on this computer.

## 3. If the keyring is locked or missing

Odin stores profile credentials in Linux Secret Service, not a plaintext fallback file. A key field reports **Set**, **Not set**, or **Keyring unavailable; saved value unknown**. Unknown does not mean no key exists.

1. Read the **Provider readiness** banner for the locked/unavailable keyring notice.
2. With the core connected, choose the banner's **Retry** button yourself. This explicit owner action may request the bounded system keyring unlock prompt. Merely opening Settings or refreshing a list does not authorize that prompt.
3. Complete or dismiss the system prompt in the isolated desktop session. If Retry times out while a prompt is still present, resolve that prompt before retrying; do not pile up unlock attempts.
4. Check the new status. Successful Retry refreshes credential state, Settings and accounts. It **does not replay a failed key write or authorize a new device login**. If a key save was rejected, deliberately enter and save it again after recovery. If a command outcome is unknown, follow [Recovery](recovery.md) before issuing another write.

If there is no accessible Secret Service/default collection, Retry can still fail. Odin does not create a missing collection as if an unlock succeeded, and does not fall back to saving the credential in a file. Have the isolated session's keyring repaired/provisioned by its operator, then Retry. A missing keyring is not successful setup.

## 4. Understand the readiness result

| Banner | What it establishes |
| --- | --- |
| **Not configured** | The provider is still at the fresh/incomplete starting point. |
| **Setup incomplete** | The selected provider needs more configuration. |
| **Saved, not effective yet** | Saved choices exist, but the running core has not adopted them or the provider is unavailable. |
| **Ready** | The core has adopted the saved model and provider. This is **not a generation or connection test**. |
| **Provider degraded** | The core reports a provider/keyring problem or cannot confirm provider health. Read the reason. |
| **Readiness unavailable** | No usable current-core readiness projection is available. |

Fields also distinguish **Saved**, **Running**, and **Applies after a restart**. See [Settings](settings.md#saving-and-running-are-different). Do not label setup successful just because the form saved, a credential says Set, or the banner says Ready. In an approved isolated candidate, a harmless request with a completed reply can separately establish that that request ran; it is not a guarantee of future generations. Continue with [Chat and results](chat-and-results.md).

## 5. Choose startup and notification privacy

Choose **Startup and notifications** in the banner, or **Settings → General**:

1. **Start Odin when you log in** is initially **off**. Leave it off unless you want the app to start at login; turning it on is opt-in.
2. **Show message previews in notifications** is initially **on**. Turn previews off if other people can see the desktop. If **Desktop notifications** is off, its preview control is disabled; re-enable notifications only if you intend to use them.
3. Set **Quiet hours** and their start/end times if wanted. Mute or unmute an individual conversation from its **⋯** menu.

These app-local controls are separate from core settings. OS notification acceptance, actual appearance and whether someone saw a message are separate facts. Preview settings do not prevent provider network access or remove saved history. See [Accessibility](accessibility.md) for keyboard/screen-reader use and the acceptance limits.

## 6. Closing is not exiting

Closing the window leaves the app/core running so admitted work can continue. It does not repair an unavailable scheduler or make an unconfigured provider work. To reopen, use the launcher or the tray's **Open Odin** if a tray is available.

There may be **no tray** on your desktop. The app has a one-time notice about continued work, but notification failure does not remove the other routes. Reopen it from the launcher, then choose **Odin → Exit Odin** in the app menu or press **Ctrl+Q**. The packaged launcher's **Exit Odin** action is another route when your launcher exposes it. Exit requests an orderly stop; uncertain cleanup can remain visible on the next start rather than being declared undone. Read [Background work](background-work.md) and [Recovery](recovery.md) before relying on sleep, shutdown or recovery behavior.

## 7. History, attachments and knowledge

Conversation history is stored for continuing/reviewing conversations, not a model-training job performed by this app. That is **not a promise about the provider's retention or training policy**. A configured online model sends request context to that provider; tools, remote SSH targets and integrations can make their own network requests. A local model choice alone is not a blanket local-only guarantee.

Do not put passwords or keys in chat, memory, documents or ordinary Settings fields. Secret-field redaction is not a guarantee that every piece of private prose will be removed. Keep private history, account details and support logs out of screenshots.

- Attach a file to a message for that request using the composer controls in [Chat and results](chat-and-results.md). Adding an attachment is not automatically a knowledge-library import.
- Use **Settings → State → Knowledge** if you deliberately want searchable retained document text. This has its own **Source**, **Text**, **Load a text file**, and **Add** controls; see [Settings](settings.md#state-memory-lists-and-knowledge). Memory is a third kind of retained state, not the same as an attachment or history.
- At this main watermark, knowledge-management storage exists, but the default request engine is not wired to that knowledge store. Do not assume adding a document makes it available to model-side knowledge tools. That wiring is described separately under **pending: #40** in Settings.

## Supported scope and next steps

This is a Linux app with a local, profile-owned core. It can manage configured SSH hosts; it is not a phone app or a remote client for an Odin server, and there is no supported import of an existing Odin installation's configuration, secrets or history. A knowledge text-file upload is not an installation import.

- [Settings](settings.md): providers, tools, hosts, retained state and pending sections.
- [Chat and results](chat-and-results.md): send, attachments, control receipts and evidence.
- [Background work](background-work.md): schedules and work while hidden, asleep or exited.
- [Recovery](recovery.md): failures, unknown outcomes and quarantine.
- [Updates](updates.md): candidate compatibility and release/upgrade boundaries.
- [Accessibility](accessibility.md) and [Linux release checklist](../release/linux-v1-checklist.md): acceptance still required.

## Source evidence and validation limits

Main links are local to this candidate tree: [Settings view](../../app/src/renderer/src/views/Settings.vue), [readiness banner](../../app/src/renderer/src/components/FirstRunBanner.vue), [Codex accounts](../../app/src/renderer/src/components/CodexAccounts.vue), [field controls](../../app/src/renderer/src/components/SchemaForm.vue), [General](../../app/src/renderer/src/views/settings/General.vue), [model-reference parser](../../src/llm/model_ref.py), [runtime readiness](../../src/desktop/runtime.py), [keyring backend](../../src/desktop/secrets.py), [core composition](../../src/desktop/core.py), [management composition](../../src/desktop/management.py), [app lifecycle](../../app/src/main/index.ts).

This draft was checked against source, not by signing into a real account or running a native candidate. Provider success, private real-keyring unlock, OS notification visibility, login startup, tray/no-tray behavior and the complete combined pending-branch build still require isolated candidate evidence and the release gates. Nothing here authorizes testing the active desktop or using another installation's credentials.
