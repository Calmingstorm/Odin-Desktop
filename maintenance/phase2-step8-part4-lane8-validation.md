# Phase 2 step 8 part 4A: lane8 6A restoration

## Scope and disposition

Work order: `/home/odin/reviews/desktop-step8-part4-lane8.md`.
Assignment SHA256: `20f094868694949d7e3fc89d74f9277e4d1a293e0c7578311f7b1c6bb0b5d12c`.
PR: <https://github.com/Calmingstorm/Odin-Desktop/pull/48>, draft against main.

Exactly **97 assigned suites** are accounted: **24 whole restored, 14 whole retired,
59 deferred**. **177 individual case definitions** retire exclusively for removed
Discord, multi-user, HTTP/WebSocket listener, bearer-session or Odin web UI
surfaces. Every case has its frozen source hash, exact case identifier, reason and
`Claude, review of step 8 part 4` authority. Eight individual mixed registry/schema/
cache contracts are proposed for reviewer decisions, not retired; they remain in
the deferred suite. Zero unsafe command-data substitutions were authored.

The authoritative artifact is `phase2-step8-part4-lane8-dispositions.json`, SHA256
`0b8601be06252b40878b667d4f3aa63c2c126cd0aae0bd25f5bd453b5c1097fa`.
All 97 inherited source files retain their exact hashes. All 62 lane6 assignment
rows remain byte-equivalent as parsed JSON to their pre-work rows. Partial pure
support tests are deliberately not counted as whole-suite restorations.

## Real behavior fixes

- Compose the genuine profile-local UsageRollup, connect both trajectory-saver
  observers and catalog lookup, and settle it during engine cleanup.
- Wire retained optional calibration observers to agent, loop, housekeeping and
  runner owners. Core resume now releases only the exact TurnKey workload scope.
- Full qualification exposed a real usage provenance bug after writer composition:
  an empty, incomplete backfill was reported as estimated zero. It now remains
  unknown until generation evidence exists or backfill completes; complete empty
  history still reports measured zero. The inherited assertion was not changed.
- Merge lifecycle safety retains producer quiescence, original resource evidence,
  management MCP producer settlement and no cleanup-success fabrication.

## Fresh full qualification

Qualified source head: `8f8cb0aac83015c23b7c128090863fc9badf99f6`.
Fresh checkout:
`/home/odin/desktop-step8-part4-lane8/qualification/corrected`.
Parent folder is group-writable/setgid. Locked `uv sync --locked --extra dev`, copied
0755 Python interpreter, restricted PID/mount isolation, non-root UID 1003 and
throwaway sanitized HOME/XDG environments. No active graphical session used.

**35/35 groups: 15,831 passed, 2 skipped, zero failures, zero errors.**
New lane8 groups: tools **401**, computer **370**, Hyprland **150**, campaigns
**244**. These include explicit provenance checks and separately labeled partial
support, so 1,165 group passes are not 1,165 whole-restored inherited cases.

Qualification-plan SHA256:
`97c91656488d1ca8f345bcdc3d11cd26365828ad9b93d18b442e8440205e6e64`.
Every final per-group JUnit receipt is in the fresh checkout's `.test-state/`.
The continuation aggregate is `.test-state/qualification-continuation-result.json`.

Two existing skips: the native Hyprland wire binary was not supplied; Playwright
is installed, so the missing-import branch cannot be executed. Existing mock
coroutine, subprocess event-loop-close and aiohttp fixture warnings remain.

Execution was not uninterrupted. An initial run filled the filesystem and was
invalidated; a subsequent complete run found the actual usage bug above. The
corrected fresh run completed groups 1-19 before the background shell supervisor's
15-minute lifetime ended. Groups 20-35 were continued on the same clean checkout,
same locked environment and unchanged head, with the original passing receipts
retained. No test retry or assertion weakening was added to any harness or product.
Disposable uv cache pruning and concurrent release of unrelated temporary work
restored disk headroom; no source/user output was removed by this task.

Logs:
- `/home/odin/desktop-step8-part4-lane8/fresh-qualification-corrected.log`
- `/home/odin/desktop-step8-part4-lane8/fresh-qualification-corrected-continuation.log`

## Short gates and moving main

Offline drift: zero errors. Lint: seven inherited findings, zero new findings.
Phase2 ownership plan and exact suite accounting passed. Earlier fresh short gate
set: 182 passed; post-usage-fix targeted runtime/management regression: 33 passed.

After qualification, main moved from `58d75d01` to package-ownership merge
`f597c1af`. It was merged, never rebased, at `69601df0`. The conflict resolution
awaits real 6A management startup before committing the package upgrade fence.
Post-merge package/core/services/calibration/usage gate: **81 passed, 1 skipped**
(native AppImage artifact is not supplied). Receipt SHA256:
`f3dbc66532dd7fba4128b0371acc80c8098bfd0a46489ae9fdbe3e4d9ecc1d97`.
Post-merge drift, lint and suite accounting again passed. A second full qualification
was not represented as having run on the later merged head: the full proof above
is pinned to its actual source head, and moving-main validation is separate.

Latest integrated services-part-a: `dda129d8f0597d12dbb16837baa5b84ec1c866dc`.
No PR merge, deployment, live-service modification, `/opt/odin` change or active
desktop input was performed. All adaptation records remain pending independent
review. Browser-wait real Chromium proof uses the explicit existing packaging
candidate at `/home/odin/desktop-p41-final-stage/runtime`; it is an external test
fixture prerequisite, not a portable installed-browser or native qualification.
