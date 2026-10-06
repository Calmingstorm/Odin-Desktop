# Phase 2 step 5 completion: management-domain parity

## Artifact and scope

This change completes the named management methods missing from merged step 5.
The request table names **21 original test files**, although its introductory
paragraph says 20. All 21 are retained byte-for-byte and restored as whole,
hash/corpus-bound adapters. Nothing in another lane is implicitly accepted.

The branch started at `main@5dd8cfc5`; main was merged, not rebased, as reviewed
requests (#22), controls (#23), and packaging (#24) landed. No live installation,
service, active desktop, credential or real account was modified. No deployment
or merge approval is claimed.

## Named methods and actual owners

- Records: `audit.diffs`, `audit.failures`, `audit.tail`, `logs.stats`, `logs.tail`.
  Diffs preserve filters, malformed-limit fallback and full content. Failure
  aggregates use retained rotation snapshots and settle handle release. Tails
  are bounded follow reads with opaque source-bound cursors, complete newline
  and UTF-8 records, rotation/truncation reset and pagination metadata. No
  renderer socket is introduced.
- Knowledge: `knowledge.chunks`, `knowledge.duplicates`, `knowledge.merge`,
  `knowledge.version`, `knowledge.diff`; learned context: `learned.list`,
  `learned.update`, `learned.delete`. Generation-disabled CRUD remains usable.
  Merge has Odin's delete-only behavior: keep the retained source unchanged and
  remove the duplicate source, not concatenate their content.
- Observability: the `observability.*` aggregates, recovery stats/recent,
  `capacity.snapshot`, `turn_state.snapshot`, `pools.ssh`, `pools.http`,
  `pools.close`. Pool closure affects SSH only and is a journaled mutation.
  Capacity snapshots never acquire breaker probe admission. Missing owners
  remain unavailable rather than invented counters.
- LLM admin: `openrouter.catalogue`, `openrouter.endpoints`, `openrouter.select`,
  `providers.compat.diagnostic`, plus the inherited model/provider read and
  switch methods required by the whole endpoint corpus. Existing retained
  public/auth-scoped caches, route-profile validation, pin/unpin, quick-add
  references and measured-cache summary are used. Selection changes routing
  policy, not the active main model. Credential-bearing copies are scrubbed.
- Trajectories: list/read/search/message methods use the retained saver and
  preserve path guards and filter-before-limit selection. `tools.list` now
  contains actual affordance cost/risk. `codex.accounts.refresh` uses the same
  serving account pool, per-account refresh lock and keyring persistence.

Composition now binds the actual request graph. Management, native knowledge
tools and skills share one durable KnowledgeStore, not two disconnected stores.
The retained runner and observations share one CompressionStats instance.
Zero samples remain `prefix_measurement=unmeasured`, hit rate null and upstream
cache unmeasured; an actual compression operation updates its measured counters.
The actual reflector, audit snapshot lock, breaker registry and trajectory saver
are observed, with read-only relocated-history fallbacks where needed.

Odin's single owner has admin-equivalent management access to every retained
memory scope. Previous synthetic personal-scope rows and extra scope restrictions
were corrected to pinned handler behavior, not maintained as a new tier system.
Native tool owner admission is unchanged. `total_window_tokens` is an exact
public schema-count exception beside existing token-budget exceptions; credential
substring rules and storage-secret policy are unchanged.

## App artifact

Existing Codex accounts and Tools panels gain refresh and reported cost/risk.
The smallest honest sections were added to existing settings screens:

- Records: diffs, failures, statistics, audit/log follow reads, observability,
  recovery/capacity/pools, and trajectories.
- State: chunk/dedup/version/diff inspection and learned-context CRUD.
- Models: catalogue/profile/eligibility details, preview/pin selection, quick-add
  references, measured cache and diagnostics.

Results are returned records, not inferred measurements. Capability refusals,
unread values, failed refreshes and unknown mutation outcomes stay distinct.
Tails retain at most 200 displayed lines, track local discarded display lines
separately, permit one outstanding tail request, and stop on error or unmount.
Bridge coercion preserves numeric-string fallback and string error filters.

## Frozen corpus and proof boundaries

`scripts/maintenance/record_step5_completion.py` explicitly enrolls the 21
filenames and named-method tests in the existing management qualification group.
It preserves all historical 326 Phase-2 members, all 869 original hashes and
every previously selected group/selector. Static full-export and runtime
assertion/decorator/signature/parameter guards are separate from passing evidence.

Historical tier/WebSocket security assertions execute sealed original policy
inside test-only fixtures. They do not introduce tiers or WebSockets into the
Desktop. Separate authenticated IPC and real Broker tests prove the actual
single-owner transport. Frozen Codex file-mutation regressions retain their
original hermetic file fixtures; independent named-method tests prove the actual
keyring-only shared serving refresh path and cancellation settlement.

Limits retained honestly: an enormous complete tail record can require
proportionate memory; same-inode truncate/regrow past the old offset between
reads is not detectable from upstream inode/size evidence alone. This is
source/runtime qualification, not native desktop, installer, live OAuth,
provider availability or independent semantic approval.

## Validation record

Working-tree targeted evidence: integrated records/knowledge/trajectory and
composition selection **657 passed**; LLM selection after the public window-count
fix **83 passed**; observability selection **303 passed**; final shared-owner
selection **66 passed**; accounting **84 passed**. The app implementation check
passed **691 tests**, typechecks and production builds. Earlier targeted failures
are retained under `/home/odin/desktop-step5-evidence/` rather than relabelled.

The final fresh-checkout full qualification, exact execution head and app gates
will be recorded in `phase2-step5-completion-result.json`. Enrollment and pending
exact-byte lineage records are not independent approval.
