# Maintenance API and honest gates

`python scripts/maintenance/inventory.py refresh` regenerates deterministic full upstream and safety indexes from the immutable hash-verified archive and separately owned test-plan.json. Never captures or approves current source drift. Re-run after test/selection finalization.

`report` checks exact baseline/shared/ledger bytes, selected removals, excluded reintroductions, case corpus, unknown engine/test/asset/lock additions, and index tampering. `report --require-review` additionally blocks pending independent review; initial records are pending Claude, never fake-approved.

`record PATH --reason TEXT --contract TEXT --invariant TEXT --owner Odin --tests TEST_PATH ...` records one explicit exact-byte adaptation as pending. Concrete reasons and tests are mandatory. Do not loop with generic explanations blessing arbitrary changes. Removed paths need selection review. Upstream test corpus cannot be recaptured automatically; add Desktop tests or provide separately reviewed identical-case proof.

System prompt allows exactly nine D7 substitutions; guards exactly two non-runtime substitutions. Every surrounding byte stays protected even against coherent patch/digest changes. C1-C7 schema/receipt changes need exact records and review. No blanket classifier/governor/guard exemptions. Upstream post-baseline commit index stays empty and separate from initial Desktop deltas.

PR 2 item A's complete wording/disposition table is
[`pr2-model-facing-string-approvals.md`](pr2-model-facing-string-approvals.md).
It includes the merged D18 request preamble approval and explicitly lists new/changed
model-facing diagnostics without an exact D7/C1-C7/part-D entry. Inventory completion
is not a claim that those uncovered strings have been approved.

Conservative safety manifest protects all retained source/native/helper/test bytes and therefore includes transitive safety helpers whose names do not advertise danger. Native assets/historical isolated runners are provenance, not authorization to execute or package installers. Full archive and original license stay immutable and excluded from installed package content. Repository private, product distribution/license decision pending.

Limitations: this static offline checker cannot authenticate JSON reviewer identity or approve semantic equivalence. Coherent arbitrary ledger/tool changes require independent PR review and external branch protections. Static associations are import witnesses, not executed coverage. Phase2 retained code is lineage, not qualified shipping behavior. Built distribution, dependency resolver semantics, dynamic imports, reference cleanliness and platform proofs remain separate gates. Future upstream commits require reviewed three-way port-state support; this initial implementation expects the empty post-baseline ledger.

Tests must use CONTRIBUTING's isolated PID namespace and sanitized owner environment. No live desktop, install, restart, upstream or live-state operation was authorized.

`selection-overrides.json` separately records exact-path removed/replaced reuse-map entries, never existence-based exclusion. Entries require upstream_sha256, reason, contract, invariant, replacement disposition, tests, owner, reviewer and state. Only six named server/transport composition surfaces in REPLACEABLE_SURFACES qualify; arbitrary safety helpers cannot be dropped through a JSON override. Other selection changes require independent tooling/design review. Empty at initial handoff; parent owns final decisions and must document Phase2 unavailability honestly.

Manifest test/fixture/asset associations use deduplicated closure IDs/tables. Safety entries contain immutable upstream SHA256s and test closure IDs. Delta evidence tests include SHA256; changed evidence requires explicit re-record/review.
