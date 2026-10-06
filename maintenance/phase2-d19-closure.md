# Phase 2 D19 closure inventory

**Phase 2 exit: NOT CLOSED.** This disposition inventory records five Aaron wording approvals, not full runtime-parity certification.

## Scope and counts

Baseline: `16e35e8f370661a2baf8e7030a27919b3e658b3b`. Section 4 of `maintenance/pr2-model-facing-string-approvals.md` contains **50 rows = 43 explicit NONE rows + 7 internal control/storage rows**. The requested 52 does not match the actual source; no rows are invented. The broader audit totals 53 only by including three section-5 documentation rows, which are out of this operational inventory.

| Disposition | Rows |
|---|---:|
| Removed by restored behaviour | 19 |
| Pending restoration (2 unassigned) | 14 |
| Internal unreachable guard (Claude review) | 12 |
| Proposed mechanical | 0 |
| Proposed behavioural (Aaron review) | 0 |
| Approved behavioural (Aaron, 2026-10-06) | 5 |
| Total section-4 rows | 50 |

## Removed by restored behaviour

- **D19-024, D19-025:** The old dependency refusal literals are absent. `tests/test_desktop_d19_behaviour.py::test_composed_skill_dependency_resolution_and_actual_admitted_execution` exercises preinstalled dependencies and missing-dependency installer success/failure through the real composed manager and admitted skill execution. Package metadata is real; missing-dependency pip subprocess I/O is stubbed. Dynamic result delivery remains gated, so these rows do not close skill delivery.
- **D19-045:** The old main-entry deferral is absent. Evidence: `tests/test_desktop_core_entry.py::test_real_core_accepts_node_style_socketpair_stdin_and_exits_on_parent_eof`, `tests/test_desktop_core_entry.py::test_entry_uses_containment_and_finalize_barrier`, and `tests/test_desktop_d19_behaviour.py::test_real_main_entry_and_local_client_complete_supervised_shutdown`.
- **D19-046:** The old CLI deferral is absent. `tests/test_desktop_d19_behaviour.py::test_real_cli_entry_authenticates_to_composed_core` exercises the actual CLI entry against the authenticated composed core, not just the LocalClient class.
- **D19-022, D19-023:** The skill history and scheduling fences are absent. `SkillContext` again delegates to its session-manager and scheduler surfaces, as v4.13.0 does; Desktop composes them as the request-bound transcript search and the admitted schedule service the native tools use. Evidence: `tests/test_desktop_d19_behaviour.py::test_restored_skill_history_searches_the_request_transcript`, `::test_restored_skill_scheduling_binds_owner_and_destination`, `::test_restored_skill_scheduling_refuses_an_unknown_destination` and `::test_skill_history_and_scheduling_require_an_admitted_request`; Odin's original `TestDelegations` and no-callback `TestMessaging` cases run again through the shared foundation adapter.
- **D19-003 to 008, 010, 018 to 021 and 043:** restored by merged PRs after round 3. Each row's restoration observation and evidence tests are in `maintenance/phase2-d19-closure.json`.
- **D19-049:** Merged **PR #69** restores the live `health.get` delivery projection. Exact evidence: `tests/test_desktop_health_delivery.py::test_health_delivery_ready_after_startup_and_real_guarded_turn`. Startup and a completed real guarded turn both report delivery ready, with durable publication observed. The ready/not-ready and uncomposed-owner diagnostics legitimately remain in `check_delivery`: this is composed behaviour restoration, not literal removal. The gate requires this exact status, restoration kind and test nodeid, without waiving active-string checks for any other row.

## Proposed mechanical substitutions

**NONE.** No instruction or behaviour change is presented as a Claude-reviewed noun swap.

## Recorded behavioural decisions and baseline context

**Aaron approved D19-011, 012, 013, 016 and 026 on 2026-10-06.** Their JSON status is `approved_behavioural`, reviewer `Aaron`, with `approval_date`. No behavioural proposals remain. Rows **014 and 015** are internal mis-composition guards with never-invoked branch proofs below; **043** is pending **D17 restoration (next bridge task)** because fail-to-start is stricter than Odin's warn-and-ignore. No config code is changed here. Rarity below is an engineering estimate from guard conditions, not measured incident frequency. Baseline citations refer to the pinned `maintenance/odin-v4.13.0.tar.gz`, SHA-256 `845d783bd4ee46cd44e63d56532512fd9cef10d08b1432e45047d155c6b348d0`.

### D19-011: permission denial propagation
**When Odin sees it:** A requested tool or selected `invoke_skill` target is denied by authenticated owner policy or its live request scope has been revoked, producing `permission_denied`; unusual in normal single-owner use but expected when stale calls cross a policy/scope change.
**Baseline:** Odin already returns `permission_denied` with `Permission denied: tool scope revoked or unavailable.` or `Permission denied: restricted tool authority.`, and owner-policy denial says `Permission denied: tool '{tool_name}' is not available for tier '{tier}'. Contact an admin to upgrade your permissions.`; the added selected-skill scope check is Desktop-specific, not a wholly new denial state (`src/tools/executor.py:763-780,824-836,882-930`; `src/discord/native_tools/skills_tools.py:154-179`).

### D19-012: delivery readiness recheck
**When Odin sees it:** Immediately before output delivery, an admitted tool has lost live handler readiness or the executor lacks its required readiness policy, so delivery raises `Output capability unavailable.`; rare capability-change races or broken composition, not an ordinary successful-tool response.
**Baseline:** Odin's `deliver_output` has no equivalent general post-execution handler-readiness check and normally returns/delivers the result, although retained-output retrieval and binary retention already recheck permissions, disabled-tool state and request/host scope (`src/tools/executor.py:663-709,721-751`).

### D19-013: unavailable handler refusal
**When Odin sees it:** A stale or manually supplied model call names a tool whose handler is not ready in this installation, yielding `Tool unavailable: '{name}' has no ready handler for this installation and was not executed.` with `tool_unavailable`; uncommon when healthy because unavailable tools are normally absent from the catalog, but realistic after readiness changes.
**Baseline:** Missing handlers return `Unknown tool: {tool_name}` with `unknown_tool`, configured-disabled tools return `Tool disabled by configuration: '{name}' is disabled for this installation and was not executed.` with `tool_disabled`, and otherwise resolved handlers proceed without Desktop's general readiness gate (`src/tools/executor.py:824-836,882-907`; `src/tools/builtin_policy.py:52-63,66-90`).

### D19-014: missing retention consumer
**When Odin sees it:** A native/provider/deferred result reaches runtime delivery through an executor class without callable `deliver_output`, raising `Output retention unavailable: no authenticated executor consumer is configured. Do not replay the tool.`; exceptional missing-consumer composition, not a normal configured Desktop flow.
**Baseline:** Odin explicitly supports the equivalent embedded-dispatcher case by calling `deliver` without a store, returning small scrubbed output normally and reporting `Retention unavailable; output not retained; no continuation exists.` when retention is needed (`src/tools/runtime_delivery.py:40-52`; `src/tools/output_delivery.py:270-290`).

### D19-015: missing output authority
**When Odin sees it:** Runtime delivery has an executor but cannot establish output authority because its class lacks callable `check_permission` or the built-in policy is missing, raising `Output authority unavailable. Do not replay the tool.`; exceptional malformed or incompletely composed executor state.
**Baseline:** Odin runtime delivery does not require those authority interfaces before handing output to `deliver_output` or its no-store fallback, while normal retained-output delivery enforces permission and scope checks, so missing-interface delivery is allowed rather than rejected with this text (`src/tools/runtime_delivery.py:40-52`; `src/tools/executor.py:663-689,721-751`).

### D19-016: output revocation/readiness race
**When Odin sees it:** Runtime delivery rechecks a completed tool and finds live permission denial or lost handler readiness, raising the denial text followed by ` Do not replay the tool.`, or `Output capability unavailable. Do not replay the tool.`; rare revocation/readiness races where prior effects are explicitly not grounds for retry.
**Baseline:** Odin has no equivalent universal runtime-delivery precheck or no-replay suffix at that boundary, but already refuses unauthorized binary retention with `Originating output scope is no longer authorized.` and continuation with `Retrieval is not authorized; no continuation exists.` (`src/tools/runtime_delivery.py:40-52`; `src/tools/executor.py:691-709,740-748`).

### D19-026: empty resume fetch
**When Odin sees it:** Resume fetch returns `None` without a positive not-found result, reporting `the original message could not be fetched yet` and leaving preserved work unresolved instead of declaring deletion; rare empty-adapter/store-failure behaviour, not a normal missing-message response.
**Baseline:** The identical phrase already covers transient/unexpected fetch exceptions, but an empty `None` read specifically marks the row rejected with `original message unavailable`, releases calibration and returns `the original message is gone`, exposed by explicit resume as `I couldn't resume the preserved work: the original message is gone. Ask again from scratch if you still need it.` (`src/discord/turn_resume.py:429-435,441-469`).

### D19-043: unsupported configuration keys
**When Odin sees it:** Startup or explicit configuration loading encounters an unsupported top-level key, such as a typo or old server-only section, and stops with `Config validation failed: unsupported top-level configuration fields`; uncommon for generated fresh profiles but realistic for hand-editing/obsolete-config reuse, primarily a startup diagnostic rather than a routine tool result.
**Baseline:** Odin warns `Ignoring unknown config key(s): %s — check for typos (known top-level sections: %s)` and continues with Pydantic dropping unknown fields, deliberately permitting slightly-ahead configurations rather than failing boot (`src/config/schema.py:1772-1775,2014-2018,2041-2047,2062-2079`).

## Internal unreachable guards

Reviewer: **Claude**. Eleven guarded rows were never invoked on the representative real composed profile: chat with tool/history and durable file output, MCP start/connect/tool publication/disable/close, shutdown, and **background admission refusal only**. No assigned guard was reached; this is not a global-unreachability claim for arbitrary legacy callers.

All nine cite `tests/test_desktop_d19_unreachable.py::test_composed_flows_never_invoke_legacy_guards`. Callable spies raise on invocation and assert zero calls even if a caller swallows the exception; original code-object trace spies additionally catch pre-imported aliases, with `test_original_guard_code_spy_catches_preimported_resume_alias` as a positive control. Other positive controls are `test_fail_spies_are_attached_to_existing_callable_targets` and `test_missing_reader_branch_spy_positive_control` in the same file.

| Row | Exact AST path / selector | Proof |
|---|---|---|
| 001 | `src/discord/native_tools/channel_ops.py` / `ChannelOpsTools._handle_read_conversation` | AST-selected missing-reader return only: raising trace spy on actual code-object branch lines; handler and composed reader positively execute, backstop never does. |
| 014 | `src/tools/runtime_delivery.py` / `deliver_runtime_output`, `deliver_runtime_result` | AST-selected actual missing-consumer raise branches, raising code-object/line spies; zero hits, successful delivery helpers positively execute. Both raise branches have malformed-executor positive controls. |
| 015 | `src/tools/runtime_delivery.py` / `_require_retention_authority` | AST-selected missing-authority raise branch, raising code-object/line spy; zero hits, successful authority checks positively execute. Missing permission and missing policy have separate positive controls. |
| 017 | `src/tools/output_authorization.py` / `owner_output_scope` | Raising callable and original code-object spies; zero calls. |
| 027 | `src/discord/tool_loop.py` / `_require_phase2_wiring` | Raising callable/code-object spies, including imported resume alias; zero calls. |
| 028 | `src/discord/delivery.py` / `DeliveryService.__init__` | Raising constructor/code-object spies preserve class identity; zero calls. |
| 032 | `src/discord/intake_pipeline.py` / `_require_phase2_admission` | Raising callable/code-object spies and verified caller globals; zero calls. |
| 037 | `src/discord/slash_commands.py` / `register_commands` | Raising callable and original code-object spies; zero calls. |
| 038 | `src/discord/wiring.py` / `build_services` | Raising callable and original code-object spies; zero calls. |
| 039 | `src/discord/wiring.py` / `build_components` | Raising callable and original code-object spies; zero calls. |
| 040 | `src/discord/wiring.py` / `start_mcp` | Raising callable and original code-object spies; zero calls. |
| 006 | `src/discord/native_tools/agents_tasks.py` / `AgentTaskTools._handle_spawn_agent` | Separate AST + compiled-code omission + real-owner trace proof behind the unconditional 005 fence. |

**Background limitation:** no successful background task was executed. This branch has no `authenticated_scope`, `register_background`, or `background_execution` composition seam; `delegate_task` is hidden/refused before its handler, so requested successful composed-background guard coverage awaits **PR #37 (6B)**. The tests expose that pre-dispatch limitation rather than fabricating a task-owned context.

Rows **014/015** share the composed-flow proof and cite `test_runtime_miscomposition_branch_spies_positive_control` in the same test file. Their exact raises remain live for mis-composed executors; this disposition does not claim they are removed or approve malformed-engine delivery.

**006** cites `tests/test_desktop_d19_unreachable.py::test_restored_agent_context_requires_admission_and_reaches_real_registration`: its obsolete inner raise has no executable bytecode line or diagnostic constant, and a fail-on-line code-object spy has zero hits. The restored agent path requires admission and reaches real registration only with a valid admitted context; stale contexts remain refused. The composed-flow proof now exercises `background_admission`, not `background_admission_refusal`; this is scoped admission/registration evidence, not full background qualification.

## Pending restoration

Every pending fragment must still have an active AST match in the current checkout; the gate recomputes this and fails when a merged change removes/inactivates a fragment until disposition/evidence is updated. D19-010's folded export failure retains actual expression slots, not the audit's descriptive placeholders.
Each normal fragment binds to its recorded source path. D19-050 explicitly records its cross-module operation caller paths, so an identical string elsewhere cannot mask a restored/removed caller.

| Rows | Owner | Exact pending reference | Dependency / scope |
|---|---|---|---|
| 002, 031 | Odin | PR #48 (media publication) | Generated-image/browser-screenshot publication identity and durable bytes. |
| 033, 034, 035, 036, 041, 042, 044 | Odin | PR #37 (6B) | Work/report/schedule recovery, native producers, background execution and publication. |
| 029, 030 | Odin | PR #37 (6B) | Foreground admission/binding; **P3.5** is the separate native receiver/quarantine qualification dependency (`docs/work/phase-3-app-v1.md:238-269`). |
| 047 | Odin | P3.3 | Relaunch/bounded shutdown/replacement acceptance, not PR61 status reporting (`docs/work/phase-3-app-v1.md:175-209`). |
| 048, 050 | unassigned | unassigned | Two gaps remain unassigned below. |

- **048:** Actual onboarding is **P3.2**, outside the permitted owner references (`docs/work/phase-3-app-v1.md:133-171`); PR61 fresh-profile parity evidence does not restore `setup_wizard.is_setup_needed`, and P3.3/P3.5 do not own onboarding.
- **050:** The omnibus `require_phase2` helper spans conversation, skill, lifecycle, setup, work and scheduling operations; PR37, PR62, PR61 and P3.3 are only operation-level dependencies, and PR42 inbound webhooks do not restore the whole row.

No pending row is assigned to **PR #42 (step 7)** or **PR #61 (step 8 closure, lane 2)** merely because scheduling/status words appear; their inspected work does not own a complete remaining row. There are no fictitious lane names.

**Round-3 merged-code recheck:** merged `main` at `c680b15d`, including #69. Every other pending row and each 050 caller still has its active source-bound diagnostic, so no additional removal/restoration is claimed. The path-keyed ledger retains both parent path sets; actual changed bytes and test citations are re-recorded with `inventory.py record`.

## Evidence and limits

**Round 3:** **92 gate tests**, **63 guard/composed/health tests**, and **68 short fixture/ownership tests** passed in the restricted ordinary-user PID namespace. D19 gate statement coverage: **252/258, 97.67%**. Drift report has **0 errors**, ownership-plan gate passes, lint has no new findings, and touched-file Ruff/diff checks pass. No full qualification. Current counts and external artifact digests are in `phase2-d19-round3-validation.json`. A malformed-status regression and an incorrect coverage selector were corrected before these final results; initial evidence is retained.

**Round 2:** 76 gate tests passed with **97.53% gate statement coverage** (237/243 statements; rounded report: 98%), plus 47 guard/composed tests (15 new guard tests and 32 existing composed tests), and 38 hermetic short-gate fixture tests. All ran under the sanitized ordinary-user PID namespace. D19 and ownership-plan gates passed; no new lint findings and touched-file Ruff/diff checks passed. No full qualification was run this round. Small receipts and external artifact digests are in `phase2-d19-round2-validation.json`.

Two test-instrumentation corrections were not runtime restorations: the first incremental coverage selector named a file as a module and collected no data; an initial alias-trace spy accidentally targeted the shared `contextlib` wrapper instead of the unwrapped guard generator. The corrected final runs passed; both failed-attempt logs are retained outside Git. Background-task execution remains explicitly unproved pending PR #37.

The paired JSON preserves each exact source-location/string key, fragments, resolved source path and table-line number. Expanded AST observations are deliberately omitted: `scripts/maintenance/d19.py` computes them during the gate. Plain-language `restoration_observation` distinguishes literal absence/presence from demonstrated composed behaviour.

Composed test references cover authenticated current-conversation history, real durable generate_file/post_file bytes, retention paging and live capability revocation, revision-bound attachment admission and deduplication, shared management/executor/runner owners, and orderly shutdown. Negative proofs of hidden tools, skill callback fences and unsupported foreground computer input identify remaining limits, not restorations. Scoped legacy-guard proofs change disposition, not source bytes or background parity.

Health is restored by #69; image/browser media publication, autonomous/scheduled producers, full skill delivery, relaunch, onboarding, qualified foreground computer control, unknown-key D17 parity and mixed web endpoints remain open.

**Previous-round evidence only:** executed locally in the sanitized ordinary-user PID namespace: **46 gate tests**, **32 composed-engine tests**, and **165 existing integration/regression tests** passed. The then-current gate module had **97% statement coverage**. A first coverage command used the dynamic module's wrong import name and collected no data; the corrected path-based run produced the measured coverage. These are not round-2 validation counts or current coverage measurements.

**Previous-round qualification only:** the full classified qualification ran once: **31/31 groups, 14,704 passing executions, three skips, zero failures/errors**; no full qualification is requested or claimed for round 2. That inherited run is not final product acceptance, and its drift/lint results are previous-round evidence. Raw qualification evidence is external, with path and SHA-256 in `phase2-d19-validation.json`; round-2 validation is recorded separately after the focused tests and short gates.

The static gate validates coverage, dispositions and references, not composed runtime restoration or wording approval. Raw logs, full AST scans and large artifacts are not stored in Git here. No model-facing source or approval-table bytes are changed.
