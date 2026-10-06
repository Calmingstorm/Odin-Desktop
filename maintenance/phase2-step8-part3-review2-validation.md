# PR35 round2 dispositions and qualification

Review: `/home/odin/reviews/desktop-pr35-round2.md`.
Authority: **Claude, review of #35, round 2**. PR31 fixes were completed first at
`5201dc7454a07d311e0757d038c966eee5e64a85`; no PR31 changes are repeated here.
Main remains `0b7d596f`; no rebase, force-push, target merge or deployment.

## Exact assigned-suite dispositions

| Step | Assigned | Restored | Retired | Deferred |
|---|---:|---:|---:|---:|
| 2 | 8 | 7 | 1 | 0 |
| 3 | 27 | 12 | 15 | 0 |
| 4 | 12 | 6 | 5 | 1 |
| Total | 47 | 25 | 21 | 1 |

Four formerly deferred suites now export all retained original executions:

- Dispatcher: 19 original executions; exactly two new foreign-caller case
  retirements, plus the unchanged round1 guest-tier retirement. No owner-ID
  translation or executor permission bypass.
- CLI: six original executions; exactly three removed HTTP executions, recorded
  as two case definitions. Real local IPC no-transport spies replace only setup;
  no HTTP facade, changed original assertions or counterfeit request fields.
- Steering parity: five original executions; the two parametrized tier-denial
  batch executions are retired at case level. Real owner and request IDs project
  one-to-one onto golden identity fields only. All other data, event order,
  guards, delivery, assertions and original parameters remain exact. Disposable
  native read plus real dispatcher and output gates, not synthesized output.
- Codex: 287 retained original executions and two distinct added executions for
  `read_conversation` with `{"limit":10}`. Five removed tool rows retire exactly
  ten chat/agent executions. The unchanged equality assertion now receives the
  real 63-name Desktop documentation catalog. Every other assertion is unchanged.

There are **704 unique retained inherited executions** across the 25 restored
assigned suites. The two new Codex executions and adapter/guard tests are
supplemental, never additional original coverage. Global historical population:
326 = 34 restored + 26 retired + 266 deferred. Original 869 paths, hashes and
immutable archive remain unchanged. Prior failed runs and round1 evidence remain
immutable, not retroactively labelled passing.

`test_executor_timeout_durability.py` remains deferred with exact blocker
**awaiting #28 and #37**. It belongs to the step8 restoration part for 6A/6B.
The previous actual not-started retention-settlement finding remains recorded;
this disposition does not repair or qualify that unsupported route.

## Accepted round1 work

Named acceptance only, cited to **Claude, review of #35, round 2**: terminal
calibration release, resumed generation in typed-resume results, search filters,
executor order, SQLite statement-cache fix, authenticated prompt CLI, and the
delivery investigation finding no D2 output drop. The SQLite delta remains
explicitly copied-Odin code with likely upstream applicability. Odin itself is
untouched. New round2 implementation remains pending independent review.

## Targeted evidence and short gates

- Initial combined development selection: 630 passed, one accounting failure.
  The suite-map writer had published new classifications before its test-plan
  update; the coherence test correctly rejected that intermediate state. Receipt
  `integrated.log` and `integrated.xml` remains visible. No runtime failure waived.
- Final integrated source selection: **432 passed in 52.17s**, zero failures or
  skips; `integrated-source.log` and `integrated-source.xml`.
- Final coherent accounting selection: **236 passed in 50.43s**, zero failures or
  skips; `accounting-final.log` and `accounting-final.xml`.
- Ruff: seven inherited findings, zero new. Pip dependency check passed.
- Suite map: valid, exact 326 historical memberships and current counts.

Evidence root: `/home/odin/desktop-pr35-round2-20261006/`.
All tests use Python3.12, nonroot odin, isolated PID/mount namespaces, env-i and
throwaway HOME/XDG with no display, DBus, credentials or live profile.

## Final fresh-checkout qualification

Pending the single final 33-group invocation, after final exact byte accounting
and short gates, from a fresh frozen checkout under a group-writable parent.
The final result JSON will name the tested commit, every group and JUnit/log hash.
No full-product/native/release acceptance, active-desktop operation, live service
change, upstream edit or deployment is claimed.
