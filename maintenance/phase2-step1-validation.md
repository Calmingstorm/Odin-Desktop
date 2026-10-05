# Phase 2 step 1: core process and local transport

Base: pulled `main@52c90f53186551faf149a6313b0a10e441bb1a2c` before branching.
Implementation is one review PR, not a deployment or a claim of complete Phase 2 parity.

## Implemented boundary

- App launch: `python -m src --socket <path> --token-file <path> --profile <id> --data-dir <path>`.
  The app creates the token; the core never creates or repairs it. stdin must be the app-held pipe.
- Profile roots match the app and protocol (`odin-desktop/<profile>`), without Phase 1's extra `profiles` component.
  Explicit token/data roots are shared by runtime path resolution. App logs, drafts and window preferences are
  scaffolding, not imported engine state or authority.
- One sealed owner authority and identity-directory runtime lock, one shared private SQLite store, one listener.
  The entry retains profile ownership through the byte-identical containment/finalization helpers.
- Minor 2 framing/hello/welcome/ping, UID/token/profile checks, private socket, live-socket refusal and inode-safe
  cleanup. Only `status.get`, `events.subscribe` and `runtime.shutdown` are advertised as ready.
- FULL-synchronous durable command admission, final receipts and permanent binding tombstones. Callback results and
  events commit together. A pending/unknown command never automatically replays; unknown receipts are not pruned.
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
