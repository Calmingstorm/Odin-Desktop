# Windows install safety (phase 5)

How the Windows installer and uninstaller (electron-builder NSIS, one-click, per user) protect a running Odin and an
unfinished installation, and what they don't cover. The scope is Aaron's decision (2026-10-11): the minimal design,
with the limits below accepted for the first Windows release.

## What they guarantee

- **They never end Odin.** electron-builder's own check ends a running `Odin.exe` with `taskkill`; Odin's
  `customCheckAppRunning` replaces it, in the installer and the uninstaller alike. A running Odin, or anything that
  can't be checked, means a refusal (exit 2) with nothing changed.
- **They take the app's lease.** The installer opens `%LOCALAPPDATA%\odin-desktop\install-ownership\nsis\lease` and
  takes the guardian's lock on it exclusively, without waiting.
  - **Refusals:**
    - if the app or its core holds the lock: "Odin is running";
    - if the lease isn't an ordinary file of its own (a reparse point, or more than one link);
    - if its folders, created private when missing, can't be prepared.
  - **The handle** is held until the installer exits.
- **They refuse while anything runs from the installation.** A process whose image is under the install folder is
  enough, even without the lease (an app started before it existed), and even when `Odin.exe` itself is gone from a
  damaged installation. The check runs the native 64-bit PowerShell, with paths passed through the environment, and
  excludes only the uninstaller's own image. A check that can't run refuses.
- **They respect this boot's lifetimes.** With an installed tree, that tree's guardian judges the receipts read-only
  (`ownership.py receipts --kind nsis`).
  - A lifetime from this boot without confirmed cleanup refuses ("Restart the computer"). An earlier boot's no
    longer fences, by its well-formed boot identity.
  - Anything a restart won't change refuses with "couldn't confirm" instead: a record that can't be read, a
    record bound to no well-formed boot (a lifetime admitted while the boot identity couldn't be read), or no
    readable boot identity now. The guardian's exit says which (3 or 2); its own failure exits 1 and reads as
    "couldn't confirm", never as restart advice. It judges every record, whatever goes wrong with one, so a
    lasting refusal always wins over restart advice, whatever order the folder lists them in.
  - An interrupted write's leftover temporary in the receipts folder isn't a record and is skipped. It never got
    renamed into place: an interrupted start admitted nothing, and an interrupted end left the record it was
    replacing, which still counts. No writer can be mid-write then, since the installer holds the lease.
  - Results are compared as text, so a guardian that doesn't start refuses too.
- **An unfinished run fences Odin.** `transaction.json` is written before anything changes. While it exists, the
  app's guardian refuses every start ("An Odin installation didn't finish. Run the Odin installer again.", exit 75 on
  Windows only). The installer removes it only when all of these hold:
  - this run holds the lease: taken at its start, held until it exits, and never shared for deletion, so the lease
    file can't be deleted or renamed meanwhile;
  - `Odin.exe`, the uninstaller and the sealed bundle's manifest are in place.

  The marker records the lease's file identity, the operation and the target version, for diagnosis. Nothing
  reads them: the marker's presence is the fence.

  A run that ends with the marker still there, because it couldn't be removed or the app's files aren't all in
  place, fails (exit 2, "Run the installer again") instead of reporting success, since Odin wouldn't start.

  An uninstall leaves its marker: with no tree nothing can start, and the next install takes it over.
- **Upgrades:** electron-builder runs the old uninstaller with `--updated`. When it finds the installer's marker, it
  leaves the fence to the installer, which holds the lease, and removes the old files.
- **The profile, lease and receipts survive uninstall,** as on Linux.

## Accepted limits

These were raised in the reviews of the phase 5 design and left out by decision. They are candidates for a later
release.

- **A missing or damaged installation skips the receipts check.** Its guardian is the only reader the installer has.
  So a crash that left a this-boot lifetime unconfirmed, followed by a deleted or broken tree, installs without
  waiting for a restart.
- **The upgrade fence is inferred, not proven.** An old uninstaller run by hand with `--updated` while a stale marker
  exists skips its own checks. Running uninstallers by hand with internal flags is unsupported.
- **Two installers at once.** The lease serializes them once each holds it. What happens before, and a second
  installer taking over a dead one's marker while the first's files are still being written, isn't qualified.
- **Power loss.** The marker is written and removed with ordinary file operations. A sudden power cut can leave a
  state the next run must repair. Nothing is fenced less than after a process kill, but no stronger guarantee is
  made.
- **Completion is checked by presence, not content.** The final check confirms that the app, uninstaller and manifest
  exist. It doesn't re-verify every file, and stock steps that clear their own errors (shortcuts) aren't
  re-checked.
- **Same-user redirection.** The lease file is checked by handle, but its folders, the install folder's ancestors and
  `Programs` aren't validated as non-redirected. Same-user code is outside the boundary, as everywhere else in Odin
  Desktop.
- **A damaged lifetime record** refuses every install ("couldn't confirm") until it's removed by hand. Records
  are written atomically, so only disk damage or editing produces one.
- **A process the check can't read** (its image path unavailable) is treated as not from the installation.
- **The writability probe** (`customInit`) runs before the lease is taken, so a refusal after it may leave an empty
  install folder.

## Tests

`scripts/packaging/windows-installer-acceptance.ps1` (hosted CI, and the Legion as a standard user):
- an install over the running app, and an uninstall while it runs, are refused and end nothing;
- the same for a bundled process running without the lease;
- an unfinished run fences the start, and a rerun completes;
- this boot's unconfirmed receipt refuses, and an earlier boot's passes;
- an interrupted write's leftover passes, and a damaged receipt refuses;
- a linked lease is refused;
- with `Odin.exe` gone, a process still running from the installation refuses the install;
- a marker the installer can't remove fails the install, and the next run clears it;
- an in-place uninstall doesn't count itself.

The upgrade from one version to the next runs on the Legion with two builds of the same tree.
