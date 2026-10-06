# PR39 merge-main validation, 2026-10-06

## Final integration after concurrent PR28 main merge

After the first push, PR28 independently advanced main to
`cd52a8e2b055a9c4abc051a49566b9daf3e1bd79`. A second true merge incorporates
that main on top of `76a0da7060b4499777cd4de9a4d866a0107e526d`; no rebase or
force-push. The smoke conflict now treats Step 6A skills/MCP/computer management
as served while retaining capability-absence and actual refusal assertions for
unserved Part B execution/native input. Production behavior on both sides survives.

The automatically merged ledger was independently checked against the supplied
three-way path-union helper: byte-identical, 372 entries, no differently changed
shared entry. The whole requested gate set was rerun after a fresh locked venv
and npm provisioning in the recreated lane worktree. Final run passed:
inventory zero errors, zero new lint findings, plan, 38 short fixtures,
49 Python + 9 Node release tests, typecheck/build + 789 app tests,
39 release-notice + 45 isolation tests, normal-user packaging 79 passed and
12 expected skips, isolated root transaction file 12 passed, real Broker/core
22 passed, private-display onboarding 6 passed, both workflow actionlint and
diff checks. The real-core smoke additionally passed with 40 screen observations
and the newly served management capabilities; native input remained unavailable.

Final external evidence is under `latest-main/` and
`latest-main-all-gates.log` in this run's artifact directory. Exact hashes are
in `pr39-merge-latest-main-artifacts.json`. The initial qualification below is
retained as history, not substituted for this final rerun. No suite failed or
was retried; no assertions were relaxed. No package build, native desktop input,
Actions dispatch, publication, deployment or service changes occurred.

Request: merge main into the approved P4.3 release-notice branch without rebasing,
preserving both sides, run the requested short/app/release/packaging gates, and push.

## Integration

- Original approved head: `1c48529b0af3ad18d9c413882166cb6ee40702d1`.
- Merged main: `ed0069674533c23e70a0302652a2fb76901ff385`.
- Isolation launcher combines main's 600-second whole-gate deadline and typed
  interface with P4.3's selected cached-Node PATH. Capability probes remain
  10 seconds; suite failures are not replayed. Tests retain both environment
  noninheritance assertions and the cached-Node regression.
- Main's ownership wrapper, `odin-desktop.bin` split and executable AppArmor
  attachment are preserved byte-for-byte, as is the engine workflow's
  self-hosted short-runner label split and draft-PR gate.
- The approved self-hosted release workflow is unchanged. Default dispatch is
  dry-run; the separately guarded publishing path is not exercised or authorized.
- Updated stale packaging README statements about workflow triggers/publication.
- Ledger is byte-identical to `/home/odin/reviews/merge_ledger.py`'s path-keyed
  union of the three Git stages: 352 entries. No entry was changed differently
  by both sides, so no `inventory.py record` regeneration was required.

## Observed gates

All commands completed successfully against the resolved merge tree, using the
existing locked development environment. No fresh qualification clone was made.
Throwaway HOME/XDG and PID isolation were used; graphical onboarding ran only in
the launcher's private display, not the workstation's active session.

| Gate | Result |
| --- | --- |
| inventory report | 0 errors, byte-drift clean; review-pending metadata remains honest |
| lint gate | zero new findings |
| Phase 2 plan | pass |
| short Cinnamon/GNOME hermetic fixtures | 38 passed |
| release helper Python | 49 passed |
| release helper Node | 9 passed |
| npm run check | typecheck, 789 tests, build passed |
| focused release notice | 39 passed |
| focused isolation launcher | 45 passed |
| packaging, normal UID/GID | 91 run: 79 passed, 12 expected skips |
| packaging, isolated real-root transaction file | 12 passed |
| actual Broker/core contracts | 22 passed |
| onboarding, private display | 6 passed |
| actionlint, both workflows | pass |
| staged diff check | pass |

Normal-user packaging executed the real ordinary-owner AppImage lease/replacement
tests, wrapper/AppArmor checks, isolated SSH key generation, namespace hiding, and
disposable real-dpkg maintainer-script row. Eleven root-only transaction rows were
skipped there and passed in the separate real-root mount/PID/network namespace.
The remaining intentional skip is the read-only bind-mount fixture, which belongs
to candidate namespace qualification. This merge does not claim that acceptance
gate, a new package build, full lifecycle qualification, or an Actions release run.

The process-manager start was unavailable because its 20-job cap was occupied.
A bounded detached gate launcher with streamed logs and an explicit exit receipt
was used instead. It exited 0; no suites were retried or assertions relaxed.

Raw logs, execution script, and their SHA-256 manifest are retained outside Git at
`/mnt/storage/odin-desktop-evidence/pr39-merge-main-20261006/`.
See `pr39-merge-main-artifacts.json` for exact paths/digests.

No rebase, force-push, attribution trailer, main merge, workflow dispatch, tag,
release, upload, deployment, service restart, or active-desktop input.
