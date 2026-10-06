# Phase 2 step 8, part 3: restore the step 2 to 4 suites

## Scope and lineage

The requested artifact is a review PR against `phase-2/controls-resume`, not a
deployment or merge to the target branch. Work follows the supplied
`/home/odin/reviews/desktop-step8-part3.md`. Started at controls base
`b8d7191024701d0af41b03ec7bbd9a7a7d6762d8`, merged `main` to obtain reviewed
step-8-part-1 accounting and step-5 management, then merged the moved controls
base `62229d8013be0d8418cb7ad692dba6bf68a8539f`. No rebase or force-push.

Both sides' maintenance records and source services are preserved. Shared delta
entries retain exact historical merge-lineage snapshots, concrete contracts,
pending independent review, and current byte patches. The composed status
endpoint returns management status and the real request engine's diagnostics;
the merged lifecycle test checks both. No old unavailable-method expectation is
applied to a now-served method.

## Parent-owned dispositions

The map owns exactly 47 assigned original suites. Parent reviewed the candidate
adapters rather than accepting passing output as equivalence.

| Step | Assigned | Restored | Deferred | New retirements |
|---|---:|---:|---:|---:|
| 2 | 8 | 6 | 2 | 0 |
| 3 | 27 | 6 | 21 | 0 |
| 4 | 12 | 2 | 10 | 0 |
| Total | 47 | 14 | 33 | 0 |

All 869 original paths and SHA-256 values remain. The historical 326-member
population is still 298 deferred + 23 restored + 5 already reviewed nonpassing
step-1 retirements. No disposition in this lane marks a new suite retired.

`phase2-step8-part3-adaptation-plan.json` gives each restored selector/adaptation
and each exact deferred blocker. Seven batch candidate records preserve targeted
results and failed/rejected attempts. `phase2-suite-map.json` is the current
status authority; candidate records are implementation provenance, not final
qualification or independent approval.

### Whole restored suites

Step 2:
- `test_channel_cursor_campaign`: frozen adapter.
- `test_channel_history_recency`: unchanged original.
- `test_channel_logger_edge_regressions`: unchanged original.
- `test_pr341_b10_channel_consistency`: frozen adapter.
- `test_pr341_b7_channel_reconciliation`: frozen adapter.
- `test_search_history_source_priority`: frozen adapter.

Step 3:
- `test_command_shell_framing`: frozen adapter.
- `test_process_zero_offset`: frozen adapter.
- `test_compatible_output_reserve`: unchanged original.
- `test_computer_privacy_r5`: unchanged original.
- `test_delivery_turn_observation`: unchanged original.
- `test_turn_durability_heartbeat`: frozen adapter with actual request admission.

Step 4:
- `test_bounded_process_wait`: frozen adapter with real admitted request worker.
- `test_computer_native_vision_r5`: unchanged synthetic original.

Eight complete frozen adapters and six unchanged originals preserve every
assertion, signature, decorator and parameter expression. Frozen loaders pin
archive and source bytes, exact setup node hashes, and full exports. Independent
complete AST reverse replay rejects collateral setup edits. No subset selection
or exclusion is used to claim a restored suite. The original source files are
not edited.

The heartbeat adapter passes the original store through actual worker-owned
request admission, obtains the real handle/lease and leaves its production
timer running while all six original cases inspect renewal, stolen leases,
store death, concurrent checkpoints and closed-store refusal. Two exact legacy
admission call substitutions preserve all ten original assertions; no fake
enabled handle, raw lease construction or replacement store.

The bounded-wait adapter genuinely replaces the obsolete bot setup: real
temporary `OwnerAuthority`/`PermissionManager`, actual engine composition,
committed `RequestService.submit`, admitted worker task, sealed request envelope,
real ledger admission and real tool-loop execution. Its read-through component
facade preserves the original executor mocks and observes the original returned
five-tuple. Safeguards prove fake and sealed-but-unbound requests are rejected.
No `_assert_request` replacement, synthetic enabled lease, or wait-policy change.

### Deferred and rejected work

Exact blockers distinguish absent legacy transport/presentation contracts from
remaining supported-engine fixture work. They name guest/multi-requester/tier
assertions, Discord interaction edits/presence/HTTP retry helpers, native social
operations, obsolete CLI/REST/web-chat interfaces, literal requester/source
goldens, and ownerless retention. These are not silently retired or replaced
with a privileged gateway facade. Supported resume/durability obligations remain
load-bearing even when their complete original suite still needs adaptation.

The attachment candidate replaced malicious archive traversal with harmless
members plus a symlink boundary. Although the same `BLOCKED` assertion passed,
the security property changed. Parent rejected it, removed its export, and
left `test_attachments.py` deferred. Its diagnostic result is explicitly
unqualified. Forbidden original traversal setup was not executed.

`test_channel_logger.py` was not executed: it has prohibited recursive-deletion
setup and incompatible obsolete guild/default-author provenance assertions.
The whole `test_session_search.py` probe produced 44 passes and ten failures at
the unavailable REST route. It remains wholly deferred; its neutral cases are
not exported as restored-suite evidence.

## Validation and execution boundaries

All pytest executions use `USER=odin`, repository Python 3.12, the
`run-phase1-tests.py` mount/PID namespace launcher, `env -i`, and disposable
HOME/XDG roots. No display, DBus, live credentials, service/install data, or
active desktop is passed. Only synthetic computer data/loopback tests run;
native backend and live-desktop qualification remain absent.

The integrated restoration selection passed **339 executions**, zero failures
or skips, before the final gate. These include static safeguards and repeated
vision execution, not 339 unique restored inherited cases. The subsequently
integrated heartbeat targeted selection passed 13 executions, six inherited
and seven safeguards. The 14 restored suites account for **164 unique
parameter-expanded inherited cases**.

Targeted merge integration exposed and corrected missing diagnostic routing.
Some initial explicit selections omitted the imported controls module's pytest
plugin, causing missing `graph` fixture errors; no assertions were skipped.
An auto-resume checkpoint-integrity failure also appeared repeatedly and is
retained as diagnostic evidence, not called a clean pass.

The failure was a real CPython 3.12 shared SQLite statement-cache race: an
auto-waiter and owner read the same cached SELECT concurrently. One returned a
valid payload with a missing digest; an independent connection confirmed intact
stored bytes and matching SHA-256. Another reproduction returned malformed
operation tuples. The fix disables only that connection's statement cache with
`cached_statements=0`. No digest validation, write fence or resume contract is
weakened. A new eight-reader, 2,000-read Desktop regression failed against the
original source and passed after the fix. Three consecutive composed selections
passed 104 executions each; three consecutive durability selections passed 110
each. Temporary payload logging was removed. Original inherited store tests
remain byte-identical.

## Final frozen-checkout gate

The full qualification ran **once**, from fresh frozen checkout
`19f3c4a6ae3b7bc3433bba96aa97e73984439bfa` under
`/home/odin/desktop-phase2-step8-part3/qualification/final`. Both checkout and
parent have mode 2775, group-writable; umask 002 preceded checkout and dependency
sync. `uv sync --locked --extra dev`, `pip check`, exact-byte drift, suite-map
and lint gates passed. Lint retained 43 prior findings, zero new. A mistyped
base SHA initially failed the lint setup; the corrected exact base passed
before the full test invocation.

**Observed full gate: 32/33 groups passed; 14,633 passing executions, one failure,
zero errors and two skips. The full qualification did not pass.** All three
restoration groups passed: step 2 has 73 executions, step 3 has 103, and step 4
has 88. Safeguards and repeated vision cases are included in those executions;
there remain 164 unique inherited cases across the restored fourteen suites.

The one failure is the existing Desktop startup assertion:
`test_desktop_core_entry.py::test_real_core_starts_with_symlinked_xdg_or_socket_folder[cache]`.
The process did not publish its listener within the helper's 300 x 0.01-second
poll budget. It was not observed exiting first. No captured child stderr proves
the cause, so this is not labelled a harmless scheduling issue or a proven
symlink regression. A separate, unchanged-source isolated diagnostic selection
of all four symlink variants passed four cases in 7.64 seconds. That follow-up
does not replace the failed full run. No assertion, startup deadline or selector
was changed to green the gate, and no second full qualification was run.

The draft review PR retains this unresolved full-gate failure. Its failure
receipt, per-group JUnit hashes, complete log, diagnostic follow-up and tested
source identity are in `phase2-step8-part3-result.json`. The full log is
`/home/odin/desktop-phase2-step8-part3/qualification/full-qualification.log`.
After the full run only this document and generated result receipt changed;
source, tests, dependency lock, qualification selectors and exact-byte ledger
remain the tested bytes.

Inherited coroutine-not-awaited and closed-loop subprocess-finalizer warnings
remain visible and unsuppressed. No warning-clean claim.

No full Phase 2 parity, native qualification, release acceptance or independent
approval is implied by the restored subset. No deployment, live-service change,
target-branch merge, active-desktop action, rebase or force-push is authorized or
performed.
