# P3.6 D11 matrix and Phase 3 closure

**Phase 3 NOT CLOSED.** This PR adds the executable evidence runner, machine matrix,
actual Electron security/content regressions and a precise closure inventory. It
does not rebuild a feature to manufacture a matrix entry or waive a native gate.

## Artifacts and reproduction

- Binding work: [`phase-3-app-v1.md`](../docs/work/phase-3-app-v1.md), section 1/P3.6.
- Executable schema/accounting: [`desktop.py`](../scripts/qualification/desktop.py).
- Current row/gate inventory: [`phase3-matrix.json`](phase3-matrix.json).
- Raw artifacts: `/mnt/storage/odin-desktop-evidence/p36-20261007/`.
- Candidate build consumes merged #89 (fence), #94 (logout), #95 (Wayland window).
  It is **interim**, because P3.5 is still being built on another lane.

Interim build source: `243a613a00cb1751357648915dc1881b773f189b`.
The later accounting/guest harness changes do not alter shipped product bytes.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `.deb` | 342198876 | `31e7baee6779f77ca2d696d0f2b097ad1da655195d93bcede28a617eb538ca5c` |
| AppImage | see artifact manifest | `a757435633334db1970227463f9fa454da9e3e57a38c25e9a5d7206ecd5a9000` |

Both retained under the raw artifact directory. AppImage is built/hashed, not a
native D11 row run. Bundled resource manifest hash:
`a278eed51825a7c4d98d6931c8b279faa8f1ba57fb8e2d0304a202d4a523538f`.

```sh
python3 scripts/qualification/desktop.py check maintenance/phase3-matrix.json
# Accounting validity is not qualification. This deliberately fails until final:
python3 scripts/qualification/desktop.py check maintenance/phase3-matrix.json \
  --artifact-root /mnt/storage/odin-desktop-evidence/p36-20261007 --require-ready
python3 scripts/qualification/desktop.py pack-tools --output /external/new-tools.tar
# First acquire /run/odq-lab.lock with a root-owned `p36 ...` owner. No odq VM
# may be running/frozen. Never steal another lane's lock or stop its guest.
python3 scripts/qualification/desktop.py row --vm odq-cinnamon \
  --candidate /external/candidate.deb --source-sha EXACT_40_HEX_SOURCE_SHA \
  --tools /external/new-tools.tar --output /external/new-cinnamon-row
```

The runner validates exact lab ownership/devices with the existing lab driver,
hashes transport bytes before dpkg, requires a new external evidence directory,
and compares the shipped manifest source to the immutable candidate identity.
It installs only inside the marked VM and runs Electron as `odq` in a fresh
HOME/config/data/cache tree. Guest rendering keeps that guest's compositor/bus,
never the workstation's. No `computer_*`, host capture/input, host apt, VM
removal, disk/snapshot replacement, service deployment or live configuration.
Graceful poweroff is recorded. Unknown cleanup retains the lock for operator
recovery; no replay or force-stop fallback. Release only the lock this lane owns
after confirmed stopped state. Hyprland consumes P3.5 evidence instead of this
app probe, with exact candidate **and environment** identity checked on reuse.

## What the behavior tests actually prove

`app/test/e2e/desktop-security.spec.ts` runs through the existing restricted
PID/HOME/Xvfb/private-bus launcher. `desktop-probe.cjs` is shared with the real
guest candidate probe. Production sandbox/context isolation/no Node are
inspected, named bridge malformed arguments/file references are refused, a
fabricated File cannot stage a disk path, served CSP blocks inline script,
event attributes and renderer network, and actual permission/navigation/popup
attempts are refused. A second actual webContents with shipped preload is denied
by the production sender check. The installed IPC handler is also exercised
with synthetic wrong-origin/subframe events using observed frame identities.
Those last two are **event-boundary regression**, not native iframe transport
qualification. No generic RPC or qualification shortcut is added to production.

The separate content test uses the controlled fixture transport but the real
DOM/components/preload: 5,000-line reply, Markdown table, inert script fixture,
decoded image and forward/back report pages. It is source regression, not
provider, native dialog, computer input or packaged content acceptance.
Resize/1.5x scale/focus/reload are inspected with real Electron, without claiming
physical display scaling or human/Orca visibility. Screenshots alone never
qualify keyboard, speech, tray, permission consent or native release.

## Gate checklist, observed inventory versus acceptance

| Gate | Status | Evidence and limits |
|---|---|---|
| UI parity / P3.1 | In progress | `p31-slice{2,3,4,5,6}` validation; composed source slices, final native candidate pending |
| P3.2 | Done (source scope) | `p32-onboarding-validation.md`; fresh/retry real-core contracts, no current native keyring claim |
| P3.3 | In progress | `phase3-lifecycle.md`, #59; packaged/native final rows still moving |
| P3.4 | Blocked | `phase3-orca-runner.md`; earlier KDE Qt chooser missing AT-SPI; source automation is not Orca acceptance |
| P3.5 | In progress | Separate native lane; identical candidate results not available yet |
| D11 four rows | Pending/interim | Machine row inventory and per-row artifact reports; no mixed hashes reused |
| P4.2 | In progress | `phase4-packaging.md`: 13 earlier actual ownership cases, corrected fence #89; rerun exact final candidate lifecycle/upgrades |
| 326 inherited suites | Done dispositions, not all passes | 99 restored, 77 retired, **150 named deferrals** with specific blockers and Aaron decision 3; zero missing dispositions |
| Section-4 D19 | Done wording inventory | 50 actual rows: 19 restored/removal, 23 unreachable, 8 Aaron-approved; zero open wording rows |
| Runtime fresh-host parity | In progress | Fresh-profile parity valid, exact dynamic contracts exist; current bundled native/helper/fresh-host acceptance is separate |
| Final candidate | Blocked by sequencing | Must be built after P3.5 merge; #89/#94/#95 already merged |

The 150 suite deferrals are inventoried **exactly** in the retained
`phase2-closure-inventory.json` and `maintenance/phase2-suite-map.json`, not a new
326-suite restoration task. Existing Phase 2 closure reports `ready=true` for
its approved exit-obligation inventory; that boolean is not this Phase 3 gate.
Old prose in D19 docs calling exit open does not override the current executable
inventory. No previously approved disposition is silently changed here.

## This PR's final source gates (2026-10-07)

Fresh worktree `/home/odin/desktop-p36-fresh-20261007`, source
`28e6de9b` plus ledger-only `98ac6dd7fab2bf25869940921bf4cf115cf13981`.
Fresh locked Python dev environment and `npm ci --ignore-scripts`; pinned
Electron installed explicitly. Product/probe source did not change between
the fresh app gates and the ledger-only update. Latest main `aa3d61b3` merged.

| Gate | Actual result |
|---|---|
| Full `npm run check` | Typecheck/build pass; **1049 tests, 108 files passed** |
| Fixture smoke | Passed, sandbox intact, normal Exit, isolated screenshot retained |
| Real-core + onboarding | **66 + 6 passed** |
| New actual renderer/security/content E2E | **2 passed**, zero retries/skips |
| Matrix targeted | **34 passed** |
| Additional Desktop boundaries | **504 passed**, zero failures/skips |
| Full inherited qualification | **38/38 groups**, **19,313 passed, 3 skipped**, zero failed groups; 379 deselected per reviewed selectors |
| Offline lab fixtures | **159 passed, 4 skipped** because restricted helper lacks distinct subordinate UID/GID mappings |
| Drift/lint/ownership/D19/closure | Zero drift errors/new lint findings; seven inherited lint findings; ownership plan and exact closure inventories pass |
| Matrix check | Valid accounting, **ready=false**, not qualification |

The full inherited run was executed once after the final source changes. Its
three skips and coroutine/mock/aiohttp warnings are preserved, not promoted to
native qualification. Earlier developing probe failures (module/preload observer
setup) preceded the corrected 2/2 run. Initial final drift check caught four
unledgered new qualification scripts **before any engine suite ran**; explicit
ledger records fixed that accounting failure, with no source/assertion/guard
change. `final-drift.json` and corrected report both remain retained.

**No P3.6 VM row was run in this turn:** Claude initially owned the lab, then
P3.3 held `p33 2026-10-07T16:26:57Z GNOME missing rows req-7747a619`, still held
at 17:20 UTC. Bounded lock polling ran for 30 minutes and code/gates proceeded
meanwhile. `lab-wait-receipt.json` records the owner. No lock theft, guest stop,
input, capture or disk action was attempted. Thus the interim candidate proves
construction plus source renderer harness, **not the VM runner in operation**.
All four D11 rows remain pending, with P3.4's earlier KDE accessibility blocker
and P3.5's promised-backend gaps explicitly retained. Final candidate run is
pending P3.5 merge and lab availability; current row statuses are not waived.

Raw logs, candidate installers, screenshots and hashes remain in the external
artifact directory, indexed by `artifact-manifest.json`. The small committed
manifest pointer/results are `p36-results.json`. No tests are claimed to have
run on a new final-candidate hash. No publishing/deployment/live desktop action.

### Additional immutable package evidence and CI, 17:49 UTC

Both **extracted immutable interim** formats passed the existing packaging
driver's manifest, credential-signature/development-artifact scan, real bundled
core/D14 probe and sandbox-intact GUI/Exit proof. Both GUI lanes recorded fresh
clean independent app/core lifetime receipts. Evidence:
`interim-package-qualification/qualification.json` and its per-lane JSON/PNG.
The overall driver **returned fail**, solely because the actual installed `.deb`
lane was not proven. This is eight passing extracted-package checks, not P4.2
upgrade/install acceptance or a native D11 row. No `--force-depends` install was
used to manufacture that missing acceptance.

PR #97 CI run `37658777046`: both short gates and all five qualification shards
passed, but `full-suites` **failed**: `real-core-work.test.ts`, “all six kinds
are destination-bound; actual task finishes and unknown release remains unknown”,
timed out waiting for actual manager proof admission. CI recorded 65/66 real-core
passes, unlike the local fresh 66/66. The exact cause is unproved; it is not
silently classified as load, erased by local success or retried for a green badge.
Full failure log retained at `ci-full-suites-failure.log`.

P3.5 now has open PR #98, still with native gate blocked. A second bounded
30-minute acquisition attempt continued while the same P3.3 lock remained held.
Final matrix/required acceptance remain pending, not completed by these checks.
At 17:56 UTC that second wait ended with the same P3.3 lock still held, no
acquisition and zero guest operations. Exact final blocker is
`lab-final-blocker.json`; followup artifact hashes are indexed by
`artifact-manifest-followup.json` through `p36-artifacts.json`.

## Decisions and remaining work

### Latest approved decisions and hard admission blocker, 19:08 UTC

Merged #100 records Aaron's **Decision G**: Orca/AT-SPI results block nothing;
existing evidence remains. Prior references in this historical report calling
the KDE chooser speech/tree gap a release blocker are superseded. Keyboard-only
coverage remains required and still lacks full current-candidate native tasks.
Decision H permits two VMs/two lock slots, but does **not** authorize raising
the lab disk budget or weakening capacity/ownership guards. This lane used the
more conservative one-guest handoff; no live workstation interaction.

New actual P3.5 summary reports X11 limited, GNOME/KDE/Hyprland blocked by absent
scope/exact-ABI plugin support, and failed restart-quarantine observation.
Candidate hash `6ae4203e...` differs from P3.6 `31e7baee...`, so those native
results are upstream blockers, **not reused acceptance**. #98 remains unmerged.

Latest unchanged lab preflight **refuses all further starts**:
`Lab pool allocated usage 54.5 GiB plus 50 GiB growth/reserve exceeds the 100 GiB
aggregate budget.` Request expressly forbids VM removal/disk/snapshot changes.
No other lane's data cleanup, capacity-floor change, direct Incus start bypass,
or final-candidate claim is authorized. Aaron must authorize capacity remediation
or a reviewed lab-budget/storage change before more native coverage can run.
Final candidate additionally requires reviewed P3.5 merge. These are current
hard blockers, not a task Odin can finish honestly by waiting or changing labels.

### Native interim handoff, 18:28 UTC (supersedes earlier lock blocker)

Lab lock finally acquired at 18:03 UTC after coordination on #59; all VMs
were stopped before admission. Every attempted guest was gracefully stopped,
and the exact p36 lock was released at 18:28 UTC. No other lane's VM/lock touched.

- **Cinnamon limited:** actual ordinary dpkg reinstall and packaged X11
  rendering/security probe passed (`cinnamon-final-interim/probe.json`, PNG).
  Ubuntu 24.04.5, kernel 6.8.0-146, Cinnamon 6.0.4/Muffin 6.0.1, Virtio GPU/Mesa
  25.2.8, Electron 44.5.1/Chromium 152.0.7977.130, Python 3.12.15. Portal was
  actually absent. Initial accounting blocked the empty portal inventory and
  mislabeled Electron's `versions.chrome` key; these collector defects are fixed,
  not counted as app failures. Later reinstallation hit boot-cleanup refusal.
- **KDE limited:** actual normal dpkg reinstall and packaged **native Wayland**
  security/rendering probe passed. Plasma 5.27.12/KWin 5.27.11, KDE portal 5.27.11,
  same candidate/runtime/GPU family; exact environment/helpers/artifact hashes
  in `kde/row.json`. No Orca, SNI tray, KWallet or native chooser claim.
- **GNOME blocked:** initial session helper omitted Wayland display and distro
  Node18 could not run the pinned Playwright. Reused reviewed session discovery
  and copied the host Node22 binary as guest test tooling (not installed product)
  corrected those harness prerequisites. Normal dpkg repeatedly refused running
  lifetime/current-boot cleanup, including after normal Exit and guest reboots.
  No lease deletion, acknowledgment, force install or fence bypass. Logs in
  `gnome-next-boot/runner.log`; no renderer qualification claimed.
- **Hyprland pending:** P3.5 #98 is still unmerged/native-blocked; no unrelated
  candidate results imported.

The machine matrix's `observed_row` pointers preserve complete immutable row
records. Its main statuses stay conservative full-row acceptance statuses,
with `observed_status=limited` where only rendering/security passed. The initial
resource preflight correctly refused a temporary low-storage interval; after
unrelated scratch settled, unchanged preflight admitted without floor changes.

Additional isolated installed-package alternative: `interim-installed-sandbox`
passed three manifest/scan/bundled-core/GUI lanes, including installed dpkg
export, with identical manifests and fresh independent clean lifetime receipts.
It uses the existing driver's **`dpkg --force-depends` private namespace fixture**,
so it is not dependency-resolution/P4.2 upgrade acceptance. Ordinary guest dpkg
installation is separately observed on Cinnamon/KDE. Neither closes final
candidate/native lifecycle acceptance. Required complete rows still missing.

Actual VM findings changed only the qualification harness: owned-session
discovery, local Node22 tooling, guest pciutils, explicit absent-portal records,
correct Chromium version key and bounded --exit settlement interval. Updated
focused accounting tests passed 34/34. Previously recorded full gates predate
these harness-only fixes; they are not represented as rerun final-harness gates.
Final immutable candidate must still follow P3.5 merge; Phase 3 remains open.

### Refreshed complete source gates, 19:03 UTC

Fresh checkout `desktop-p36-fresh2-20261007` at
`7f2326f069ef271856fe119b2f077c1d1e85645b`, with all guest harness fixes and
reviewed upstream startup-Exit #96/user docs #99 merged. Full gates rerun once
after that source merge: **1054 app tests (109 files)**, typecheck/build and
fixture smoke pass; **66 real-core + 6 onboarding**, **2 renderer E2E** pass;
**511 additional Desktop**, **38/38 qualification groups, 19,313 pass/3 skips**,
and **159 offline lab fixtures/4 capability skips**. JUnit confirms zero failures
or errors across 19,316 inherited tests. Drift/lint/ownership/D19 inventories
clean. This supersedes the earlier source-gate watermark, not the interim
package SHA. The earlier CI admission timeout remains retained and un-erased.
Latest logs/JUnit/hashes in `artifact-manifest-final2.json` and `p36-artifacts.json`.
P3.5 #98 remains open at this report; final one-candidate qualification cannot
precede that reviewed merge. No earlier candidate's native subset becomes a
final result merely because newer source tests pass.

No extra owner approval/governor/allow-list or model instruction is introduced.
No Aaron decision is needed to keep building/running interim evidence under the
approved lab rules. If KDE native dialog accessibility or any required promised
backend remains unresolved, it blocks release and needs Aaron's explicit scope
decision or a reviewed fix, never an undocumented waiver. Mint fallback and
Ubuntu 26.04 Hyprland are recorded lab limits, not claims about other distros or
physical GPU/driver combinations. P4.6 still requires immediate supervised
authorization for the exact final build on the active desktop.
