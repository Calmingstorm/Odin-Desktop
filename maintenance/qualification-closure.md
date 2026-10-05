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
| Foundation definitions | 724 | 130 | 7 | 15 | **0** |

These populations overlap and are not unique execution counts. Every newly
resolved case has a named reason, frozen source digest and actual collected
executable/replacement selector. Removed transport expectations are not quietly
rewritten. Mixed validator parameter rows preserve the 12 retained original
cases and separately record both obsolete web-port rows and their explicit
current-schema rejection proofs.

D17 review intentionally retires the final `HostAccessEntry` serializer
execution, changing foundation accounting from 725/129 to 724/130. All 34
original host ACL/DTO definitions are current-contract replacements, not old
ACL parity. `pr2-d17-case-triage.json` records these and two corrected
executor/config mappings. Frozen source bytes remain untouched; every current
replacement selector exists in the fresh isolated collection.

The legacy `blocks_phase1` flag remains true on deferred wiring/native rows to
prevent claiming implemented parity. Those are now **explained out-of-scope
obligations**, not unresolved Phase 1 neutral mappings. Actual loop cancellation,
self-stop, sanitization, lease identity, evidence digests, skill snapshots,
knowledge validation/ingestion, schema redaction, model identity and timeout
algorithms are proved separately from closed request/delivery admission.

## Execution

The pre-D17 complete **28-group isolated run passed: 13,081 passing executions,
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

## Second hosted portability correction

Run `37248121752` proved the FTS correction and trusted interpreter copy: the
first two groups passed in hosted CI. The remaining Hyprland group exposed two
previously ambient test dependencies:

- The old `_trusted_filesystem` fixture globally rewrote `os.fstat` owner to
  root, including the actual non-root hosted test interpreter. Its frozen
  autoload cases now use an exact setup-import adaptation whose root ownership
  model applies only to the temporary artifact tree and its ancestors. Real
  interpreter/process measurements retain their real UID/mode. All 66 original
  cases and one new fixture-scope regression passed; no production trust check
  changes or native input were used.
- `test_hyprland_input_loss_campaign.py` imports a real native guardian Client
  and requires an existing fixed `/tmp` executable. Direct-only spawn scanning
  missed that import closure. The seven cases are now explicitly native/manual
  gated, alongside the original wire helper suite, rather than building or
  invoking an ambient executable to make CI pass. Their bytes remain frozen.
  Prior local successes used that ambient native helper and are not qualifying
  evidence for authorized neutral scope. This narrows the current executable
  gate; it does not assert those native contracts are implemented or disproved.

The seven native cases were not among the 259 historical failures or 876
foundation definition populations. Those exact neutral mappings remain closed.
`test-plan.json` now has 357 neutral candidate paths and 100 native/manual paths.

## PR 2 review items 1 to 7 (D17)

All seven requested changes are applied. Main-only design commits are
`e3888f96` and `8a4b7e27`, merged into the bring-over branch. Source and tests
remain in PR 2. The authenticated owner takes the original governor admin path,
honoring `owner_can_override` and original force/strict/exfil precedence; absent
governor/permission-manager defaults match Odin. Host access is every live
enrolled targetable host with a separate default-only preference. Risk and
recovery modules are now whole-file byte-identical to the pinned archive.
The Linux host test is restored. FTS locking and catalog reservations are
explicit intentional ledger entries; FTS is an upstream candidate, not an
upstream change performed here.

Focused combined validation passed **1,520 tests, one inherited skip**. The
first full D17 gate found three remaining integration errors: a stale owner-only
error-message assertion after the open-default correction, stale exact adapter
association digests, and the stale 725/129 accounting totals. These were fixed
without changing any frozen assertion or adding a suite exclusion. All 26
touched gate-correction cases passed. A fresh full 28-group rerun is required;
its actual result is posted to PR 2, not inferred from the focused runs.

Static drift after integration: **1,236 shared paths, 196 exact ledgered paths,
201 pending independent reviews, zero unexplained errors**. Seven inherited lint
findings remain named; no new lint findings. The lock check and repository
environment dependency check pass. This is not a new coverage, bundle, native
input, Phase 2 wiring, merge or release claim. The skill-manager computer-name
reservation consumer limitation discovered during item 7 is explicitly recorded
in `pr2-review-items-5-7.md`; catalog nonpublication tests do not claim universal
collision prevention.
