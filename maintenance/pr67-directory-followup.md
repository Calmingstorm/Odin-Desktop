# PR67 directory normalization follow-up

Source-only follow-up from `fbce112b4e9809b1b11ea0d77b58c5dbdb4075dc`,
in `/home/odin/desktop-pr67-directory-req9133`. No VM, live chmod, candidate
repair, full candidate build, native retry, merge or deployment was performed.

## Evidence and correction to the diagnosis

The parent reported one native KDE install of qualified deb
`62529a3f86f40e558b7126f09c2602ace16f8a94f561bbd1623867bdab0e08a9`.
Postinst refused `AppArmor source directory is not immutable`; guest diagnostics
showed root-owned `/opt` 0755, `/opt/Odin` and resources 0775, profile 0644.

Direct inspection of that retained deb (SHA reverified) shows the archive itself
contains **root:root 0755** `/opt`, `/opt/Odin`, and `/opt/Odin/resources`.
Consequently the guest's 0775 does not establish malformed archived directory
modes. Dpkg can retain modes on existing directories. A disposable stale-0777
fixture reproduces the same refusal without bypass, chmod repair, or parser use.
The precise history of the existing native directories was not investigated by
this source-only task. The parent's half-configured guest remains untouched.

The old hook nevertheless has a real construction defect under umask 0002:
it normalizes resource children, not the unpacked app or resources roots, and
does not normalize top-level Electron directories. This follow-up normalizes the
whole directory tree (including both roots) **before sealing**, canonicalizes
resource files as before, preserves internal directory/file symlinks and does
not follow a linked external tree. Linked app/resources roots are refused before
any write or chmod. Fpm ownership is explicitly root/root.

## What qualification actually covered

The retained generated postinst calls `apparmor_profile` unconditionally. The
earlier real-dpkg log reaches `Setting up odin-desktop`; lack of parser tools
does **not** skip source-directory checks or profile/ownership-receipt creation.
It skips only kernel parsing/loading. Core/private-Xvfb GUI passes therefore do
not establish AppArmor attachment or native installation on a stale root.

The qualifier now audits root-owned 0755 directories and matching installed
profile/receipt **before export/chown**. It does not precreate or chmod installed
application directories. The generic distro-hook fixture now uses generated
production hooks rather than a trivial shell postinst, and actual root ownership
in the deb. A fresh root-only fixture feeds real afterPack output from hostile
umask 0002 into dpkg, proves postinst acceptance/profile/receipt, then separately
proves a stale 0777 root fails and is not exported. Production guards are unchanged.

## Verification

- Packaging suite: **123 tests, 100 passed, 23 explicit skips**, no failures.
  Pinned builder FPM_BINARY was supplied. Tiny fixture deb/SquashFS packages only,
  not rebuilt release candidates.
- Real-root PID-isolated generated-hook/install prerequisite suite: **8 passed**.
- Real-root PID-isolated transaction suite: **22 passed**, including 0775/0777
  refusal, parser/fence behavior, and symlink guards.
- Inventory report: **zero errors**. All source changes are `app/` scope;
  inventory.record does not accept these paths and no authority was broadened.
- `git diff --check`: passed. Root disk: 119 GB free.

Raw logs and artifact hashes: external
`/mnt/storage/odin-desktop-evidence/pr59-packaging-direction-req9133/directory-followup/`,
listed in [the manifest](pr67-directory-artifacts.json).

The old qualified candidate is **not cleared for another native install** and
does not contain this source fix. A new authorized build and qualification are
required before the next authorized native attempt. Rebuilding alone cannot
repair pre-existing writable install directories; any offline transition or
repair requires separate explicit authorization. No retry is authorized here.

Publication check: GitHub reports PR67 merged at `2026-10-06T11:33:36Z`; its
remote source branch no longer exists. The original parent worktree still points
to fbce112b. This follow-up must not recreate the deleted branch under the
conditional unchanged-source-head push instruction. Local commit is retained for
the parent to choose an authorized follow-up branch/PR; no push or main update.
