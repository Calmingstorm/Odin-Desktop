# Phase 2 work order: the desktop engine (Odin)

**Status:** approved by Aaron on 2026-10-05 ("gogo").
**Owner:** Odin builds; Claude reviews every PR and owns [`protocol.md`](../design/protocol.md).

## Goal

Odin's real engine runs as Odin Desktop's core process and speaks the protocol the app already uses. Everything gated
in Phase 1 works again with Odin's own behaviour (D2, D17). It is proven headless: a test harness supervises the core,
and nothing runs on an active desktop.

## Rules (carried from Phase 1)

- **D17:** nothing stricter than Odin. **D19:** mechanical wording swaps go to Claude; anything that changes what Odin
  is told to do goes to Aaron.
- Every change ships with tests that exercise real code, never document wording. Suites run only in the isolated PID
  namespace (`CONTRIBUTING.md`). No destructive or attack test inputs. Never `/opt/odin`, live config or live data.
- Pull `main` before branching. One PR per step below, in order. Claude reviews each; nothing merges without that.
  No attribution trailers.
- The protocol is the contract with the app. A change to it goes through Claude as a `protocol.md` minor bump, and the
  development fixture follows it.

## Steps (one PR each)

0. **File plan.** For each step below, the modules added or changed, from the reuse map's Phase 2 rows (the 30
   `replace` files and the Phase 2 parts of `keep with adaptation`). Claude reviews it; Aaron gets a short summary.
1. **Core process and local transport.** The core entry point the app starts in place of the fixture
   (`ODIN_DESKTOP_CORE_CMD`): the owner-only socket, `SO_PEERCRED`, the profile token, `hello`/`welcome`, parent-link
   shutdown on stdin EOF, one core per profile, framing, ping. The durable event journal (sequence, cursor, retention,
   `reset_required`) and durable command identity (receipts, tombstones, `id_conflict`, `receipt_expired`).
2. **Conversations.** The durable conversation store and transcript, child conversations (inherited and labeled),
   history paging, `conversation.snapshot` with its watermark, `conversations.list` with activity,
   `read_conversation` and `search_history` over the transcript.
3. **Requests and delivery.** `submission.send` admission (durable, deduplicated) into the existing turn runner, with
   anti-hedging, continuation, the completion judge and nudges unchanged. Committed-only replies (D9), tool events,
   artifacts (the files Odin posts), notification intents, and follow-up queueing.
4. **Controls.** Stop and Steer with receipts, guarded resume, and unknown-outcome handling on the existing turn state.
5. **Runtime.** Keyring secrets, settings over the protocol, fresh-profile provisioning with Odin's local host and
   default host, Codex device-code login, `runtime.shutdown` and `status.get`.
6. **Background work.** Agents, loops, schedules with D12's missed-run policy, background tasks, skills (delivery and
   dependency installation), MCP startup, computer-use admission, and the browser with bundled Chromium.
7. **Webhook triggers** (D10, [`core-contracts.md`](../design/core-contracts.md) section 8).
8. **Closure.** The roadmap's Phase 2 exit criteria: all 326 deferred suites back (adapted, never dropped), every
   section-4 wording row dispositioned, fresh-profile host parity proven at runtime, and the core-contract gate
   scenarios passing headless. Maintenance accounting updated.

## Step 0 file plan (review required, not implementation)

Based on pulled `main@dde24a11a43028e77ecb66ede330ef59f27f8f9c` and the pinned Odin v4.13.0 inventory. Protocol
**minor 2** is current. Claude's **minor 3** draft is a dependency, not an already approved interface: this plan
names service owners now; exact new method names, schemas, limits, events and capabilities are bound to the
reviewed draft before implementation. This PR implements only ownership accounting and its behavior tests.
It does not start the core, publish tools, or claim any Phase 2 runtime gate passed.

### Inventory and boundaries

- The reuse map has 34 textual `replace` rows: four package-overview rows (`packaging`, `permissions`,
  `src/discord/cogs`, `src/discord/views`) and **30 actual source/UI file rows**. Overviews are not additional files. The manifest
  covers all **409 source/UI rows**: 30 replace, 233 keep with adaptation, 127 keep as is, 19 strip.
  `pyproject.toml` is an additional distribution replacement outside those 409 rows.
- `maintenance/phase2-file-plan.json` is the machine-readable ownership index. The offline checker
  `scripts/maintenance/phase2_plan.py` requires every replacement exactly once, every adapted source/UI path to
  have one family owner, and all 20 v1 service surfaces to resolve to a step's named modules. It consumes JSON, not
  this document's wording. This proves inventory coverage, **not implementation or semantic parity**.
- Copied modules stay at upstream `src/` paths. New transport/service seams go under `src/desktop/`. Existing
  modules below are adaptation targets **or dependencies to compose**; a listed byte-identical helper is not
  permission to change it. The JSON's `existing_modules` includes both. Actual changes still need exact per-path
  drift records, tests and review. No copied guard, classifier, governor or recovery helper is blanket-exempted.
- Phase 1 already supplied `src/desktop/{authority,capabilities,errors,paths,profile,secrets}.py`, authenticated-owner
  façades, private paths and neutral adapters. Extend those, not a second owner, executor, registry, lock/store
  graph or secret namespace. Request/control/delivery composition remains deferred; imports/readiness tests are
  not runtime admission proofs.
- No app edits or edits to Claude's `docs/design/protocol.md` here. Claude owns the fixture, bridge and UI.
  There is no server API, remote-client mode, existing-install data import or generic IPC passthrough. Step 7's
  approved webhook integration ingress is not a management API. Native packaging/desktop qualification is later.

### Step 1: core process and local transport

**Add under `src/desktop/`:** `core.py`, `lifecycle.py`, `ipc.py`, `ipc_auth.py`, `protocol.py`, `commands.py`,
`events.py`, `local_client.py`.

**Change/compose:** `src/{__main__,cli,constants,restart}.py`, existing Desktop profile/path/authority/error modules,
`src/permissions/{__init__,manager,host_access}.py`. Preserve entry-point subreaper/finalization barriers and
`src/tools/{process_manager,local_supervisor}.py` containment.

- `core.py` owns one service graph per profile; `lifecycle.py` owns startup, quiescence, stdin EOF and ordered exit.
  The app supplies the token-file path and supervises the child through `ODIN_DESKTOP_CORE_CMD`; no daemonizing.
  Profile locking is separate from socket liveness and prevents simultaneous profile ownership.
- `ipc.py` owns framing/connection lifetime; `ipc_auth.py` verifies `SO_PEERCRED`, private socket/token state and
  profile identity. Token creation remains the app's responsibility. `protocol.py` validates handshake, negotiation,
  envelopes and typed scrubbed responses. `local_client.py` is optional authenticated local CLI transport only.
- `commands.py` owns durable semantic command identity, receipts, tombstones, `id_conflict`, `receipt_expired`.
  `events.py` owns durable profile sequence/cursors, retention, catch-up and `reset_required`. These are distinct
  from existing effect/checkpoint state. Later mutations consistently transact domain state, receipts and events;
  no acknowledgement before required storage commits, and no claim of exactly-once external effects.
- **Tests:** `tests/test_desktop_ipc.py`, `test_desktop_command_journal.py`, `test_desktop_event_journal.py`,
  `test_desktop_core_lifecycle.py`: framing, peer/token/profile checks, duplicate/conflicting commands, receipt
  expiry versus unknown outcomes, retention/reset, profile lock races, parent EOF and temporary-profile restart.

### Step 2: conversations, transcript and search

**Add under `src/desktop/`:** `conversations.py`, `transcript.py`, `search.py`.

**Change/compose:** `src/discord/{channel_logger,channel_state}.py`, `src/discord/native_tools/channel_ops.py`,
`src/sessions/manager.py`, `src/search/{fts,hybrid,vectorstore}.py`, and step 1's event journal.

- `conversations.py` owns revisioned create/list/update, child inheritance/label, and new delete, reset-context and
  mark-read operations. Delete/reset remain distinct, respecting active/queued/unknown work; details await minor 3.
- `transcript.py` owns committed messages, paging/provenance and snapshots with watermarks, activity, controls and
  the complete unresolved-effects set. Compacted LLM sessions are not the transcript. Child context is a recorded
  inheritance snapshot, not a live alias to the parent's history.
- `search.py` owns drafted `search.query` and `messages.around`, and backs `search_history` with transcript-aware
  FTS/vector retrieval. Model `read_conversation` remains authenticated-current-conversation only, without a
  foreign-ID input. App navigation/search across the owner's conversations is a distinct service operation.
- **Tests:** `tests/test_desktop_conversations.py`, `test_desktop_transcript.py`,
  `test_desktop_conversation_search.py`: two conversations/child, paging/hit navigation, snapshot/tail races,
  reset versus delete, unread state, redaction/search errors and restart after compaction.

### Step 3: requests, delivery, attachments and result reading

**Add under `src/desktop/`:** `requests.py`, `attachments.py`, `delivery.py`, `artifacts.py`, `tool_details.py`,
`notifications.py`, `services.py`.

**Change/compose:** `src/discord/{intake_pipeline,attachments,delivery,tool_loop,tool_loop_helpers,wiring}.py`,
`src/discord/{completion,response_guards,turn_recorder,prompts,llm_gateway}.py`, `src/tools/executor.py`,
`src/tools/{output_authorization,output_delivery,output_retention,runtime_delivery,result_capture}.py`,
`src/turn_state/{store,codec,durability}.py`, copied LLM/reflection/trajectory helpers.

- `services.py` builds real engine dependencies once. `requests.py` durably admits/deduplicates submissions,
  queues follow-ups and derives trusted owner/request/host bindings before calling the **existing turn runner**.
  Anti-hedging, continuation, completion judge, nudges, budgets and guards stay unchanged. No simplified runner.
- `attachments.py` owns bounded chunk upload, commit/cancel, type/size checks, expiry and core-owned references.
  Admission adopts validated content with the submission identity. App-provided paths are not arbitrary file-read
  authority. Explicit “add to knowledge” uses step 5's ingestion service, never automatic ingestion or URL leakage.
- `delivery.py` commits only guarded replies (D9), publishing tool/message/artifact/notification events with
  durable intents/outbox settlement. Native tool/skill/agent/schedule callbacks all use this sink. A closed window
  cannot remove the destination. Execution, storage and delivery outcomes stay separate.
- `artifacts.py` owns scoped references/bounded reads; `tool_details.py` projects scrubbed arguments, summaries
  and retained-output cursors without rerunning tools. Reauthorize each read through the copied authorizer.
  Artifact durability differs from evidence TTL/quota and process-spool retention. Step 6 adds stored report pages.
- `notifications.py` persists intents/unread destinations and notification events. Preview/mute/quiet-hour
  policy and OS notifications remain the app's work; no unguarded reply-text event.
- **Tests:** `tests/test_desktop_requests.py`, `test_desktop_delivery.py`, `test_desktop_attachments.py`,
  `test_desktop_artifacts.py`, `test_desktop_tool_details.py`; restore real-loop characterization and completion/
  continuation, image-only inputs, lost acknowledgements, failed storage/outbox recovery, disconnected delivery,
  evidence expiry/reauthorization and no duplicate external execution.

### Step 4: Stop, Steer and guarded resume

**Add:** `src/desktop/controls.py`.

**Change/compose:** `src/discord/{turn_resume,steer_notifications}.py`, `src/turn_state/{store,codec,durability}.py`,
command journal and request admission. Copied guard/classifier/recovery modules remain the behavior contract.

Own request/generation-bound Stop/Steer receipts, queued-versus-consumed controls, cancellation settlement and
bounded finalization. Stale Stop cannot target a successor; late Steer is not a new submission. Guarded resume
restores spent budgets/checkpoints, rechecks current authority/config/host policy and blocks unresolved effects.
Reconciliation is explicit/evidence-backed; later success does not erase uncertainty. Preserve resume empty-read
disposition or obtain its D19 decision. Replace confirmation presentation only where Odin already requires that
control or computer consent. **No new generic approval, per-command confirmation or owner tool/host allow-list.**

**Tests:** `tests/test_desktop_controls.py`, `test_desktop_resume.py`, original recovery/helper/turn-state cases
adapted to trusted temporary profiles: long harmless/stubbed calls, lost controls, stale generations, spent budgets,
cancellation and unknown outcomes. No automatic replay shortcut.

### Step 5: runtime, settings, credentials and management

**Add under `src/desktop/`:** `runtime.py`, `provisioning.py`, `settings.py`, `management.py`, `codex_accounts.py`,
`hosts.py`, `state.py`, `knowledge.py`, `records.py`, `integrations.py`.

**Change/compose:** Desktop secrets/profile/lifecycle; `src/setup_wizard.py`;
`src/config/{schema,apply_registry,persistence,environment,initialization,startup_context,migrations}.py`;
`src/health/{checker,server,startup}.py`; provider credential/lifecycle/quota modules;
`src/tools/hosts/{registry,control,trust}.py`; `src/permissions/{host_access,persistence}.py`;
`src/tools/handlers/state.py`; `src/knowledge/{store,importer}.py`; audit/logging/usage/monitoring/planning stores.

- `runtime.py` owns `status.get`, usage/quota/context with measured/estimated/unknown labels and `runtime.shutdown`.
  Shutdown quiesces the actual graph, never re-executes over unproven descendants/input ownership.
- `provisioning.py` creates fresh independent profile/workspace/local/default-host state matching Odin. Prove
  explicit/omitted host selection and `http_probe`'s local fallback at runtime with harmless/stubbed execution.
  Invalid preferences cannot become an owner ACL; a missing remote target cannot become local.
- `settings.py` serves schema/revisioned writes (drafted `settings.set`) through copied apply/persistence/
  sensitivity rules, keeping saved/effective/pending-restart values distinct. Secrets are write-only. Locked or
  failed keyring operations cannot leak a fallback secret file or acknowledge a successful write. Provider
  readiness/provisioning cannot add Desktop-specific owner consent.
- `management.py` dispatches validated **named** commands, not arbitrary Python/HTTP. `hosts.py` handles enrollment/
  test/commit/remove with trust/generation/lease rules; `state.py` memory/lists; `knowledge.py` explicit ingest/
  search/remove; `records.py` bounded audit/log/usage reads. `codex_accounts.py` owns device-code login/cancel,
  labels/activate/remove and vault secrets. `integrations.py` owns optional outbound/email/configuration state;
  step 7 wires inbound triggers.
- Adapt retained domains from `src/web/api/{config_admin,llm_admin,codex_admin,hosts,knowledge_mem,observability,
  integrations}.py`, `src/web/{api_common,bootstrap_policy,onboarding}.py` into these services. Not shipped HTTP
  registrars; obsolete social/RBAC registrations go, domain invariants remain.
- **Tests:** `tests/test_desktop_runtime.py`, `test_desktop_settings.py`, `test_desktop_provisioning.py`,
  `test_desktop_management.py`, `test_desktop_codex_accounts.py`: temporary keyring adapter, revision/write/
  corruption failures, scrubbed secrets, actual fresh-profile host parity and an untouched alongside-state sentinel.

### Step 6: background work, skills, MCP, browser and computer admission

**Add under `src/desktop/`:** `work.py`, `reports.py`, `skills.py`, `mcp.py`, `computer_binding.py`,
`workspace_diagnostics.py`; also `src/computer/runtime/dependency_resolver.py`.

**Change/compose:** `src/agents/{manager,results,trajectory}.py`; `src/discord/{background_task,scheduled_events,
scheduled_context,scheduled_report}.py`; `src/discord/native_tools/{agents_tasks,scheduling,skills_tools,registry,
media,knowledge}.py`; `src/tools/{autonomous_loop,process_manager,skill_manager,skill_context,browser,
branch_freshness}.py`; `src/tools/mcp/`; `src/scheduler/{scheduler,history}.py`; Desktop capability/service modules;
retained computer controller/store/integration/provenance/policy and runtime adapters.

- `work.py` lists/controls agents/tasks/loops/processes/schedules through actual managers, with immutable run/
  generation/owner bindings, durable destinations and actual settlement. Compose step 4's controls, never bypass.
  Nested-agent budgets/completion and queued-not-consumed parent corrections remain unchanged.
- D12 schedule recovery coalesces ordinary missed runs, bounds workflow catch-up and never replays uncertain
  external effects. `reports.py` pages stored results; a page read cannot rerun its check.
- `skills.py` restores real lifecycle/schema/publication and dependency installation; `mcp.py` configured
  supervised startup/management. Skill/MCP text or credentials do not manufacture human authority. Browser
  startup resolves bundled Chromium with copied URL/network/workspace rules, not the operator's browser/session.
- `computer_binding.py` supplies genuine owner/conversation/foreground-turn and management/recovery bindings.
  Preserve existing consent/scope/quarantine/generation/freshness/release uncertainty/no-replay. The dependency
  resolver owns worker-only GI discovery; workspace diagnostics replace server-URL/git-prefix coupling with
  bounded local diagnostics, not a new force-push governor or generic shell route.
- All 56 adapted computer/runtime rows have step-6 wiring owners. Native sandbox/backend, packaged binary,
  accessibility and active-session qualification remain Phase 3 gates. Headless proofs use stubbed backends or
  hard-isolated disposable graphics; unsupported backends are not advertised as usable to meet a count.
- Adapt `src/web/api/{agents_loops,schedules_api,skills_api,computer,turn_state,_agent_display}.py` domains into
  work/skills/computer/controls. No browser/session token or fabricated privileged test shim supplies authority.
- **Tests:** `tests/test_desktop_work.py`, `test_desktop_reports.py`, `test_desktop_skills.py`,
  `test_desktop_mcp.py`, `test_desktop_schedule_recovery.py`, `test_desktop_computer_binding.py`,
  `test_desktop_browser_runtime.py`; restore deferred manager/dependency failure behavior within safe scope.

### Step 7: webhook integration ingress

**Add:** `src/desktop/webhooks.py`.

**Change/compose:** integrations/lifecycle/requests/events, `src/config/webhook_text.py`,
`src/scheduler/{scheduler,history}.py`, retained integration logic from `src/web/api/integrations.py`.
`src/notifications/outbound_webhooks.py` remains separate outbound delivery.

Implement core-contracts section 8: explicitly configured lifecycle/bind policy, scoped source authentication,
signature/replay/body bounds, durable acceptance identity and schedule/run mapping, current-policy admission,
revocation and publication receipts. Trigger input does not inherit owner authority from profile ownership.
Disabling ingress fences stale work per contract. No chat/settings/control API on this listener.

**Tests:** `tests/test_desktop_webhooks.py` and safe inherited authentication/persistence/text/scheduler adapters:
duplicates, storage failure, disabled/revoked ingress, replay/size limits, unknown dispatch, parent-loss cleanup,
using ephemeral loopback and temporary profiles only.

### Step 8: closure and later-phase handoff

**Add:** `src/desktop/package_status.py` for package identity/update-status/lifecycle handoff only, not updater/
installer execution or native packaging qualification.

**Change/compose:** `src/packaging/__init__.py`, `src/runtime_paths.py`, `src/version.py`, Desktop provisioning/
settings/lifecycle; `maintenance/{test-plan,case-accounting,qualification-plan,desktop-deltas,manifest,
safety-manifest}.json`, wording/disposition table, exact adapters in `tests/desktop_adapters/`, safe gate tooling.

- All **326 deferred suites** return with reviewed Desktop execution/adapter mappings and original assertions/
  case data/budgets, never dropped or relabeled as passing. Restore named turn-loop/agent/recovery/helper/Codex
  replay suites. Prohibited inputs require reviewed safe adapters/pure cases, not prohibited commands even mocked.
  Native/manual requirements stay distinct and honest.
- Every section-4 **NONE** wording row is removed by restored behavior or explicitly dispositioned under D19:
  mechanical swaps to Claude, behavior/instruction changes to Aaron. Include unavailable/not-implemented/readiness
  gates, attachment suffix/image URLs, skill dependencies and resume empty-read handling. No blanket approval.
- Prove fresh local/default-host parity and all unchanged headless gates below. Record actual suite/case artifacts,
  storage/unknown-effect outcomes and approvals, not just aggregate passing totals.
- Phase 3 owns the distribution validator replacing `src/packaging/validate.py`, actual update/rollback installer,
  app navigation/settings/onboarding. Step 8 supplies status/quiescence contracts only. Packaging, tray/autostart,
  Chromium inclusion and native/backend qualification remain explicit later gates, not waived here.
- **Tests:** `tests/test_desktop_core_contracts.py`, `test_desktop_phase2_closure.py`,
  `test_desktop_package_status.py`, restored inherited suites and offline drift/ownership gates. Each step runs
  touched tests; closure runs the full reviewed headless corpus in the isolated PID namespace.

### Every replacement file: primary step and concrete owner

Phase 1 adaptations stay at copied paths where already present; deferred behavior is wired in the named step.
Excluded server files stay excluded and receive named replacements. App/package rows name only core counterparts.

| Reuse-map source file | Step | Engine owner / boundary |
|---|---:|---|
| `src/__main__.py` | 1 | entry point → `src/desktop/core.py`, `lifecycle.py` |
| `src/cli.py` | 1 | façade → `src/desktop/local_client.py` |
| `src/constants.py` | 1 | retain Desktop constants, no Discord limits |
| `src/restart.py` | 1 | teardown veto → `src/desktop/lifecycle.py` |
| `src/setup_wizard.py` | 5 | façade → `src/desktop/provisioning.py` |
| `src/health/server.py` | 5 | status façade → `src/desktop/runtime.py`, no server API |
| `src/packaging/__init__.py` | 8 | Desktop namespace / `package_status.py`; native packaging later |
| `src/packaging/validate.py` | 8 | `package_status.py` handoff; distribution validator Phase 3 |
| `src/permissions/__init__.py` | 1 | existing owner façade / `src/desktop/authority.py` |
| `src/permissions/host_access.py` | 5 | live-host/default preference → `src/desktop/hosts.py` |
| `src/permissions/manager.py` | 1 | sealed owner / `src/desktop/authority.py` |
| `src/permissions/token_manager.py` | 1 | `src/desktop/ipc_auth.py`, not tier/token administration |
| `src/computer/runtime/gi_support.py` | 6 | `src/computer/runtime/dependency_resolver.py` |
| `src/tools/branch_freshness.py` | 6 | local façade / `src/desktop/workspace_diagnostics.py` |
| `src/tools/output_authorization.py` | 3 | authorizer wired to real origins/leases |
| `src/discord/__init__.py` | 1 | inert namespace; composition in `src/desktop/core.py` |
| `src/discord/client.py` | 1 | `src/desktop/core.py`, `lifecycle.py`; no bot |
| `src/discord/cogs/scheduled_report_pagination.py` | 6 | `src/desktop/reports.py` |
| `src/discord/delivery.py` | 3 | adapter → `src/desktop/delivery.py`, `artifacts.py` |
| `src/discord/views/confirm.py` | 4 | `src/desktop/controls.py`, only existing required controls |
| `src/web/api/security.py` | 5 | `src/desktop/management.py`, `ipc_auth.py`; no RBAC admin |
| `src/web/api/self_update.py` | 8 | `package_status.py`, `lifecycle.py`; actual updater later |
| `src/web/authentication.py` | 1 | `src/desktop/ipc_auth.py` |
| `src/web/computer_binding.py` | 6 | `src/desktop/computer_binding.py` |
| `src/web/session_store.py` | 1 | connection identity in `ipc_auth.py`; transcript in step 2 |
| `src/web/websocket.py` | 1 | `src/desktop/ipc.py`, `events.py` |
| `ui/js/pages/api-tokens.js` | 5 | app counterpart to `ipc_auth.py`; no server bearer UI |
| `ui/js/pages/setup.js` | 5 | app counterpart to `provisioning.py`, `settings.py` |
| `ui/js/pages/tabbed-page.js` | 8 | Claude's app navigation, no engine module to fabricate |
| `ui/js/pages/update.js` | 8 | app update UI; `package_status.py` handoff only |

### Minor-3 v1 service ownership

New wire schemas/events await the reviewed draft. Existing command/receipt/event boundaries apply to management
mutations too. `management.py` routes only validated named operations, not a generic escape hatch.

| Interface surface | Step | Engine module(s) |
|---|---:|---|
| Conversation delete/reset/read/children | 2 | `src/desktop/conversations.py`, `transcript.py` |
| Search/jump (`search.query`, `messages.around` drafted) | 2 | `src/desktop/search.py`, `transcript.py` |
| Chunk upload/cancel/commit; explicit knowledge choice | 3 | `attachments.py`, `requests.py`; knowledge service step 5 |
| Artifact references/bounded reads | 3 | `artifacts.py`, `src/tools/output_authorization.py` |
| Tool details/retained cursor pages | 3 | `tool_details.py`, copied output delivery/retention |
| Stored report pages | 6 | `reports.py` |
| Agents/tasks/loops/processes/schedules listing/controls | 6 | `work.py`, `controls.py`, actual managers |
| Usage/quota/context/core health | 5 | `runtime.py`, copied usage/window/health observers |
| Notification events/unread destinations | 3 | `notifications.py`, `delivery.py` |
| Settings schema/revisioned writes/write-only secrets | 5 | `settings.py`, `secrets.py`, config apply/persistence |
| Skills lifecycle/dependencies | 6 | `skills.py`, `src/tools/skill_manager.py` |
| MCP server lifecycle | 6 | `mcp.py`, `src/tools/mcp/manager.py` |
| Host enrollment/trust | 5 | `hosts.py`, host registry/control/trust |
| Memory/lists | 5 | `state.py`, `src/tools/handlers/state.py` |
| Knowledge ingest/search/remove | 5 | `knowledge.py`, knowledge store/importer |
| Audit/log records | 5 | `records.py`, audit/logging stores |
| Turn-state inspection/guarded recovery | 4 | `controls.py`, turn-state store |
| Computer admission/status/reconciliation | 6 | `computer_binding.py`, computer controller/store |
| Codex accounts/device-code login | 5 | `codex_accounts.py`, copied auth/credential lifecycle |
| Integration configuration | 5, 7 | `integrations.py`; `webhooks.py` in step 7 |

Unqualified shorthand paths in this table are under `src/desktop/`, not new copies of retained modules.

### Review-worktree cleanup accompanying step 0

Both branches' committed fixes were patch-equivalent to fixes already on pulled main. Their three dirty files
contained old evidence text/hash refreshes: actual source digests/patches and safety selection changes were already
represented on main, while document pins and one test digest were older than main. No new real fix was found, so
no cleanup-fix PR is needed. Stale changes were discarded after preserving diffs; both branches/worktrees and eight
detached review worktrees for merged PRs 1, 3 and 4 were removed. Untracked independent review probes were archived
outside the repo, not silently promoted into runtime proofs or inherited-suite accounting. Only the primary
checkout and design-main worktree remain. No live install, service or active desktop changed.

## The gate

The roadmap's Phase 2 gate, unchanged: two conversations and a child; stop and steer during a long tool call; a
disconnect and catch-up during a workflow; a restart after compaction; lost receipts with no duplicate execution;
unknown dispatch and outbox recovery; resume with spent budgets; storage failure; revocation; loss of the core or the
app; running alongside a server install with fresh data; and the webhook acceptance cases.

## Claude during Phase 2

- Reviews every PR and keeps `protocol.md` and the fixture in step.
- Points the app at the real core (in place of the fixture) for an end-to-end smoke as each step lands.
- Builds the app's v1 interface in parallel ([`app-v1-plan.md`](app-v1-plan.md)).
