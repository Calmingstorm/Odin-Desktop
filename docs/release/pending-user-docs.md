# Pending user-documentation drafts

**Maintainer-only historical archive. Not the current user guide, current branch
heads, a merged feature list, or release qualification.** These task instructions
are preserved from `docs/user/` at documentation commit `3a83d7f`. Their original
main source watermark was `0b7d596f7e870d06699722f151c4d9837c5433f1`.
Statements about main below describe that historical source, not today's main.
Use [P4.4 validation](../../maintenance/p44-user-docs-validation.md) for the
original source/review watermarks and evidence limits. Its test results do not
qualify a composition of the pending branches.

Move these instructions into user docs **only after the corresponding change is
merged and its actual integrated behavior is verified**. Do not instruct ordinary
users to check out these branches. Candidate procedures belong in an approved
isolated desktop, never the active workstation or live installation as a wording
test. No fixture may stand in for an unavailable real service.

| Pending change | Historical reviewed source, not current head |
| --- | --- |
| #28: skills, MCP, browser, computer management and workspace diagnosis | `2d91071a692a646b6d8c466daa5711a37cd8c93f` |
| #37: background owners, schedules, reports and foreground binding | `4ede9e75fb079a0a305c7b24f89700d7fb7c4416` |
| #39: manual release notice | `1c48529b0af3ad18d9c413882166cb6ee40702d1` |
| #40: account/provider administration, shared knowledge and extended records | `6321eec26e1c87dd5b9682e902723818a5fdda03` |
| #42: ingress and integration privacy | `50f90306176dd2abd724a1a2d5b97199d294b9c8` |

#36 is merged and is deliberately **not** a pending draft here. Its package,
compatibility and replacement instructions belong in the current user guides.
The archive does not supersede their verification or the release checklist.

## Skills, MCP, browser and workspace diagnosis (#28)

The historical main had Skills/MCP screens without their named real-core
management composition. An unavailable panel is the expected boundary, not a
working empty skill library. Runtime skill support and a management UI are
different facts. Do not use fixture sample skills or MCP examples as evidence of
a real loaded library, connected servers or published tools.

#28 adds real browser runtime/activation, computer bindings, Skills and MCP
management adapters, and workspace diagnostics. It does not prove the combined
app/backend matrix, portal consent, receiver-side input release or active-desktop
qualification. Do not treat one pending branch as containing every other branch's
services. A visible field or saved enabled value does not establish a live backend;
computer use still needs supported capabilities, explicit consent and qualified
native ownership, not merely display identifiers. No new owner command approval
or tool/host allowlist is added by these screens.

Use these controls only when the core reports support:

- **Settings → Skills**: read diagnostics before **Open**, editing and **Validate**.
  Validation compiles without executing; saving loads code, and **Test** executes.
  Do not test an uncertain effect as a harmless recovery check. Use the reviewed
  candidate's actual controls and receipts when that service is integrated;
  adding code that executes as a tool is not required first-run setup.
- **Settings → MCP servers**: read state/error. **Reconnect** requests reconnection;
  **Refresh tools** refreshes inventory. Neither proves a previous tool call had
  no effect. Header/environment values are stored but never read back; a blank
  secret field does not prove a lost credential. Server commands/connections can
  run code or make network requests. Follow per-server state/receipts and field
  apply labels. A published-tool limit is not a new owner permission allowlist,
  and saving configuration is not successful server connection evidence.
- **Browser tools**: the branch qualifies configured CDP or bundled Chromium
  before exposing a usable generation. Saved browser settings require restart
  and do not change the boot snapshot. Missing bundled Chromium requires install
  repair, not changing PATH, copying workstation profiles or disabling guards.
  Records has no generic browser repair button. A new session does not replay an
  old click/submission/navigation.
- **Workspace diagnosis**: bounded status observations are read-only and local.
  A partial count is not complete; local Git refs do not establish remote freshness.
  Observation does not fetch, prune, run repairs or clear fences.

Historical pinned sources:
[composition](https://github.com/Calmingstorm/Odin-Desktop/blob/2d91071a692a646b6d8c466daa5711a37cd8c93f/src/desktop/management.py),
[Skills adapter](https://github.com/Calmingstorm/Odin-Desktop/blob/2d91071a692a646b6d8c466daa5711a37cd8c93f/src/desktop/skills.py),
[MCP adapter](https://github.com/Calmingstorm/Odin-Desktop/blob/2d91071a692a646b6d8c466daa5711a37cd8c93f/src/desktop/mcp.py),
[browser runtime](https://github.com/Calmingstorm/Odin-Desktop/blob/2d91071a692a646b6d8c466daa5711a37cd8c93f/src/desktop/browser_runtime.py),
[computer binding](https://github.com/Calmingstorm/Odin-Desktop/blob/2d91071a692a646b6d8c466daa5711a37cd8c93f/src/desktop/computer_binding.py),
[workspace diagnosis](https://github.com/Calmingstorm/Odin-Desktop/blob/2d91071a692a646b6d8c466daa5711a37cd8c93f/src/desktop/workspace_diagnostics.py),
[Skills screen](https://github.com/Calmingstorm/Odin-Desktop/blob/0b7d596f7e870d06699722f151c4d9837c5433f1/app/src/renderer/src/views/settings/Skills.vue),
[MCP screen](https://github.com/Calmingstorm/Odin-Desktop/blob/0b7d596f7e870d06699722f151c4d9837c5433f1/app/src/renderer/src/views/settings/Mcp.vue).

## Native-input limits and recovery (#28 and #37)

These branches do not qualify all promised native backends. #28 exposes management
without foreground input authority; #37 adds foreground binding, not final native
qualification. Enabling a backend, headless tests, a receipt or a status read is
not proof of native input support. Status/background requests never authorize
terminals, credential/security prompts or Odin's control plane.

- **Shared X11:** release depends on a surviving guardian and acknowledged owned
  input cleanup. Abrupt sole-guardian loss can lose its ledger. There is no proven
  universal server-side release guarantee. A missing process does not prove the
  mouse/keyboard released. Stop after unknown release.
- **Hyprland:** release_confirmed may mean only a drained guardian ledger and
  closed local resources, without compositor acknowledgment. This is not compositor
  or receiver proof. Scoped native targets/safe same-process dialogs require fresh
  observations; XWayland or ambiguous surfaces do not become supported by recovery.
- **Quarantine:** RELEASE-ALL, later success, another backend or app restart cannot
  erase unknown release. Hyprland may require retirement of the **exact** recorded
  resources, operator-verified external cleanup and explicit reconciliation before
  a fresh session with renewed consent/observation. Release-only recovery never
  resumes input; partial work must not be replayed.

### Inspect Computer use

1. Open **Settings → Records → Computer use → Refresh**. This is read-only status.
   Note exact session ID, generation, state and recovery reason. On historical
   main the backing computer service was unavailable; do not infer a safe empty
   desktop from unavailability.
2. When the core supplies a quarantined session, the screen may offer **Release…**.
   **Release this session?** asks you to check the computer first and says cleanup
   stays unverified. **Cancel** leaves it unchanged.
3. Do not press Release to dismiss a warning. The renderer sends the exact
   session/generation and `ACKNOWLEDGE UNVERIFIED CLEANUP …`. The returned recovery
   record, not RPC success, determines the outcome. “Closed on your word” is
   attestation, not receiver proof. This is not a universal Hyprland exact-resource
   cleanup/fresh-target wizard. If required steps are not supported by the screen,
   stop and obtain operator help instead of improvising a reset.
4. If cleanup stays unverified or quarantine remains, do not start input. Even a
   released session does not authorize old bindings: obtain newly observed targets
   and required renewed consent, never replay the old action.

Never diagnose a stuck key by injecting another press/release; it can interfere
with a human's actual hold. Safe manual diagnosis uses the affected application's
visible state and platform/resource evidence without new Odin input. Exact cleanup
belongs to a qualified operator. Do not terminate a desktop session, restart a
compositor or indiscriminately kill helpers as a test.

Historical pinned sources:
[Computer use UI](https://github.com/Calmingstorm/Odin-Desktop/blob/0b7d596f7e870d06699722f151c4d9837c5433f1/app/src/renderer/src/views/settings/Records.vue),
[Release payload/outcomes](https://github.com/Calmingstorm/Odin-Desktop/blob/0b7d596f7e870d06699722f151c4d9837c5433f1/app/src/renderer/src/stores/records.ts),
[#28 management boundary](https://github.com/Calmingstorm/Odin-Desktop/blob/2d91071a692a646b6d8c466daa5711a37cd8c93f/src/desktop/computer_binding.py),
[native controller](https://github.com/Calmingstorm/Odin-Desktop/blob/0b7d596f7e870d06699722f151c4d9837c5433f1/src/computer/controller.py).
Qualification remains governed by the
[isolated native-input work order](../work/phase-3-app-v1.md#p35-isolated-native-input-containment-and-quarantine).

## Background kinds, controls and schedules (#37)

In chat, select **Work → Refresh**. The panel groups work by kind and offers only
the controls supplied for that item. **Open conversation …** returns to its
conversation. Closing this panel does not stop work. For schedules, open
**Settings** or **Ctrl+,**, then **Scheduled and running work**. At historical
main the real-core work-list and schedule routes were not wired to those screens:
unavailable is not an empty list or proof nothing is running. Real conversation
requests and Stop/Steer were separate from these pending owners. Saving a webhook
or turn-state field is not proof a timer or running-work list is functional.

| Kind | Meaning | Limit |
| --- | --- | --- |
| Task or workflow | A finite chain of steps, possibly depending on earlier results. | Cancelling does not undo completed steps. |
| Agent | A separate reasoning worker with its own context and possibly child agents. | A correction sent to it is not necessarily read yet. |
| Loop | Repeated reasoning cycles toward a goal, with a limit or stopping condition. | Stopping future cycles does not undo past cycles. |
| Process | A tracked command under its original host/process ownership. | A kill request or missing PID alone does not prove all descendants or external effects are gone. |
| Schedule | A saved time, recurring-time or event rule that starts a supported action. | Pausing the rule does not cancel an already-running action. |

The branch binds records to their original owner, conversation, run and generation.
Controls must not affect a successor with a similar name. Use only the actions
offered for that record: there is no universal Pause, Undo or Restart for all work.

### Read the receipt, not just the button

| Wording | Meaning |
| --- | --- |
| **Sent**, or “sent, waiting for confirmation” | The app dispatched the command and awaits a receipt. This does not establish admission, execution or completion. |
| **Queued** | A follow-up was accepted to wait, or steering guidance entered a mailbox. Steering has not yet been read. A queued follow-up is a separate future request, not guidance to the current one. |
| **Consumed**, or “Odin has read it” | The task read the steering message at a safe boundary. This does not promise the requested outcome. |
| **Confirmed** | The relevant owner confirmed the particular control. For conversation Stop, the target turn settled. It is not an undo or a guarantee that every external effect stopped. |
| **Unknown** | The command or effect's outcome cannot be established. It may already have happened. It is not a safe-to-retry failure. |

Some controls report **requested** before settling, **done** for their particular
operation, or **not available** when the target/action no longer applies. An agent
correction can be queued without consumed; Run now has its own run history. Read
the later work state as well as the initial receipt. A host/helper acknowledgment
proves something about that layer only. It is not proof that the receiving
application saw a keystroke, released a button, or made the intended change.

If a change says “waiting for Odin to confirm” or “outcome unknown,” do not click
again, create a replacement task, or request the same action under a new name.
The app retains the original command identity and can settle a late receipt without
dispatching another action. Refresh/read the existing record instead. Inspect the
actual destination through a **read-only** view and request help with the original
request/run identity, time, error and sanitized observations. Do not retry until
the responsible owner has reconciled the original effect.

### Manage a schedule

1. Open **Settings → Scheduled and running work → New schedule**.
2. Choose a description, destination conversation, action and timing. One-time
   dates must be in the future; recurring timing has a time-zone choice. Resolve
   local-time ambiguity warnings before saving. Do not put credentials in
   descriptions, commands or URLs.
3. Save, then read the returned state and next-run time. Saving is not a run receipt.
4. On an existing row, **Pause/Resume** changes future timing. **Run now** is an
   explicit execution request, not a history refresh. **Runs** reads stored history.
   **Edit** changes the rule; **Set a new time** handles an inert one-time rule
   where offered.
5. **Reset failures** resets bookkeeping, not an unknown-effect fence. **Delete…**
   removes the schedule, not already-completed real-world effects.

The renderer labels run rows “Succeeded” or “Failed”; those broad labels alone do
not distinguish known failure from uncertain effect. Read the error and recovery
record before any retry. The historical deletion dialog says its history goes with
it, but the pinned #37 engine retains schedule history after deletion. Do not
promise erasure based on that dialog.

### Close, sleep, clock changes and Exit: D12

**Window Close is not Exit.** Historical main hides the window and retains its
owned core; reopening the launcher returns to the app. Background work continuing
through that hidden core is the #37 integration, not a separate service. Use tray
**Open/Exit** where present, **Odin → Exit Odin** or **Ctrl+Q**, or the launcher Exit
route. Without a tray, reopen using the launcher to use the window Exit route.

The approved **D12** missed-run policy is:

- An exited app runs nothing. There is no independent daemon, root service or
  lingering scheduler after Exit. Login startup launches the app, not a second
  scheduling service.
- Sleep is not execution. After wake/restart, overdue reminders become one bounded
  catch-up notice, not every missed reminder delivered in a burst.
- Missed actions, including checks and workflows, wait for an explicit user run.
  There is no catch-up workflow replay. Recurring rules move past the missed slot;
  missed one-time actions do not secretly execute later.
- The branch checks due times at startup and while running. A forward clock jump
  can make a slot overdue like sleep; a backward jump can change the wait for a
  future slot. Wall-clock displays are not proof of execution. Read saved run
  history before choosing **Run now**.
- An uncertain reserved run is not an ordinary missed run. Restart, Resume or
  Reset failures must not replay it. Resolve uncertainty first.

Ordinary ticks have a lateness grace; missed-slot counting is bounded and can be
truncated after long downtime. A catch-up notice is not an exact count of all
missed events. Native sleep/wake and packaged lifecycle qualification remain
release gates, not established by unit tests alone.

### Background recovery

Open **Work → Refresh**, or **Settings → Scheduled and running work → Runs** for
the original schedule. Read its existing conversation, work state and error before
using a control. Runs reads history; **Run now** executes. Pause prevents future
schedule firing, not already-dispatched effects. Reset failures does not resolve
an unknown run.

The branch preserves uncertain runs across restart and refuses replay even after
failure-counter reset. An ordinary missed action after sleep/clock jump differs:
D12 waits for an explicit run, while reminders coalesce. Paused alone does not tell
you whether a retry is safe. Agent corrections can be queued without consumed.
Stopping loops, cancelling workflows or terminating processes does not undo
completed steps. Control the original record only; a stale target must not affect
a successor. Do not delete locks, receipts, journals, cleanup files or profiles to
make an error disappear. Restart or recovered connectivity does not resolve old
effects; acknowledging a cleanup notice archives it, not quarantine or effects.

Historical pinned sources:
[work service](https://github.com/Calmingstorm/Odin-Desktop/blob/4ede9e75fb079a0a305c7b24f89700d7fb7c4416/src/desktop/work.py),
[schedules](https://github.com/Calmingstorm/Odin-Desktop/blob/4ede9e75fb079a0a305c7b24f89700d7fb7c4416/src/desktop/schedules.py),
[composition](https://github.com/Calmingstorm/Odin-Desktop/blob/4ede9e75fb079a0a305c7b24f89700d7fb7c4416/src/desktop/core.py),
[due-time recovery](https://github.com/Calmingstorm/Odin-Desktop/blob/4ede9e75fb079a0a305c7b24f89700d7fb7c4416/src/desktop/schedule_recovery.py),
[scheduler](https://github.com/Calmingstorm/Odin-Desktop/blob/4ede9e75fb079a0a305c7b24f89700d7fb7c4416/src/scheduler/scheduler.py),
[uncertain-run tests](https://github.com/Calmingstorm/Odin-Desktop/blob/4ede9e75fb079a0a305c7b24f89700d7fb7c4416/tests/test_desktop_schedule_recovery.py),
[schedule screen](https://github.com/Calmingstorm/Odin-Desktop/blob/0b7d596f7e870d06699722f151c4d9837c5433f1/app/src/renderer/src/views/settings/Work.vue).
See [D12](../design/00-brief.md) and the
[native lifecycle work order](../work/phase-3-app-v1.md#p33-native-lifecycle-trayno-tray-notifications-and-login-startup).

## Reports and evidence expiry (#37)

A conversation summary, saved report and full tool evidence are different records.
The **Kept until** time on tool output is its evidence deadline. Retained tool
evidence has a fixed 24-hour lifetime, per-result/global storage limits, and current
owner/tool/host authorization on each read. Reading does not extend its deadline.
Not every result is retained in full. A surviving summary or receipt does not prove
the original full evidence remains available.

Use offered output-reading/file-save controls before expiry if you need a private
copy. A quota refusal, expiry or scope refusal cannot be repaired by paging harder.
Repeating an effectful command is a new action, not retrieval of old evidence.
Unavailable/expired file references do not guarantee retained bytes; an independent
saved copy must be protected by you.

#37 supplies the real stored-report service behind the existing report view.
Historical main's controls did not prove `reports.page` was available in the real
core. Once a candidate includes that service, use **Previous**, **Next**, **Copy
page** and **Retry** on the named report. These read the stored run, never rerun its
check. **Copy page** copies only the displayed page. There is no report **Save as…**
operation to assume from file cards. A rendering failure does not authorize
repeating its producer.

Report snapshots do not share evidence's 24-hour TTL, but are bounded,
authorization-checked and removed with their conversation. Deletion, explicit
invalidation or changed scope can make a report unavailable while history still
shows its reference. There is no universal 30-day report period or promise of
permanent retention. Use evidence's displayed **Kept until** and unavailable
response rather than applying that deadline to every report.

Historical pinned sources:
[report service](https://github.com/Calmingstorm/Odin-Desktop/blob/4ede9e75fb079a0a305c7b24f89700d7fb7c4416/src/desktop/reports.py),
[report viewer](https://github.com/Calmingstorm/Odin-Desktop/blob/0b7d596f7e870d06699722f151c4d9837c5433f1/app/src/renderer/src/components/ReportViewer.vue),
[tool-output UI](https://github.com/Calmingstorm/Odin-Desktop/blob/0b7d596f7e870d06699722f151c4d9837c5433f1/app/src/renderer/src/components/ToolActivity.vue),
[evidence storage](https://github.com/Calmingstorm/Odin-Desktop/blob/0b7d596f7e870d06699722f151c4d9837c5433f1/src/tools/output_retention.py),
[artifact scope/deletion](https://github.com/Calmingstorm/Odin-Desktop/blob/0b7d596f7e870d06699722f151c4d9837c5433f1/src/desktop/artifacts.py).

## Manual release notice (#39)

In **Settings > General > App version and updates**, the pending UI initially
says **Not checked**. Checking is **manual and opt-in**: select **Check for
updates** when you want an anonymous request to GitHub. There is no default
automatic/background poll and no persistent automatic-check switch in this
implementation.

| Result | Meaning and next action |
| --- | --- |
| A new version is available | A valid published stable version is newer. **Open release page in browser** opens the validated page; it does not download/install an asset. |
| Up to date | Only a successful comparison with accessible, valid stable-release metadata supports this message. It is not a security audit. |
| This app is newer than the latest published stable release | The candidate's product version sorts newer than the accessible stable release. It does not establish release approval. |
| No published stable release is available | No valid stable release was found in a successful response. This is explicitly not an up-to-date check. Drafts and prereleases do not count. |
| Can't check for updates | Private/denied access, offline, rate limiting, invalid/incomplete metadata or an invalid app version prevented a reliable comparison. Do not read this as up to date. |

While this repository is private, anonymous requests cannot read its releases;
the expected result is **Can't check for updates**, even if your browser can
access the repo. Your browser cookies and keyring credentials are not used by the
check. You may visit the fixed
[Releases page](https://github.com/Calmingstorm/Odin-Desktop/releases) yourself.
Use your own browser GitHub session; do not give the app a GitHub token or copy
one from standalone Odin. Retry offline or rate-limited checks later;
checking/opening a link never stops or restarts work, replays effects, clears
quarantine or replaces an executable.

This is a notice only, not an in-app download, staging, install or Apply operation.
The approved unsigned `.deb`/AppImage distribution model is not evidence an asset
exists or authorization to install or publish it. Hash/provenance checks are not
independent signature verification. Replacement remains the current user guide's
external package-manager/manual path after clean Exit and reconciliation.

Historical pinned sources:
[notice service](https://github.com/Calmingstorm/Odin-Desktop/blob/1c48529b0af3ad18d9c413882166cb6ee40702d1/app/src/main/release-notice.ts),
[UI/defaults](https://github.com/Calmingstorm/Odin-Desktop/blob/1c48529b0af3ad18d9c413882166cb6ee40702d1/app/src/renderer/src/components/ReleaseNotice.vue),
[publication limitations](https://github.com/Calmingstorm/Odin-Desktop/blob/1c48529b0af3ad18d9c413882166cb6ee40702d1/maintenance/phase4-releases.md).

## Account refresh and OpenRouter administration (#40)

#40 adds **Refresh sign-in** for a listed Codex account and an **OpenRouter models**
panel under **Settings → Models and providers**. Neither was a historical main
feature at the archived watermark. On a candidate containing that reviewed change:

- **Refresh sign-in** requests the account refresh; read its receipt. It is not
  the first-run keyring Retry or a new **Add account** login.
- **Reload catalogue** reads core-reported models/profiles/eligibility,
  fetched/stale status and errors. Missing measurements are not estimates.
- Supply the provider's **Model ID (author/slug)** and optional **Provider pin
  (blank uses automatic routing)**; **Read endpoints** inspects them. **Select
  model** changes the compatibility-provider configuration. Read the selection
  receipt and main-model/apply state rather than assuming a reply was generated.
- **Read compatibility diagnostic** can report unhealthy or unavailable results.
  A diagnostic failure is not a reason to fabricate a catalogue or read keys back.

Historical pinned sources:
[account UI](https://github.com/Calmingstorm/Odin-Desktop/blob/6321eec26e1c87dd5b9682e902723818a5fdda03/app/src/renderer/src/components/CodexAccounts.vue),
[OpenRouter UI](https://github.com/Calmingstorm/Odin-Desktop/blob/6321eec26e1c87dd5b9682e902723818a5fdda03/app/src/renderer/src/components/OpenRouterAdmin.vue).

## Shared knowledge and learned context (#40)

#40 adds shared knowledge-store composition and knowledge detail routes/UI.
This wiring must not be implied for historical main merely because its State
panel worked. A successful manual Add/search did not establish retrieval during
chat. Shared model-side knowledge wiring alone is not evidence that the separate
attachment **Add to knowledge** ingestion handler has been implemented. An
attachment and an explicitly ingested knowledge document are separate records;
the source label is not an automatically followed path. Existing local knowledge
search is not a promise every future embedding/provider/tool path stays offline.

**Archive correction after #46 merged:** the historical missing attachment-handler
description above is superseded on current main. Checked attachments now select
the existing processing intent, while ingestion remains a model-tool operation.
Shared-store integration still must not be described as an automatic knowledge
write or proof of successful ingestion. See the current claim map in
[P4.4 validation](../../maintenance/p44-user-docs-validation.md).

On that candidate, **Read chunks**, **Find duplicates**, **Read version**, and
**Read diff** inspect core-reported results. Supply the actual listed source/version
identifiers; an unread or unavailable result is not zero duplicates. **Merge
sources…** keeps the named source unchanged and deletes the other, **without
copying content**. It is destructive, not an automatic union of documents.

**Refresh learned context** reads learned entries/metadata. For an existing
**Learned entry key**, select **Change content** and/or **Change category**, enter
the intended changes, then **Update learned entry** and inspect the receipt.
**Delete learned entry…** requires confirmation. Learned context is separate from
explicit Memory and Knowledge entries. Do not infer reflection success or training
from a count alone. Saved memory may enter provider request context; do not store
secrets in it. **Context → Reload context** is a context-file reload, not a model
restart or installation import.

Historical pinned sources:
[shared-store composition](https://github.com/Calmingstorm/Odin-Desktop/blob/6321eec26e1c87dd5b9682e902723818a5fdda03/src/desktop/services.py),
[knowledge routes](https://github.com/Calmingstorm/Odin-Desktop/blob/6321eec26e1c87dd5b9682e902723818a5fdda03/src/desktop/knowledge.py),
[Knowledge details/Learned context UI](https://github.com/Calmingstorm/Odin-Desktop/blob/6321eec26e1c87dd5b9682e902723818a5fdda03/app/src/renderer/src/components/KnowledgeDetails.vue).

## Extended records and observability (#40)

#40 adds record inspection/export, observability routes and tool trajectory
details, not historical main. Those panels expose runtime/recovery statistics,
recent recovery, capacity-breaker state and SSH/HTTP pool observations as reported,
not fabricated estimates. **Close host pool…** and **Close all pools…** close SSH
connections with confirmation; HTTP pools are unchanged, and new work can open
new connections. They do not revoke a host's trust or undo commands.

Read availability/error and timestamp. Usage distinguishes measured, estimated
and unknown values. Audit search/verification is scoped to available records;
not enabled, partial/unsigned coverage and failed verification are not a complete
verified record. Integrity verification is not correctness or receiver proof.
Turn state concerns durable checkpoints, not proof an effect was rolled back.
Export/inspection output can still be sensitive despite secret scrubbing: share
only sanitized material, never credential/history screenshots. Preserve the
original request/run identity and distinguish facts from guesses. Report **Copy
page** copies one page; evidence may expire while its summary survives. Do not
rerun a command to recover expired output.

Historical pinned sources:
[record routes](https://github.com/Calmingstorm/Odin-Desktop/blob/6321eec26e1c87dd5b9682e902723818a5fdda03/src/desktop/records.py),
[observability routes](https://github.com/Calmingstorm/Odin-Desktop/blob/6321eec26e1c87dd5b9682e902723818a5fdda03/src/desktop/observability.py),
[Record details UI](https://github.com/Calmingstorm/Odin-Desktop/blob/6321eec26e1c87dd5b9682e902723818a5fdda03/app/src/renderer/src/components/RecordDetails.vue),
[Observability UI](https://github.com/Calmingstorm/Odin-Desktop/blob/6321eec26e1c87dd5b9682e902723818a5fdda03/app/src/renderer/src/components/ObservabilityDetails.vue),
[Trajectory details](https://github.com/Calmingstorm/Odin-Desktop/blob/6321eec26e1c87dd5b9682e902723818a5fdda03/app/src/renderer/src/components/TrajectoryDetails.vue).

## Incoming integrations, uncertainty and privacy (#42 and #37)

An incoming webhook delivers an event to an explicitly configured listener and
matching schedule. It is not a phone/server client, remote-management API, import
of another Odin install, or permission for an external sender to operate Desktop.
Managed SSH tools are a separate supported host feature. #42's listener is
distinct from #37's work/schedules and historical main's outbound target settings.
Do not expose a candidate listener as a remote administration endpoint.

The pending listener accepts eligible enabled trigger schedules with required
source authentication. Disabled, unconfigured, unbound and accepting are different
states. Bind failure does not choose a fallback address. Exit closes the listener;
unknown handoff is retained and that internal receipt is fenced against automatic
replay. It does not pause the valid trigger or future authenticated deliveries.
Each new delivery has a new identity; identical bodies and provider retries can
execute again. An HTTP delivery acknowledgment is not proof of a resulting
workflow's success at its receiver.

### Diagnose an incoming integration failure

Distinguish an unavailable/unbound listener from an accepted event whose handoff
is unknown. Do not redeliver a payload to diagnose uncertain acceptance. The branch
retains the unknown internal receipt without replaying it, but does not pause the
valid trigger or future authenticated deliveries. Identical bodies and provider
retries are new deliveries and may execute again; receipt recovery is not body
deduplication or exactly-once external effects. Interrupted scheduled runs follow
their separate one-time/recurring recovery rule. Inspect the existing conversation/
schedule instead. This listener is for integrations, not remote management; do not
publish/open an endpoint as a repair.

### Keep payloads and destinations private

Payloads and outgoing subscriptions can contain private project, conversation or
result information. Check destinations and event choices before enabling them.
Authentication does not make payload text owner instructions. Use supported secret
fields, not secret-bearing listener/destination URLs. Do not share signed URLs,
raw payloads, headers or config exports. Redaction does not remove all private
content. The reviewed outbound code stores credential-bearing URLs privately in
the keyring and returns a public projection; that is not permission to expose
the original URL. No general-purpose remote access setup is documented here.

Share sanitized source type, delivery time, status and record IDs only, not raw
payloads, signing secrets, authentication headers or secret-bearing URLs.

Historical pinned sources:
[ingress/listener recovery](https://github.com/Calmingstorm/Odin-Desktop/blob/50f90306176dd2abd724a1a2d5b97199d294b9c8/src/desktop/webhooks.py),
[outbound privacy](https://github.com/Calmingstorm/Odin-Desktop/blob/50f90306176dd2abd724a1a2d5b97199d294b9c8/src/desktop/integrations.py).
See the [integration work boundary](../work/phase-3-app-v1.md).

## Promotion checklist (maintainer-only)

- [ ] Confirm the relevant change is merged. Record the actual integrated main
  commit and changed source identities; do not replace historical pins silently
  or call them current heads. Consult
  [P4.4 validation watermarks](../../maintenance/p44-user-docs-validation.md).
- [ ] Trace each task, exact label, receipt, service binding and apply/restart
  rule to that integrated implementation. Check unavailable behavior using the
  real core; fixture success is not composition evidence.
- [ ] Verify the relevant combined dependencies, not each branch in isolation:
  #28/#37 native ownership, #37 reports/schedules and #42 handoff, #40 shared
  request knowledge versus the separately missing attachment-ingestion handler.
- [ ] Verify failure and recovery wording, including unknown outcomes, exact
  owner/run/generation fencing, no replay, native release limits, receipt-local
  webhook uncertainty, report/evidence retention and deletion privacy.
- [ ] Verify the actual procedures in an approved isolated candidate. Native
  provider/keyring/SSH/input, sleep/wake, packaged lifecycle, notification/login
  and accessibility evidence remains separate from source review and unit tests.
  Never use the active workstation to qualify a draft without immediate approval.
- [ ] Retain private-repository can't-check states, manual-only release notice,
  unsigned external replacement limits and truthful unavailable/unknown states.
  Do not turn a missing service into an empty successful result.
- [ ] Move only verified tasks into the appropriate `docs/user/` guides. Link
  current guide references to the new reviewed source watermark; retain this
  archive's historical provenance and document any superseded instructions.
- [ ] Update validation/navigation/release gates without borrowing old branch
  tests as a combined runtime pass. P4.5/P4.6 and Aaron's separate approvals in
  the [Linux release checklist](linux-v1-checklist.md) are not waived by promotion.

This file preserves task text for later verification. It grants no deployment,
publication, installation, native-input, live-desktop or external-effect authority.
