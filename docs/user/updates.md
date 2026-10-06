# Updates, compatibility and rollback

**First draft for unreleased Linux candidates.** Main source watermark:
`0b7d596f7e870d06699722f151c4d9837c5433f1`, inspected 2026-10-06.
Pending behavior is labeled below and is not part of an authorized release.
Candidate tests and this guide do not grant install, publication or live-desktop
permission. Follow candidate procedures in an isolated desktop only.

## Where updates come from

The approved Linux v1 model is
[GitHub Releases for Calmingstorm/Odin-Desktop](https://github.com/Calmingstorm/Odin-Desktop/releases)
with x86-64 `.deb` and AppImage assets. The repo remains private. Use your own
browser GitHub session for access; do not give the app a GitHub token or copy one
from standalone Odin. An approved model is not evidence that a version or release
asset is already available.

The assets are **unsigned**. Ordinary hashes/provenance identify the candidate
bytes and help detect changes, but are not independent signature verification.
There is no custom feed, update manifest, signing-key enrollment or key-custody
procedure. `.deb` updates go through the package manager. AppImage updates are
user-managed replacements. There is no in-app download, staging, install or Apply
operation.

Source: [Aaron's approved decisions C/D](../work/phase-3-app-v1.md#decision-c-github-releases-and-manual-installation).

## Check for a new version

**pending: #39**

In **Settings > General > App version and updates**, the pending UI initially
says **Not checked**. Checking is **manual and opt-in**: select **Check for
updates** when you want an anonymous request to GitHub. There is no default
automatic/background poll and no persistent automatic-check switch in this
implementation.

| Result | Meaning and next action |
|---|---|
| A new version is available | A valid published stable version is newer. **Open release page in browser** opens the validated page; it does not download/install an asset. |
| Up to date | Only a successful comparison with accessible, valid stable-release metadata supports this message. It is not a security audit. |
| This app is newer than the latest published stable release | The candidate's product version sorts newer than the accessible stable release. It does not establish release approval. |
| No published stable release is available | No valid stable release was found in a successful response. This is explicitly not an up-to-date check. Drafts and prereleases do not count. |
| Can't check for updates | Private/denied access, offline, rate limiting, invalid/incomplete metadata or an invalid app version prevented a reliable comparison. Do not read this as up to date. |

While this repository is private, anonymous requests cannot read its releases;
the expected result is **Can't check for updates**, even if your browser can
access the repo. Your browser cookies and keyring credentials are not used by the
check. You may visit the fixed Releases page above yourself. Retry offline or
rate-limited checks later; checking/opening a link never stops or restarts work,
replays effects, clears quarantine or replaces an executable.

Sources pinned to the pending head:
[notice service](https://github.com/Calmingstorm/Odin-Desktop/blob/1c48529b0af3ad18d9c413882166cb6ee40702d1/app/src/main/release-notice.ts),
[actual UI/defaults](https://github.com/Calmingstorm/Odin-Desktop/blob/1c48529b0af3ad18d9c413882166cb6ee40702d1/app/src/renderer/src/components/ReleaseNotice.vue),
[publication limitations](https://github.com/Calmingstorm/Odin-Desktop/blob/1c48529b0af3ad18d9c413882166cb6ee40702d1/maintenance/phase4-releases.md).

## Before any replacement

Read the candidate/release notes and [installation limits](install.md). Keep the
current exact executable/package and its hash available, as well as a private
copy of important user-owned files. Do not take a live database copy while the
core is writing and call it a verified backup.

Choose **Exit Odin**, not window close, and wait for its outcome before replacing
files. A killed process or an absent PID is not proof of clean effect/native
resource cleanup. If there is unknown cleanup, quarantine, failed Exit or a
pending package transaction, stop and ask the reviewer to reconcile that exact
state. Never delete its evidence to make an update proceed.

Sources: [main lifecycle](../../app/src/main/lifecycle.ts),
[main shutdown evidence](../../app/src/main/shutdown.ts),
[upgrade requirements](../work/phase-3-app-v1.md#p42-ownership-alongside-isolation-migration-and-upgrades-phase-3-gate).

## Upgrade a guarded `.deb` candidate

**pending: #36**

1. Obtain the reviewer-approved replacement `.deb` as a local file and verify
   its identity/version/hash against that candidate's record.
2. Follow **Before any replacement** above. Exit every owned Desktop app/core
   using the installation and preserve clean shutdown evidence.
3. Open the replacement with the distribution package manager and upgrade/reinstall
   `odin-desktop`. Let the manager run ownership preflight and dependency checks.
   A busy lifetime, unresolved cleanup or incomplete transaction is a refusal,
   not permission to force the operation or kill unrelated services.
4. After successful package-manager completion, launch **Odin** normally. If
   compatibility or migration refuses startup, preserve the error/profile and
   follow the compatibility section below. Installation exit status alone does
   not prove successful profile migration or an operational app.

**Earlier P4.1 candidates are an exception:** direct P4.1-to-P4.2 upgrade is
deliberately refused because the old launcher lacks lifetime fencing. The
evidence records a separately externally fenced offline remove/install transition
in a disposable guest. That is not an ordinary desktop upgrade recipe. Stop and
ask the reviewer for a controlled isolated transition; do not copy its chmod
fault/acceptance steps onto a workstation.

Sources:
[pending package transactions](https://github.com/Calmingstorm/Odin-Desktop/blob/30402eb95154d9a4d3076fb5cae165771d4aee36/app/packaging/deb_transaction.py),
[legacy exception and acceptance boundaries](https://github.com/Calmingstorm/Odin-Desktop/blob/30402eb95154d9a4d3076fb5cae165771d4aee36/maintenance/phase4-packaging.md).

## Replace an AppImage yourself

**pending: #36**

Do not truncate/overwrite a running or mounted AppImage. The pending branch
supplies a **manually run, offline** `replace-appimage.py` helper beside
`ownership.py`. The app does not invoke it. It requires an ordinary user Python
interpreter for this separate helper, not for normal bundled app operation.
Until a release provides/distributes this helper as a user tool, get those exact
reviewed files from the candidate reviewer. Do not assume there is a replacement
button or that the helper is installed on your PATH.

1. Obtain the new local AppImage and its expected SHA-256 from the candidate
   record. Preserve the old file/hash. Exit the app/core cleanly as described above.
2. As the ordinary owner, run `replace-appimage.py` with Python, supplying its
   documented `--source` (new local file), `--destination` (existing AppImage's
   exact stable path) and `--sha256` (expected new-file digest). Use the reviewed
   helper beside its matching `ownership.py`; do not run it as root. Paths with
   spaces must be supplied as single quoted arguments. The helper documentation
   linked below is the authority for the invocation and refusals.
   Its invocation shape is shown below; replace every placeholder with the exact
   reviewer-supplied local path/digest before use in the isolated candidate desktop.
3. The helper copies to a new inode in the destination directory, checks identities
   and hashes, and atomically replaces the **same path**. It does not download,
   execute new bytes, stop the app or prove a complete bundle's origin. A refusal
   for non-owned/symlink/read-only/non-writable paths must not be bypassed.
4. If replacement is interrupted, do not launch around its transaction marker.
   The documented explicit rerun with the **same destination and hash** can
   recover an exact durable stage or confirm already-committed bytes. A partial
   stage without durable identity, changed destination or different transaction
   needs manual reviewer inspection, not arbitrary retries or marker deletion.
5. Only after confirmed completion, launch the stable AppImage path normally and
   inspect the startup/compatibility outcome. Same-path replacement keeps the
   login command. If you deliberately relocate the file instead, the old login
   command is detected as stale/disabled; explicitly enable **Start at login**
   for the new command. Relocation and autostart editing are not one atomic step.

This is cooperative user tooling, not a guarantee against an owner bypassing it
with shell writes. Old-inode tests and extracted candidates do not qualify actual
FUSE lifetime; that remains an isolated native gate.

```text
python3 "/path/to/replace-appimage.py" --source "/path/to/new.AppImage" --destination "/path/to/existing.AppImage" --sha256 "<expected-new-file-sha256>"
```

`ownership.py` must be beside the helper at the supplied path. This is a manual
local-file replacement command, not an app download/install command.

Sources:
[helper procedure and limitations](https://github.com/Calmingstorm/Odin-Desktop/blob/30402eb95154d9a4d3076fb5cae165771d4aee36/app/packaging/APPIMAGE-REPLACEMENT.md),
[helper implementation/arguments](https://github.com/Calmingstorm/Odin-Desktop/blob/30402eb95154d9a4d3076fb5cae165771d4aee36/app/packaging/replace-appimage.py),
[stable autostart command](https://github.com/Calmingstorm/Odin-Desktop/blob/30402eb95154d9a4d3076fb5cae165771d4aee36/app/src/main/autostart.ts).

## Compatibility, failed migrations and safe rollback boundaries

**pending: #36**

Product version, protocol, storage, turn/checkpoint format and computer quarantine
format are separate compatibility facts. The pending code inspects existing
state before writable attachment/boot sweeps, including SQLite WAL data. Newer,
foreign, corrupt or incompatible state refuses startup **without treating it as
a fresh empty profile**.

A private hash-manifested backup is durably published before existing migration
owners run. Default location:
`~/.local/share/odin-desktop/default/package-backups/<backup-id>/` (or the
profile's custom data root). `package-state.json` records `pending` or `committed`.
This backup covers config/data with deliberate exclusions: locks, IPC token,
logs, previous package backups and the package-state record itself. It does not
back up the system keyring, external workspace files or undo external effects.
It is **not** a full-system restore point or an automatic rollback service.

If startup fails or you need an older version:

1. Stop attempted work and retain the current executable, complete current profile,
   cleanup/quarantine evidence and candidate identities. If a core is running,
   use normal Exit. Do not force an unresolved cleanup into a clean state.
2. Record the error and whether the package manager finished. For a pending
   migration, use only its exact compatible candidate under reviewer guidance;
   another candidate/version cannot claim that transaction. Compatible retries
   run idempotent migration owners, never replay external work.
3. Ask the reviewer to validate the intended older candidate against a **private,
   isolated copy** of the complete current state before authorizing a downgrade.
   The older candidate must itself have the compatibility/ownership checks.
   A package-manager downgrade or an old file at the same path does not convert
   upgraded storage back to its old format.
4. If that candidate refuses newer storage/checkpoints, stop. Keep/reinstall the
   compatible candidate through its normal external replacement path after clean
   shutdown, or obtain a separately reviewed recovery plan. Do not delete
   `package-state.json`, locks, unknown receipts or quarantine to make old code run.
5. Do **not** blindly restore a pre-upgrade backup over the current profile. It
   can discard evidence of effects since the backup and allow unsafe replay.
   The implementation has no automatic backup-restore command or state rollback;
   no user restore recipe is qualified here. Owner-assisted restoration requires
   explicit reconciliation of the current fences/effects and a separately
   validated procedure. If it cannot be done safely, retain the compatible
   version/state rather than promise rollback.

Ordinary-user compatibility refusal and backup tests are recorded, but they are
not qualification of every older executable. Keep unknown effects and native
quarantine intact across any package repair.

Sources:
[actual compatibility/backup code](https://github.com/Calmingstorm/Odin-Desktop/blob/30402eb95154d9a4d3076fb5cae165771d4aee36/src/desktop/package_state.py),
[behavior cases, including simulated older-reader refusal](https://github.com/Calmingstorm/Odin-Desktop/blob/30402eb95154d9a4d3076fb5cae165771d4aee36/tests/test_desktop_package_state.py),
[candidate acceptance and open gates](https://github.com/Calmingstorm/Odin-Desktop/blob/30402eb95154d9a4d3076fb5cae165771d4aee36/maintenance/phase4-packaging.md).

## Dependency and security maintenance

Desktop maintains a pinned copy of selected Odin source, not a dependency on your
standalone install. Updating standalone Odin does not update Desktop, and changing
the bundle with pip/npm is not a supported user update path. Electron Chromium
and the separate tool Chromium are separate maintenance obligations. Pinned
dependencies, model/helper assets, hashes and legal notices need review before
distribution; pinning is not evidence that all security findings are resolved.

The maintenance policy requires weekly upstream review during active support,
immediate triage of critical safety/security fixes, and a pinned reviewed upstream
watermark for each release. **Those are maintainer obligations, not a guarantee
that every review has happened.** The current recorded watermark is only Odin
`v4.13.0` at `cd7530906e9cfa10a0fa900247d7ce2a8bb33e25`. Candidate evidence reports
11 locked npm audit findings (ten high, one critical); maintainer/reviewer triage
on the exact release candidate is a release-gate blocker. This draft does not
resolve or waive them, and a blind `npm audit fix` is not a qualified update.
Release notes must identify reviewed fixes and outstanding limits,
not infer identical-engine parity from a passing aggregate test count.

Sources: [recorded baseline](../../maintenance/baseline.md),
[maintenance policy](../design/maintenance.md#cadence),
[locked-graph findings](../../maintenance/p41-packaging.md),
[resource pins and legal boundaries](../../app/packaging/README.md).
