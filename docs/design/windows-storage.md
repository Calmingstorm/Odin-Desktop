# Windows: the engine's private storage and durability contract

Owner: Claude, reviewed by Odin. Windows port phase 2a (2026-10-10). The phase plan and its review rounds are the
source; this page records what Windows does differently from Linux and why. Linux behaviour is unchanged.

## How Windows code is selected

- `current_platform()` returns the Windows platform on `win32`. Until phase 2b its app-to-engine transport and core
  lifetime refuse, so a Windows core never starts half-built.
- Storage functions that differ carry `@windows_variant("module:function")` (`src/desktop/platform/variants.py`). On
  every other system the decorator returns the original function, so Linux runs the same object with nothing imported.
  On Windows the call goes, with the same arguments, to the named variant in `src/desktop/platform/windows_*.py`.
- `maintenance/windows-variant-sources.json` pins each routed Linux original. If one changes, a test fails until its
  Windows variant has been reviewed against it.

## Private storage (`windows_files.py`)

- **Held chain.** A path must be on a local drive. It is resolved once (Windows' counterpart of Linux's `realpath`),
  then every folder from the volume root down is opened and held with list and traverse access and without delete
  sharing. While the chain is held no folder in it can be renamed, deleted or replaced, so a path under it names the
  held objects. Every open, create, replace, removal and SQLite connection happens under such a chain.
  - Missing folders are created beneath the held part with the private descriptor, then held themselves.
  - A junction or symlink met while holding is refused.
  - The innermost handle's final path must equal the resolved path.
- **Volumes.** Private state lives on local fixed NTFS volumes only. Network paths are refused before anything resolves
  them.
- **Who may have access.** Our folders and files may grant access to the user, OWNER RIGHTS, SYSTEM and Administrators.
  - A null DACL grants everyone and is never private. An empty DACL is private.
  - Deny entries and inherit-only entries grant nothing here.
  - Any other entry type, or a descriptor that can't be read, fails closed.
- **"Ours".** An object's owner must be the user or the owner this process gives new objects. They are the same for a
  normal user. An elevated administrator's new objects belong to the Administrators group (Linux: `st_uid` equals the
  effective uid).
- **Repair.** Inside `odin-desktop\<profile>` every folder is ours. When we own it and it isn't private, its DACL is
  replaced with `D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;OW)`, the descriptor Python's own
  `os.mkdir(path, 0o700)` applies. Linux tightens only the `odin-desktop` and profile folders, because a POSIX child
  is no more open than the private folder above it; a Windows child is checked against its own DACL. Folders above the
  namespace are only checked: their owner must be the user, SYSTEM, Administrators or TrustedInstaller.
- **Files** are opened without following a reparse point and verified through the handle: regular, link count 1 where
  Linux checks it, ours, and private. Ordinary files share read, write and delete, so a reader never blocks a replace.
  Lock files are held without delete sharing, so a locked file can't be swapped out.

## Publication and durability

**The recorded contract.**
- A Windows barrier flushes the object whose name changed, through a handle naming it.
- Microsoft documents that file-system metadata is cached and that a file must be flushed, or opened write-through, to
  store its metadata changes.
- This is a Windows platform delta, not a claim of equivalence with a POSIX folder fsync, and not a power-loss proof.
  The tests inject failures; they don't cut power. No administrator volume flush is used.

| Linux operation | Windows barrier |
|---|---|
| replace, then folder fsync | flush the temp file, rename it by its own handle over the target, flush that same handle |
| create a file, then folder fsync | flush the created file |
| create a SQLite database, then folder fsync | after the schema commits, flush the database and any `-wal`/`-journal` |
| unlink a marker, then folder fsync | retire it: rename it by its own handle to a tombstone, flush that handle (below) |

Every consumer keeps its Linux decision after the commit point. A failure before it leaves the old value and raises.

| Function | A failed barrier after the commit point |
|---|---|
| `write_private_atomic` | returns False (identity: durability degraded; cleanup: error; audit marker: repair required) |
| `sessions/manager._atomic_json` | `_PublishedButUnsyncedError`; the reset path keeps its epoch and fence |
| `agents/results.publish_result` | raises, as on Linux |
| `scheduler/history._record_interrupted_sync` | raises; the outbox stays |
| audit append and repair | quarantine; the fence is never cleared silently |
| conversation journal set-up | `JournalStorageError` |
| package state records | raises |
| config file, migration markers, ordinary history pruning | best effort, as on Linux |

## The audit repair marker

A deletion has no object left to flush, so Windows retires the marker instead:
1. Rename it by its own handle to `<log>.repair-required.retiring-<32 hex>`. This is the visible commit point.
2. Flush that handle.
3. Only on success, delete the tombstone (best effort).

- At start, the marker **or any matching tombstone** means repair is required.
- After the existing tail repair succeeds, settlement makes sure an active marker exists, retires it, and flushes every
  other matching tombstone. Only then are the tombstones deleted and the fence cleared.
- Any failure keeps every tombstone and the fence.
- There is no generic tombstone sweep, and nothing else matches the name pattern.

## Other members

- **Locks.** `LockFileEx` on one byte far past any data. Windows locks are mandatory, and this range never blocks the
  file's own data. A non-blocking miss raises `BlockingIOError`, as `flock` does.
- **Secrets.** One DPAPI-encrypted file per credential in `data\secrets\dpapi`. The secret store's namespace is both
  the file-name salt and DPAPI's entropy, so another profile's ciphertext never decrypts. Credential Manager is not
  used: it caps a secret at 2,560 bytes.
- **Workspace.** `windows_workspace.resolve_workspace` keeps Odin's contract. The pinned `src/tools/workspace.py` is
  untouched.
- **Boot identity.** The kernel's boot identifier GUID.
- **Time zones.** Windows has no system zone database, so the `tzdata` package is a Windows dependency. New Windows
  profiles start in UTC until the app supplies the system zone (phase 4).

## Not on Windows yet

- The app-to-engine pipe and core lifetime arrive in phase 2b.
- Commands, the shell, safety rules for PowerShell and cmd, processes, SSH (including saved hosts), MCP, skills,
  editing and PDFs arrive in phase 3.
- Saving generated images arrives with the media tools in phase 3.
- Odin's own onboarding store, environment editor and startup context have no caller in the Desktop engine and stay
  Linux-only.

## Evidence

- Native tests (`tests/windows/`) run on GitHub-hosted Windows Server 2025 in CI.
- They also ran on a Windows 11 device, both as an elevated administrator and as a standard user.
- Untested systems are not claimed as supported.
