# 1.0.0 independent install directory

Task: `/home/odin/reviews/desktop-opt-odin-desktop-20261007.md`.
Branch: `packaging/opt-odin-desktop`, based on freshly fetched main
`7aa0d8e0` (PR #114). No installation, VM/lab work, desktop input, service
change, or access to the actual `/opt/odin` or `/opt/Odin` directories.

## Implementation

- Both productName inputs are `odin-desktop`, giving electron-builder's Debian
  mapping `/opt/odin-desktop`. The explicit desktop entry, AppImage entry,
  native application name and window title remain Odin.
- Before single-instance admission or readiness, Electron receives the visible
  name Odin and a userData directory `<appData>/odin-desktop/electron`. This is
  normally `~/.config/odin-desktop/electron` and respects XDG_CONFIG_HOME.
- Updated launcher classification, both package-ownership implementations,
  AppArmor ELF attachments, package qualification/discovery drivers and live
  documentation. Historical maintenance Markdown was not rewritten.
- Only upgrade preinst/prerm examine the former location's ownership marker.
  A marked Desktop installation also receives the process scan. Fresh installs,
  remove/purge/configure/unwind do not inspect the former install directory.
  Guarded upgrade preflight records the legacy launcher target, allowing
  configure to replace its direct or indirect symlink without accessing the
  removed executable. Bounded component-wise link-text traversal refuses foreign
  targets, old-directory aliases, cycles and excessive chains. Primary package
  leases, receipt fences and process checks remain unchanged.
- Eleven engine/test/script deltas were recorded with inventory.record. Existing
  reason/contract/invariant text and test references were retained and appended;
  no existing extra fields required restoration.

## Tests and observed results

All dynamic tests ran as UID 1003 under the unchanged required private PID/mount
launcher, with sanitized HOME/XDG and no live graphical session.

| Gate | Result |
|---|---|
| npm run check | Typecheck, 1,234 tests in 123 files, production build passed |
| Complete app/packaging/tests | 127 passed, 31 capability skips |
| Engine/package/native-driver/offline-orchestration focused files | 200 passed |
| Ruff on transaction and its test | Passed |
| inventory report | No errors, byte-drift-clean-review-pending |
| lint gate | Exit 0 |
| phase2 plan | Exit 0, existing planned-not-implemented status |
| D19 report | No errors |
| phase2 closure report | Exit 0 but NOT clean: inherited settings hash error |
| Independent source review | No concrete findings; not package/native acceptance |
| git diff --check | Passed |

The packaging run includes real pinned fpm mapping/extraction and generated shell
launcher behavior. Desktop-name regressions use electron-builder's real Debian
and AppImage entry generators, not documentation wording assertions. Legacy
upgrade/fresh-install fixtures exercise real transaction markers, locks, scans
and symlinks with privileged provisioning and AppArmor application mocked.

The 31 packaging skips are 27 root transaction fixtures, one root lease fixture,
one read-only mount fixture, one missing chroot fixture, and one root dpkg fixture.
No privileged installer/native acceptance is claimed.

### Inherited closure defect

The closure report contains `parity: stale hash: src/desktop/settings.py`.
Both source and proof are unchanged from the fetched main. Main source SHA-256
is `183dd23133c74c62242a467cb28e24f64755a47d46b7b03252f3be6591255c6c`;
the proof pins `5900062b471979920ed3c02f03698f741f80b53618cc401ba17bb942cab60da4`.
This task neither refreshes evidence for unrelated settings behavior nor calls
that report a clean pass.

### Intermediate corrections

An initial identity test failed TypeScript's checked array-index typing; corrected
before the passing complete check. The first passing check had an erroneous outer
wrapper reading an undefined return value; the corrected wrapper and full check
were run again successfully. An extra packaging wrapper rejected FPM_BINARY as
an environment override before starting tests; the final run sets that fixture
variable in its isolated child command. An extra Python run named nonexistent
files and collected no tests; corrected selection passed 200 tests. A narrowing
of alternatives handling would have changed an existing skipped privileged case;
the original case was retained, bounded traversal restored, and equivalent
non-root regressions added. No thresholds, guards or test skips were weakened.

## Retained evidence

Directory: `/mnt/storage/odin-desktop-evidence/opt-odin-desktop-20261007/`.

| Artifact | SHA-256 |
|---|---|
| app-check.log | 8ada1ba41638e68a0e3dcec948937de0a9338496f383fa5a33745ac8b3b6d3f6 |
| packaging-final-verified.log | 0c9ba547b85a9393fb41fe77911d511a0a19d78c0bb9828b064980b1d3bc0d79 |
| python-final-verified.log | fcf5eb7f1c7de84229dad4425ab49e412696cf71354c4b7dcb9db2ba97c7c1cc |
| inventory.json | 4ec892736e32f63a789c13e9fa82c81daae8fbf1da45ae034e6dd0a06d35031e |
| lint_gate.json | 9d34ab5bc2efad4fadb7e30a2f0674d4426c54769eed8fb7fe58b6cfe61c4584 |
| phase2_plan.json | ee20850a561b355e8240ab57ec1ff604439ca4f5322807e31a00dbd9139f2a48 |
| d19.json | 99fbe39a2df60200f49c3a6fe3687bd84a772cd584157ff47bd9863cb3395ac6 |
| phase2_closure.json | 7cb542353d8541b70241389de8aacb89b68f62560be26ca5edd614239624616e |
| app-check-initial-type-error.log | 200974bf0bfe653f1e606edf5d22112ad211addf0e2740c5a22d4a5bcffa5c98 |
| app-check-wrapper-error.log | 425e23646d710bf220569cc188c393ae6d64f0e5b878ef1fce7a39480407619e |
| packaging-final.log | ec578709c3fa850f7dc1106d80f96f666d6a3819c3a8a0a13c829fb8749b7e70 |
| python-final.log | 285d4d00fa3530ff7605e33ce7693bc5b9047270d603a0f019afd8ee15ab8648 |
