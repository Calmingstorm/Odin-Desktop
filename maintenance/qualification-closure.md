# Phase 1 neutral-case closure

The previous draft snapshot at `060e1698` was not complete. Its 20 historical
and 82 foundation neutral mapping gaps are now **zero**. This record supersedes
the earlier blocked snapshot, not its historical failed-run evidence.

## Exact accounting

`case-accounting.json` retains all 259 historical failure rows and all 876
definitions across the 38 original foundation suites, with original hashes.

| Population | Original/faithful executable | Exact current-contract replacement | Actual Phase 2 wiring | Native/prohibited scope | Unmapped neutral |
|---|---:|---:|---:|---:|---:|
| Historical failures | 185 | 66 | 8 | 0 | **0** |
| Foundation definitions | 725 | 129 | 7 | 15 | **0** |

These populations overlap and are not unique execution counts. Every newly
resolved case has a named reason, frozen source digest and actual collected
executable/replacement selector. Removed transport expectations are not quietly
rewritten. Mixed validator parameter rows preserve the 12 retained original
cases and separately record both obsolete web-port rows and their explicit
current-schema rejection proofs.

The legacy `blocks_phase1` flag remains true on deferred wiring/native rows to
prevent claiming implemented parity. Those are now **explained out-of-scope
obligations**, not unresolved Phase 1 neutral mappings. Actual loop cancellation,
self-stop, sanitization, lease identity, evidence digests, skill snapshots,
knowledge validation/ingestion, schema redaction, model identity and timeout
algorithms are proved separately from closed request/delivery admission.

## Execution

The final complete **28-group isolated run passed: 13,081 passing executions,
zero failures/errors, two inherited skips**. Counts include duplicates and new
tests. A subsequently added accounting-total regression passed in the focused
23-case maintenance/accounting check; it does not retroactively increase the
28-group execution receipt. Local evidence is `.test-logs-closed-corpus-final.txt`
and `.test-state/qualification-{0..27}.xml`.

All test execution uses the sanitized non-root PID namespace. No native input,
active graphical lifecycle, live service, production profile or provider call
was used. All 851 retained upstream paths are still byte-identical.

## Hosted CI failure and actual corrections

Hosted run `37245152626` failed despite the earlier local selected gate passing.
Two causes were investigated, not hidden by exclusions:

1. `FullTextIndex.has_session` read the shared SQLite connection without the
   transaction lock while concurrent backfills wrote it. Existing reads now
   hold the retained lock through execute/fetch; the lock is reentrant for
   same-thread calls. No SQL/schema, mutation transaction boundary, exception
   suppression, retry or output shape changed. Deterministic sensitivity tests
   fail against the old behavior. New cases passed repeatedly; original
   atomicity cases passed five repeated isolated runs.
2. Hosted Python toolcache executables may be group-writable. The unchanged
   native peer trust algorithm correctly rejected that interpreter in fake-peer
   tests. CI now creates a repository-owned `venv --copies` interpreter, whose
   creation enforces mode 0755. Production trust checks are not relaxed and no
   real compositor/helper is installed or exercised.

`maintenance/fts-read-lock.md` holds the narrow source-change proof. The hosted
rerun status must be checked separately; local success is not hosted success.

## Remaining review and later phases

- Independent Claude review remains mandatory before merge. Exact byte drift
  is explained, not self-approved: 1,234 shared paths, 193 ledgered paths, 198
  pending independent reviews, zero unexplained divergence.
- No new lint findings; seven exact named inherited findings remain visible.
- Phase 2 owns authenticated request/control wiring, durable conversation
  delivery/outboxes, destination binding and app supervision.
- Complete Chromium/model/native-helper/app bundle shipping and hard-isolated
  native qualification remain later obligations. Phase 1 supplies required
  dependency inputs and fail-closed publication, not a ready app release.
- The earlier temporary-runtime-skill boundary incident remains disclosed in
  `validation.md`. Cleanup is verified; it is not erased by test success.

No merge, deployment, restart, coverage percentage or release parity is claimed.
