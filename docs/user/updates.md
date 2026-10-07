# Updates, compatibility and rollback

## Find a version

Use [Odin Desktop Releases](https://github.com/Calmingstorm/Odin-Desktop/releases)
for `.deb` and AppImage files. If the repository is private, use your own browser
login. Do not give the app a GitHub token or copy credentials from another Odin
installation. If the page has no published files, there is no release to download.

Read release notes and check the file's SHA-256 as described in
[Install](install.md#download-and-check-the-file). Release files are **unsigned**:
a matching hash identifies bytes, not an independent signature.

There is **no in-app update download or apply operation**. Use the package manager
for `.deb` upgrades and manual replacement for AppImage. Updating standalone Odin
does not update Desktop. Changing the bundled runtime with pip or npm is not a
supported user update method.

## Check for a release notice

Open **Settings → General → App version and updates**. It starts at **Not
checked**. Select **Check for updates** to make an anonymous GitHub request;
there is no automatic background check.

| Result | What to do |
|---|---|
| A new version is available | **Open release page in browser**, then check the files and follow the replacement steps below. Opening the page does not install anything. |
| Up to date | A successful comparison found no newer published stable version. This is not a security audit. |
| This app is newer than the latest published stable release | Your app version sorts newer; that is not release approval. |
| No published stable release is available | No valid stable release was found. Drafts and prereleases do not count; this is not an up-to-date result. |
| Can't check for updates | Access, connectivity, rate limiting or invalid/incomplete metadata prevented a reliable comparison. |

While the repository is private, **Can't check for updates** is expected even
when your browser can view it. The check does not use browser cookies or keyring
credentials. Use the Releases page in your own browser instead. Do not supply a
GitHub token. Checking or opening a page does not restart work, replay effects,
clear quarantine, download a package or replace an executable.

## Before replacing anything

1. Keep the current exact package/executable and its digest, plus private copies
   of important files you saved elsewhere. A database copied while the app writes
   is not a verified backup.
2. Choose **Exit Odin**, not window Close, and wait for shutdown.
3. If cleanup is unknown or Exit failed, restart the computer before trying a
   package change. Odin refuses changes while the app or its core runs, and an
   unclean lifetime fences changes for the rest of that boot. The `.deb` refusal
   says **Restart the computer, then try again**. The manual AppImage helper may
   instead report unresolved lifetime evidence.
4. If a package transaction is pending, evidence is unreadable, or refusal remains
   after restarting, stop and use [Recovery](recovery.md). Do not delete records
   or force installation. A restart does not repair an interrupted transaction.

A missing PID is not proof of clean shutdown. Replacement does not undo external
effects or clear native-resource uncertainty.

After restart, valid ownership records from the previous boot no longer block
replacement. Retained cleanup notices, effect history and native quarantine are
not erased or declared resolved. Missing or malformed boot evidence stays fenced;
restarting is not a blanket override for every refusal.

## Upgrade a `.deb`

1. Obtain and check the replacement `.deb` and its version.
2. Exit every app/core using that installation and preserve clean shutdown evidence.
3. Open the file with your distribution's package manager to upgrade or reinstall
   `odin-desktop`. Let it perform dependency and ownership checks.
4. After the manager finishes, launch **Odin** normally and read any startup error.
   Package installation success alone does not prove successful profile migration
   or a working provider.

Busy lifetimes, unresolved cleanup or incomplete transactions can refuse the
operation. Do not force it or kill unrelated services.

Some older development packages lack the guarded launcher needed for direct
upgrade and are deliberately refused. Ask for a controlled offline transition
if you encounter that refusal; do not bypass it with permission changes or
manual file deletion.

## Replace an AppImage

Do not truncate or overwrite a running or mounted AppImage. The manual offline
`replace-appimage.py` helper replaces the **same stable path** without truncating
the old inode. It is not invoked by the app and is not a download tool.

The helper and its matching `ownership.py` are maintained as separate files, not
an installed app button or command on your PATH. Obtain a trusted matching pair
from the distributor before using this procedure. The helper needs an ordinary
user's Python interpreter; normal app operation does not.

1. Obtain the new local AppImage and expected digest; preserve the old file/digest.
   Exit the app/core cleanly.
2. As the ordinary file owner, run the helper with Python, supplying `--source`
   for the new file, `--destination` for the existing stable path, and `--sha256`
   for the new file's expected digest. Keep `ownership.py` beside the helper.
   Quote paths containing spaces. Never run it as root.
3. Read the outcome. Non-owned files, symlinks and read-only/nonwritable paths
   refuse replacement. Do not bypass those checks.
4. If interrupted, preserve the transaction marker. An explicit rerun with the
   **same destination and digest** can recover an exact durable stage or confirm
   already-committed bytes. Changed identities, missing durable stage information
   or a different transaction require manual help, not arbitrary retries.
5. After confirmed completion, launch the stable path and inspect startup.

For example, replace each placeholder with the actual local path or digest:

```text
python3 "/path/to/replace-appimage.py" --source "/path/to/new.AppImage" --destination "/path/to/existing.AppImage" --sha256 "<expected-new-file-sha256>"
```

Same-path replacement preserves the login command. If you move the AppImage,
its old login command is detected as stale; explicitly enable **Start at login**
for the new path. Moving a file and updating login startup are separate steps.

This helper relies on cooperation; it cannot stop a file owner ignoring it with
direct writes. Native mounted-AppImage behavior is not yet confirmed on every
target desktop. Keep shutdown and transaction evidence rather than treating
file-copy success as proof of complete cleanup.

## Compatibility and failed migrations

App version, protocol, storage, checkpoints and computer quarantine have separate
compatibility requirements. Newer, foreign, corrupt or incompatible existing
state can refuse startup; it is not silently treated as an empty profile.

Before migrations, the app creates a private backup under
`~/.local/share/odin-desktop/default/package-backups/<backup-id>/`, or the custom
profile data root. It covers configuration/data with exclusions such as locks,
IPC tokens, logs and previous backups. It does **not** back up the system keyring
or external files or undo real-world effects. It is not an automatic restore point.

If startup or migration fails:

1. Preserve the current package, profile, cleanup/quarantine records and error.
   If a core is running, use normal Exit.
2. Record whether installation finished. A pending migration must be recovered
   with its exact compatible build; another version cannot claim that transaction.
   Compatible migration retries do not replay external work.
3. Ask for support before downgrading. An older version must be checked against
   a private isolated copy of the complete current state. Installing old bytes
   does not convert newer storage to an older format.
4. If the older version refuses, keep or reinstall the compatible version through
   its normal replacement path after clean shutdown.

Do not delete `package-state.json`, locks, unknown receipts or quarantine to make
old code run. Do not restore a pre-upgrade backup over newer state blindly: it can
discard effect evidence and permit unsafe replay. There is no automatic backup
restore or state rollback command. Keep the compatible version and state if a
safe supported recovery cannot be established.

## Security fixes and maintenance

Use release notes to identify included fixes and remaining limits. A pinned
dependency or a successful launch is not proof of security review. Electron's
browser runtime and the separate tool browser both need maintained releases.
Report suspected security problems privately with sanitized details; do not
modify the bundle or run dependency-manager repair commands as an update path.
