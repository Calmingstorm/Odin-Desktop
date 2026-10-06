# PR #35 review round 1

## Requested artifact and dispositions

This is an update of PR #35 on `phase-2/restore-steps2-4`. GitHub retargeted it to
`main` after controls PR #23 merged. Main `5ba8d6df` was merged into this branch,
preserving both status assertion sets and both exact ledger lineages. No rebase,
force-push, merge to the target, upstream
Odin change, deployment, restart or active-desktop operation.

Parent-owned review dispositions:

| Step | Assigned | Restored | Retired | Deferred |
|---|---:|---:|---:|---:|
| 2 | 8 | 7 | 1 | 0 |
| 3 | 27 | 9 | 15 | 3 |
| 4 | 12 | 4 | 5 | 3 |
| Total | 47 | 20 | 21 | 6 |

Six additional suites restore retained coverage: session search, attachments,
delivery-review regressions, pure tool-loop helpers, steering runtime, and
steering checkpoint/resume. Group A's 21 whole-suite retirements cite exactly
`Claude, review of #35`; they are not passing tests. All original 869 paths,
bytes and hashes and the historical 326-member population remain accounted for.
Across that historical population: 29 restored, 26 retired, 271 deferred.

`phase2-step8-part3-review1-adaptation-plan.json` is the disposition authority;
candidate records preserve failed attempts as well as successful ones. Case
retirements and the helper's bot-only loop branch are exact source-hashed,
reviewer/reason-pinned records. The offline reader rejects blanket, dynamic or
unreviewed exclusions. Neither candidate output nor this parent audit is
independent PR approval.

## Retained behavior and actual changes

- Failed-retention delivery investigation found no Desktop D2 drop. The original
  ownerless `deliver_runtime_output(object(), ...)` is not an authenticated
  Desktop consumer. An actual composed executor with exhausted quota proves the
  same scrubbed failed-retention head/tail assertions. Supplemental actual
  RequestService publication and native history-delivery paths pass separately.
- Attachments use Claude's approved nested, tmp-contained zip-slip substitution:
  `../../escape.txt` remains inside `tmp_path` even if extraction is broken, while
  the original extraction-folder boundary assertion remains intact. The earlier
  symlink substitution remains rejected historical evidence, not the new proof.
- Real `search.query` now implements role and timestamp filters. The obsolete
  HTTP fixture maps query, conversation, time and limit inputs to the real search
  service, without a product HTTP route. One removed API multi-user identity case
  is explicitly retired; copied session/history provenance cases remain intact.
- The copied executor restores unknown-tool classification before tool-specific
  middleware/readiness, after canonical-owner authentication, native reservation
  and tool-scope checks. Known tools still need all guards. Foreign caller and
  known-handler readiness regressions remain load-bearing.
- The SQLite `cached_statements=0` fix remains a desktop delta to a copied Odin
  module. The same upstream connection pattern means the bug likely exists in
  Odin too. The delta says so plainly; upstream was not changed.
- Authenticated prompt CLI is implemented: argument/piped prompt, timeout,
  guarded committed reply, prose/JSON, existing or new conversation, local socket
  and token. Timeout never cancels or retries admitted work. Accepted resume
  receipts now expose the actual generation, and recent settlements sort by
  settlement time so an old resumed request is visible. This is product behavior
  with supplemental temporary IPC tests, not restoration of the frozen HTTP CLI
  assertions.

## Six exact deferrals, not silent retirements

1. **Executor dispatch:** original literal `u-42`, `alice`, `bob` callers fail
   canonical-owner admission. No owner bypass, fabricated handler identity or
   assertion adaptation was accepted. Unknown-name precedence is fixed, but a
   partly passing suite is still deferred.
2. **Codex replay matrix:** full documentation catalog was tried. Original 67-name
   corpus versus Desktop's 63 names removes five Discord/RBAC names and adds
   `read_conversation`. Original catalog equality and missing-schema cases fail;
   no synthetic schemas or input-matrix rewrite. The review explicitly permits
   explaining why catalog substitution cannot preserve the original assertion.
3. **Steering parity:** literal legacy owner/request/prose goldens and synthetic
   event instrumentation cannot become authentic production observations merely
   by adding admission. Prototype removed; retained runtime suites are restored.
4. **Resume admission:** real owner/controls/worker experiments do not justify
   normalizing the unchanged Discord-specific access-denial assertion. Rejected
   normalization is not qualified or part of a restored corpus.
5. **Timeout durability:** two original cases pass through actual admission; four
   registered/unregistered wait/dynamic-tool matrix variants are unavailable in
   the actual capability route. Retention rejects that unavailable output before
   WI3 settlement. No invented readiness; capability/settlement remains a gap.
6. **Frozen CLI coverage:** the prompt product is built, but inherited HTTP URL,
   header, request and daemon-argument assertions need explicit IPC adaptation or
   removed-surface disposition review. Proposed HTTP retirements are not approved
   group-C pins. The whole original suite remains deferred.

Blocked experiment wrappers live under `tests/diagnostics`, outside default
Desktop test discovery and all qualification selectors. Their failure receipts
remain evidence, not waived failures or claimed restoration.

## Validation

The earlier full gate remains failed historical evidence: 32/33 groups,
14,633 passes, one startup listener-budget failure, two skips. An unchanged-source
isolated startup/lifecycle diagnostic in this review passed 53 cases. No startup
deadline, assertion or selector was weakened, and that diagnostic does not erase
the failed historical full run.

Parent integrated selection: 361 passed. Final CLI/request/resume and rejected
adapter safeguards: 98 passed. After main integration, startup/lifecycle,
management, CLI and suite-map selection: 225 passed. The first parent CLI attempt
selected nonexistent file names and executed no tests; the next run found a new
timeout test's response race and a missing AST import, both corrected before the
98-pass run. The timeout fixture now blocks actual admitted execution with events
rather than assuming admission completes inside 0.1 seconds.

Final byte ledger and suite map have zero errors. Ruff has seven inherited
findings and zero new. Original suite membership and hashes remain unchanged.

Final review-round qualification will run exactly once from a fresh frozen
checkout under a group-writable parent, using Python 3.12, non-root `odin`,
mount/PID namespaces, `env -i`, throwaway HOME/XDG and no display, DBus, credentials,
live installation or native backend. The complete receipt records every group,
JUnit hash, log hash, tested SHA and verdict. Pending that invocation, this file
does not claim a clean full gate.
