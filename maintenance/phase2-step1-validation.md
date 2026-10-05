# Phase 2 step 1: core process and local transport

Base: pulled `main@52c90f53186551faf149a6313b0a10e441bb1a2c` before branching.
Implementation is one review PR, not a deployment or a claim of complete Phase 2 parity.

## Implemented boundary

- App launch: `python -m src --socket <path> --token-file <path> --profile <id> --data-dir <path>`.
  The app creates the token; the core never creates or repairs it. stdin must be an app-held FIFO or stream socket.
  Linux Node `spawn(..., {stdio: ['pipe', 'pipe', 'pipe']})` supplies a Unix stream socketpair, not a FIFO.
- Profile roots match the app and protocol (`odin-desktop/<profile>`), without Phase 1's extra `profiles` component.
  Explicit token/data roots are shared by runtime path resolution. App logs, drafts and window preferences are
  scaffolding, not imported engine state or authority.
- One sealed owner authority and identity-directory runtime lock, one shared private SQLite store, one listener.
  The entry retains profile ownership through the byte-identical containment/finalization helpers.
- Minor 2 framing/hello/welcome/ping, UID/token/profile checks, private socket, live-socket refusal and inode-safe
  cleanup. Only `status.get`, `events.subscribe` and `runtime.shutdown` are advertised as ready.
- FULL-synchronous durable command admission, final receipts and permanent binding tombstones. Callback results and
  events commit together. A pending/unknown command never automatically replays; unknown receipts are not pruned.
  Reads and unavailable methods do not reserve command IDs or write durable receipts. Existing identities remain
  authoritative even for methods no longer served. Known final bodies expire after seven days at startup and hourly;
  bindings remain permanent and pending/unknown outcomes never expire.
  This is not an exactly-once external-effect guarantee.
- Durable profile sequence, retained cursor interval, replay/reset and response-before-replay/live serialization.
  Owner revocation is checked for historical replay as well as live events.
- Parent EOF and signals quiesce in order. A stalled connection replay is cancelled before persistence closes.
  Future conversation/execution/config/background services remain unavailable, not substituted with fixture data.

## Intentional protocol dependency

The request explicitly adopts **only** the corrected command-identity refusal rule from
`protocol/minor-3@61d38b725564394225a3bfe0cb2fb280c3a406cd`:
`busy`, `stale_binding` and validation refusals are final answers. Same ID returns the original answer;
a retry after the cause clears is a **new command ID**. This supersedes minor 2's stale busy-error table wording.
The core still announces minor 2 and does not implement or advertise the unreviewed minor 3 service surface.
Claude's protocol/design documents and app files are unchanged.

## Evidence

- Incremental isolated PID-namespace run: **220 tests passed**, including the new transport/journal/lifecycle tests
  and touched foundation/root/distribution suites. Combined `src.desktop` coverage: **92%**; new modules individually
  **91% to 99%**. The separately deferred profile provisioning module is not claimed covered by this step.
- Independent probes initially exposed identity FIFO blocking, stale lock-file authority, synchronous failure logging
  before the watchdog, and replay after owner revocation. All four fixed with behavioral regression tests.
  Original independent probes, unmodified: **12 passed** in the isolated runner.
- New tests exercise real Unix framing, real SQLite reopen/transaction visibility, benign subprocess interruption,
  actual app-style subprocess launch, parent EOF, duplicate ownership, SIGTERM and temporary-profile restart.
  Snapshot transaction tests prove the journal composition primitive, not the deferred conversation snapshot method.
- Drift records are exact per path and pending review. Changed evidence pins on unchanged source records are
  evidence-only refreshes, not source recapture or new approval. Original upstream tests remain unchanged.
- Fresh checkout at `0923bb32`: locked dependency installation, drift, lint and ownership checker passed.
  **29/29 qualification groups passed**, with **13,289 passing executions, 2 skips, 0 failures and 0 errors**.
  The separate file-plan behavior suite passed **30/30**. The final core-transport group passed **144/144**.
  Group totals include existing overlapping adapters, not unique-case or full inherited-suite claims.
  Inherited AsyncMock/unawaited-coroutine warnings remain visible; this is not a warning-clean claim.
  Logs: `/home/odin/reviews/desktop-step1-fresh-{install,gates}.log`; JUnit:
  `/home/odin/reviews/desktop-step1-fresh/.test-state/qualification-{0..28}.xml`.
  The added group is `phase2-core-transport`; existing deferred suites and native gates are not silently promoted
  or discarded. Only this evidence document changes after that verified code commit.

## Scope exclusions

No `/opt/odin`, live config/data, live service, active-desktop input, destructive command inputs, deployment,
merge, self-restart or attribution trailers. `process_manager` and `local_supervisor` remain unchanged.
Native desktop/app bundling and all later Phase 2 steps require their own review and qualification.

## PR #14 first review fixes

Review baseline: `81d00a151cdfb9dde25ddcbf04d1530e9e13658a`.

1. **Node parent link:** accept FIFO or stream socket stdin; reject regular files and datagram sockets. A real
   `python -m src` subprocess with socketpair stdin proves handshake, ready status and orderly parent-EOF exit.
2. **Startup diagnostics:** the existing final stop log emits one bounded line with failure kind, a fixed refusal
   reason when recognized, and involved path, only while the existing finalization watchdog is armed. Arbitrary
   exception text/repr, hostile class hashing and credential contents are never emitted. Containment/finalization
   helper bodies remain source-identical. Actual missing/unsafe-token subprocess tests verify the output.
3. **Namespace parity:** tighten only user-owned `odin-desktop/<valid-profile>` namespace components to `0700`,
   through held no-follow descriptors. Foreign owners and links remain refused with involved path; unrelated
   ancestors are not chmodded. SSH socket parents are privately provisioned instead of inheriting umask `002`.
4. **Receipt cost/retention:** unavailable methods refuse without a receipt, reads use read-only identity lookup,
   and startup/hourly pruning expires only known final bodies. Old identities, conflicts and unresolved outcomes
   stay authoritative. Storage failure during maintenance stops admission; the task closes before the journal.
5. **Serialization:** corrected the transport docstring. This step still serializes dispatch across connections.
   Before adding long-running services, partition safe per-request work from admission/snapshot/replay/publication
   serialization and prove status/keepalive responsiveness under a stalled or long-running request.
6. **Test HOME isolation:** the distribution module's autouse fixture isolates HOME/XDG even for plain pytest.
   A nested plain targeted invocation proves the inherited temporary HOME/XDG trees remain untouched.
7. **Interrupted app save:** recognize only `drafts.json.tmp` and `app-state.json.tmp` as opaque owned scaffolding.
   Do not read, delete or import them; links, arbitrary `.tmp` files and engine state still refuse bootstrap.

### Regression evidence

- Final entry regressions copied into a disposable unchanged-baseline archive: **6 failed**, specifically Node
  socketpair launch, all three scrubbed diagnostic cases and both interrupted-save cases. The socketpair process
  exited 1 and the original diagnostic was only `Odin stopped`.
  Log: `/home/odin/reviews/desktop-step1-round1-entry-final-baseline.log`.
- Namespace/HOME regressions before the fix: **10 failed, 11 passed, 84 deselected**; final touched files:
  **115 passed**. Logs: `/tmp/desktop-path-regressions-before.iQZkEe/before-corrected.log` and
  `/tmp/desktop-path-regressions-final.anSPSI/final.log`.
- Final receipt regression file against an unchanged-baseline archive: **55 failed, 2 passed**. Final touched
  receipt/lifecycle/journal/IPC run: **170 passed**. Logs: `/tmp/desktop-receipt-final-baseline.log` and
  `/tmp/desktop-receipt-final-after.log`.
- Entry/lifecycle/root-byte tests after fixes: **63 passed**, lifecycle coverage **94%**, authority **90%**.
  Log: `/home/odin/reviews/desktop-step1-round1-entry-combined.log`.
- Final combined touched suites: **324 passed**, combined `src.desktop` coverage **93%**. An earlier combined run
  caught test-only environment leakage from the new entry mock and missing explicit asyncio plugin loading in the
  nested pytest probe. Both fixtures were corrected, not production assertions or ancestor permissions.
  Log: `/home/odin/reviews/desktop-step1-round1-final-touched.log`.
- All execution uses isolated PID/mount namespaces and non-live HOME/XDG. These incremental runs are not the full
  gate; the final fresh-checkout gate result is recorded below after it completes.

### Fresh-checkout full gate, run once

- Code checkout: `13cb95a016b4130092d3e140db227fbd758d748c`, with a new copied-interpreter venv and locked dev extras.
  Drift, lint, ownership checker and its **30 tests** passed. All 29 qualification groups ran once:
  **13,389 passed, 2 skipped, 1 failed, 0 errors**. The new transport group passed **228/228**.
- The sole failure was `test_common_safety_primitives_byte_identical`, whose older whole-file SSH-pool assertion
  had not been adapted for review finding 3's required private-directory provisioning change. Corrected it to
  permit **exactly** the import and constructor-call substitution, retaining byte identity for every other SSH
  safety byte. This is a named source adaptation, not a blanket exemption. Subsequent touched owner/path tests:
  **52 passed**. Evidence digest refreshes on unchanged source rows do not recapture or approve source changes.
- The full gate is **not rerun**, per the once-only instruction. The failed group is checked separately from the
  corrected clean checkout `6325cc9c205676543cbdc5773f5fae8060ac3898`: **446 passed**, drift and lint clean.
  That does not turn the original full run into a green run. Corrected group log:
  `/home/odin/reviews/desktop-step1-round1-corrected-boundary.log`; JUnit:
  `/home/odin/reviews/desktop-step1-round1-corrected/.test-state/review-corrected-boundary.xml`.
- Full log: `/home/odin/reviews/desktop-step1-round1-fresh-gates.log`; JUnit under
  `/home/odin/reviews/desktop-step1-round1-fresh/.test-state/qualification-{0..28}.xml`.
  Inherited unawaited-AsyncMock warnings remain visible; this is not a warning-clean claim.

## PR #14 round 2: D17 directory and socket-path parity

Review baseline: `31a48c24d7d3535f0fff2659a5da50d807af7bc7`.

- Removed directory permission-mode refusals in profile provisioning and IPC parent traversal. Owned
  `odin-desktop/<profile>` components are still repaired to `0700`; unrelated ancestors and existing configured
  socket folders are never chmodded. Foreign nonroot directory owners and links remain refused. Root-owned
  directories are accepted without attempting to repair another owner's namespace.
- Configured SSH socket paths keep their original relative/absolute spelling for OpenSSH. Only the guard's path
  is normalized, so `../sockets` works. Missing folders are created `0700`, existing folders are used unchanged,
  and the default profile socket folder is still created `0700` under umask `002`.
- Fail-before-fix run against unchanged production source: **34 failed, 15 passed, 126 deselected**. It includes
  actual supervised core startup below `0775`/`0777` XDG ancestors and all configured socket-folder review rows.
  Log: `/home/odin/reviews/desktop-step1-round2-before.log`.
- Final touched suites: **212 passed**. Combined paths/IPC-auth coverage **98%**, IPC-auth **100%**.
  Log: `/home/odin/reviews/desktop-step1-round2-final-touched.log`.
- Exact source-adaptation records and unchanged-source evidence pins are refreshed separately; no source
  recapture or independent approval is implied. Drift, lint and file-plan ownership checks pass.
- First new checkout, created after `umask 002` and verified `0775`: all 29 groups ran, with **13,426 passed,
  2 skipped, 1 failed, 0 errors**. The sole failure was the older data-diagnostic test expecting an owned `0755`
  namespace to be refused rather than repaired. That expectation contradicts this review's D17 requirement;
  replaced it with real `0755`/`0775`/`0777` diagnostics that prove namespace repair and untouched ancestors.
  Diagnostic suite: **37 passed**. Only that Desktop test and its evidence records change; production source
  remains the tested `c1204d9a` implementation. Logs:
  `/home/odin/reviews/desktop-step1-round2-fresh-gates.log` and
  `/home/odin/reviews/desktop-step1-round2-diagnostics.log`.
- Final clean checkout: `e3da247dca8a7ceb1f977265792ccf616672367d`, created after `umask 002` and verified
  `0775`, with a new copied-interpreter venv and locked dev extras. Drift, lint and ownership checks passed,
  file-plan behavior tests passed **30/30**, and all **29/29 qualification groups passed**:
  **13,429 passing executions, 2 skips, 0 failures, 0 errors**. Core transport passed **240/240**.
  All use the unchanged sanitized PID/mount-namespace launcher. The earlier failed run remains recorded above.
  Final log: `/home/odin/reviews/desktop-step1-round2-final-gates.log`; JUnit:
  `/home/odin/reviews/desktop-step1-round2-final/.test-state/qualification-{0..28}.xml`.
  Inherited unawaited-coroutine warnings remain visible. Only this evidence document changes after the verified
  code commit; no merge, live-service operation or attribution trailers.

## PR #14 round 3: D17 symlinked directory parity

Review baseline: `d1098b3025643bb6ecb0b6686fc0a181df447672`.

- Profile provisioning resolves directory links before walking the real folders with held no-follow descriptors.
  IPC resolves only parent folders; token/socket leaf no-follow checks, credential ownership/mode checks,
  descriptor-relative bind and inode-bound cleanup remain unchanged. Configured SSH socket spellings are preserved.
- Missing folders remain `0700`; existing modes remain accepted. Only real, owned Desktop namespace components
  are repaired, never unrelated link targets. Foreign nonroot target owners refuse, root-owned targets are used
  without chmod, and a directory substituted with a link after resolution still refuses.
- Fail-before-fix selection on unchanged production source: **20 failed, 1 passed, 174 deselected**. This includes
  real supervised core startup for all linked config/data/cache/socket locations, configured existing/new and
  relative/absolute linked SSH socket paths, namespace links, and target-owner decisions.
  Log: `/home/odin/reviews/desktop-step1-round3-before.log`.
- Final touched suites: **198 passed**; paths/IPC-auth combined coverage **98%**, IPC-auth **100%**. The first
  incremental run exposed one older parent-link refusal assertion, now updated to accept linked parents while
  retaining token-leaf refusal. Nondirectory and post-resolution substitution refusals are also covered.
  Log: `/home/odin/reviews/desktop-step1-round3-final-touched.log`.
- Exact source-adaptation records and unchanged-source evidence pins are refreshed separately; no source
  recapture or independent approval is implied. All execution uses sanitized PID/mount namespaces and temporary
  HOME/XDG roots. Fresh-checkout full gate evidence follows after it completes.
- First fresh `0775` checkout at `9e22c47f9c68e2c998e271be536160ff3c1fe4e2`: locked dependencies, drift, lint,
  ownership checker and its **30 tests** passed. All 29 groups ran: **13,445 passed, 2 skipped, 1 failed,
  0 errors**. The sole failure was another older folder-link refusal assertion in trust-directory materialization.
  Updated that Desktop test to prove real linked-folder materialization, exact contents, `0600` trust-file mode
  and unchanged unrelated target-folder mode. Production source is unchanged from the tested code commit.
  Log: `/home/odin/reviews/desktop-step1-round3-fresh-gates.log`; JUnit under
  `/home/odin/reviews/desktop-step1-round3-fresh/.test-state/qualification-{0..28}.xml`.
- Final combined touched suites, including the trust-directory test: **215 passed**, paths/IPC-auth combined
  coverage **98%**, IPC-auth **100%**. Log: `/home/odin/reviews/desktop-step1-round3-final-combined.log`.
