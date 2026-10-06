# Phase 2 D19 closure inventory

**Phase 2 exit: NOT CLOSED.** This is a disposition inventory and review proposal, not wording approval or full runtime-parity certification.

## Scope and counts

Baseline: `16e35e8f370661a2baf8e7030a27919b3e658b3b`. Section 4 of `maintenance/pr2-model-facing-string-approvals.md` contains **50 rows = 43 explicit NONE rows + 7 internal control/storage rows**. The requested 52 does not match the actual source; no rows are invented. The broader audit totals 53 only by including three section-5 documentation rows, which are out of this operational inventory.

| Disposition | Rows |
|---|---:|
| Removed by restored behaviour | 4 |
| Pending restoration | 29 |
| Proposed mechanical | 0 |
| Proposed behavioural | 17 |
| Total section-4 rows | 50 |

## Removed by restored behaviour

- **D19-024, D19-025:** The old dependency refusal literals are absent. `tests/test_desktop_d19_behaviour.py::test_composed_skill_dependency_resolution_and_actual_admitted_execution` exercises preinstalled dependencies and missing-dependency installer success/failure through the real composed manager and admitted skill execution. Package metadata is real; missing-dependency pip subprocess I/O is stubbed. Dynamic result delivery remains gated, so these rows do not close skill delivery.
- **D19-045:** The old main-entry deferral is absent. Evidence: `tests/test_desktop_core_entry.py::test_real_core_accepts_node_style_socketpair_stdin_and_exits_on_parent_eof`, `tests/test_desktop_core_entry.py::test_entry_uses_containment_and_finalize_barrier`, and `tests/test_desktop_d19_behaviour.py::test_real_main_entry_and_local_client_complete_supervised_shutdown`.
- **D19-046:** The old CLI deferral is absent. `tests/test_desktop_d19_behaviour.py::test_real_cli_entry_authenticates_to_composed_core` exercises the actual CLI entry against the authenticated composed core, not just the LocalClient class.

## Proposed mechanical substitutions

**NONE.** No instruction or behaviour change is presented as a Claude-reviewed noun swap.

## Proposed behavioural review by Aaron

These are proposals for Aaron, not approvals; retained active guards cannot be declared removed just because an alternate real path works.

- **D19-001:** Retain the missing-reader backstop while routing authenticated history to the real durable transcript reader.
- **D19-011:** Propagate permission codes without exposing unauthorized tool results.
- **D19-012:** Recheck live output capability before retaining or delivering a skill result.
- **D19-013:** Reject an unavailable handler explicitly without pretending the tool executed.
- **D19-014:** Refuse retention without an authenticated consumer and forbid replay of the tool.
- **D19-015:** Refuse output lacking authenticated authority and forbid replay of the tool.
- **D19-016:** Refuse revoked output capability and forbid replay of the tool.
- **D19-017:** Retain the legacy missing-scope refusal while real request owners supply scoped output authority.
- **D19-026:** Treat an empty original-message read as unresolved rather than proof of deletion.
- **D19-027:** Keep the legacy tool-loop wiring guard while the real admitted core uses ToolLoopRunner.
- **D19-028:** Keep the legacy delivery-constructor guard while the real core uses DurableDelivery.
- **D19-032:** Keep the legacy intake guard while the real core admits authenticated revision-bound requests.
- **D19-037:** Keep the legacy registration guard while real owner-bound controls are composed separately.
- **D19-038:** Keep the legacy composition stub while the real CoreService composes shared runtime owners.
- **D19-039:** Keep the legacy component stub while the real core binds request, control and durable surfaces.
- **D19-040:** Keep the legacy MCP startup stub while the real supervised management path owns MCP state.
- **D19-043:** Reject unsupported top-level configuration fields rather than silently accepting them.

## Pending restoration

Every pending row has owner **Odin** and a lane/reference. D19-010's folded export failure remains present with actual expression slots rather than the audit's descriptive placeholders.

- **D19-002** | owner: **Odin** | reference: media generate_image/browser artifact publication lane.
- **D19-003** | owner: **Odin** | reference: PR37 durable producers/admission/publication lane.
- **D19-004** | owner: **Odin** | reference: PR37 durable producers/admission/publication lane.
- **D19-005** | owner: **Odin** | reference: PR37 durable producers/admission/publication lane.
- **D19-006** | owner: **Odin** | reference: PR37 durable producers/admission/publication lane.
- **D19-007** | owner: **Odin** | reference: PR37 durable producers/admission/publication lane.
- **D19-008** | owner: **Odin** | reference: PR37 durable producers/admission/publication lane.
- **D19-009** | owner: **Odin** | reference: skill-delivery lane 3: context callbacks, output readiness and export publication.
- **D19-010** | owner: **Odin** | reference: skill-delivery lane 3: context callbacks, output readiness and export publication.
- **D19-018** | owner: **Odin** | reference: PR37 durable producers/admission/publication lane.
- **D19-019** | owner: **Odin** | reference: PR37 durable producers/admission/publication lane.
- **D19-020** | owner: **Odin** | reference: skill-delivery lane 3: context callbacks, output readiness and export publication.
- **D19-021** | owner: **Odin** | reference: skill-delivery lane 3: context callbacks, output readiness and export publication.
- **D19-022** | owner: **Odin** | reference: skill-delivery lane 3: context callbacks, output readiness and export publication.
- **D19-023** | owner: **Odin** | reference: skill-delivery lane 3: context callbacks, output readiness and export publication.
- **D19-029** | owner: **Odin** | reference: computer foreground qualification and owner-bound control lane.
- **D19-030** | owner: **Odin** | reference: computer foreground qualification and owner-bound control lane.
- **D19-031** | owner: **Odin** | reference: media generate_image/browser artifact publication lane.
- **D19-033** | owner: **Odin** | reference: PR37 durable producers/admission/publication lane.
- **D19-034** | owner: **Odin** | reference: PR37 durable producers/admission/publication lane.
- **D19-035** | owner: **Odin** | reference: PR37 durable producers/admission/publication lane.
- **D19-036** | owner: **Odin** | reference: PR37 durable producers/admission/publication lane.
- **D19-041** | owner: **Odin** | reference: PR37 durable producers/admission/publication lane.
- **D19-042** | owner: **Odin** | reference: PR37 durable producers/admission/publication lane.
- **D19-044** | owner: **Odin** | reference: PR37 durable producers/admission/publication lane.
- **D19-047** | owner: **Odin** | reference: supervised relaunch teardown/replacement lane.
- **D19-048** | owner: **Odin** | reference: fresh-profile onboarding lane.
- **D19-049** | owner: **Odin** | reference: health/readiness projection lane.
- **D19-050** | owner: **Odin** | reference: PR37/PR42 mixed web-management endpoints and management projection lane.

## Evidence and limits

The paired JSON preserves each exact source-location/string key, fragments, resolved source path and table-line number. Expanded AST observations are deliberately omitted: `scripts/maintenance/d19.py` computes them during the gate. Plain-language `restoration_observation` distinguishes literal absence/presence from demonstrated composed behaviour.

Composed test references cover authenticated current-conversation history, real durable generate_file/post_file bytes, retention paging and live capability revocation, revision-bound attachment admission and deduplication, shared management/executor/runner owners, and orderly shutdown. Negative proofs of hidden tools, skill callback fences and unsupported foreground computer input identify remaining limits, not restorations. Successful history and file publication do not remove their still-present legacy backstops.

Health remains pending because the actual projection still emits its delivery-unavailable diagnostic. Image/browser media publication, autonomous/scheduled producers, full skill delivery, relaunch, onboarding, qualified foreground computer control and mixed web endpoints remain open.

Executed locally in the sanitized ordinary-user PID namespace: **46 gate tests**, **32 composed-engine tests**, and **165 existing integration/regression tests** passed. The gate module has **97% statement coverage**. A first coverage command used the dynamic module's wrong import name and collected no data; the corrected path-based run produced the measured coverage. No runtime failures were hidden by that reporting correction.

The static gate validates coverage, dispositions and references, not composed runtime restoration or wording approval. Raw logs, full AST scans and large artifacts are not stored in Git here. No model-facing source or approval-table bytes are changed.
