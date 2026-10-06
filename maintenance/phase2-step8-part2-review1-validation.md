# PR34 review disposition implementation

Review authority: Claude, review of #34, supplied in
`/home/odin/reviews/desktop-pr34-review.md`. The requested merge of main was
attempted first at `main@1c72a3f1`; the branch already contained that commit.
No rebase was performed. Later main advancement is recorded below when merged.

## Applied dispositions, not a whole-product acceptance claim

- 36 exact reviewed retirements are separately admitted by path/reason/reviewer.
  The original five #26 dispositions remain unchanged, with original bytes.
- All 20 group B suites remain deferred with the exact blocker
  `awaiting the step 5 completion PR`.
- Six suites remap to their actual later owner: three request/recording suites
  to step 3 and three computer/process suites to step 6. No remap passes a test.
- Seven complete group C corpora are restored: audit signing, hosts, provider
  reload rejection, quota checks, malformed agent policy, integration validation,
  and outbound webhooks. Together they retain 175 inherited parameter executions.
- Partial inherited image, LLM-admin and log search corpora are executable and
  explicitly partitioned. Their complete files remain deferred, not restored.
- Health endpoint/startup suites still mix removed HTTP role/Discord truth with
  health behavior absent from the current Desktop result shape. Output fences
  still require native history readiness absent from the pre-merge step 3 graph.
  Neither status projections nor canonical UUIDs manufacture those features.

Historical accounting before the later main merge is
**326 = 26 restored + 41 retired + 259 deferred**. Original frozen bytes and
membership hashes are preserved. All lane decisions, seals, partitions and
references are in `step8-part2-review-*.json` and the executable suite map.

## Product fixes independently exercised

- Rejected webhook boot configuration no longer overwrites the saved desired
  URL during unrelated CRUD. Mutation, adoption rejection, restart, subsequent
  mutation, comments, credentials and malformed saved targets have real tests.
- Id-less webhook rows preserve absent IDs instead of materializing `id: ''`.
- Full-image form roundtrips preserve follow/pin presence, including defaults.
- Host CRUD restores import, audit, reference conflict detail and actual prompt
  invalidation while preserving enrollment, persistence and live lease fences.
- Policy-only/startup-only provider saves preserve the serving transport graph.
- The retained quota observer is composed once, reads the current live serving
  pool, starts only after core admission, and closes before provider retirement.
- Audit writer and reader resolve the same keyring authority without incidental
  schema hydration. Signed restart verification and locked-keyring refusal are
  tested; reads still never construct or initialize a writer.

Parent applied-code review found the keyring audit authority split; it was fixed
and the new restart test passes. No active desktop, live config, service or
upstream repository was modified. No actual provider endpoint or real keyring
was used. Local HTTP receivers are disposable inherited delivery fixtures.

## Targeted verification before the final fresh qualification

- Existing management/hosts/integrations/providers/settings/model/core suite:
  204 passed.
- Parent combined new adapters, partial corpora, accounting and product probes:
  489 passed, with two collection warnings from inherited `Test*` exports.
- Audit authority/records/quota/provenance/accounting: 177 passed.
- Canonical map checker: zero errors. Exact-byte drift: zero errors.
- No-new-lint gate: seven inherited findings, zero new findings.

These overlapping targeted counts are not unique inherited-case totals and do
not replace the single final full qualification. Final result receipt follows
the fresh-checkout execution and records all groups, failures, warnings and skips.
