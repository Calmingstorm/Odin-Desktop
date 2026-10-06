# PR59 direction item 4: package construction and install prerequisites

Base: freshly fetched `origin/main` `efc5e20c76e5d43ddea466c844ada46456b9d663`.
Own workspace: `/home/odin/desktop-pr59-packaging-req9133`.
Evidence root: `/mnt/storage/odin-desktop-evidence/pr59-packaging-direction-req9133/`.
No edits to the parent direction worktree, existing lane7 evidence, live services,
active desktop, or VMs. This is construction/isolated package qualification, not
native desktop acceptance or authorization to release.

## Exact original artifact diagnosis

Original source provenance was `cd52a8e2b055a9c4abc051a49566b9daf3e1bd79`,
not current main. Original `.deb` SHA-256:
`b43517d5b224501ca275f7bfa963673743a4e568c23fdfe38d22e0b8675b44d2`.
Original AppImage SHA-256:
`3205d674fd7f3b0aabdb038e9df5331ef7138d0738c1e1da929eac1c1217ecbc`.
The identical embedded manifest SHA-256 was
`f6035aecad061f396939bbd26f2b7e42d296f6b3cd9a3bde84bdd2e08cab8d33`.

1. **Debian AppArmor failure is permissions, not changed profile bytes.**
   The sealed manifest expects `0644`, 397 bytes, digest
   `926869e30a92bab182cf6db4c6ff953a47df49a36d355977920d00207243567b`.
   Original unpacked resources after packaging and the actual Debian data archive
   contain `0664`, with exactly those bytes/digest. Pinned electron-builder
   `app-builder-lib/out/targets/FpmTarget.js` copies its templated AppArmor file
   into resources **after afterPack seals the manifest**. The source profile is
   unchanged; collaborative build permissions cause the late copy's mode drift.
   Existing unprivileged diagnostic extraction masked that drift to `0644`, so
   that extraction alone was insufficient. A new root extraction reproduces
   precisely `Bundle inventory/digest mismatch: apparmor-profile`.

2. **AppImage ASAR failure is extraction permission drift, not ASAR byte drift.**
   The sealed ASAR is `0664`, 27,197,133 bytes, digest
   `b61f46b279cf3bdcc3cfcffc896a4887a470250e734743ab0befd5323a0f032d`.
   `unsquashfs -ll -offset 188392` confirms the original image stores `0664`.
   Existing unprivileged extracted evidence is `0644`, same size and SHA-256.
   Runtime/legal inputs had been normalized, but builder-created ASAR and
   ownership files were not. No evidence supports non-reproducible ASAR content
   or a stale content digest. This diagnosis does not assert cross-host installer
   reproducibility.

3. **Python install failure is a qualifier root-toolset omission.**
   Original `package-qualification.log` shows dpkg reaches preinst and exits 127:
   `/usr/bin/python3: not found`. The tiny disposable dpkg root only copied shell
   tools, while the generated hooks execute that absolute system interpreter.
   Additionally `python3-minimal` omits `json` on a genuinely minimal Debian
   installation, so production Pre-Depends must be `python3`. Root-hook process
   scanning also needs the same private PID namespace's `/proc` inside the chroot,
   not the workstation's `/proc`.

## Fix boundaries

- Canonicalize resource file permissions (`0644` or executable `0755`) and
  directories (`0755`) **before sealing**; preserve symlinks. Explicit build
  umask `022` makes the late fpm AppArmor copy agree. Do not rewrite candidate
  manifests or loosen mode/content verification.
- Stage a matching trusted distro Python ELF/stdlib closure only for disposable
  maintainer hooks, check required imports before dpkg, and remove install-only
  Python before exporting the candidate root. Host Python remains masked for
  runtime probes. Use private `/dev` and `/proc` for the dpkg chroot.
- Generated-hook behavioral regression tests exercise real disposable dpkg;
  sealed-mode tests exercise the real afterPack hook and both Debian/SquashFS
  round trips, plus post-seal mode and byte tamper rejection.

## Inventory and review

`inventory.py record` deliberately accepts engine/test/asset/script scope but
rejects `app/` paths. All production changes here are in `app/`, so there is no
applicable engine delta to fabricate or recapture. Run the report and retain its
zero-error result. New tests use production behavior, not Markdown assertions.
Independent review is required; author's model self-review is not approval.

## Final measurements

- Packaging suite: 120 tests, 98 passed, 22 explicit root-only fixture skips in the
  unprivileged PID-isolated run. Real generated-hook dpkg prerequisite row passed.
- Inventory report: zero errors. The attempted app-path `record` fails explicitly
  outside the tool's scope; no metadata authority was broadened to hide this.
- One fresh full candidate build from committed source
  `d57b76cbe60877be13f71cc787c265793db6d76f` succeeded. Only immutable pinned cache
  input copies were reused; existing cache and evidence were not modified.
- Full `--install --gui --user hyprlab` package qualification: **PASS, zero
  errors**. Debian extracted, AppImage extracted, and real disposable-dpkg
  installed-root each pass manifest, payload scan, real core and private-Xvfb GUI.
  All share resource manifest digest
  `d3741949d974292a745b523ad6d8a15ca9e18929b4f83b19c560c366cf0534a7`.
- System Python masked during all candidate runtime probes, isolated network,
  real first-start SSH key, sandboxed renderer, clean app/core receipts, offline
  browser/embedding and pinned separate-fixture PDF installation all pass.
- [Artifact manifest](pr59-packaging-artifacts.json) contains paths and SHA-256s.
  Candidates live in the external evidence root's `candidates/` directory.
- 119 GB remained free on `/` after qualification. Own worktree retained pending
  the parent's cleanup decision.

Qualification uses `dpkg --force-depends`, not clean-distro dependency resolution;
Xvfb is not native graphics/session acceptance; AppImage extraction is not FUSE.
No native input was attempted. Native rows remain OPEN until the parent measures
them on these qualified candidates in the authorized guest lane. Evidence-only
follow-up commits do not change the candidate source commit.
