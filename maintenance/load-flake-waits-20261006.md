# Bounded load-flake harness observations

Request: `/home/odin/reviews/desktop-load-flake-waits.md`. Branch created only
after pulling `main` at `f29ffc34900d3d0b4020740cadcc3baa033f668b`.
PRs #58 and #55 were not changed. No product source file changes.

## Per-item disposition

| Item | Exact wait and classification | Change and observed product timing |
| --- | --- | --- |
| 1. Settings owner round-trip returns `no_receipt` | `RealCoreHarness.broker()` supplies 15,000 ms to the actual `Broker` request timer. Expiry settles the product `no_receipt` outcome in `app/src/main/broker.ts`, not an independent assertion deadline. | **Unchanged.** The test override remains 15 s; the app's production default remains 30 s. This is not claimed fixed. Its reported expiry was not reproduced: all 11 settings tests passed under load before and on final code. A provisional 45 s override was tested, then rejected and reverted because it delays the product outcome. Provisional logs are retained, not final-code proof. |
| 2. #58 settings IPC read | Historical `task1/fresh-full-executable.log:392-405` identifies the first `settings.set` response header in `test_schema_write_event_and_stale_binding_over_transport`; `request()`/`receive()` imposed a 3 s test read. | That one call now supplies **15 s**. All other RPC/event reads remain unchanged. The Python transport does not impose a product settings-RPC response deadline. The 5 s product hello/write-drain guards are separate and unchanged. |
| 3. Regular-file socket occupant | `lifecycle.spec.ts`'s 25 s `expect.poll` for `coreState === 'failed'` is an observation deadline. Reproduced under eight-worker CPU pressure: expected `failed`, received `running`, timeout 25,000 ms. | Poll **25 -> 60 s**; enclosing two-launch test **40 -> 240 s**, containing two 30 s launches, 45 s readiness, two 30 s exit observations and the 60 s failure poll. Product supervisor remains at three restarts in a five-minute window with 1/3/10 s backoffs. Four cold process attempts plus backoffs have no fixed total startup SLA. The failure/file-preservation assertions are unchanged. After change the entire lifecycle file passed; the first after-run case took 35.637 s total. |
| 4. Lifecycle resource-warning startup | The test originally at `lifecycle.spec.ts:333` calls `waitForCore`, whose 15 s harness deadline waits for ready link, PID and instance ID. | Helper **15 -> 45 s**. The product's 5 s handshake, reconnect policy and supervisor restart limits are unchanged; cold imports have no fixed product readiness deadline. The historical failed lane-7 trace was not recovered; the request identifies the timeout and the later preserved lane-7 run passed. This run's complete lifecycle file passed before and after, so no reproduced item-4 failure is claimed. |
| 5. Exact per-attachment ingestion note | Candidates are the shared 3 s RPC reads, 15 s submission read and 5 s `settled()` task wait. No retrieved historical failure identifies which expired. The older `intent-first.log` is a development `KeyError`, not load-timeout evidence. | **Unchanged, unresolved.** No guessed timeout increase. All four parameter cases and the source-order case passed in both loaded before/after Python file runs. Passing is not proof of which prior wait expired. |

## Additional directly observed harness expiry

The first loaded real-core all-file run passed the requested settings file but
failed the existing restart/catch-up contract's **8 s `core-changed` event wait**.
That wait starts *before* `core.start()`, which already permits 25 s cold socket
creation, then the Broker must reconnect and handshake. Only the two event waits
in that one restart contract now explicitly allow **35 s**. The product Broker
hello timer remains 5 s by default (the unchanged harness override is 3 s), and
the reconnect policy is unchanged. No startup, command, or fixture is retried;
all sequence, cursor, duplicate, instance and reset assertions remain identical.

## Proof and limits

All engine/graphical descendants ran as UID 1003 in the repository's private
PID namespace with disposable HOME/XDG, Xvfb and private D-Bus. No active desktop
display/bus, live config, installed app, service or `/opt/odin` was touched.
Dependencies came from frozen `uv.lock` plus `npm ci`. Electron's skipped binary
download was explicitly provisioned in the disposable checkout. npm reported
11 inherited dependency vulnerabilities (10 high, 1 critical); no lock updates
or automatic audit fixes were made.

Load came from **eight continuously busy worker threads** in a separate disposable
repository namespace. Ten-second samples record wall time, cumulative CPU time
and host load. First load run lasted 1,200.108 s and consumed 9,549.184 CPU seconds.
Host load at test starts ranged approximately 13-29, higher than the reported
8-12 range. This is scheduler/CPU pressure, not a claim of identical CI I/O load.

- Before settings file: **11 passed**, unchanged product timers.
- Before lifecycle after binary provisioning: **13 passed, 1 failed**, exactly the
  regular-file 25 s poll; separate missing-Electron setup run retained.
- Before Python files: **18 passed**; separate nonexistent-selector setup failure
  retained, zero collected, not counted as test execution.
- After lifecycle: **14 passed**, Playwright retries **0** throughout.
- After Python files: **18 passed**, including the untouched attachment cases.
- Final real-core files with product timers restored: **22 passed**, 0 failures or
  unhandled errors, in 125.30 s under renewed eight-worker load.
- Typechecks passed; Broker/supervisor/isolation launcher regressions: **73 passed**.
- Byte drift clean, no new lint findings (seven inherited), ownership-plan and
  `git diff --check` passed. Exact engine-test delta and 19 dependent evidence
  seals were re-recorded with `inventory.py record`, all pending independent
  review. The 19 destinations were checked byte-identical to the base first.

Every executable invocation is single-run, with no test retry mechanism added.
Separate before/after and provisional/corrected invocations are preserved and
named, not folded into a fabricated clean first run. No full engine qualification,
onboarding, accessibility, native desktop or installed-package gate is claimed.

Raw logs/traces and CPU-load script are external to Git:
`/mnt/storage/odin-desktop-evidence/load-flake-req51800a06/`.
The adjacent artifact manifest records sizes, absolute paths and SHA-256 digests.
