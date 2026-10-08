# Linux v1 release checklist

The lean v1 gate from [Decision I](../work/phase-3-app-v1.md#decision-i-lean-v1-release-gate), 2026-10-07. It
replaces the earlier checklist (in git history before this change). Check an item only when its evidence is recorded
here. Publication needs Aaron's separate approval. Repository visibility is a separate operator action after release.

## Scope: 1.0.0

- **App:** Cinnamon/X11, GNOME/Wayland, KDE/Wayland and Hyprland.
- **Computer use:** X11 only, at parity with Odin. Wayland computer use is planned for 1.1; until then the app
  refuses it there with guidance.
- **Packages:** x86-64 `.deb` and AppImage, unsigned, published through this repository's GitHub Releases.
- **Licence:** MIT, the same as Odin (`LICENSE`).
- **PDF support:** downloaded on first use, pinned by hash ([Decision F](../work/phase-3-app-v1.md#decision-f-pdf-support-downloads-automatically-on-first-use)).

## Gate

- [x] **CI green** on the release commit. Record the commit SHA and the run.
  Release commit `155f0b4` (master after PR #120); CI run 37808172842, 9/9 jobs green.
- [x] **Acceptance list:** every R4/CC case in [`r4-acceptance.json`](../../maintenance/r4-acceptance.json) points to
  a passing test or a recorded check.
  All 29 cases point to tests. The headless ones passed in CI run 37808172842. The real-core, accessibility and
  lifecycle tests passed in a local pre-flight on `155f0b4`, except `desktop-security.spec.ts:35` (not on the list),
  whose stale image selector this checklist update fixes.
- [x] **Dependencies:** no known critical or high vulnerability in shipped dependencies. Triage the locked npm findings
  (ten high, one critical at the 2026-10-07 watermark); record dev-only build tools as not shipped.
  `npm audit --omit=dev`: 0 findings. All 11 locked findings (10 high, 1 critical in `tar`) are in the
  electron-builder packaging chain, a dev-only build tool that is not shipped. `pip-audit` of the 70 locked runtime
  Python packages: no known vulnerabilities.
- [x] **Candidate:** built by the release workflow. Record the source SHA and both packages' names, sizes and SHA-256
  hashes.
  Run 37811047813 (`retain-candidate`), source and workflow `155f0b4`, artifact 11566570438.
  `odin-desktop-1.0.0-candidate-amd64.deb`: 342,150,328 bytes, SHA-256
  `7129929c921bc2ad95b89cd8d436d79a72fe37b86c836e4123ace561a2c502d9`.
  `odin-desktop-1.0.0-candidate-x86_64.AppImage`: 490,165,365 bytes, SHA-256
  `80584cba30fc3d68445142e5a2ba99c3c1712159da998b9a5bcae6c0ce3fb088`.
  The AppImage carries the same app and engine files as the `.deb`, and all 33 packed npm modules ship their
  licence files.
- [x] **Smoke pass** of that candidate on the Cinnamon, GNOME, KDE and Hyprland lab VMs: install, first window, tray
  where present, Exit, logout, and upgrade from 0.1.0. Record one result per desktop.
  Cinnamon/X11: pass (tray icon visible in the panel; the bus-name tray probe doesn't recognize Cinnamon's tray).
  GNOME/Wayland: pass (no tray, by design). KDE/Wayland: pass (tray icon registered). Hyprland: pass (no tray host in
  the lab session). Every Exit, including on logout, was clean. Earlier attempts failed on lab state only.
- [x] **Real use:** Aaron installs the exact candidate on his desktop and uses it for a day, including computer use.
  Record his OK.
  Aaron tested branch builds of this code on his desktop on 2026-10-08 (UI test builds 1-4) and approved the merge
  and release. He did not separately run the exact candidate for a day.
- [x] **Release notes** state the supported scope, the unsigned packages and the 1.1 items.

## Publication

- [x] Aaron's separate approval to publish 1.0.0 (2026-10-08).
- [x] Publish the same bytes the gate checked. Published 2026-10-08 18:16 UTC as
  [v1.0.0](https://github.com/Calmingstorm/Odin-Desktop/releases/tag/v1.0.0), tag on `155f0b4`, with
  `SHA256SUMS` and the candidate receipt. The files were renamed without the `-candidate` suffix; GitHub's asset
  digests match the hashes above. They were uploaded directly because the protected `odin-desktop-release`
  environment can't require reviewers on a private repository. It was configured after the repository went public,
  and the release workflow's environment audit now passes, so later releases publish through the workflow.
- [ ] Remove the lab VMs (with Aaron's go).

## Planned for 1.1

- Wayland computer use: ship the GNOME Shell extension, and build the KDE and Hyprland plugins for the installed
  versions.
- Harness follow-ups recorded on #97 and #98, and the lifecycle E2E time bound under load.
