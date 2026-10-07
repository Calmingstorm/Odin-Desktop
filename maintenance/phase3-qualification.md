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

## Decisions and remaining work

No extra owner approval/governor/allow-list or model instruction is introduced.
No Aaron decision is needed to keep building/running interim evidence under the
approved lab rules. If KDE native dialog accessibility or any required promised
backend remains unresolved, it blocks release and needs Aaron's explicit scope
decision or a reviewed fix, never an undocumented waiver. Mint fallback and
Ubuntu 26.04 Hyprland are recorded lab limits, not claims about other distros or
physical GPU/driver combinations. P4.6 still requires immediate supervised
authorization for the exact final build on the active desktop.
