# Shared core contracts

Owner: Odin. Round 2, 2026-10-04. Proposed design, not implementation authorization.

## 0. Status, evidence and scope

This document specifies the six seams agreed in [round 2](../discussion/03-claude-round2.md). It is a domain contract, not a Python interface, wire implementation or claim that these services already exist. Shell and extraction recommendations are in [04-odin-round2](../discussion/04-odin-round2.md).

Source references are relative to Odin **`cd7530906e9cfa10a0fa900247d7ce2a8bb33e25`**, the inspected round-1 baseline. A read-only Git check this round found `/opt/odin` still at that commit. Claude's spot-check of `3849d917` is additional evidence supplied by Claude, not a checkout I inspected. Source and public documentation reads are the only research performed. No code, imports, tests, installations, endpoint probes, configuration changes or service operations were performed.

**Existing** means the cited source supplies that part of the behavior. **New** means desktop infrastructure or extraction changes are required. Each seam has an evidence map; its proposed contract is not observed desktop behavior.

### Common domain vocabulary

| Type | Fields and meaning |
|---|---|
| Installation identity | Stable `installation_id`; distinguishes Desktop from an alongside server. Never inferred from a source directory or port. |
| Profile identity | Stable `profile_id`, authenticated `owner_id`, isolated config/data/secret namespace and storage identity. One core owns a profile at a time. |
| Runtime identity | Fresh `core_instance_id` and ownership epoch for each core incarnation. A PID alone is not identity. |
| Execution endpoint | Stable local/remote `endpoint_id`, profile and negotiated capabilities. Execution machine is explicit; disconnected remote never becomes local. |
| Conversation identity | Stable `conversation_id`, monotonic mutation revision, optional parent and inheritance snapshot. Names are presentation, not identity. |
| Submission identity | Client-generated unpredictable `client_submission_id`, scoped to endpoint/profile/conversation, immutable once admitted. Not a content hash. |
| Message identity | Core-issued `message_id`, revision, role/provenance and originating submission/request. |
| Request identity | Core-issued `request_id`; generation, lease and revision fence execution ownership. Resumed lineage retains identity but obtains a new live lease. |
| Operation identity | Unique `invocation_id`, originating request/background run, parent invocation if nested, tool and target binding. Retrying cannot erase prior uncertain dispatch. |
| Background identity | Stable task/schedule/loop/agent identity, distinct run/iteration identity and core-owned destination. |
| Reference | Opaque artifact, evidence, report or cursor reference with scope, availability and retention metadata. Possession is not authorization. |

Persisted deadlines use UTC; live elapsed time/budgets use monotonic clocks. Event order uses sequence numbers, not timestamps. Fencing IDs/hashes are not user credentials or capabilities.

All surfaces share the existing guard/classifier/validation stack and preserve personality/system-template bytes unchanged. Accurate adapter metadata is not permission to add always-on desktop instructions; new tool guidance belongs in tool descriptions. The literal Discord wording conflict stays an Aaron decision. Baseline: `src/llm/system_prompt.py:16-34,66-134` and `src/discord/tool_loop.py:2517-2700`.

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
3. Resolve lost acknowledgements by lookup or resending the **same** ID. Reconnect, REST fallback or restart cannot mint a replacement automatically.
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
- History is data, not current instructions. Inheritance/import/artifacts cannot confer authority.
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

Sink serves foreground turns, schedules, workflows, loops and permitted skills **without UI connection**. Publications have immutable producer identity and idempotency key.

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
| First launch | Isolated profile/storage/credentials and explicit background/startup preferences. No implicit server-data/environment reuse. |
| Second launch | Attach to proven core/open UI. Incompatibility refuses use; no competing core on same stores. |
| Close window | Enabled background work continues into inbox; tray is optional, launcher/status must reopen. Explicit window-lifetime mode initiates disclosed safe shutdown. |
| Quit UI | Presentation detaches only. If UI owned notification broker, popups wait/fail visibly; durable inbox still works. No popup promise without broker. |
| Quit Odin | Stop admission, drain/cancel, checkpoint, release children/input, flush. Preserve unknowns and veto unsafe replacement. Not undo. |
| Login/startup | Opt-in per-user login core; UI startup separate. Keychain/session negotiated. Linger/boot-before-login requires owner scope. |
| Sleep/offline | No execution while asleep. Re-evaluate deadlines/leases/settlement on wake; no fabricated runs. Locked/absent graphical session cannot renew input. |
| Core crash | Exclusive storage reconciliation, interrupted/unknown records preserved. Automatic daemon restart restores availability, not effects/input. |
| UI crash | Core continues; replacement authenticates/catches up. No duplicate work by reopening. |
| Update | Verify compatible bundle, quiesce, settle ownership, snapshot/migrate and switch under approved authority. Compatible UI-only restart independent. Unknown native ownership blocks unsafe replacement. |

Proposed initial missed-run policy: overdue reminders produce bounded/coalesced catch-up notices with due time/lateness/omitted count; effect-capable missed runs are recorded and need explicit recovery/run, not burst catch-up. Normal timezone/DST and known retry rules remain. Needs owner acceptance; not verified current sleep behavior.

### Config, credentials and updates

- Separate persisted/effective values, apply mode, activation and restart. Context/cache reload is not service restart.
- Secrets stay core/platform-owned, never returned to renderer. Entry/import is bounded native onboarding, not secret-read RPC.
- Activation, dependency acquisition, startup and updates are explicit. Save/upgrade cannot activate disabled tools.
- Writable skill/dependency environments stay separate from immutable core packages. No skill installation mutating core/another install.
- UI/protocol/core/storage/checkpoint versions are independent. Check compatibility before writable attachment. Rollback cannot opportunistically interpret newer state or restore weaker security.
- Alongside server install/service/data/credentials are outside Desktop lifecycle authority.

### Evidence map

| Existing at baseline | New or adapted |
|---|---|
| Startup: `src/__main__.py:515-520,548-595,599-655`; wiring: `src/discord/wiring.py:100-199,1130-1357`. | Per-user composition, profiles/locks, independent lifetime/startup modes. |
| Scheduler admission: `src/scheduler/scheduler.py:374-418`; nonretryable failure: `src/scheduler/scheduler.py:1562-1611`. | Core/durable-inbox readiness, missed-run policy; no unconditional connected shim. |
| Apply/sensitivity: `src/config/apply_registry.py:15-36,54-84`; teardown veto: `src/restart.py:49-59,80-98`. | Desktop inventory/native secrets/startup/update and no replacement over unresolved resources. |

## 6. Tool authority and platform service

### Capabilities are not authority

Descriptor identifies tool/feature, target platform/host, configured/enabled state, dependencies, qualified guarantees, supported subset, unavailability reason and revision. Management may show unavailable features. **Model catalog contains only configured, qualified tools with truthful target constraints.**

Core grant binds owner, conversation/request/background origin, targets/tools, host trust/runtime generation, deadline and any computer consent. UI can narrow preferences, not manufacture grants. Removing user-tier admin cannot become universal always-admin native/indirect dispatch.

### Invariants

1. Filter publication **and** enforce dispatch for built-ins/native/skills/MCP/nested/background calls. Stale offered tools refuse after revocation/config changes.
2. Reserve native names so skills/MCP cannot shadow disabled tools. Unknown optional features publish no promised-placeholder tools.
3. Recheck host/trust/lease/output scope at dispatch/retrieval. Alias/cursor is not authority; rebinding host cannot grant old evidence.
4. Preserve trusted outcome/dispatch provenance through wrappers/IPC, not inferred from tool text/JSON/exit zero/later retry.
5. Preserve governor/workspaces/transactional patches/process ownership/validation/recovery. Management effects use same core boundary, never alternate direct shell paths.
6. Computer input is supervised foreground with exact consent/observation/focus/generation bounds. UI presence cannot make an agent/schedule foreground. Unknown release halts input, no alternate bypass.
7. Local owner, not root. Elevation is an exact approved native operation, no blanket renderer privilege.
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
| Computer bounds: `src/computer/policy.py:29-45,59-86`; uncertainty: `src/tools/execution_outcome.py:8-68`. | Authenticated desktop foreground/native consent with quarantine intact. |

## 7. Local transport and acceptance

Domain services require neither HTTP nor a toolkit. Recommended local transport: owner-protected Unix socket, later owner-ACL named pipe; native broker/explicitly authorized clients only. Authenticate profile/installation/protocol before commands. Peer identity checks where supported plus private profile-scoped installation credential, never in renderer/URL/arguments/log/transcript. Same-user malware is not solved by socket/token; renderer compromise remains a threat.

Handshake: installation/profile/endpoint/core incarnation; protocol major/minor range; required/optional features; core/UI versions; storage readiness; capability revision; journal lineage/catch-up; attachment limits and privacy policy. Reject incompatible required features before writes. Schema-validated length-bounded structured payloads, not pickle/arbitrary objects. Transfer large bytes separately; read subscriptions cannot invoke tools.

Eventual shared acceptance: duplicate/conflicting submissions/lost receipts; stale Stop/Steer; crash after dispatch; outbox recovery without effects; guarded resume/current policy/spent budgets; branch cutoffs; compaction/restart with files; UI-closed schedules/missed-run policy; expired cursors/slow clients; revoked evidence/tool/host scope; disabled/unsupported tools absent; alongside isolation; UI/core/update incompatibility. Native proofs are additional platform-specific requirements. None was authored or run in this documents-only round.
