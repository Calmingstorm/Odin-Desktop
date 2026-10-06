# Step8 part2 batch C

Independent worktree `/home/odin/desktop-phase2-step8-part2/batch-c`, branch
`phase-2/step8p2-batch-c`, base `b74056c4c9a16071426cb832db361cf86c84989a`.
Read CONTRIBUTING and `/home/odin/reviews/desktop-pr26-review.md` before execution.
Assignment: step5 paths sorted, indices `[2::4]`, **21 owned suites**.
Prior audit `auditc5ab488b` was unavailable. Fresh frozen-source and current
entrypoint inspection plus read-only child `5339d0da` supplied evidence.

## Whole-suite result

Three suites are restorable, subject to parent integration/qualification:

| Suite | Mode | Inherited definitions | Assertions |
|---|---|---:|---:|
| `test_search_small_delivery_budget.py` | direct original | 2 | 9 |
| `test_turn_recorder_webhook_campaign.py` | direct original | 3 | 13 |
| `test_knowledge_ingest_outcomes.py` | full frozen adapter | 25 | 98 |

Original files remain byte-for-byte unchanged. All21 original hashes verified by
`frozen_source` against pinned archive. JSON records every original digest, complete
case/assertion counts, concrete blocker source/case references and proposed status.
No subset is counted restored; deferred means a whole-suite adaptation blocker,
not a final retirement or a failing test execution.

## Precise ingestion adaptation

`tests/desktop_adapters/step8_runtime_c.py` pins original source SHA256:
`b2e46ac4039a15a267e14d9edd40ac420f4492ab5593fe7cc3f83ae8cb382a6d`.
Only `BulkImporter(store)` becomes
`BulkImporter(store, admitted_roots=[tmp_path])` at these original positions:

| TestImporterOutcomes method | Line |
|---|---:|
| `test_reimport_of_stored_file_reports_already_stored` | 287 |
| `test_identical_content_under_another_source_is_skipped_not_failed` | 308 |
| `test_durability_failure_is_still_an_error` | 328 |
| `test_near_duplicate_import_is_skipped_with_the_existing_source` | 341 |
| `test_plain_int_results_from_a_double_keep_old_semantics` | 375 |
| `test_unchanged_counts_as_success_and_duplicate_as_skipped` | 391 |
| `test_web_url_reimport_reports_unchanged` | 427 |

Before call AST SHA256:
`e159c243595f10ab2c0d3a56c7a4c1d1c84b27df07e4bd30d5929e1eb37ec159`.
After call AST SHA256:
`b7d59529b5f9169038899808c2185b6f48b33155e3ffaafa397ac0ae46fbf969`.
Owner/line/exact AST/digests guard each hunk. Independent expected whole AST and
corpus equality preserve all98 assertions,25 signatures/decorators and4 classes.
Line362 classification-only `BulkImporter(MagicMock())` stays unchanged, with no
new fixture signature. Every original definition/helper/import is executed/exported.
Literal whole `CORPUS_SELECTIONS`, empty exclusions, pinned `SUITES`, complete
compile-exec/register_module and `load(globals())` establish static full association.

Real importer roots are injected through `src/knowledge/importer.py:83-104`, never
mocked. Added boundary proof checks admitted success, outside denial with no durable
content, and no-root denial. Negative guards reject altered assertions/setup store/
roots and dropped helpers/cases; full export proof checks all original methods.
No denial-root test is relaxed or bypassed.

## All other owned decisions

The JSON has precise `blocked_on`, `references` and `evidence` for every entry.
Concrete whole-suite blockers:

| Index | Suite | Required full adaptation |
|---:|---|---|
| 2 | `test_audit_tail_v412.py` | Missing websocket byte reader/subscriber, not EventJournal parity. |
| 6 | `test_auth_snapshot_routes.py` | Removed token/auth middleware, owner/vault snapshot and last credential fencing. |
| 10 | `test_campaign_agent_routes_coverage.py` | Malformed policy JSON settings carrier, not agent execution. |
| 14 | `test_campaign_prefix_measurement.py` | Truthful runtime compression status instead of HTTP projection. |
| 18 | `test_campaign_startup_health.py` | Missing `_wire_observability`/stub HealthServer, knowledge corrupt-state/readiness mapping. |
| 22 | `test_codex_quota_check.py` | Bot quota wiring/current-serving pool, reload/retired-pool composition. |
| 26 | `test_config.py` | Reviewed legacy Discord secret/setup-wizard disposition plus defaults. |
| 30 | `test_executor_output_retention.py` | Live token revocation/host generations/web chat-WebSocket request scope. |
| 34 | `test_hosts_api.py` | Named HostRegistry transport preserving concurrency/audit/publication vetoes. |
| 42 | `test_listener_consent.py` | Reviewed management listener/admin consent versus real owner provision authority. |
| 46 | `test_onboarding_campaign.py` | Temporary profile/vault instead of old HTTP/Discord env carrier. |
| 50 | `test_pr341_b8_turn_totals.py` | Real request-recorder-JSONL-rollup Desktop source adaptation. |
| 54 | `test_process_retention_security.py` | Blocked executor helper/web principal live scopes plus persisted process policy. |
| 62 | `test_startup_onboarding_context.py` | ProfilePaths provisioning, legacy config/env/state/launch path ownership. |
| 70 | `test_web_api_llm_admin.py` | Complete named provider/settings fault/parameter matrix, no success-only subset. |
| 74 | `test_web_api_security_routes.py` | Corruption/audit/host invariants mixed with reviewed obsolete tier/RBAC cases. |
| 78 | `test_web_campaign_truth.py` | Owner IPC current identity/actual-serving truth, not configured-as-executed. |
| 82 | `test_websocket_bootstrap_auth.py` | IPC/session publication/subscriber fences, no permissive bootstrap route. |

## Validation and limits

Safe inspection: runner/conftest, originals, helper `test_knowledge_import`, real
importer. Existing webhook network stub and patched safe_fetch remain; DB/files
temporary. Only requested touched selections executed:

```
USER=odin .venv/bin/python scripts/run-phase1-tests.py tests/test_search_small_delivery_budget.py tests/test_turn_recorder_webhook_campaign.py tests/test_desktop_phase2_runtime_c.py
```

Final: **46 passed in10.92s**, exit0, zero skips:30 inherited cases and16 adapter/
provenance/root checks. Runner uses PID/mount namespace, `env -i`, odin user,
temporary HOME/XDG state and no display/DBus/session/credential inheritance.
Log: `/home/odin/desktop-phase2-step8-part2/batch-c-targeted-final.log`.
Static `_full_adapter` check returned True. Ruff on both new test modules passed.
No full qualification; deferred suites inspected only, never counted passing.

Only two new test modules and these two maintenance records changed. No product,
shared map/test-plan/ledger/checker/qualification-plan edits, no live/native desktop
or `/opt/odin` actions, no push. Parent owns central ledger and final integration.
