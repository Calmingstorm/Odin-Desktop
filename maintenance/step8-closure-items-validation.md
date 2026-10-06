# Phase 2 step 8 closure items, req04650fd0

Implementation PR: https://github.com/Calmingstorm/Odin-Desktop/pull/61
Base fetched before branch: `da2d3d4adbc7864ed78ffb972e3792f8557fbcb2`.
Engine/test qualification tree: `cd2be334b8e0b8554705fe3bed74b7a22df8352a`.
Subsequent `c33e391f5535b9ff9abe814b755f78f0d05cf219` changes only the app
Broker test to pin the restored browser default/retry seam, including disable
and re-enable. No engine, Python test or qualification selection changes.

## Delivered scope

- Package identity, compatibility, notice-only update status and existing
  lifecycle handoff are exposed through `status.get` and `runtime.status`.
  Reuses `package_state`, profile authority, shutdown, cleanup journal and the
  external P4.2 package-ownership barrier. No generic RPC, updater/installer,
  network release check or apply. Acceptance is not quiescence, and even clean
  core shutdown never asserts replacement safety.
- Real profile tests cover identity across restart, inert reads, pending commit,
  shutdown acceptance, parent loss, producer/close barriers, uncertain cleanup,
  storage/listener failure and replaced fencing.
- Exact existing behavioral core-contract pins are mapped in
  `step8-core-contract-coverage.md`. New pins cover independent conversations
  versus same-conversation FIFO, and retained submission identity after actual
  destination deletion and core restart. Body-free submission tombstones and
  other unsupported contracts are explicitly listed as gaps, not passes.
- `phase2_closure.py report` composes immutable suite validation, the D19 bridge
  checker when present, and the parity checker. CI uses report only. Missing
  inventory, proposals, deferred rows, malformed or stale proof never become
  readiness. Enforcing Phase 2 exit remains a separate change.
- Fresh settings/local/default-host/access parity loads original v4.13.0 code
  from the pinned archive in a disposable tree and provisions an independent
  Desktop profile. Actual executors select omitted/explicit localhost and the
  authenticated-owner `http_probe` fallback with only execution stubbed.
  Complete observation digests and 38 finite reviewed-decision delta rows are
  checked, with source/approval hashes and omission/staleness negative tests.
- The parity proof found three unapproved fresh-template divergences. Restored
  browser enabled, the exact two localhost:3000 browser targets, and the exact
  localhost:8188 skill URL under D17. Existing profiles and schema defaults are
  unchanged. Added locked test-only `discord.py==2.7.1` so clean environments
  import the unmodified pinned executor without ambient dependencies.

## Observed gates

Focused development tests: package-related selection 98 passed, 1 candidate
resource skip; core seam selection 16 passed; parity/provisioning/settings 49
passed; closure temporary-data checker tests 20 passed. These are not aggregate
product acceptance counts.

Final app checks: typecheck/build and 747 app tests passed. Actual isolated
Broker/core 22 tests and onboarding 6 tests passed after the fresh-default
correction. The first post-restoration Broker run had 21 passed and 1 failed
because its old assertion expected the browser to be unavailable. Updated that
Desktop-origin assertion to the existing enabled retry-seam contract and added
actual disable/re-enable pins. No native browser qualification is implied.

Offline inventory: zero drift errors, zero new lint findings, plan ownership
checker passed, suite map has zero integrity errors, actionlint passed with the
declared self-hosted runner-label configuration, and diff whitespace clean.

Full qualification: pending final receipt. An initial delegated invocation
lost its command-supervisor ownership at 900 seconds during group 17. Its
partial output is retained and is not a qualification pass. No process from
that invocation remained. `manage_process` was unavailable at its configured
20-job capacity. A bounded independent process starts the complete qualification
again from group 1, with streamed/retained output and explicit exit receipt.
No alternate test/isolation launcher, exclusion or weakened assertion is used.

## Current report and scope limits

At this branch's immutable base, closure reports **not ready**: all 326 historic
suites remain accounted, 9 restored, 5 retired and 312 without final disposition.
The D19 bridge inventory has not landed on this branch and is explicitly missing.
Fresh-profile parity is valid and the checker has zero integrity errors. This
PR does not change other lanes' dispositions or claim Phase 2 exit.

P4.3 was pending PR39 when mapped; later main advancement does not retroactively
qualify its integration with this branch. The core does not duplicate or pretend
to have run that app-owned release notice. Distribution/native qualification,
external replacement/preflight, publication, body-free tombstone privacy and
other mapped open contracts remain separate gates.

Raw evidence belongs outside Git:
`/mnt/storage/odin-desktop-evidence/step8-closure-req04650fd0/`.
The final small artifact manifest will pin paths, sizes and SHA-256 values.
All execution used sanitized non-root PID namespaces and disposable profiles;
onboarding used the existing isolated graphical launcher. No deployment,
service restart, live-config mutation, active-desktop input, tag/release/upload
or merge performed. Root disk stayed above the required 60 GB available.
