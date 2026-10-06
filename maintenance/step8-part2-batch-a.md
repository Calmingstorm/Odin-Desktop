# Step 8 part 2, batch A

Base: `b74056c4c9a16071426cb832db361cf86c84989a`. Independent branch/worktree only.
Assigned sorted step-5 indices `[0::4]`: **22 whole suites**, all recorded with
original source SHA-256 in `step8-part2-batch-a.json`.

## Restoration candidates and exact setup evidence

Three whole suites restored by the targeted selection. Fifteen inherited test
executions, no inherited assertion/signature/decorator/parameter exclusions.

* **56, provider_shutdown_budget**: direct original, four executions. Actual
  `src.discord.wiring.shutdown_services` and
  `src.llm.client_lifecycle.shutdown_provider_clients`. Desktop ProviderOwner
  calls the same provider shutdown primitive (`providers.py:527-529`). This
  proves retained shared shutdown budget/settlement behavior, **not** identical
  Desktop session/browser/image ownership composition.
* **64, tool_failure_visibility**: frozen adapter, four executions. The removed
  bot import and `_make_bot` body become a fixture container around the actual
  `ToolExecutor`. The execution user argument projects to the authenticated
  temporary owner. `BuiltinToolPolicy` admits the real ready multi-host handler,
  consistent with management's actual readiness at `management.py:147-156`.
  Unknown-host denial is produced by the real executor/domain handler. No
  injected error, unrelated policy refusal, or transport subprocess.
* **20, cancelled_persistence_settles**: frozen adapter, six functions/seven
  executions. The executor fixture calls the real class with private profile and
  authentic owner manager. The removed REST registrar setup becomes a narrow
  request projection into `StateService.handle("memory.set", ...)`, using the
  same gated executor backend. Success syntax `.status == 200` is returned only
  after the real domain reports a committed `saved` result. Errors and
  cancellation propagate, with no invented HTTP failure codes. All original
  stores, threaded gates, double cancellations, held-lock and not-done checks,
  subsequent writes, and disk comparisons remain unchanged. Inherited
  `ToolExecutor._save_all_memory` reference remains the real class method.

The JSON records **all five exact source setup hunks** with before/after SHA-256.
The `_make_bot` before-source segment is resolved from its original sealed symbol
rather than copying its inert credential literal into a report. Its hash pins
the entire original source segment. Exact-once replacement, exact reverse replay
to **complete original bytes**, and complete assertion/case/class AST corpus
equality are checked fail-closed before compilation. Two source hashes also live
as literal `SUITES` constants. Frozen archive and retained-file equality are
verified by `frozen_source`. No AST filters or partial exports exist.

Static association: `CORPUS_SELECTIONS` values are all `None`,
`CORPUS_EXCLUSIONS = {}`, literal `SUITES` hashes; `load(globals())` reaches
`export_suite`, which executes the complete checked tree then calls
`register_module(namespace, module, prefix=name, full_class_name=True)`.
Fixtures are copied separately without modifying their signatures.

## Nineteen whole-suite blockers

All remain uncounted. Concrete per-suite paths, source hashes and evidence are
in the JSON, not a partial class whitelist.

| Index | Suite | Whole-suite blocker |
|---:|---|---|
|0|action_diffs|Missing real diff-only filtered management query.|
|4|auth_entry_preservation|Removed tiers/token inventories and CRUD.|
|8|bootstrap_runtime_bind|Removed TCP/bootstrap listener and dynamic credentials.|
|12|campaign_authorization_persistence|Removed multi-user tier/ACL/token stores.|
|16|campaign_provider_reload_coverage|Removed exact persist/rollback call seam.|
|24|computer_config_admin_r19|Missing step-5 computer owner and obsolete HTTP admin contract.|
|28|connection_pools|Missing pool metrics/close management outcomes.|
|32|health_shutdown|Removed actual WebSocket lifecycle.|
|36|independent_credential_review|Old file/shadow/registrar contract differs from vault.|
|40|knowledge_versions|Missing named version-detail/diff retrieval.|
|44|log_search|Missing log stats; prohibited destructive literal input, not executed.|
|48|openrouter_admin_boundaries|Missing preview/pin/cache/quick-add management contract.|
|52|pr356_storage_compatibility|Removed legacy init/install/diagnostic HTTP contract.|
|60|startup_auth_middleware_review|Removed HTTP/anonymous-WS/Discord readiness contract.|
|68|web_api_integrations_validation_coverage|Actual lazy dispatcher and error semantics differ.|
|72|web_api_observability|Missing aggregate stats and exact publication/persistence seams.|
|76|web_campaign_policy_races|Removed multi-tier/token-specific WS races.|
|80|web_websocket|Removed real WS transport/auth/subscription contract.|
|84|webui_selected_trace_filters|Missing selected trajectory read/path guard surface.|

## Targeted validation and limits

The sanitized non-root mount/PID runner was used with explicit `USER=odin`:

```
USER=odin .venv/bin/python scripts/run-phase1-tests.py \
  tests/test_provider_shutdown_budget.py tests/test_desktop_phase2_runtime_a.py \
  --junitxml=.test-state/step8-runtime-a-commit.xml
```

Initial pytest: **21 passed in 13.03 seconds**, but shell exit 1 because the tee
destination raced initial `.test-state` creation. Tests themselves succeeded.
The clean repeated invocation after the folder existed: **21 passed in 12.99
seconds**, shell exit 0; `.test-state/step8-runtime-a-final.log` and XML retained
locally (not committed). Includes six adapter guard/domain tests and all fifteen
inherited executions.

Read-only independent reviewer `9a2bc547` approved the code/setup projections
without required code changes and requested clean validation evidence. After
adding an explicit authentic-owner, ready-handler, non-policy-failure pin, the
final post-review selection above passed **22 tests in 13.43 seconds**, shell
exit 0. Seven adapter guard/domain tests plus all fifteen inherited executions.
After the parent-requested integration `entries` projection was added, the same
final selection passed **22 tests in 13.05 seconds**, shell exit 0, and Ruff and
`git diff --check` passed. That is the current final log/XML at
`.test-state/step8-runtime-a-commit.{log,xml}`. JSON contains all invocations,
including the initial shell failure, without hiding it.

Parent static association review required a syntactically explicit
`hashlib.sha256(original).hexdigest() != SUITES[name]` condition rather than the
equivalent local `digest` helper. After that guard-only change the final selection
passed **22 tests in 12.99 seconds**, shell exit 0, Ruff and diff checks passed.
Current last evidence: `.test-state/step8-runtime-a-explicit-hash.{log,xml}`.

No full qualification, obsolete listener suite, prohibited literal selection,
live/native desktop, live installation or running-service operation. No product
code changed. Shared maps, ledger, test plan, checker and qualification plan were
not edited. Parent owns disposition/integration and full qualification.
