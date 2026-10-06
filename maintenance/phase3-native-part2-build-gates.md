# Lane7 native Part2: fresh build and gates, 2026-10-06

## Disposition

**Partial native evidence, not P3.3 closure or package qualification.** Parent
native matrix and VM cleanup are recorded in `phase3-native-part2.md`. This
document records the independent build child, which owned no VM, never invoked
Incus, changed no host service, and did not touch `/opt/odin` or the active desktop.

Build source was exact merged main
`cd52a8e2b055a9c4abc051a49566b9daf3e1bd79`, detached in its own checkout under
`/mnt/storage/odin-desktop-evidence/lane7-p33-native-20261006/build-checkout`.
No unmerged PR54 code was used. Initial free space was 120GB on `/` and 135GB
on storage; later checks remained above the required 60GB. Project-local locked
Python/dev and npm dependencies only were installed. Shared packaging cache was
reflink-copied to a child-owned cache, never modified in place.

## Candidate identities

Both files reside under that build checkout's `.packaging-candidates/`:

| File | Bytes | SHA-256 |
|---|---:|---|
| `odin-desktop-0.1.0-candidate-amd64.deb` | 341819480 | `b43517d5b224501ca275f7bfa963673743a4e568c23fdfe38d22e0b8675b44d2` |
| `odin-desktop-0.1.0-candidate-x86_64.AppImage` | 489718435 | `3205d674fd7f3b0aabdb038e9df5331ef7138d0738c1e1da929eac1c1217ecbc` |

Builder-sealed resource manifest: 8,492 files/links, 975,874,441 bytes,
SHA-256 `f6035aecad061f396939bbd26f2b7e42d296f6b3cd9a3bde84bdd2e08cab8d33`.
This is build identity, not successful extracted-manifest verification.

## Fresh observed gates

- `npm ci --ignore-scripts`, pinned Electron provisioning, `npm run check`,
  documented `npm run package:candidate`: exit 0; 78 app test files / 747 cases,
  typecheck and production build pass. Locked npm audit reports 10 high and one
  critical vulnerability; no dependency upgrade or audit fix was attempted.
- Isolated real-core contract: 22 passed. Isolated onboarding: six passed.
- Isolated source lifecycle E2E: 29 passed. Fixture smoke and real-core smoke
  pass, the latter observing 40 screens. These use private Xvfb/DBus and PID
  isolation, not a workstation graphical session.
- Focused packaging/core/ownership/accounting selection: 347 passed, one skipped
  because exact previous candidate resources were not supplied; one subprocess
  destructor warning. No skipped upgrade proof is counted as passed.
- Packaging behavior: 91 cases, 79 pass and 12 explicit prerequisite skips.
  Eleven skipped root transaction cases plus the hook case separately ran in a
  sudo-created root PID/mount namespace: 12 pass. The initial nonprivileged
  unshare was denied before any test started, retained separately. Read-only
  mounted replacement remains skipped.
- Build-source drift: zero errors, review pending. Lint: zero new findings,
  seven inherited. Ownership-plan checker passes. Parent-final exact ledger
  byte-drift report also passes with four newly recorded native helper files.
- Parent native-helper final scrubbed-namespace guard run: ten passed, recorded
  separately from its erroneous initial environment run with ten setup errors.
- Final parent engine lint classification with the build checkout's locked Ruff
  passes (zero new/seven inherited). Separate broad lint of the new native helper
  files reports 20 import-order/line-length findings; not fixed or concealed.

## Failed gates retained, no rerun or waiver

The complete candidate qualifier fails before executing lanes: its disposable
dpkg root copies shell tools but omits `/usr/bin/python3`, required by the
current P4.2 preinst/postrm hooks. Both fail with exit 127. This is a harness
prerequisite defect; it is not clean-distro dependency resolution or successful
installation evidence.

A separate first extracted-only lane passes both bounded package/ASAR scans,
including zero distributed PyMuPDF/MuPDF files, but fails sealed manifests:

- `.deb`: `apparmor-profile` is archived with mode 0664, manifest records 0644.
- AppImage: `app.asar` normalizes to 0644, manifest records 0664.

Content SHA-256 values match. Read-only diagnostics confirm the build user's
umask is 0002 and the builder rewrites the profile after sealing. Neither
manifest nor candidate was edited to manufacture a pass. Extracted core/GUI
attempts did not start because the non-sudo controller lacked chown authority.

A different **unpacked first-execution behavior-only** proof, run through sudo
and the existing bwrap controller as nonroot `hyprlab`, passes real packaged
core, fresh profile/ed25519 key/workspace, shutdown, offline sandboxed Chromium,
384-dimensional local model, pinned PDF first-use fixture, helper usage refusal
without input, and sandbox-intact GUI normal Exit with clean lifetime receipts.
It is explicitly partial and does not retry or waive failed package gates.

The 31-group full classified corpus was started once in verified nonroot PID
namespaces. Groups 1-12 completed; group 8 has 43 failures, group 9 has 40 failures
and five errors, including unchanged ownership guards rejecting the foreign
`/mnt/storage` ancestor. Group 13 was entered but no result was captured before
the local command supervisor lost ownership. No live child remained when
checked. The full gate is **unfinished with observed failures**, not a pass.
No retry, guard relaxation, test assertion modification or manufactured result.

## Evidence

Raw logs, screenshots, qualification JSON, integrity comparison and full-corpus
XML/logs remain outside Git in the lane evidence root. The compact build artifact
manifest pointer is `phase3-native-part2-build-artifacts.json`; parent native artifacts
remain separately inventoried. No raw artifact over 100KB was added to Git.
These candidates remain local and unreleased. No tag, release, upload or merge.
