# Linux v1 release checklist

The lean v1 gate from [Decision I](../work/phase-3-app-v1.md#decision-i-lean-v1-release-gate), 2026-10-07. It
replaces the earlier checklist (in git history before this change). Check an item only when its evidence is recorded
here. Publication needs Aaron's separate approval. The repository stays private unless Aaron approves a change.

## Scope: 1.0.0

- **App:** Cinnamon/X11, GNOME/Wayland, KDE/Wayland and Hyprland.
- **Computer use:** X11 only, at parity with Odin. Wayland computer use is planned for 1.1; until then the app
  refuses it there with guidance.
- **Packages:** x86-64 `.deb` and AppImage, unsigned, published as a GitHub release on the private repository.
- **PDF support:** downloaded on first use, pinned by hash ([Decision F](../work/phase-3-app-v1.md#decision-f-pdf-support-downloads-automatically-on-first-use)).

## Gate

- [ ] **CI green** on the release commit. Record the commit SHA and the run.
- [ ] **Acceptance list:** every R4/CC case in [`r4-acceptance.json`](../../maintenance/r4-acceptance.json) points to
  a passing test or a recorded check.
- [ ] **Dependencies:** no known critical or high vulnerability in shipped dependencies. Triage the locked npm findings
  (ten high, one critical at the 2026-10-07 watermark); record dev-only build tools as not shipped.
- [ ] **Candidate:** built by the release workflow. Record the source SHA and both packages' names, sizes and SHA-256
  hashes.
- [ ] **Smoke pass** of that candidate on the Cinnamon, GNOME, KDE and Hyprland lab VMs: install, first window, tray
  where present, Exit, logout, and upgrade from 0.1.0. Record one result per desktop.
- [ ] **Real use:** Aaron installs the exact candidate on his desktop and uses it for a day, including computer use.
  Record his OK.
- [ ] **Release notes** state the supported scope, the unsigned packages and the 1.1 items.

## Publication

- [ ] Aaron's separate approval to publish 1.0.0.
- [ ] Publish the same bytes the gate checked, then remove the lab VMs.

## Planned for 1.1

- Wayland computer use: ship the GNOME Shell extension, and build the KDE and Hyprland plugins for the installed
  versions.
- Harness follow-ups recorded on #97 and #98, and the lifecycle E2E time bound under load.
