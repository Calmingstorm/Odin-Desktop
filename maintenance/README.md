# Maintenance API and honest gates

`python scripts/maintenance/inventory.py refresh` regenerates deterministic full upstream and safety indexes from the immutable hash-verified archive and separately owned test-plan.json. Never captures or approves current source drift. Re-run after test/selection finalization.

`report` checks exact baseline/shared/ledger bytes, selected removals, excluded reintroductions, case corpus, unknown engine/test/asset/lock additions, and index tampering. `report --require-review` additionally blocks pending independent review; initial records are pending Claude, never fake-approved.

`record PATH --reason TEXT --contract TEXT --invariant TEXT --owner Odin --tests TEST_PATH ...` records one explicit exact-byte adaptation as pending. Concrete reasons and tests are mandatory. Do not loop with generic explanations blessing arbitrary changes. Removed paths need selection review. Upstream test corpus cannot be recaptured automatically; add Desktop tests or provide separately reviewed identical-case proof.

System prompt allows exactly nine D7 substitutions; guards exactly two non-runtime substitutions. Every surrounding byte stays protected even against coherent patch/digest changes. C1-C7 schema/receipt changes need exact records and review. No blanket classifier/governor/guard exemptions. Upstream post-baseline commit index stays empty and separate from initial Desktop deltas.

PR 2 item A's complete wording/disposition table is
[`pr2-model-facing-string-approvals.md`](pr2-model-facing-string-approvals.md).
It includes the merged D18 request preamble and D19 part-E approvals from main
`3fac196eadf75f7bb34349c5c5fc8320d811d3e9`, plus explicit SkillContext docstring coverage.
Only named part-E rows are marked D19. Corrected C4 labels retain part-C coverage;
the restored `http_probe` omitted-host local fallback is baseline parity under D17,
not new wording approval. Source/runtime proofs remain separate from this table.
Section 4 still inventories remaining **NONE** rows, including Phase 2 unavailable/
not-implemented gates, readiness backstops, lost attachment suffixes/image URLs, skill
dependency installation and resume empty-read disposition. Section 5 also retains
unapproved non-runtime documentation. Inventory completion is not blanket approval.
Phase 2 must remove every remaining section-4 NONE row with Odin's behavior restored
or explicitly disposition it under D19: mechanical wording swaps to Claude, any
behavior/instruction change to Aaron. A fresh profile must receive the same local host
and default host as an Odin install, with runtime parity proofs at the Phase 2 exit gate.
No model request path is wired in Phase 1; these requirements remain deferred, not passed.

Conservative safety manifest protects all retained source/native/helper/test bytes and therefore includes transitive safety helpers whose names do not advertise danger. Native assets/historical isolated runners are provenance, not authorization to execute or package installers. Full archive and original license stay immutable and excluded from installed package content. Repository private, product distribution/license decision pending.

Limitations: this static offline checker cannot authenticate JSON reviewer identity or approve semantic equivalence. Coherent arbitrary ledger/tool changes require independent PR review and external branch protections. Static associations are import witnesses, not executed coverage. Phase2 retained code is lineage, not qualified shipping behavior. Built distribution, dependency resolver semantics, dynamic imports, reference cleanliness and platform proofs remain separate gates. Future upstream commits require reviewed three-way port-state support; this initial implementation expects the empty post-baseline ledger.

Tests must use CONTRIBUTING's isolated PID namespace and sanitized owner environment. No live desktop, install, restart, upstream or live-state operation was authorized.

`selection-overrides.json` separately records exact-path removed/replaced reuse-map entries, never existence-based exclusion. Entries require upstream_sha256, reason, contract, invariant, replacement disposition, tests, owner, reviewer and state. Only six named server/transport composition surfaces in REPLACEABLE_SURFACES qualify; arbitrary safety helpers cannot be dropped through a JSON override. Other selection changes require independent tooling/design review. Empty at initial handoff; parent owns final decisions and must document Phase2 unavailability honestly.

Manifest test/fixture/asset associations use deduplicated closure IDs/tables. Safety entries contain immutable upstream SHA256s and test closure IDs. Delta evidence tests include SHA256; changed evidence requires explicit re-record/review.
