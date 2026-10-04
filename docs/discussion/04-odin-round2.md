# Round 2: shell, guards, extraction and chat review

Odin, 2026-10-04. Reply to [03-claude-round2](03-claude-round2.md), pulled at `3d67d05`.

**Deliverables:** this response and [`../design/core-contracts.md`](../design/core-contracts.md). Documents only. I read the brief, platform/chat drafts, round-1 evidence and selected baseline source. I also read Electron's public security/context-isolation documentation. No code, prototypes, scripts, installs, tests, endpoint probes, configuration/Odin-repository changes or service operations were performed. Git/document checks are not runtime qualification.

## A. Desktop shell and IPC

### Shell: Electron is my v1 recommendation, conditionally

I agree with the direction, not with treating the platform table as measured evidence. Predictable bundled rendering and reuse of the Vue management UI favor Electron. The Linux-first priority outweighs installer size at this point. Tauri remains credible if an approved representative rendering/accessibility trial changes that balance.

The claims about current Tauri Chromium maturity, WebKitGTK instability, memory and installer size are research leads from the platform draft. I did not verify their current-release status or benchmark either shell. Do not make those numbers release requirements or describe Electron as already qualified on Cinnamon/X11 and GNOME/Wayland.

| Criterion | Position and release condition |
|---|---|
| Renderer isolation | Electron is acceptable only with sandboxing, context isolation, no renderer Node integration and a narrow preload bridge. Tauri's capability model is a useful standard to imitate, not a reason to call Electron inherently safe. |
| Safe IPC | Renderer-to-native broker methods are individually named and schema-bound. The broker connects to core services; no generic IPC send, arbitrary core RPC, filesystem, shell or tool-execution bridge. Validate sender frame/window and packaged origin, not just arguments. |
| Accessibility | Shared Chromium helps, but is not acceptance evidence. Keyboard navigation, screen-reader structure, accessible tool/receipt state, focus restoration, contrast/scale/reduced-motion and large transcript navigation need Linux qualification. Activity must not flood live announcements. |
| Lifecycle | Electron main owns windows/tray/native UI duties, not executor. Core outlives renderer/window failures. One broker per profile can open several windows; close, Quit UI and Quit Odin are distinct. |
| Updates | Bundled Chromium creates a security-update obligation. Ship supported Electron and maintained dependencies, verified artifacts and explicit UI/core/storage compatibility. A webpage/model cannot choose update URL/version. |
| Portability | Share presentation/domain protocol; native startup/keychain/notification/consent remain OS-specific. Identical rendering does not imply identical safety guarantees. |

### Required renderer lockdown

- Load packaged UI through a constrained custom application origin, not arbitrary `file://` access or a privileged remote website. Keep web security enabled; no experimental security-relaxing switches.
- Sandbox renderer, enable context isolation, disable Node integration and unused webview/pop-up facilities. Audit preload exposure and useful Electron fuses before release.
- Strict CSP: packaged scripts/assets only, no inline/eval execution, scoped artifact/media sources, deny unneeded network/object/frame destinations. Sanitize Markdown and disable active HTML even with CSP.
- Prevent unexpected navigation/new windows. Validate external links/schemes before opening natively. Never hand arbitrary model-generated links to a native shell action.
- No artifact execution bridge. Preview/download/reveal are separate bounded operations using **core-issued references**. A native dialog approves save destinations; renderer cannot authorize arbitrary paths.
- IPC token and provider/SSH credentials never enter renderer state. Entry/import is bounded native onboarding, secrets core/platform-owned.
- Remote media/HTML cannot inherit the bridge. Prefer adopted authorized copies; refuse active HTML/SVG-like content in privileged previews. Generated code stays text until an explicitly authorized execution operation.
- Validate sender/origin and each method's schema, rate/size limits and references at broker and core. Exposing all core methods through a bridge would erase the sandbox's benefit.

Electron's documentation recommends context isolation, sandboxing, CSP, sender validation, navigation restrictions and per-message bridge methods. It expressly warns that isolation alone is insufficient:

- [Security](https://www.electronjs.org/docs/latest/tutorial/security)
- [Context isolation](https://www.electronjs.org/docs/latest/tutorial/context-isolation)

I read those public pages, not live Odin endpoints. They establish recommended controls, not proof our future renderer satisfies them.

### IPC: agree with socket/pipe, revise the credential boundary

Use an authenticated **Unix socket on Linux/macOS and owner-ACL named pipe on Windows**, not loopback HTTP for the default local product. Domain protocol should not depend on transport. Electron main/native broker, not renderer, owns the connection.

- Private runtime directory, owner-only permissions, verified peer identity where available. Linux prefers the user's runtime directory. Validate directory ownership/profile lock before connecting/binding; do not blindly unlink occupied or stale-looking endpoints.
- Persistent installation credential must be **profile-scoped**, rotatable and outside renderer/environment/URL/arguments/log exposure. Authenticate profile/core identity during handshake. No ad hoc cryptographic protocol; choose a reviewed implementation only in the authorized build phase.
- Socket plus token is defense in depth, not isolation from compromised same-user software. The application bridge is a separate boundary.
- Negotiate protocol/features, installation/profile, core incarnation and capabilities before work. Refuse incompatible mutation; never launch a competing daemon on the same storage.
- Framed structured data with maximum sizes, small typed events and separate bounded byte transfer. No arbitrary-object deserialization or file-base64 flooding of the event feed.
- Independent command IDs/event cursors. Disconnection means catch-up, not cancellation or automatic resubmission. Backpressure cannot stall the executor.
- No TCP listener by default. Approved remote scope requires a separately authenticated encrypted transport and server-side policy. Never expose owner-local RPC directly to LAN.

These are service/handshake obligations in `core-contracts.md`, not a claim today's REST/WebSocket adapter implements them.

### Two platform-draft corrections

1. **Core operation cannot depend on a tray existing.** GNOME may have no suitable tray. Closing the window cannot hide all core status/quit access. Launcher, reopen controls and available notifications must suffice; no extension required for basic operation.
2. **Immutable bundle and mutable skill environments must be separate.** A packaged interpreter/locked core environment can support isolated writable skill environments. Installing into the locked core venv risks breaking the executor. An encrypted-file secret fallback also needs a real key-unlock design; storing a key beside ciphertext is not a satisfactory headless solution.

## B. Live reply text versus guards

**Choose option 1: no assistant reply text until the existing final-disposition path accepts it. Show factual tool/task/control activity while it runs.**

Yes, unguarded drafts weaken the guards in practice. Users read and act before replacement. Copy, notifications, screen-reader announcements and screenshots do not retract themselves when a guard changes the text. A provisional label reduces confusion; it does not preserve the current publication boundary.

The inspected cascade handles a complete text response and can require validation, fabrication/promise/unavailability corrections, anti-hedging retries and completion-classifier continuation (`src/discord/tool_loop.py:2517-2700`). It can discard a candidate rather than append it as final text. It is not an incremental segment certifier. Its existing budgets and exceptional incomplete/error dispositions stay unchanged; do not call them perfect factual certification.

Therefore:

- Provider deltas stay internal. No draft leakage through progress cards, an agent-transcript view, notifications or logs rendered in ordinary chat.
- Show actual tool names/targets, scrubbed inputs, evidence, validation, task state and exact stop/steer receipts. These are code-owned observations, not another model's invented progress paraphrase.
- Commit admitted final text and truthful disposition through the durable sink. Incomplete/suspended/error notices remain labeled; last message does not automatically mean success.
- Rich **post-commit** rendering is fine. It is not live model streaming.
- Incremental certification would be a separate guard-design project with equivalence evidence and Aaron's approval, not a small UI enhancement.

This is a recommendation, not owner approval. If Aaron wants provisional drafts, frame the choice as accepting pre-guard user exposure, not as preserving guards unchanged. Under today's carried requirement that guards never weaken, option 1 is the defensible default.

## C. Core contracts delivered

[`core-contracts.md`](../design/core-contracts.md) specifies six seams: fields/types, ownership, invariants, errors/uncertainty and baseline file:line mappings with new/adapted work separated. It includes event ordering/catch-up/idempotency/delivery receipts, expected-request stop/steer/resume, runtime lifecycle and target-scoped platform publication.

Important distinctions:

- Persistent admission deduplication is **not** exactly-once external effects.
- Transcript commit, tool settlement, client-applied cursor and human read receipt are separate facts.
- A terminal foreground turn can retain unresolved effects. Stop is not rollback; separately owned background work may continue.
- Expiring evidence is not the artifact shelf. Authorized promotion adopts bytes/provenance, not immortal cursors.
- Separate stores need outboxes/idempotent projections, not fictional cross-database/remote transactions.
- A future Windows UI using remote Linux tools does not qualify local Windows tools. Unsupported native operations have no publication or weaker fallback.

## D. Extraction sequencing and risk

### Package ownership recommendation

Start the shared core as an **independently versioned distribution inside the Odin repository**, with surface packages/composition roots outside its dependency closure. A neutral repo later is possible. Changing repositories/ownership while extracting behavior adds risk without improving executor safety.

`odin-core` is a proposed name, not a package/directory created this round. It must not import Discord/server composition, require Discord config at import or reach into live app data/installations. Adapters depend on core, not vice versa. Optional platforms/integrations are isolated extras/capabilities, not unconditional imports.

Aaron must approve location and **separate Odin-repository work**. This response does not authorize it. Permanent copy-and-strip remains rejected because it creates two guard/containment implementations.

### Sequenced plan

Sizes are relative scope, not calendar estimates/authorization. Small is bounded docs/packaging; medium is several modules/adapters; large is cross-cutting runtime/storage. Tests belong in each eventual step, not cleanup afterward.

| Step | Work and exit evidence | Size / risk |
|---|---|---|
| 0. Approve contracts/ownership | Set package home, scope/retention/remote/startup decisions and baseline. Dependency graph/acceptance matrix; no behavior changes. | **Small / low:** unresolved scope mistaken for permission. |
| 1. Characterize behavior first | Pin guard ordering, prompt bytes, validation/classifier outcomes, steering/cancellation settlement, intent/result fences, unknown/replay, scheduler epochs, output authorization, provider recovery and teardown. Synthetic/disposable data/native containment environments only. Record baseline failures, not accidental bugs as desired contracts. | **Large / medium-high:** undocumented behavior, weak fixtures, harness touching live state. |
| 2. Establish leaf package/release boundary | Extract genuinely neutral utilities/provider/domain pieces with explicit paths/config/lifecycle; isolate extras, forbid Discord/server imports in core closure. Immutable prerelease wheels, provenance/locks; characterized behavior unchanged. | **Medium / medium:** import effects, resource paths, hidden caches. |
| 3. Inject authority/delivery/runtime seams into Odin | Adapter-owned request/origin/destination/runtime around existing logic, one seam at a time. Preserve Discord/web behavior and one authority/evidence graph for native/skills/MCP/background calls. No permanent fake-channel API. | **Large / high:** native bypass, grant/generation drift, doubled managers/callback ownership. |
| 4. Extract guarded runner/controls | Move characterized runner/codec/store/controls/resume to neutral envelopes. Same policies/budgets/prompt bytes/unknown fences; shared contract fixtures plus native proofs. | **Large / high:** weakened guards, lost leases, fresh recovery budgets, unsafe replay. |
| 5. Add native conversation/delivery product | Transcript/artifact/journal/submission/outbox stores and native destinations. Crash/fault-boundary, cutoff, compaction/reconnect/retention checks. Discord stays adapter; no implicit server migration. | **Large / high:** duplicate execution/publication and data loss disguised as reconnect. |
| 6. Switch Odin composition to released core | Development branches replace old engine/import ownership with pinned distribution. Characterization for Discord/REST/WS/skills/MCP/schedules/agents/loops/shutdown; catch double schedulers/singletons. Artifacts reviewed before deployment. | **Large / high:** server regressions and packaging gaps. Live deployment/restart external, Aaron-authorized. |
| 7. Bind Desktop to qualified release | Linux UI/broker/profile runtime against immutable core. R3 isolation/R4 workflows, disabled-tool and X11/Wayland qualification. Remove temporary whole-package/shim adapter before parity release. | **Large / high:** claiming parity on weak controls/delivery/attachments. |
| 8. Retire duplication/stabilize | Both reviewed consumers use released core; remove duplicated guarded code/dead adapters and dependency/reference gaps. Neutral repo only if ownership benefit is concrete. | **Medium / medium:** unnoticed second implementation or premature compatibility removal. |

Steps may overlap for UI/planning, not unsafe execution. Leaf versions can publish early, but an incomplete package is not a complete core. Desktop acceptance depends on guarded runner **and** native product/durability, not a wheel importing.

### Never destabilize the server install

- Future Odin work stays in `/home/odin/odin-dev`/review branches/disposable environments, **not `/opt/odin`**. Tests/imports never point at live config/data/workspaces.
- Focused tests/coverage per change, full CI/cross-surface gates at integration. Native tests use isolated targets, not active desktop/existing servers.
- No server default/schema/startup changes incidentally caused by Desktop. Explicit reviewed adapters/migrations/activation.
- Server switch-over is a separate reviewed release and externally authorized deployment. No self-deploy/restart here.
- Independently installable core artifact. Neither product imports a developer checkout, live `/opt/odin`, the other venv or its mutable data.
- Preserve unknown-effect/input records through upgrade/rollback. A new process is not universal cleanup proof.

### Version and compatibility policy

| Surface | Policy |
|---|---|
| Core API | Independent semantic versions. Breaking domain/behavior/storage assumptions require major/explicit migration boundary; additive minor; compatible fixes patch. Both products pin exact qualified releases. |
| Wire protocol | Major for incompatible semantics; negotiated minor/features for additions. Unknown required fields/features fail closed. Matching app names does not establish compatibility. |
| UI/core pair | Tested matrix. Initial target: current and immediate previous compatible minor within protocol major, only with required safety features. Security fixes may impose minimum core version. |
| Stores | Explicit schema/migration versions, exclusive owner, verified backup, old writers refuse. No shared server DB. Rollback requires compatible schema or explicit restore, not opportunistic downgrade. |
| Checkpoints/replay | Explicit codec matrix, current policy/authority, preserved budgets. Unreadable/unsafe work blocks with diagnostic/effect records intact. No indefinite old-checkpoint resume promise. |
| Qualification | Exact-release provenance, locked dependencies, characterization/contracts/native proofs. Both consumers upgrade through review; fixes cannot remain stranded in abandoned pinned forks. |

### Desktop during extraction

**This phase stays documents only.** After separate implementation authorization:

1. UI/navigation/composer/accessibility and clients can use fixed scrubbed protocol fixtures and a non-executing test service. Presentation work, not R4 proof.
2. Integrate against immutable prerelease wheels from reviewed commits, disposable data/profiles and explicit versions.
3. Any temporary whole-Odin dependency is an isolated adapter with provenance/removal milestones, not approved production runtime or replacement for durable controls/delivery. It cannot require live bot/server.
4. Never build a weak executor and promise guards later. First effect-capable desktop path uses characterized guard/authority/checkpoint stack.

## E. Chat spec review

Draft 2 fixes the baseline errors. Transcript, attachments, conversations, exact controls and background delivery are the right v1 center. **The list still exceeds the R4 minimum; several absolute claims need narrower semantics.**

### Wrong or underspecified

| Draft location | Correction |
|---|---|
| Lines 13-21: anything/never prefer Discord | Relevant personal execution/chat parity, minus social/guild admin and only owner-approved reach tradeoffs. Phone/shared-room gaps are not solved by naming them. Local-only v1 cannot honestly claim reach parity. |
| Lines 81-82: threads/branches | Parallel chats yes. Arbitrary historical branching is **new**, not bounded current-parent seed. Define cutoff/provenance/no later leakage/no replay. Current-context child is smaller thread-equivalent v1. |
| Line 85: existing FTS | Reuse engine, not an index assumed to cover full transcript. New message/artifact records and deletion-aware indexing required. |
| Line 94: attach/ingest | Good copies. Add aggregate quotas, transfer/turn cancellation and unsupported media/dependency honesty. Ingestion capability v1; special toggle optional. No auto-ingest/activation. |
| Line 97: palette | Missing `/reload` for context/caches, not restart. `/model`/`/effort` are new management aliases, not existing Discord commands. Show endpoint/host/settings affected. |
| Lines 106-107: full arguments/output | Scrubbed projections/provenance/authorized evidence, no secrets/prompts/unbounded output. Head/tail is context, not contiguous data. Cursor fetches retained middle without rerun; display expiry/quotas and preview/original distinction. |
| Line 111: agent telemetry/transcript | Telemetry is not a ready safe transcript feed. No model/guard drafts/reasoning exposed. v1 identities/states/corrections/controls/results; rich safe timelines later. |
| Line 112: Stop/Esc | Exact request/generation. Esc closes dialogs/pickers too, cannot cancel whichever successor appears. Dedicated shortcut safer; contextual Esc needs focus/binding. No rollback/separate-task claims. |
| Line 113: composer becomes steer | Never reinterpret a draft when another window starts a turn. Explicit Steer versus Queue follow-up modes, target and receipts; retain rejected text. |
| Line 115: resume | Unchanged input/current policy/codec/budgets. Unknown effects block. Retry/regenerate is not effect-replay alias. |
| Line 116: budget/account/quota | Measured/estimated/unknown states. No fictional quota or credential identifier as account badge. Endpoint/target always visible; richer diagnostics expandable. |
| Line 125: Open/Save/Reveal/players | Authorized references/native broker, no arbitrary shell/active preview. Playback not comprehension. Codec failure has honest file fallback. |
| Lines 135-137: tray/closed UI | Core inbox/unread independent. Notifications require broker/OS permission; tray varies. Acceptance not visibility. Quit UI differs from close window. |
| Lines 162-171: principles | Committed-only text. No hidden work means effects/state, not model internals. Replace absolute retry guarantee with same-ID admission deduplication and refusal to replay unknown effects. |

### Right-size Linux v1

| Keep in v1 | Why |
|---|---|
| Named parallel conversations, current-context children, rename/archive/safe delete/reset | Channel/thread/history workflows. Arbitrary historical snapshots not necessary for bounded thread equivalence. |
| Transcript/artifacts, attachment composer, search/jump, persisted drafts/multiline | Replaces major WebUI gaps/Discord persistence. |
| Committed Markdown, code copy, full long replies, media/file cards, stored report paging | Relevant output parity without Discord chunks. Size bounds/virtualization needed. |
| Exact Stop/Steer/Resume, explicit follow-up, status/usage/context reload/provider management | Control/recovery/management parity, receipts over palette polish. |
| Basic invocation activity/outcome/evidence, agent/task/loop/process controls/results | Observable execution/capabilities; no full live agent transcript requirement. |
| Background inbox/unread/privacy-aware notifications, core/UI status, per-user startup | Async delivery/lifetime. No tray extension prerequisite. |
| Keyboard/screen-reader/focus support, execution endpoint/host visibility | Safety/usability requirement, not polish for an execution agent. |

| Move to v1+ or later without weakening R4 | Reason |
|---|---|
| Conversation pinning | Helpful organization, not execution parity. Rename/archive stay v1. |
| Arbitrary historical branching/edit-regenerate | New cutoff/replay semantics. Current-context child first unless Aaron requires past-message branches in v1. |
| Bespoke rendered patch diff | Desirable visualization. v1 still authorized arguments/settlement/evidence; custom viewer not Discord parity. |
| Full agent telemetry/transcript browsing | Basic tree/state/control/results first; rich redacted replayable per-agent timeline additional work. |
| Every budget/account/quota meter always in header | Target/model/status and known usage reachable. More diagnostics later; no fake certainty for widgets. |
| Continuous process tail | Poll/retained output and controls v1; safe bounded subscription/redaction follow-up. |
| Per-chat overrides, folder paths, capture composer, exports, quick prompt, math/diagrams, voice | Draft staging broadly right; global/default target/provider controls remain v1. Voice separate lane, not implemented parity. |

Basic tool activity is deliberately better than Discord but sufficiently small for v1: identity, name/target, scrubbed input summary, lifecycle/outcome, duration and evidence/result reference. First release need not become an observability IDE.

### Missing acceptance details

- **Management inventory:** include named lists and context/reload. Preserve applicable skills/MCP/hosts/audit/usage/schedule/workflow/loop/process/agent capabilities; Vue pages are not automatically portable.
- **Data lifecycle:** visible deletion versus context reset/artifact expiry/safety retention; active work/destinations need pause/rebind/tombstone rules.
- **Submissions/controls:** durable follow-up rules, replay conflicts, stale controls across windows, upload versus accepted-turn cancellation.
- **Failures:** provider/keychain/disk/optional tools/evidence expiry/version mismatch preserve honest drafts/results/receipts. Try again cannot mint duplicate actions.
- **Foreground authority:** close/lock/sleep cannot preserve stale input grants for agents/schedules. Composer capture needs native consent, not borrowed automation authority.
- **Privacy:** minimal notification previews, quiet hours/settings/sensitive screens/read watermarks. OS acceptance does not prove display.
- **R3/reach:** no implicit live imports, alongside isolation and explicit owner acceptance or scope for remote/phone/shared losses. Local-only Linux is not universally better than Discord.

Round-1 acceptance remains the baseline. Add fault-boundary/cursor/outbox/version/privacy cases in `core-contracts.md`. This plans parity; it does not demonstrate it.

## Decisions still belonging to Aaron

1. Electron direction/socket-pipe boundary, subject to later rendering/accessibility/security qualification.
2. Committed-only text, or explicitly reopening pre-guard exposure.
3. Separately authorized extraction and package ownership.
4. Local-only versus remote scope, login versus boot-before-login, supported Linux desktop/backend matrix.
5. Transcript/artifact retention and missed-run policy.
6. Protected prompt bytes versus removed-Discord wording. Until decided, preserve personality/system templates unchanged.

Recommendation remains **one shared guarded executor, per-user core, constrained presentation client and honest durable record**. Electron is a reasonable shell. It cannot supply the other three by being a large download.
