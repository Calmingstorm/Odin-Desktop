# User-managed AppImage replacement

This manual offline helper exists because truncating a mounted AppImage can
damage its old read-only lifetime. The app never invokes it. It does not
download, install, execute new bytes, stop work or signal processes. First
choose **Exit Odin**, not window close. The shared stable per-user lifetime
lease lives outside the mount and is retained by a surviving core. Free leases
or absent PIDs are not cleanup receipts. Shared preflight requires clean app/core
Exit evidence and never acknowledges unknown cleanup or clears native quarantine.

Run `replace-appimage.py` beside the standalone `ownership.py` using an ordinary
owner Python interpreter, supplying explicit local `--source`, existing
`--destination` and `--sha256`. Never run it as root. This user-supplied hash
checks integrity, not origin/signature. Header checking is not full candidate
bundle validation. Parent-owned candidate inventory qualification is separate.

The helper intentionally replaces the **same destination path**. It copies
bytes to a private new inode in that directory, fsyncs, checks the old identity
and bytes, then atomically renames. It never truncates the old inode. Nonwritable
destinations/read-only mounts, symlink files and non-owner files refuse. This is
cooperative fencing, not protection from an owner ignoring it with shell writes.

`appimage-replacement.json` durably records an interrupted transaction in the
ownership directory. The launcher must fence admission while it exists. An
explicit rerun with the same destination/hash recovers the exact durable stage
identity or confirms the already-committed hash. A partial stage lacking durable
identity, changed destination or different transaction requires manual inspection.
No receipt, profile, native fence or unrelated pending file is erased.

Same-path replacement preserves the autostart command. For manual relocation,
the app detects a launcher for the old command as stale and reports start at
login disabled for the current command. Explicit enabling writes the new
command, never a transient FUSE mount executable. Relocation and autostart
editing are deliberately not claimed as one atomic cross-file transaction.

## Evidence boundary

Behavior tests use ordinary users inside PID/mount/network namespaces with
disposable state, no desktop or bus and harmless storage/permission failures.
Synthetic AppImage-shaped files are never executed. An open read-only file proves
old-inode preservation, not FUSE lifetime or native cleanup. Actual extracted
candidate execution remains separate. Actual FUSE-mounted AppImage lifetime,
restricted/oldest Ubuntu sandbox behavior, native lifecycle and login acceptance
remain open until the exact candidate is tested in the approved isolated lab.
