# Bring-over and dual maintenance

Owner: Odin. Round 3, 2026-10-04. Design only; no copying, build, test or CI implementation is authorized by this document.

## 1. Decision and invariants

**D4 is settled:** bring the needed Odin code into this repository and maintain both repositories. There is no shared package, dependency on an installed Odin, or extraction/refactor campaign in Odin. The six [core contracts](core-contracts.md) are internal Desktop boundaries. "Shared" below means common source lineage and behavior maintained separately, not a runtime library.

- **D1:** only the approved Discord-reference substitutions change personality/system templates. All other bytes remain identical. Approval covers exact wording, not a license for a rewrite. Other model-facing and guard/classifier substitutions have their own inventory and approval records.
- **D2:** agents, continuation, anti-hedging, response guards, completion classification and every retained engine capability behave the same. Transport adaptation cannot reset budgets, weaken containment or alter uncertain-effect/no-replay rules. Interface-specific facts change only where documented.
- **D3:** the app main process owns a supervised engine child. Close hides the window; Exit stops the engine and app. No system service, daemon fallback or window-lifetime mode is copied.
- **D5/D6:** fresh Desktop data and credentials; no existing-user import or remote client/access feature in the first versions. A versioned protocol seam is retained, not implemented remote authentication/listening. SSH to configured managed hosts is still an execution capability.
- Removed social/multi-user/server-only features leave no operative references. Authority, target trust, provenance, output protection and computer consent are not "multi-user leftovers" to delete.
- Configured integration-triggered schedules remain a D2 capability. Removing the general server API does not silently remove trigger semantics; the app-owned event-ingress strategy must be explicitly designed and qualified without a remote chat/control client. Outbound webhooks are not a substitute for inbound triggers. Track this closure separately from the future remote-client seam.

## 2. Baseline: choose, freeze, record

### Selection

The design evidence baseline is **Odin `cd7530906e9cfa10a0fa900247d7ce2a8bb33e25` (v4.13.0)**. It is not automatically the eventual implementation baseline. At Phase 1 approval, choose one clean, identified upstream commit with known release/test evidence and no unresolved relevant security regression. Prefer the then-approved stable release, not an unreviewed moving branch head or the live installation's incidental version. Aaron authorizes the bring-over phase; reviewers record why this baseline is suitable. If it differs from the design baseline, first reconcile the reuse map and mention inventory against the new files and line numbers.

Do not copy `/opt/odin` as a working directory, live config/data, generated context, secrets, browser profiles, user-created skills, caches or deployment junk. Use the upstream repository object at the frozen SHA in an isolated implementation workspace. No upstream branch/worktree/source change is required for this process.

### Baseline record (planned repository metadata)

Record upstream repository URL, full commit SHA, release/tag and resolved tag object where applicable, date, reason, upstream test/coverage/native-proof evidence and limitations, license/notices, and Desktop initial-copy commit. A tracked source manifest lists each selected path, reuse verdict, exact upstream content digest, Desktop destination, associated tests/runtime assets, dependency origin and owner. The implementation baseline and the **last reviewed upstream commit** are different fields; neither advances silently after a partial port.

Keep immutable baseline blobs available from pinned Git objects, with a verified retained source archive if necessary. A tag or download URL alone is not immutable provenance. Record missing evidence honestly; a clean upstream CI result is not proof that copying into Desktop is qualified.

## 3. Bring-over order and acceptance

This order is for the approved implementation phases, not work performed in this discussion.

| Step | Work and reuse verdict | Gate before moving on |
|---|---|---|
| 1. Inventory closure | Freeze baseline; reconcile every reuse-map row; enumerate tests, fixtures, schemas, runtime assets, helper executables and dependency/license closure. | Every selected or excluded path has a reason. The existing 409-file map is source/UI coverage, not a complete dependency/test manifest. |
| 2. Exact copy | **keep as is:** copy selected modules and tests byte-identically at their Odin paths. Copy the upstream portions of **keep with adaptation** before editing, preserving ancestry and a reviewable copy boundary. | Recorded digests match upstream. No live data or ambient Odin environment is adopted. This intermediate tree is not a shipping/runnable product. |
| 3. Remove irrelevant surfaces | **strip:** remove Discord gateway/cogs/social controls, tiers/roles/user grants, server API/token inventory and obsolete UI/config/dependencies per the map. Remove only dependency edges no retained capability uses. | A named exclusion manifest and reference/dependency checks show removal, rather than hidden UI with active backend registrations. Common execution logic inside `src/discord/` is not stripped just because of its path. |
| 4. Adapt foundation | **keep with adaptation:** introduce Desktop profile/data/secret paths, owner/target authority, capability publication and platform wiring; then request/control identity, durable admission, transcript/artifact/event outboxes and delivery destinations. Preserve guard/classifier/governor/containment logic. | Each changed hunk is ledgered; shared behavior tests pass; new boundary failure cases are covered. No fake always-connected channel or ambient always-admin dispatch becomes the foundation. |
| 5. Replace composition/surface | **replace:** build the app-owned child composition/lifecycle, local broker, onboarding and native presentation equivalents. Adapt `read_channel` to **`read_conversation`**. Apply only approved D1 and other text substitutions. | New components meet the core contracts, including lost receipts, current-conversation provenance, Exit/parent loss, renderer separation, no-tray behavior and fresh-state/alongside isolation. No shared package or service dependency is introduced. |
| 6. Complete retained functionality | Wire all retained capabilities and rebuilt management workflows, including agents, tasks, schedules/workflows/loops, search, memory, knowledge, skills, MCP, host tools, computer use and observability. | Capability inventory has an explicit implemented/qualified/unavailable entry for every retained feature. Unconfigured or unqualified features expose no model tools. "Later" UI embellishments do not defer engine parity. |
| 7. Qualify and ship | Full Desktop behavior/contract suites, isolated native platform proofs, packaging/upgrade/rollback, security, accessibility, and explicit R4 scenario acceptance. | No unexplained safety drift; ports reviewed; build/dependency provenance frozen; approved prompt differs only in approved references; release authority and platform scope satisfied. |

Steps can be small reviewed batches, but cannot skip the safety gates. New code ships with tests in its implementation PR; run touched files during development and the complete approved suite at the release gate. A passing subset must never be labeled full parity.

### Tests that come over

Bring **all tests and fixtures for retained code**, including less visible failure/recovery cases, not only smoke tests. Concrete baseline examples identify the suites to start from; this is not an exhaustive test manifest:

| Contract | Baseline test examples |
|---|---|
| Anti-hedging, response/completion and continuation | `tests/test_response_guards.py`, `tests/test_guard_capacity.py`, `tests/test_agent_completion_classifier.py`, `tests/test_wait_for_agents_deadlines.py`, `tests/test_nested_agents.py` |
| Effect classification and governor floor/shape | `tests/test_tool_effect_classifier.py`, `tests/test_risk_classifier.py`, `tests/test_governor_policy_floor.py`, `tests/test_governor_shape_matrix.py`, `tests/test_governor_shape_fixtures.py`, `tests/test_git_force_push_governor.py` |
| Durability, receipts, resume, spent budgets | `tests/test_turn_state_store.py`, `tests/test_turn_durability_heartbeat.py`, `tests/test_resume_admission.py`, `tests/test_chat_steering_parity.py`, `tests/test_chat_steering_resume.py`, `tests/test_executor_timeout_durability.py` |
| Owned execution, transactional writes, trust/output | `tests/test_local_supervisor.py`, `tests/test_local_supervisor_ack.py`, `tests/test_local_supervisor_pidfd.py`, `tests/test_campaign_remote_supervisor_proof.py`, `tests/test_apply_patch.py`, `tests/test_apply_patch_payload.py`, `tests/test_output_authorization.py`, `tests/test_process_retention_security.py`, `tests/test_local_workspace.py` |
| Input, state, schedules and nested dispatch | `tests/test_attachments.py`, `tests/test_async_utils_settled.py`, `tests/test_session_persistence_reliability.py`, `tests/test_knowledge_store_durability_preconditions.py`, `tests/test_scheduler.py`, `tests/test_scheduler_gate_races_campaign.py`, `tests/test_skill_definition_publication.py`, `tests/characterization/test_native_skill_dispatch_pins.py` |
| Computer input/guardian/quarantine | `tests/test_computer_x11_focus_guardian.py`, `tests/test_computer_pixel_guards_r19.py`, `tests/test_computer_wayland_guardian_r8.py`, `tests/test_computer_hyprland_durable_fence_r42.py`, plus the complete fixture/helper/native proof closure for the chosen backends |

Where engine code is shared, test **assertions, case data and budgets stay byte-identical**. Prefer separate thin adapter fixtures or Desktop boundary tests over rewriting upstream expectations. If a test file must change for genuine surface coupling, ledger the exact exception and retain an identical engine-case corpus; do not describe that whole file as identical. Upstream Discord/social tests may be excluded only with their stripped feature recorded. A Discord-shaped fixture for retained stop/resume/guard behavior is adapted, not discarded.

Platform proofs remain platform-specific and additional to unit tests. Desktop lifecycle and computer-input tests run only in hard-isolated graphical environments or explicitly approved acceptance sessions; no installer/autostart/teardown experiment in Aaron's active desktop. No project test runs from `/opt/odin` or against its live state.

### "Removed features leave no references": a checkable definition

No removed feature remains in executable registrations, import/dependency closure, tool schemas/names/descriptions, config fields/defaults/apply modes, native methods/routes/menus, model-facing errors/status/guard instructions, shipped default context/help, packaging hooks, autostart/service units or generated assets. Verify source, resolved dependencies **and the built distribution**, plus the runtime offered catalog and management inventory in isolated acceptance.

A raw `Discord` string count is insufficient. For example, a renderer tab can vanish while its API still accepts mutations; a transitive dependency can still start a gateway. Conversely, preserving `src/discord/tool_loop.py` for drift tracking is not shipping a Discord feature. Source paths, license/legal notices, historical design evidence, port records and intentionally negative regression fixtures may retain provenance terms in an explicit, narrow non-runtime allowlist. That allowlist cannot excuse model-facing or live feature references. Separately, credential-recognition patterns may retain the names/shapes of real third-party secrets; this exception permits protection, not a removed feature, transport dependency, registration or model-facing guidance (detectors are live protection, so they are not part of the non-runtime allowlist). A configured third-party integration that genuinely targets Discord is evaluated as such, not silently relabeled as desktop chat; transport-only dependencies stay excluded unless a separately retained integration actually requires them.

D1's zero-Discord prompt check and approved-diff byte check are separate gates. Guards/classifiers are not exempt from review because the offending text is "just a string". The current mention inventory is a baseline discovery aid, not proof of future bundle cleanliness.

## 4. Port ledger and review cadence

### Ledger fields

The ledger is tracked and reviewable in Desktop, not a private memory or spreadsheet. It has an upstream commit index plus per-path/per-change records, so one commit that mixes UI, guard and packaging changes cannot be marked wholly irrelevant by accident.

| Field | Required value |
|---|---|
| Origin | Repository, full source commit(s)/range, issue/PR, release, direction (Odin to Desktop or Desktop to Odin) |
| Scope | Source/destination paths and symbols, reuse verdict, baseline digest, exact change/hunks and dependency/test/assets closure |
| Intent | Bug/security/behavior/UI/platform/dependency change; actual contract affected; applicability to each product |
| State | Pending, in review, ported, not applicable, conflict-blocked, intentionally divergent, or reverted; date and reason |
| Port identity | Destination commit(s)/PR, exact-copy or adaptation status, inverse/backport link and commit when completed |
| Evidence | Identical test corpus/digests, changed boundary tests and approvals, results, coverage/CI/native proof links, limitations |
| Accountability | Owner, reviewer, severity/urgency, review deadline and next revisit, approval for model-facing/safety wording |
| Divergence | Exact Desktop patch/digest, rationale, platform/surface constraint, nonweakened invariant and upstream-equivalent evidence |
| Release status | Reviewed source release/head, Desktop release containing fix, blocker/exception record and public compatibility note where needed |

"Not applicable" names the removed feature or demonstrated unaffected contract. "Intentionally divergent" is a continuing obligation, not a permanent ignore rule. Every upstream commit since the baseline gets a classified index entry, including merges with their already-indexed ancestry, without pretending each merge requires a duplicate port. Record reverts and follow-up fixes; reverting a prior fix changes its applicability and test obligations.

### Cadence

- Review each Odin release when announced, and at least **weekly** during active Desktop development or support. Track all intervening commits, not only release-note bullets. At every Desktop PR touching common code, inspect pending upstream changes in those paths before merging.
- Triage a known critical security/guard/governor/containment or uncertain-effects fix **immediately**, outside the weekly batch. Freeze affected releases until ported or a reviewed applicability decision is evidenced. Set explicit deadlines for other relevant fixes; an unowned pending entry is not maintenance.
- Before **every Desktop release**, reconcile through a pinned upstream commit/release and publish the review watermark. An Odin release review precedes any Desktop release advertised as matching it. Product versions need not share numbers or simultaneous schedules; the exact included/excluded fixes matter.
- Release CI reports outstanding relevant entries, stale reviews and blocked safety changes. Exceptions for lower-risk feature changes are scoped, owned, time-bounded and disclosed; no unexplained safety divergence is released.

### Desktop-originated fixes flow back

For a fix to common logic, open/link the corresponding Odin issue/PR and port the minimal engine fix plus identical regression cases. Keep Desktop-only UI/platform work out of the Odin diff. Mark upstream status pending until the Odin change actually lands; local Desktop completion does not prove both repositories fixed. Apply each repository's review/merge/deployment authority independently. This plan is **not** authorization to edit, deploy or restart Odin during the present phase.

If upstream cannot accept the same patch, record the conflict and a semantically equivalent upstream fix with evidence, or an explicitly reviewed divergence. Security findings follow the repository's private reporting process rather than publishing exploit detail in a public ledger.

### Conflicts and purposeful divergence

Compare three things: frozen origin, the previously ported source state, and the exact Desktop adaptation. Never resolve a conflict by blindly taking "ours" or copying a newer guard over an adapter. Split common logic from surface changes inside Desktop where it reduces conflicts, while retaining upstream paths for common modules. Record line/symbol movement in the mapping; no cross-repo extraction is needed.

For deliberate differences (owner identity, app lifecycle, delivery, storage roots, platform capability publication), document the precise changed behavior, tests and invariant retained. New upstream changes must still be reviewed against those differences. If equivalent safety cannot be demonstrated, block that capability/release rather than call it harmless drift. Guard text substitutions require the same review as runtime logic changes.

## 5. Drift control and CI design

**Common modules keep Odin's paths**, including non-transport engine modules currently under `src/discord/`. This is source-layout continuity, not retaining the gateway. New Desktop adapters may live elsewhere; explicit path mappings cover replacements/stripped modules. File versions, Desktop bundle version, upstream baseline and review watermark stay separate.

The planned drift report compares:

1. the frozen baseline manifests/blobs;
2. every reviewed upstream change through a pinned watermark;
3. the ledgered expected Desktop state (ports plus exact approved Desktop deltas);
4. actual source, tests, runtime assets and dependency lock state in the PR/build.

It reports added/removed/renamed files, exact content differences, unreviewed upstream changes, unexplained local changes, expired divergence records and test-corpus drift. Content checks are byte-based, not an AST/whitespace-normalized comparison that could conceal strings, policy values or shell payload changes. An explained difference still requires reviewer evidence; a ledger entry is not automatic safety approval. CI uses retained pinned upstream objects, not a network branch head that can change midway through the run.

### Safety gate

Maintain a reviewed safety-critical path/symbol manifest covering response/anti-hedging guards, foreground and agent completion classifiers, command/effect classifiers, governor floor and parsing, local/remote containment and descendant settlement, workspace/patch identity, outcome provenance, output authorization, durability/resume budgets and computer release/quarantine. Include transitive helpers, bundled scripts and tests, not only filenames containing `guard` or `supervisor`.

- CI **flags every divergence** in guard, classifier, governor and containment code and **fails on unexplained divergence**, missing path mappings, missing identical behavior cases or silently changed approvals/budgets. Expanding this gate to the adjacent safety contracts above prevents a helper change from escaping it.
- Approved D1/guard-string substitutions are exact-hunk exceptions with approval and tests, never file-wide ignore entries. A changed surrounding byte reopens review.
- Changes to the ledger, safety manifest or test exceptions require review by someone other than the author; otherwise deleting a guard from the manifest would make the report green without protecting anything.
- Boundary/platform tests qualify adaptations; shared engine tests stay identical. Comparing green badges with different assertions is not parity.
- Packaging gates verify no removed runtime feature references and fresh-state/alongside isolation; renderer security/native lifecycle checks are additional, not replaced by source drift checks.

The release report names the source watermark, shared modules matching byte-for-byte, ledgered adaptations, remaining ports/conflicts, identical-case coverage, failed/unqualified native scenarios and release disposition. There is no claim of "identical engines" once there are intentional adaptations; the defensible claim is identified source lineage and verified contract parity within the qualified scope.

## 6. Risks, size and mitigation

Sizes are impact judgments, not measured failure rates or effort estimates.

| Risk | Size | Mitigation / gate |
|---|---|---|
| A safety fix lands in only one repository | **Critical** | Immediate safety triage, bidirectional ledger, linked regression/PR evidence and release block until reviewed port/applicability. |
| Surface adaptation weakens a guard, classifier or containment guarantee | **Critical** | Exact safety-path drift checks, unchanged behavior cases, independent review, native qualification, no tool publication when equivalence is unproven. |
| App crash or Exit leaves a child/input owner alive | **Critical** | App-owned supervision, qualified parent-loss containment, bounded shutdown receipts, durable unknown/quarantine and blocked replacement. Never infer cleanup from PID disappearance alone. |
| Ledger/allowlists hide changes rather than explain them | **High** | Per-hunk/contract evidence, review controls on manifests, no blanket safety ignores, stale-entry gates and periodic spot audits against source. |
| Fast upstream updates outpace two maintainers | **High** | Weekly/release review plus urgent lane, owned deadlines, published watermark and deliberate release delays rather than claiming current parity. |
| Dependency/assets omitted or drift outside source modules | **High** | Test/helper/runtime/dependency closure manifests, locked provenance, built-package scans and upgrade/native proofs. |
| Thin tests pass while Desktop's authority/admission boundary fails | **High** | Shared engine cases plus new IPC/lost-receipt/storage-failure/current-policy tests and R4 end-to-end acceptance. |
| Removed features remain reachable or leak instructions into the model | **High** | Source/catalog/config/bundle reference checks, model-facing inventory, strict prompt diff gate and no UI-only stripping. |
| Existing Odin data/services are accidentally adopted or mutated | **High** | Fresh namespaces/credentials, no import feature, hostile alongside-isolation tests, explicit no-service app lifecycle. |
| Intentional platform divergence becomes invisible | **High** | Explicit guarantees/capability scope, revisit on every affected upstream change, per-platform proofs; unqualified tools absent. |
| Superficial rename produces needless port conflicts | **Medium** | Preserve common paths, small adaptation hunks and separate Desktop surface modules; do not rename safety code merely to erase provenance. |
| Users mistake source parity for reach or availability parity | **Medium** | State D3/D6 openly: app must run, missed work follows policy, no phone/remote client first versions. |

## 7. Round-3 evidence and limits

Baseline source/test-path and design-document reads support this plan. The 409-file reuse inventory belongs to the inspected baseline, not a copied Desktop engine. No code was copied or edited, no ledger generator/CI/scanner/test was implemented or executed, and no lifecycle or package was qualified. These are implementation gates for later authorization, not completed checks.
