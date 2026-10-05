# Odin Desktop: internal engine and surface contracts

Owner: Odin. Round 4, 2026-10-04. Proposed design, not implementation authorization. D1-D6 are settled.

## 0. Status, evidence and scope

This document specifies the six seams agreed in [round 2](../discussion/03-claude-round2.md), revised for [Aaron's decisions D1-D6](00-brief.md#aarons-decisions-2026-10-04-after-round-1). They are boundaries **inside Odin Desktop**, between its copied-and-maintained engine and its desktop surface. There is no shared core package, dependency on an Odin checkout, or extraction campaign in the Odin repository (D4). Historical shell and extraction recommendations in [04-odin-round2](../discussion/04-odin-round2.md) are superseded where they conflict. [maintenance.md](maintenance.md) defines bring-over, baseline tracking and dual maintenance.

Source references are relative to Odin **`cd7530906e9cfa10a0fa900247d7ce2a8bb33e25`**, the inspected round-1 baseline. A read-only Git check this round found `/opt/odin` still at that commit; round 4 also inspected its inbound receiver and scheduler admission paths. Claude's spot-check of `3849d917` is additional evidence supplied by Claude, not a checkout I inspected. Research in this round was static source/design reading. No code, imports, tests, installations, endpoint probes, configuration changes or service operations were performed.

**Existing** means the cited source supplies that part of the behavior. **New** means infrastructure or adaptation in the Desktop repository is required. Each seam has an evidence map; its proposed contract is not observed desktop behavior. All features and execution behavior carry over, including agents, anti-hedging, continuation and guards (D2), except the explicitly irrelevant social/multi-user machinery identified in the reuse map. New durability/presentation boundaries must not silently change the engine's budgets, guard dispositions or continuation rules.

**Scope limits.** First versions run a local app-owned engine. There are no user-data import/migration paths (D5), server-client mode, phone client or network listener for remote access (D6). The optional, narrowly authorized inbound-trigger listener in section 8 is an integration ingress, not a remote client or general control API; its scope still needs Aaron's choice. Versioned domain/transport seams leave room for a separately designed remote protocol later; they do not qualify authentication, reach parity or remote recovery today. Managed-host SSH execution remains an engine capability and is not remote access to the app. Desktop has fresh state and credentials, independent of an alongside Odin installation; normal Desktop schema upgrades are not imports from Odin.

### Common domain vocabulary

| Type | Fields and meaning |
|---|---|
| Installation identity | Stable `installation_id`; distinguishes Desktop from an alongside server. Never inferred from a source directory or port. |
| Profile identity | Stable `profile_id`, authenticated `owner_id`, isolated config/data/secret namespace and storage identity. One core owns a profile at a time. |
| Runtime identity | Fresh `core_instance_id` and ownership epoch for each core incarnation. A PID alone is not identity. |
| Execution endpoint | Stable local Desktop `endpoint_id`, profile and negotiated capabilities. Future remote-engine identity is reserved, not a first-version feature. A managed-host execution target is separate; disconnected hosts never become local. |
| Conversation identity | Stable `conversation_id`, monotonic mutation revision, optional parent and inheritance snapshot. Names are presentation, not identity. |
| Submission identity | Client-generated unpredictable `client_submission_id`, scoped to endpoint/profile/conversation, immutable once admitted. Not a content hash. |
| Message identity | Core-issued `message_id`, revision, role/provenance and originating submission/request. |
| Request identity | Core-issued `request_id`; generation, lease and revision fence execution ownership. Resumed lineage retains identity but obtains a new live lease. |
| Operation identity | Unique `invocation_id`, originating request/background run, parent invocation if nested, tool and target binding. Retrying cannot erase prior uncertain dispatch. |
| Background identity | Stable task/schedule/loop/agent identity, distinct run/iteration identity and core-owned destination. |
| Reference | Opaque artifact, evidence, report or cursor reference with scope, availability and retention metadata. Possession is not authorization. |

Persisted deadlines use UTC; live elapsed time/budgets use monotonic clocks. Event order uses sequence numbers, not timestamps. Fencing IDs/hashes are not user credentials or capabilities.

All Desktop surfaces use the copied guard/classifier/validation stack. **D1:** the Desktop personality/system templates remove Discord references using the exact wording Aaron approves in [prompt-changes.md](prompt-changes.md); every other byte stays unchanged. This replaces blanket byte preservation, not D2's behavioral preservation. The adapted history-read tool is **`read_conversation`**, reading the authenticated request's current visible conversation; prompt line 97 can therefore use that name. Other model-facing wording is inventoried separately in [06-odin-round3](../discussion/06-odin-round3.md). Guard/classifier wording substitutions also require Aaron's approval; no global search-and-replace or weakened guard is authorized. Accurate adapter metadata is not permission to add always-on desktop instructions; new tool guidance belongs in tool descriptions. Baseline: `src/llm/system_prompt.py:16-34,66-134` and `src/discord/tool_loop.py:2517-2700`.

### Common error and uncertainty vocabulary

Responses identify the command/entity and separate **admission**, **execution settlement**, **storage**, and **delivery**. One success boolean cannot represent all four.

| Disposition | Required meaning |
|---|---|
| `rejected` / `not_dispatched` | This boundary did not admit/dispatch the named operation. Not proof that an earlier attempt did nothing. |
| `accepted` / `queued` | Durable admission/queueing occurred. Execution, consumption and delivery remain unproven. |
| `running` / `stop_requested` | Work has a live lease, or cancellation was requested. Neither is terminal success. |
| `settled` | Named outcome is known. Publish actual success/failure, exit code where applicable, validation and cleanup evidence separately. |
| `outcome_unknown` | Dispatch may have occurred and effects cannot be established. Preserve ambiguity; no automatic replay or erasure by later success. |
| `suspended` | A supported checkpoint is preserved. Not proof every agent, process or loop can resume. |
| `storage_unavailable` | Required durable admission/checkpoint/publication is unestablished. Do not acknowledge commit or fall back to unledgered execution. |
| `stale_binding` | Expected request/revision/generation/host/consent no longer matches. Refuse; do not retarget a successor. |
| `capability_unavailable` / `incompatible` | Operation unsupported or version cannot satisfy its contract. No silent weaker substitute. |

Errors contain bounded scrubbed explanations and typed reasons, not tracebacks, credentials, raw prompts or bearer tokens. Transport timeout means the client lacks a receipt; it does not determine execution outcome.

**No general exactly-once external-effects guarantee.** The core deduplicates admission, records intents and refuses unsafe replay. It cannot atomically commit a remote deployment and its own SQLite row. The UI preserves that distinction.

## 1. Request envelope

### Type and ownership

The UI submits a **Submission**, not an execution-authority object. The authenticated adapter constructs the admitted **RequestEnvelope**.

| Field group | Contract |
|---|---|
| Identity | Endpoint/profile/conversation and client submission ID; core-issued message/request IDs after admission. Transport IDs are correlation only. |
| Content | Scrubbed admitted text and ordered attachment references. Image-only requests are valid with the existing honest placeholder behavior. |
| Provenance | Authenticated owner; surface; foreground/background origin; reference to actual human submission/configured task. History, tool output, model text and bot messages cannot assert human authority. |
| Context | Conversation revision at enqueue, reply target, optional parent snapshot, explicit follow-up disposition. Record execution-start context revision separately. |
| Selection | Explicit execution endpoint and requested host/workspace/model defaults. Client preferences are validated, not trusted identity/grants. |
| Authority | Core-derived tool scope, target/host-trust generation, config/policy revision, origin restrictions and separately obtained computer-consent binding. Never imported from model history. |
| Recovery | Immutable admitted-content/attachment digest, code/codec policy metadata, deadline and generation. Digest detects changes; it is neither identity nor authority. |

Core owns validation, secret screening, attachment adoption, IDs, duplicate decisions, queueing and execution admission. Renderer owns drafts. Optimistic local messages remain pending until matched to core-issued messages.

### Invariants and admission

1. Record submission, visible input and execution identity durably before acknowledging acceptance. Required storage failure blocks a new effect-capable turn. Desktop does **not** silently inherit today's optional startup-time legacy/no-checkpoint fallback.
2. Same submission ID and semantic payload returns original identity/current receipt. Same ID with different text, attachments, target or intent is a conflict, not an edit/second execution.
3. Resolve lost acknowledgements by lookup or resending the **same** ID. Reconnect, transport recovery or restart cannot mint a replacement automatically.
4. Retain minimal admitted-ID tombstones for the profile's lifetime, including after visible deletion, without retaining deleted message bodies just for deduplication. A complete profile reset changes profile/journal identity and rejects old-profile submissions. If bounded tombstone retention is later needed, first introduce core-issued admission epochs with explicit expiry and reject retired epochs. Arbitrary client IDs alone cannot distinguish a forgotten old submission from a fresh one; do not promise otherwise. Deliberate new requests use new IDs.
5. One foreground turn owns a conversation at a time. Other conversations can progress concurrently; cross-conversation filesystem/process/GUI ownership still applies.
6. Follow-up, steering and retry are distinct intents. Ordinary draft text does not silently become steering because a turn started elsewhere.
7. Queued requests retain identity and endpoint/target selection. Recheck current policy and record context watermark at start; no silent host/workspace substitution.

### Attachment adoption

- Native picker/drop broker transfers bounded copies into profile-owned staging. Renderer cannot supply an arbitrary host path for core reading.
- Descriptor: opaque ID, safe display name, media classification, byte size, digest, readiness/error state and supported interpretation. Adoption freezes an owned copy; later source edits cannot alter admitted input.
- Enforce per-file **and aggregate** limits, count, extraction limits, quotas and transfer cancellation. Publish sizes/formats before execution; preserve archive path/link defenses and bounded PDF/text extraction.
- Cancellation before adoption leaves no runnable request. After acceptance, transfer cancellation is not turn cancellation. Cleanup cannot delete adopted artifacts referenced by work.
- Audio/video storage/playback is not comprehension. Dependency and vision support remain honest.
- Knowledge ingestion is a separate explicit action. Attaching does not authorize ingestion, activation or dependency installation without the relevant action.

### Evidence map

| Existing at baseline | New or adapted |
|---|---|
| Secret/duplicate intake: `src/discord/intake_pipeline.py:162-211,279-282,370-386`; attachments: `src/discord/attachments.py:181-250,276-363,365-546`. | Native staged copies, aggregate limits, durable submission IDs and neutral provenance. Current duplicate cache is not persistent protocol. |
| Conversation lock: `src/discord/intake_pipeline.py:465-470`; owned cancellation/inboxes: `src/discord/channel_state.py:82-115,133-170`. | Client expected bindings, durable queueing, endpoint/profile isolation. |
| Intent/result/checkpoint invariants: `src/turn_state/durability.py:9-32`; triple fencing: `src/turn_state/store.py:9-37`. | Required desktop durability/native IDs. Current loop admits checkpoints only for Discord: `src/discord/tool_loop.py:1254-1272`. |

## 2. Conversation service

### Types and owned stores

| Type | Required contents |
|---|---|
| Conversation | Identity, title, lifecycle, revision, endpoint/profile, parent/snapshot, target defaults and unread watermark. |
| Visible message | ID/revision, provenance, admitted input or committed assistant/system result, commit sequence, request/run linkage and artifact/report references. |
| Context snapshot | Compacted model-session state, context watermark, inheritance origin and selected bounded material. Not the visible transcript. |
| Transcript projection | Messages, safe tool/control cards, report revisions and artifact availability through a stated journal watermark. |
| Artifact | ID, producer, conversation/request scope, MIME/name/size/digest, availability, retention and access policy. |

Core owns model context, transcript, artifact storage and event publication. They may share transactional storage but are not interchangeable. Audit/effect ledgers remain separate safety records with separate retention.

### Invariants

- Compaction cannot truncate visible messages, controls or delivered files. Reload reconstructs committed transcript independently of model history.
- History is data, not current instructions. Inheritance/artifacts cannot confer authority. D5 excludes importing another installation's history or memories.
- `read_conversation` is the Desktop equivalent of `read_channel`: bounded, scrubbed recent visible messages from the current authenticated conversation, including its recorded role/provenance, for model context rather than republication. The request supplies identity, never a model-selected foreign conversation ID. Cross-conversation `search_history` retains its explicit profile-scoped search contract. Stored tool text and past messages remain untrusted historical data.
- Branch names a parent message/cutoff and coherent snapshot at a stated revision. Label inherited material. No live synchronization, tool replay or GUI-consent transfer.
- Current thread seed is summary plus bounded recent messages. Historical 'branch from here' needs a **new cutoff-aware** snapshot builder; current summaries may contain later messages.
- Search must index visible transcript, not only compacted sessions. Reuse search machinery with stable message IDs, endpoint isolation and retention/deletion-aware indexing. Snippets/previews are scrubbed.
- Model reset, archive, visible-history deletion and artifact deletion are distinct revision-bound operations. None implicitly stops work or deletes unresolved-effect records.
- Deleting destinations with active work/schedules needs explicit cancel/pause/rebind. Preserve a tombstoned inbox for late results; never send them to the currently selected conversation.
- Restart restores records/definitions, not asyncio tasks. History alone cannot authorize agents/loops/workflows to execute again.
- Read state advances to acknowledged/displayed watermarks. Notification acceptance is not a read receipt.

### Artifact and retention boundary

Visible message/artifact retention is product policy, separate from fixed 24-hour tool evidence. Cards report evidence expiry. Explicit authorized promotion copies bytes/provenance to durable storage; it does not make a cursor permanent or bypass live output authorization. Establish retention before promising files survive reopening.

Raw artifacts may contain secrets/executable data. Preview never executes. A scrubbed display is not a byte-faithful download; label it while protecting explicitly adopted originals. Deletion follows store/backup policy, not guaranteed forensic erasure.

Evidence references declare namespace, source invocation, scope, expiry, digest, offset unit and continuation state. Preserve Unicode code-point text offsets versus binary byte offsets; process spools have their own generation/cursor API. Raw file reads preserve their framed source interval and exact bytes. Transcript rendering cannot silently reinterpret a raw-file envelope or use a head/tail preview as contiguous evidence.

### Evidence map

| Existing at baseline | New or adapted |
|---|---|
| Sessions/compaction/persistence: `src/sessions/manager.py:523-533,1095-1116,1797-1826`; threads: `src/discord/intake_pipeline.py:471-508`. | Full transcript/artifact store, stable IDs, cutoff snapshots and native CRUD. |
| Search: `src/sessions/manager.py:1509-1525,1628-1655`; reload loses files/cards: `ui/js/pages/chat.js:433-461`. | Visible-message index, projections/catch-up and unread watermarks. |
| Separate safety store: `src/turn_state/store.py:1-37,84-108`; expiry/authorization: `src/tools/output_retention.py:88-134,186-219`. | Retention classes/authorized artifact adoption; deletion cannot erase unknown-effect safety records. |

## 3. Delivery sink and event protocol

### Delivery operations

Sink serves foreground turns, schedules, workflows, loops and permitted skills **without a renderer/window connection**, while the app and its supervised core run. Exit ends that execution lifetime; no independently running daemon is implied. Publications have immutable producer identity and idempotency key.

| Operation | Fields and semantics |
|---|---|
| Commit message | Destination, request/run, producer key, role/provenance, complete guarded text or typed core status, artifact references. Returns ID/revision/durable cursor. |
| Revise projection | Message/report ID, expected revision, producer and projection. Progress-card edit is not rewriting a final assistant claim. |
| Publish artifact | Owned immutable bytes/reference, scope/metadata; storage receipt before claims of delivery. Explicit failure never triggers replay. |
| Publish report | Stored projection, ID/revision/pages. Paging/refresh reads saved results; rerun is a distinct effect-capable command. |
| Notification intent | Destination/message/cursor, category, scrubbed private preview and deduplication key. Persist first; native adapter consumes later. |

**Assistant text becomes visible only after the existing guard/classifier path admits its final disposition.** Provider deltas/discarded candidates never cross ordinary presentation. Failure/suspension/stop notices are typed. Accepted provider-incomplete results are labeled incomplete, not successful finals.

Tool cards contain scrubbed arguments/evidence and code-owned outcome provenance. Invocation completion, exit zero, passed validation and task completion are different facts. No reasoning, full prompts or guard-rejected prose is published as live progress.

### Event envelope

| Field | Meaning |
|---|---|
| Event ID/type/schema | Stable identity, typed payload. Unknown required schema/features are incompatibility, not guessed text. |
| Endpoint/profile/stream | Scope and journal lineage; prohibits replay into another install/reconstructed store. |
| Sequence/opaque cursor | Monotonic per-profile durable commit order. Cursor is position, not permission. |
| Entity ID/revision | Conversation/message/request/invocation/report/run affected, with parent linkage. |
| Producer/command correlation | Derivation from actual work, enabling idempotent reconciliation. |
| Core incarnation/time/payload | Incarnation for liveness; UTC occurrence/commit times; bounded scrubbed content or authorized references. Time does not establish order. |

Filtered subscriptions see gaps in profile-global sequence numbers by design. Advance using the core's scanned watermark, not an assumption that event numbers are consecutive. Only core interprets/issues cursors.

### Durable event families

| Family | Events and critical distinction |
|---|---|
| Input | `submission.accepted/rejected`, `message.committed`, `request.queued/started`. Rejections retrievable by command identity where safely recordable. |
| Work | `tool.intent_recorded`, `tool.started/settled`, `validation.recorded`, `agent/task/loop/schedule.state_changed`. Settlement separates success/failure/unknown and cleanup/validation. |
| Controls | `control.receipt`, `steer.queued/consumed/closed`, `request.stop_requested`, `resume.admitted/rejected`. |
| Turn | `request.completed/failed/cancelled/suspended/interrupted`, linked to authoritative terminal/checkpoint records. Unknown operations remain visible even for terminal turns. |
| Deliverables | `artifact.published/unavailable/deleted`, `report.published/revised`, `message.committed`, notification intents/receipts. |
| Runtime | Readiness/config/capability revisions and durable interruption/recovery notices. |

Design names, not today's vocabulary. High-rate process output, in-flight metrics and liveness may be **non-durable telemetry**, explicitly labeled with separate sequence/gap metadata. Missing telemetry cannot change settlement. No draft assistant prose in telemetry.

### Ordering, persistence and reconnect

1. Entity/transcript mutations and journal events commit atomically in a shared store. Across checkpoint/task stores, use durable producer outboxes with stable keys and idempotent journal adoption. No fictional cross-database transaction.
2. Tool intents/checkpoints are durable **before dispatch**, results afterward, guard state before continuation. UI journal projects authoritative facts; it is not the safety ledger.
3. Crash between effect and result record leaves unknown settlement until reconciliation. Crash between final settlement and publication repairs via outbox, not tools rerunning or an accepted answer regenerating.
4. Client delivery is at-least-once; deduplicate event IDs and apply revisions monotonically. Command/publication admission is once per idempotency key, not once per event delivery.
5. Reconnect authenticates same endpoint/profile and presents last applied cursor. Establish snapshot/catch-up high watermark and tail-subscription barrier so no race drops events.
6. Catch-up is bounded/paginated. Slow consumers never block persistence/runner. Disconnect overrun clients with resume position; retain facts and label telemetry gaps instead of unlimited buffering.
7. Stale/expired/wrong-lineage cursors receive reset-required. Supply authorized snapshot at new watermark then tail. Never imply the missing interval was empty.
8. Journal pruning follows documented retention/snapshot coverage; transcript/artifact and submission/effect tombstones have independent retention.

### Delivery receipts

| Receipt | What it proves |
|---|---|
| Core commit | Message/artifact/report durable and fetchable under current policy. Not human visibility. |
| Client applied | Named client applied through cursor. Not attention or all conversations read. |
| Read watermark | User-facing view acknowledged a conversation position. Independent of execution. |
| Notification requested/accepted/failed | Native submission outcome only. OS acceptance is not display/reading proof. |

Publication failure is never 'delivered'. If effects already ran, preserve separate settlement/unavailable-publication status when possible; halt further effects if required storage broke. Do not replay to obtain a prettier card. Core ownership/durable inbox readiness, not renderer connection, governs destinations.

### Evidence map

| Existing at baseline | New or adapted |
|---|---|
| Discord retries/splitting: `src/discord/delivery.py:28-62,270-332,381-497`; web capture: `src/web/chat.py:81-126,306-342`. | Neutral sink, keys, full messages, durable artifacts/destinations. Web capture is transient. |
| Stream attribution/settlement: `src/tools/output_streamer.py:44-65,208-238,274-419`; result metadata: `src/tools/result_validator.py:84-136`; uncertainty: `src/tools/execution_outcome.py:8-24,27-68`. | Scoped bounded/redacted presentation, journal/catch-up and separate transient feed. |
| Saved paging: `src/discord/scheduled_report.py:514-588`; channel callbacks: `src/discord/scheduled_events.py:490-611`; skills: `src/tools/skill_context.py:205-225`. | Native durable destinations/reports/inbox/notifications. |
| Guards: `src/discord/tool_loop.py:2517-2700`; terminal durability: `src/discord/tool_loop.py:848-887`. | Final publication barrier/outbox recovery. Preserve current budgets/behavior; guards are not universal factual certification. |

## 4. Control service

### Command binding

Mutating controls carry unique `control_command_id`, endpoint/profile/conversation, **expected request ID and generation**, and applicable revision for compare-and-set. Broker/core authenticates actor. Receipt names exact command/target; no 'whatever is running now'. Duplicates return existing receipt/state.

Control admission stays responsive during long provider/tool waits. Stop cannot wait behind the foreground lock it interrupts. Atomic control/runner ownership checks protect successors.

### Stop

- Compare binding, mark cancellation for that owner, return `requested`. Already-ended and stale-target differ; neither cancels a successor.
- Inhibit further generation/effects and settle owned helpers/agents/input under existing rules. Stop does not undo email/patch/deployment.
- Settlement separately records foreground cancellation, terminal persistence, unresolved effects and resource release. 'Confirmed' is scoped, not 'everything undone/all remote children gone'.
- Bounded wait returning pending/unknown is not failure to send stop. Later journal settlement remains observable; no missing-receipt replay or broad process kill.
- Detached processes/schedules/workflows/loops have separate cancel identities. Foreground stop is not 'kill every profile task'; list what continues.
- Safe protective cancellation/release is attempted even with broken storage. Report unpersisted/unconfirmed cleanup; storage failure is not permission to keep injecting. Unknown release retains quarantine.

### Steer and follow-up

- Bounded FIFO to expected request, consumed at safe boundaries. Preserve initial 4,000-character/item and 128-item/turn limits.
- Queued means **not consumed**. Consumed names sequence and continuation/checkpoint. Closed means unconsumed at termination/interruption.
- Desktop queueing is durable. Consumption/recovery state commits before generation continues. Crash-queued items are surfaced as interrupted/closed pending explicit recovery, never applied to a successor.
- Steering can revise goals, not elevate tools/hosts, revive consent or reset guards/budgets. Preserve secret screening/provenance.
- Follow-up is a separate admitted submission. Visible enqueue/start/cancel receipts. Proposed default: FIFO after known normal terminal outcome; pause behind suspension, unknown effects or explicit stop for owner choice. Never turn suspension into a fresh request silently.

### Guarded resume

Resume binds preserved request/generation/checkpoint revision, not 'send prompt again'. Check:

1. Original input/attachment snapshots exist, same owner and immutable revision/digest. Distinguish deletion/change/unreadable/transient unavailable.
2. Compatible checkpoint/schema and remaining deadlines/budgets. Restore consumed guard flags, validation and continuation counts; relaunch grants no fresh budget.
3. Re-derive current tool/platform/host/security policy. Serialized authority cannot revive access. Reconstruct fallible state before single-winner lease acquisition.
4. No unresolved dispatch ledger entries. Applied results reconstruct evidence; unknowns require reconciliation/manual resolution, not new invocation IDs.
5. Retire GUI observations/consent across interruption. Renew only under existing release/quarantine rules. Background recovery cannot become foreground input.

Rejected resume never falls through into fresh effects. Admitted resume uses the **same** guarded runner. In-process capacity auto-resume retains exact conversation-revision checks; core restart is explicit-only. This is not automatic restart-resumption of agents/workflows/loops/processes.

Manual resolution is separately authorized/evidence-recorded. 'Clear error', later success or RELEASE-ALL cannot erase unknown effects/input release.

### Evidence map

| Existing at baseline | New or adapted |
|---|---|
| Owned request/stop: `src/discord/channel_state.py:133-170,238-316`; wait: `src/discord/slash_commands.py:503-539`; durable receipt gate: `src/discord/tool_loop.py:848-887`. | Expected client binding, durable command IDs and typed settlement/resource facts. Current controls resolve channel owner server-side. |
| FIFO/limits/closure: `src/discord/channel_state.py:35-65,172-236`; consumption: `src/discord/tool_loop.py:477-488`; classifier steering: `src/discord/tool_loop.py:2622-2647`. | Persistent queue/receipts/crash dispositions, explicit composer modes. Inbox today is process-local. |
| Explicit/auto distinction: `src/discord/turn_resume.py:1-27,118-205`; unknown rejection/rebuild: `src/discord/turn_resume.py:377-437,441-548`. | Native original lookup, IPC binding and compatibility instead of Discord fetch/tier checks. |

## 5. Runtime service

### Runtime view and ownership

Snapshot contains core/profile/endpoint, versions/protocol range, storage/ownership readiness, workloads, configuration/capability revisions, providers and native-session availability. **UI connected is not core ready; core running is not provider ready or input permitted.**

Phases: starting, ready, degraded, quiescing, stopped, interrupted/recovery-required. Degradation names unavailable capabilities. Required durability/ownership/fencing failure blocks new effects; losing UI does not.

Core owns scheduler/executors/providers/managers/stores/outbox. UI windows never create second engine graphs. Per-profile lock and handshake validate installation/profile/storage before boot sweep/scheduling. Stale PID, unknown socket occupant or inaccessible lock never authorizes deleting another core's resources.

### Lifecycle

| Event | Contract |
|---|---|
| First launch | App creates isolated profile/storage/credentials and starts its supervised core child. Explicit login-startup/privacy choices; no server-data/environment reuse or user-data import. |
| Second launch | Authenticate/focus the existing app main process, which owns the core connection. No independent core attachment, competing core on the stores, or deletion of an unknown occupant. Incompatibility refuses use. |
| Close window | Hide/destroy presentation only; app main process and core continue turns/background work into the durable inbox. Tray normally reopens. Without tray, relaunch focuses the app; Exit is in the window menu and launcher's actions, with a one-time close notice. No window-lifetime mode. |
| Exit Odin | Tray right-click Exit, window-menu Exit and launcher Exit are the same app-owned shutdown command: stop admission, drain/cancel under bounded policy, checkpoint, release owned children/input and flush, then exit. Pending/unknown cleanup remains visible and is preserved for next start; Exit is not undo or permission to erase quarantine. No independent background daemon remains. |
| Login/startup | Opt-in per-user app launch, normally minimized; app starts the core. Keychain/session readiness is negotiated. No separate core autostart, system service, linger or boot-before-login mode. |
| Sleep/offline | No execution while asleep. Re-evaluate deadlines/leases/settlement on wake; no fabricated runs. Locked/absent graphical session cannot renew input. |
| Core crash | While the app main process remains alive, it may perform bounded supervised recovery after ownership/storage reconciliation. Preserve and show interrupted/unknown records. Restart restores availability, never effects, spent budgets or input consent; unsafe ownership or repeated failure blocks restart. |
| Renderer crash | App main process/core continue. Replacement renderer uses the main-process broker and catches up; no duplicate work by reopening. Notifications remain main-process-owned. |
| App main-process crash/termination | There is no daemon fallback. A qualified parent-death/watchdog containment path stops core admission and owned execution; no claim that arbitrary remote effects are undone or every abruptly lost input hold can be released. Next app launch reconciles durable interrupted/unknown records before restarting work. An unproven surviving child/ownership fence blocks replacement. |
| Update | Verify compatible bundle, quiesce the app-owned engine, settle ownership, snapshot/upgrade Desktop schemas and switch under approved authority. Compatible renderer-only reload is independent. Unknown native ownership blocks unsafe replacement. No migration from an Odin installation. |

The core is a **supervised child of the app main process**, not of a window or renderer. Only that app supervisor can start/recover it, under the profile/storage lock. A PID or IPC disconnect is not parent-death proof. Parent-loss detection, containment and Exit deadlines need isolated platform qualification; abrupt termination cannot honestly promise universal input release. Core replacement never proceeds over unresolved ownership. Neither closing a window nor a renderer reload ends the application; Exit ends it. No background-daemon or window-lifetime alternatives are part of this product.

Proposed initial missed-run policy: overdue reminders produce bounded/coalesced catch-up notices with due time/lateness/omitted count; effect-capable missed runs are recorded and need explicit recovery/run, not burst catch-up. It applies after Exit as well as sleep. Normal timezone/DST and known retry rules remain. Needs owner acceptance; not verified current sleep behavior. Child recovery cannot automatically restart agents/workflows/loops or replay their effects.

### Config, credentials and updates

- Separate persisted/effective values, apply mode, activation and restart. Context/cache reload is not service restart.
- Secrets stay core/platform-owned, never returned to renderer. Entry/provider sign-in is bounded native onboarding, not secret-read RPC or import from another Odin installation (D5).
- Activation, dependency acquisition, startup and updates are explicit. Save/upgrade cannot activate disabled tools.
- Writable skill/dependency environments stay separate from immutable core packages. No skill installation mutating core/another install.
- UI/protocol/core/storage/checkpoint versions are independent. Check compatibility before writable attachment. Rollback cannot opportunistically interpret newer state or restore weaker security.
- Alongside server install/service/data/credentials are outside Desktop lifecycle authority.

### Evidence map

| Existing at baseline | New or adapted |
|---|---|
| Startup: `src/__main__.py:515-520,548-595,599-655`; wiring: `src/discord/wiring.py:100-199,1130-1357`. | Per-user composition, profiles/locks, app-owned child supervision, tray/no-tray lifecycle and app-only login startup. |
| Scheduler admission: `src/scheduler/scheduler.py:374-418`; nonretryable failure: `src/scheduler/scheduler.py:1562-1611`. | Core/durable-inbox readiness, missed-run policy; no unconditional connected shim. |
| Apply/sensitivity: `src/config/apply_registry.py:15-36,54-84`; teardown veto: `src/restart.py:49-59,80-98`. | Desktop inventory/native secrets/startup/update and no replacement over unresolved resources. |

## 6. Tool authority and platform service

### Capabilities are not authority

Descriptor identifies tool/feature, target platform/host, configured/enabled state, dependencies, qualified guarantees, supported subset, unavailability reason and revision. Management may show unavailable features. **Model catalog contains only configured, qualified tools with truthful target constraints.**

Core identity binds the authenticated owner, conversation/request/background origin, host trust/runtime generation, deadline and Odin's existing computer-session consent. **D17:** the authenticated owner takes exactly Odin's admin path, including `owner_can_override` (default true); Desktop adds no per-command approval, tool/host allow-list or consent step. Every enrolled, targetable host is usable, with a retained default-host preference. Non-owner sources, including webhook triggers, retain the identity Odin gives their equivalent source; renderer or model payloads cannot manufacture owner identity.

### Invariants

1. Filter publication **and** enforce dispatch for built-ins/native/skills/MCP/nested/background calls. Stale offered tools refuse after revocation/config changes.
2. Reserve native names so skills/MCP cannot shadow disabled tools. Unknown optional features publish no promised-placeholder tools.
3. Recheck host/trust/lease/output scope at dispatch/retrieval. Alias/cursor is not authority; rebinding host cannot grant old evidence.
4. Preserve trusted outcome/dispatch provenance through wrappers/IPC, not inferred from tool text/JSON/exit zero/later retry.
5. Preserve Odin's governor semantics, including the admin override and open behavior when no governor is configured, plus workspaces/transactional patches/process ownership/validation/recovery. Management effects use the same core boundary, never alternate direct shell paths. Desktop adds no approval or stricter blocking.
6. Computer input follows exactly Odin's existing session and portal consent, observation/focus/generation and release/quarantine rules, with no app-added consent prompt. UI presence cannot make an agent/schedule foreground. Unknown release halts input, no alternate bypass.
7. The core runs as the local owner. Elevation works as that account allows, without a Desktop-specific approval step; the renderer receives no blanket native privilege.
8. Capabilities are **target-scoped**. Unsupported local patch/supervision/input stays absent. Qualified remote Linux tools may publish constrained remote-only operations; not local Windows/macOS parity/fallback.

### Platform boundaries

| Boundary | Required guarantee |
|---|---|
| Shell/governor | Explicit dialect/startup; no silent alternate/weaker classification. |
| Processes | Exact leader/descendant identity, bounded output/observation, settlement/cleanup receipts. Process group alone is not universal proof. |
| Files/patches | Confinement, identity-safe transactional publication/rollback and required primitives; no unsafe overwrite emulation. |
| Computer | Qualified capture/input/target subset, measured postconditions/release, protected prompts/control-plane exclusions. Best-effort stays labeled. |
| Storage/secrets | Per-profile privacy/ACLs/migrations; content renderer cannot read credentials. |
| Browser/media | Owned sessions and safe artifacts. Renderer is not a tool or path into logged-in user tabs. |
| Native presentation | Notifications/dialogs/save/reveal/portals; model content cannot assert native-command authority. |

Backend earns publication through later qualification. Unsupported OS capability discovery cannot import Linux-only modules. A launched shell does not qualify the executor.

### Evidence map

| Existing at baseline | New or adapted |
|---|---|
| Optional catalog/reservations: `src/discord/tool_catalog.py:121-180`; native dispatch: `src/discord/native_tools/registry.py:119-155,245-256`. | Neutral revisions/target publication. Current filters are not full cross-platform registry. |
| Live bindings: `src/tools/output_authorization.py:8-54`; authorization before bytes: `src/tools/executor.py:663-689`, `src/tools/output_retention.py:186-219`. | Local owner/grant instead of web bearer/tier adapters, preserving rechecks. |
| Linux supervision: `src/tools/local_supervisor_worker.py:35-88`; patch primitive: `src/tools/apply_patch.py:963-990`. | Qualified OS implementations, no weaker Windows/macOS emulation approved. |
| Computer bounds: `src/computer/policy.py:29-45,59-86`; uncertainty: `src/tools/execution_outcome.py:8-68`. | Odin's existing authenticated session/portal consent and quarantine, unchanged; no Desktop-added approval. |

## 7. Local transport and acceptance

Domain services require neither HTTP nor a toolkit. Recommended local transport: owner-protected Unix socket, later owner-ACL named pipe, between the app main-process broker and its supervised core child. The main process owns the connection; the renderer receives only narrow named methods, never a socket/path/token or generic RPC. Authenticated second-launch/launcher actions route through the existing app, not a second engine. Authenticate profile/installation/protocol before commands. Peer identity checks where supported plus private profile-scoped installation credential, never in renderer/URL/arguments/log/transcript. Same-user malware is not solved by socket/token; renderer compromise remains a threat. D6 permits only a future remote-client protocol seam, not a TCP chat/control listener, server attachment, remote settings or remote-client implementation in the first versions. Section 8's separately activated integration ingress cannot expose these domain services.

Handshake: installation/profile/endpoint/core incarnation; protocol major/minor range; required/optional features; core/UI versions; storage readiness; capability revision; journal lineage/catch-up; attachment limits and privacy policy. Reject incompatible required features before writes. Schema-validated length-bounded structured payloads, not pickle/arbitrary objects. Transfer large bytes separately; read subscriptions cannot invoke tools.

Eventual Desktop acceptance: duplicate/conflicting submissions/lost receipts; stale Stop/Steer; crash after dispatch; outbox recovery without effects; guarded resume/current policy/spent budgets; branch cutoffs; compaction/restart with files; window-closed schedules; Exit/core/app-crash interruption and parent-loss containment; no-tray reopen/Exit and app-only login startup; missed-run policy; expired cursors/slow clients; revoked evidence/tool/host scope; disabled/unsupported tools absent; alongside isolation with fresh data/no import; renderer/core/update incompatibility; exact approved D1 wording with all other prompt bytes and guard behavior unchanged. Native proofs are additional platform-specific requirements. Cross-repo parity/drift acceptance is in [maintenance.md](maintenance.md). None was authored or run in this documents-only round.

## 8. Inbound webhook integration ingress

### Scope and owned binding

This contract covers both [decision 4](decisions-for-aaron.md#4-inbound-webhook-triggers) options: **(a) loopback only** and **(b) explicit opt-in LAN/tailnet ingress**. It does not choose between them. Option (c), omitting inbound triggers, would need Aaron's explicit D2 exception. Outbound HTTP actions and lifecycle webhooks remain separate capabilities.

The supervised core owns the receiver, secrets, normalization, receipt store and scheduler handoff. The app supervisor owns its lifetime. This is not the old health/WebUI/API server copied wholesale, a separately autostarted service, or an Electron renderer route. Only bounded trigger-delivery POSTs are exposed. A trigger credential delegates the ability to wake **already configured work**, so it is execution-sensitive even though it is not a general remote-control credential.

| Binding field | Contract |
|---|---|
| Identity | Profile/installation, opaque `ingress_binding_id`, secret generation and binding revision. Not a secret embedded in a URL. |
| Authorized candidate | Core-owned schedule ID and execution identity; supported source adapter and trigger filter. One binding authorizes one schedule, not the entire profile's matching schedules. |
| Action and destination | Stored schedule action, validated tool/workflow inputs, owner-derived background authority and conversation revision/destination. The POST cannot replace any of them. |
| Transport | Approved option, exact listen address/interface/port, protected transport policy and adapter capabilities. |
| Authentication/replay | Native verification or signed-envelope scheme, credential reference, delivery-identity rules, freshness guarantees/limitations and replay-store lineage. |
| Readiness | Configured, paused, unavailable, armed or retired, with typed reason and core/config epoch. Address existence alone is not readiness. |

Secrets stay in the profile's native secret store. Creation/copy/rotation uses the bounded native credential-management path, never a secret-read renderer RPC, model tool result or conversation message. A separately authorized fan-out requires separate bindings or an explicit owner-approved candidate set with credentials scoped to that set; a caller-supplied schedule list is never that approval.

### Lifecycle and bind policy

- A receiver can exist **only while the application and its supervised core are running, and at least one webhook-triggered schedule exists**. It additionally needs saved explicit activation, a valid armed binding and qualified transport/authentication/storage. Creating a schedule is not consent to expose a LAN port.
- No trigger schedules, only paused/inert bindings, disabled ingress or failed qualification means no accepting listener. Definitions remain visible with their reason. Pausing/deleting the last eligible binding closes it; unpausing can restore only previously approved configuration. Binding/config changes advance revisions and revoke obsolete admission.
- Hiding/crashing the renderer does not close ingress. Exit first stops trigger admission, then closes the receiver and settles its owned work under section 5. App-parent loss contains the receiver with the core; an HTTP request never starts or resurrects the app. Unknown ownership blocks replacement.
- On restart/wake, reconcile storage, ownership, interrupted ingress/runs and current policy before reopening. Restore valid definitions and availability, not pending effects. There is no local catch-up delivery queue while the app is exited. Provider-side retry or delayed first delivery is outside this app-lifetime guarantee and must obey the adapter's declared freshness policy.

| Option | Binding requirement |
|---|---|
| (a) Loopback | Bind explicit IPv4/IPv6 loopback addresses only, never a hostname resolving to a wildcard or non-loopback address. Loopback is not caller authentication. Authentication and replay checks still apply. Plain loopback HTTP does not defeat a malicious same-user process. |
| (b) LAN/tailnet | Explicit owner choice of a particular address/interface and port. No wildcard bind, public exposure, router forwarding, tunnel, firewall edit or fallback to a broader interface. Require TLS or a separately qualified authenticated encrypted overlay/termination boundary, with an exact forwarding/peer policy. A tailnet-looking IP alone does not prove protection. |

An occupied port, disappearing interface, locked keyring, broken TLS/overlay or failed store makes ingress unavailable. Never steal a port or reuse the alongside Odin listener/credential. A changed address or weaker protection needs renewed explicit approval. UI shows the actual bound address and exposure, not a promised externally reachable URL; this contract does not make cloud providers able to reach a private LAN or tailnet. A separately configured relay can be required and is not automatically provisioned.

### Authentication, replay and bounds

1. Every route authenticates with its binding's independent unpredictable secret, using constant-time comparison or verified HMAC over the **original bounded bytes**, before effects or payload publication. Missing secrets, ambiguous/duplicate authentication headers, malformed encodings and wrong source/binding fail closed. No secrets in query strings, logs, receipts, errors or notifications. IP allowlists and CORS are not authentication.
2. A native compatibility adapter preserves GitHub/Gitea body-HMAC and GitLab/generic secret-header verification. Shared-secret headers require a protected non-loopback transport. These protocols do **not** all sign delivery IDs, event headers or an event timestamp. Do not claim that a valid body signature authenticates arbitrary routing headers or establishes event age.
3. Generic clients or a configured trusted bridge can use a versioned signed envelope binding method, route/binding, secret generation, source, all match-affecting metadata, raw-body digest, timestamp and unpredictable nonce. Proposed freshness window: at most five minutes old and one minute into the future; a clock whose trust is unknown blocks new strict-mode admissions. Native adapters lacking signed freshness declare `freshness_unproven`, not an invented timestamp guarantee. Strict freshness requires the envelope/qualified bridge; that prerequisite is shown before activation.
4. Persist a replay key, body digest and receipt **before any scheduler effect**. For strict envelopes, the key includes binding/key generation and nonce; payload equality also includes all signed match-affecting metadata. Native compatibility additionally deduplicates the exact authenticated raw-body digest per binding, independently of unsigned delivery/event headers. An untrusted header change cannot turn a previously accepted body into another execution. An authenticated exact duplicate returns the original receipt without matching/executing again, including after its new-admission freshness window has elapsed; same nonce with different bytes or signed semantic metadata is a conflict. Repeated identical native payloads are conservatively one delivery, a disclosed/ledgered compatibility limitation rather than a claim to distinguish identical legitimate events.
5. Retain minimal replay tombstones for the binding's lifetime, across key rotations and separately from payload retention. A full replay store fails admission rather than pruning old keys into reusable deliveries. Retirement/rotation rejects the retired secret; profile/journal reset requires new bindings/credentials. Restart, sleep, rotation or expiry of visible output cannot erase unresolved work. A new delivery ID/credential is not permission to replay an unknown run. Deleting a binding preserves safety records while retiring its delivery credentials; recreation is an explicit new delegation, never an automatic retry path.
6. Native digest deduplication proves only that an **already seen** authenticated payload is not admitted again. It cannot recognize an unseen old captured event, nor identical events with different byte serializations. Strict-mode freshness and native compatibility must be advertised separately. Neither is an exactly-once external-effects guarantee. Source normalization/matching limitations stay explicit; do not silently label every native adapter strict or quietly drop native-provider parity.
7. Proposed bounds are explicit transport adaptations, to ledger and qualify: retain today's **10 MiB maximum request-body ceiling**; reject compressed bodies, multipart and attachment uploads, and enforce the cap incrementally while reading; at most 16 KiB total headers, a ten-second body-read deadline, eight concurrent reads and 128 live pending deliveries per profile. JSON must be an object with finite depth/node budgets (initially depth 64 and 100,000 nodes); match fields and receipt IDs are length-bounded. Oversize/encoding/parse failure rejects before dispatch. Higher caps require a reviewed configuration change, not input-controlled overrides.
8. Rate-limit per binding and profile, including pre-authentication global connection/byte limits. Once bounded replay/receipt/worker capacity is exhausted, return a typed busy/unavailable rejection, not an unbounded retry queue. Slow clients cannot block the scheduler, core controls or durable publication. Security failures get bounded scrubbed audit counters, not raw-payload log floods. No fetch of payload URLs, file extraction, template execution or dependency activation during normalization.

### Scheduler mapping and effect admission

The receiver constructs a normalized **TriggerEvent**, not a human RequestEnvelope: binding/delivery identity, authenticated source, declared metadata trust, receive time, reported occurrence time where available, bounded event/repo fields and payload reference/digest. Payload text is untrusted integration data, never new owner instructions, consent, tool inputs, paths or authority.

- Preserve supported sources `gitea`, `generic`, `github`, `gitlab`, and today's AND matching: specified source exact; event exact; repo case-insensitive substring. Empty/removed/malformed filters stay rejected/inert. Source comes from the bound adapter, not an arbitrary body field.
- Preserve receiver normalization: GitHub/Gitea event header plus repository `full_name`; GitLab `object_kind` (header fallback) plus project `path_with_namespace`; generic event default `generic` and title. Today's generic adapter supplies **no repo field**, so copying a generic body's `repo` into matching would be a new behavior change. Preserve the existing `unknown` fallbacks where valid; structurally wrong types are rejected, not coerced into a matching string.
- **Required Desktop adaptation:** today's `fire_triggers(source, event_data)` scans all schedules. Add a core-owned authorized-candidate boundary around/inside that path, preserving matching and execution gates while restricting this receipt to its bound schedule identity. Passing a per-trigger-authenticated event to the unrestricted profile-wide sweep would let one credential fire other triggers. The POST cannot select or widen the candidate set.
- Match/reserve under the scheduler lock; publish detached durable state before making it live; run callbacks outside the lock. Preserve per-schedule in-flight exclusion, schedule generation/execution revision checks, active admission nonce and restoration of only the still-current **unstarted** reservation. Concurrent distinct deliveries can be skipped as busy; this is not a new backlog or promise every received event executes.
- Replace Discord connection availability/epoch with app-owned core, required storage and authorized durable-destination readiness/epoch. It is not renderer visibility or an always-connected shim. Recheck binding/key/config and schedule revisions, lease, destination and current tool/host policy immediately before dispatch. Even actions that do not need a conversation sink require app/storage/authority readiness; retaining the outbound action's lack of Discord dependency is not bypassing Desktop admission.
- Record ingress receipt and scoped candidate disposition before acknowledging admission. Same-store mutation/journal commits are atomic; separate scheduler/ingress stores need stable producer keys and an idempotent durable handoff, not an asserted cross-store transaction. Every dispatched run has an ingress-linked run identity and durable intent/result/outbox under sections 1 and 3. An orphaned admitted handoff becomes interrupted/recovery-required; restart never retries the event to discover whether it ran.
- Preserve uncertain-tool outcomes as non-retryable/manual resolution. Known safe configured scheduler retries remain that same run's policy, not a second ingress delivery; guards, budgets and tool validation remain unchanged. No acknowledged mutation/new event bypasses an unresolved-effect fence. Pausing/deleting/rebinding affects future admission and cannot retroactively cancel already dispatched effects.

The baseline's start-marker crash quarantine is explicitly **one-time effectful schedules**, not every trigger run. Desktop's ingress-linked durable run/receipt/outbox is new work that closes that gap without claiming it already exists. Also, `fire_triggers`'s integer counts callbacks admitted/executed through its wrapper, **not successful tasks**: the callback wrapper records failures internally. Preserve separate matched, admitted, skipped, settled and outcome-unknown dispositions.

### Publication and receipts

There are two publication gates, not one:

- **Capability:** settings may show an unavailable definition and its reason. Local management can provision an inactive schedule/binding and obtain explicit ingress activation; that is configuration, not a promised live receiver. A configured, activated and qualified ingress feature can offer trigger creation before its first schedule exists, while honestly saying the listener is not yet bound. Only a successfully bound, authenticated, bounded, store-ready receiver publishes usable endpoint metadata. If trigger ingress is unconfigured/unqualified, ordinary cron/one-time scheduling can remain; the offered scheduling schema/guidance must not promise a working `trigger` input. Existing trigger records remain visible/inert with a reason, not silently converted to cron or deleted. Never put secrets in the model catalog. Loss/revocation changes the capability revision and closes stale dispatch.
- **Work/result:** first commit authenticated receipt/replay state and admission disposition. Then dispatch fenced stored work; afterward publish durable result/report/artifact and native notification intents to the stored conversation through section 3. The hidden window does not suppress this. Unknown settlement is published as unknown, and publication repair uses the outbox, never schedule rerun. A receiver acknowledgement is not completion, delivery to a human or validation success.

Suggested HTTP receipts are bounded and expose only a delivery receipt/correlation ID and ingress disposition, never tool arguments/results, transcript or secrets:

| Disposition | Response meaning |
|---|---|
| Admitted, pending | `202`: receipt and bounded live handoff durably admitted; execution/completion unproven. |
| Duplicate | `200`: original ingress receipt only; no new matching or execution, even if the original run failed/interrupted. |
| Ignored/no match | `200`: authenticated delivery recorded, no eligible match admitted. Not task success. |
| Invalid/auth/oversize/conflict | `400`/`403`/`413`/`409`: this attempted delivery rejected before new dispatch; earlier receipt effects remain separate. Avoid existence/config leakage to unauthenticated callers. |
| Busy/unavailable/retired | `429`/`503`/`410`: this attempt was refused before durable admission. Once admitted, report its stored disposition, not a misleading pre-admission rejection. Retry guidance cannot erase a prior lost receipt or replay unknown work. |

An HTTP timeout means the sender lacks a receipt. A stable delivery ID/signed nonce and identical bytes can reconcile it; minting a new identity is not retry reconciliation. Receipt lookup, if ever needed, is through owner-authenticated local management, **not** a new network transcript/status API.

Today's receiver also emits a formatted integration notice after trigger callbacks. To preserve configured notices under D2, this becomes a bounded scrubbed typed integration message in an explicitly configured conversation, with stable publication key; receipt text/raw payload never starts an unconstrained chat turn. Its publication is separate from schedule results and matching. Delivery failure after successful effects must not cause effects to run again. This behavior is not implied by retaining outbound webhooks; its availability still follows the schedule-gated receiver lifecycle above.

### D6 separation and acceptance

The listener exposes no chat submission, arbitrary command/tool call, conversation read/search, artifact/evidence download, config/credential mutation, stop/steer/resume, generic IPC forwarding or computer-input operation. The future remote-client seam has different identity, authority, subscriptions and threat model; sharing HTTP libraries does not merge their credentials or routes. Integration-triggered runs stay background-originated and cannot renew GUI consent. The local broker remains the only app peer for sections 1-7.

Phase 2 qualification must cover each selected bind mode and adapter-specific claims: no-schedule/off/paused listener absence; local first-binding provisioning and truthful catalog publication; hidden window; Exit/parent loss/restart/wake; occupied port/interface/keyring failure; TLS/overlay checks and no wider fallback; bad/missing/cross-trigger credentials; unsigned-header mutation, duplicate/concurrent/delayed deliveries and replay-store loss/fullness; signed freshness/clock failure; malformed/oversize/slow input and saturation; identical normalization/AND matching; candidate isolation; pause/delete/config/generation races; interrupted handoff; crash after dispatch; non-retryable unknown effects; failed notification/outbox repair without rerun; unavailable catalog schemas; alongside installation isolation. These are future isolated tests, not results of this discussion.

### Evidence map: preserved versus new

| Existing at inspected baseline | Desktop requirement / limitation |
|---|---|
| Receiver registration/body ceiling: `src/health/server.py:929,935-939`; wiring: `src/__main__.py:681-692`. | Separate app-owned ingress only, not the general HTTP server or Discord send callback. D3 lifecycle, explicit binds, scoped credentials and readiness publication are new. |
| Fail-closed shared/HMAC checks: `src/health/server.py:1330-1356,1467-1475,1540-1551`. | Preserve native verification; baseline uses one configured receiver secret, not per-trigger secrets. Scoped key generations, replay ledger and signed freshness are new. |
| Normalization/callback: `src/health/server.py:1368-1377,1396-1408,1441-1465,1482-1483,1537-1538,1558-1560,1603-1604`. | Preserve field mapping/matching input. `_notify_triggers` logs/swallow exceptions; it does not supply durable delivery admission or deduplication. |
| Trigger validation/AND match/fire: `src/scheduler/scheduler.py:713-739,848-926`. | Retain matching, paused/malformed skips, locked reservation/publish, callbacks outside lock. Add authorized candidate scope and durable ingress/run identity. |
| Persist-before-visible and execution identity: `src/scheduler/scheduler.py:329-364,424-443`; CRUD fence: `:234-255,1148-1157`. | Preserve atomic schedule publication and current generation/revision checks; adapt admission to app/storage/destination, not an unconditional connection. |
| Availability/recheck/nonces/overlap: `src/scheduler/scheduler.py:374-418,510-518,1339-1403,1435-1469,1472-1485`. | Preserve gate/rollback/in-flight semantics; per-trigger binding revocation and durable ingress handoff are new. |
| Unknown scheduled tool outcomes: `src/discord/scheduled_events.py:419-445,524-558`; retry exclusion: `src/scheduler/scheduler.py:1562-1594`; one-time interruption: `:201-219`. | No replay of unknown effects. Do not generalize one-time crash markers into observed trigger-run recovery. Desktop adds receipt/run durability. |
| Integration notice/delivery: `src/health/server.py:1379-1394,1441-1465,1537-1538,1603-1604`. | Separate idempotent typed notice and schedule-result publication. Today's `delivered` HTTP response follows channel sending, not an exactly-once effect/admission transaction. |
