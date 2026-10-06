# Install Odin Desktop on Linux

**First draft, not a released-product installation guide.** Reviewed source for this
draft is Desktop `0b7d596f7e870d06699722f151c4d9837c5433f1` (2026-10-06).
The repository is private and the packages described here are unreleased candidates.
Use these procedures only with an identified candidate in an isolated test desktop.
They do not authorize installing or testing on Aaron's active desktop.

Odin's recorded upstream baseline is `v4.13.0`,
`cd7530906e9cfa10a0fa900247d7ce2a8bb33e25`. The recorded upstream review watermark
is **baseline only**, not a claim that Desktop includes every later Odin fix or is
an identical engine. See the [baseline record](../../maintenance/baseline.md).

## Choose a format and check the requirements

The existing candidate builder produces Linux **x86-64** `.deb` and AppImage files.
ARM, Windows, macOS and other Linux distributions are not qualified by this draft.
Mint 22 and Ubuntu 24.04-base desktops are the approved first targets, not blanket
support for every Debian derivative or graphics driver.

| Format | What you manage |
|---|---|
| `.deb` (`amd64`) | Install, upgrade and remove with the distribution's package manager. Package name: `odin-desktop`. |
| AppImage (`x86_64`) | Keep the executable at a stable path you own. Replace or remove it yourself after clean Exit. It is not a package-manager installation. |

You need an ordinary non-root desktop login and working desktop libraries. The
`.deb` declares GTK 3, NSS, XSS, Xtst, AT-SPI, UUID, Secret Service, GBM, ALSA,
xshmfence, X11-XCB and OpenSSH client dependencies. Let the package manager resolve
them rather than bypassing dependency checks. AppImage users need host `ssh` and
`ssh-keygen` for managed SSH; those executables are not bundled. A working Linux
Secret Service keyring is needed to save/use provider credentials.

The candidate bundles its Python runtime, engine dependencies, tool Chromium,
semantic-search model and computer helpers. You do not install Python or Node to
run it. PDF support is the exception: its pinned optional component downloads
automatically on first PDF use into private user data. Failed downloads can retry
on a later use. Provider sign-in, model requests and network tools still need their
respective services; bundled resources do not make the whole app offline.

**Qualification limits:** extracted packages and sandbox-intact Xvfb launches are
recorded, but they do not prove native login/keyring/portal behavior or FUSE-mounted
AppImage operation. Stock Ubuntu 24.04 restricted-user-namespace startup remains
an open gate. No measured universal glibc/CPU floor, RAM minimum or free-disk
requirement is asserted here. Candidate byte counts in packaging evidence belong
to those exact hashes, not future release download or total installed sizes.

Sources: [builder configuration](../../app/electron-builder.yml),
[runtime selection](../../app/src/main/core-command.ts),
[packaging boundaries](../../app/packaging/README.md),
[candidate evidence and open Ubuntu gate](../../maintenance/p41-packaging.md),
[approved targets and qualification rules](../work/phase-3-app-v1.md#6-aarons-decisions-settled-on-2026-10-05).

## Get the right file

The approved release model is GitHub Releases at
[Calmingstorm/Odin-Desktop](https://github.com/Calmingstorm/Odin-Desktop/releases),
with `.deb` and AppImage assets. That decision is **not evidence that a release
has been published**. For this draft, obtain the exact candidate and its recorded
hash from the reviewer rather than downloading an arbitrary similarly named file.
Private-repository access requires your own GitHub browser session.

Release assets are **unsigned**. Published SHA-256 hashes and source inventories
help identify bytes; they are not independent signatures or a guarantee of origin.
There is no signing-key enrollment, update-feed setup or app GitHub-token setup.

Source: [approved manual-release/no-signing decisions](../work/phase-3-app-v1.md#decision-c-github-releases-and-manual-installation).

## Install a fresh `.deb` candidate

1. In the isolated candidate desktop, check that the supplied file is the `.deb`
   for `amd64` and the version/hash matches the reviewer-provided record.
2. Open it with the distribution's package installer. Review the package name
   `odin-desktop`, version and dependency changes, then install through that
   manager. Installation privileges belong to the manager, not the running app.
   Do not force missing dependencies.
3. Launch **Odin** from the desktop application menu as your ordinary user.
   Follow the first-run settings shown by the app. The package does not require
   starting a separate Odin server or service.
4. If startup fails, preserve the error and exact candidate identity for the
   reviewer. Do not run the app as root, use `--no-sandbox`, weaken AppArmor or
   change the workstation's user-namespace policy to make it start.

This is a **fresh-install** procedure, not permission to install over a running
older candidate. See [updates](updates.md) before replacing an installation.
Native package-installer acceptance must still be recorded against the exact
candidate; a successful extracted launch alone is not that proof.

The `.deb` application resources are under **`/opt/Odin`**, with uppercase `O`.
The Desktop launcher/icon use the `odin-desktop` identity. This is independent of
the unrelated standalone Odin installation. Do not copy or delete that
installation to install Desktop.

Sources: [packaging layout](../../app/packaging/README.md#immutable-runtime-layout),
[launcher](../../app/packaging/odin-desktop.desktop),
[builder configuration](../../app/electron-builder.yml).

## Run an AppImage candidate

1. In the isolated candidate desktop, check the version/hash of the supplied
   `x86_64` AppImage. Save it at a stable location in a folder you own.
2. Use the file manager's Properties/Permissions control to allow that file to
   execute, then open it as your ordinary user. Do not execute it as root.
3. If the system cannot mount/run it or the sandbox cannot start, stop and report
   the environment and error. FUSE/native mounting is not qualified by the
   extracted-package evidence. Do not substitute sandbox-disabling flags. The
   `.deb` is the intended alternative to investigate with the reviewer, not a
   claim that every blocked AppImage has a proven automatic workaround.

AppImage relocation and replacement are separate operations. Keep its path
stable if you enable start at login. See the pending upgrade procedure below
before replacing it; do not overwrite a mounted executable in place.

Source: [packaging qualification limits](../../app/packaging/README.md#qualification).

## Normal startup, close and Exit

Launch **Odin** to open the app and its supervised core. Launching it again brings
back the existing window; it is not a request to run a second engine. **Start at
login** is opt-in and initially off. It starts the app, which owns the core; it
does not install a background service.

Closing the window hides it and keeps the app/core running. With a tray, reopen
from the tray. Without a tray, the app explains that it is still running; launch
**Odin** again to reopen. **Odin > Exit Odin** in the window menu, **Exit Odin**
in the tray menu, `Ctrl+Q`, or the
desktop launcher's Exit action requests shutdown. Closing the window is not Exit.
If Exit reports unknown cleanup, treat it as unresolved, not proof that every
effect was undone. Do not delete state or repeatedly replace the executable to
clear that warning.

Sources: [lifecycle rules](../../app/src/main/lifecycle.ts),
[app startup/shutdown integration](../../app/src/main/index.ts),
[start-at-login path](../../app/src/main/autostart.ts).

## Privacy, credentials and the files you keep

Desktop provisions its own profile. It does not import another Odin install's
history, configuration, credentials, skills or browser profile. Running alongside
standalone Odin is the intended arrangement, not connecting Desktop to it.
Managed SSH remains an execution capability; a phone client, server-client mode
and import of an Odin installation are outside Linux v1 scope.

With the default XDG locations and profile `default`, the app uses:

| Content | Default location |
|---|---|
| Configuration, profile identity, IPC token, app preferences | `~/.config/odin-desktop/default/` |
| History, engine data, drafts, logs, private resource downloads and file secrets | `~/.local/share/odin-desktop/default/` |
| Cached artifacts and other cache | `~/.cache/odin-desktop/default/` |
| Socket/runtime directory | `$XDG_RUNTIME_DIR/odin-desktop/default/`; if unset, `/tmp/odin-desktop-<uid>/odin-desktop/default/` |
| App cleanup evidence outside the profile directory | `~/.config/odin-desktop/default-cleanup-state.json` |
| Opt-in login launcher | `~/.config/autostart/odin-desktop.desktop` |

Custom `XDG_CONFIG_HOME`, `XDG_DATA_HOME` and `XDG_CACHE_HOME` replace the default
roots above. Do not assume deleting only the default folders removes a profile
that used custom roots. The `secrets/` directory under data is not a substitute
keyring. Provider credentials use the Linux keyring in a namespace derived from
the Desktop profile and configuration path. If it is locked/unavailable, use
the first-run **Retry** control and the system's unlock prompt. No plaintext
fallback vault is promised.

These are private local storage boundaries, **not a promise that data never
leaves the machine**. Selected model providers and requested network/host tools
receive the inputs needed for their operations. Choose deliberately what you send
or ingest; do not include credentials or private history in support screenshots.

Sources: [app paths](../../app/src/main/paths.ts),
[engine paths](../../src/desktop/paths.py),
[profile keyring namespace](../../src/desktop/secrets.py),
[first-run Retry](../../app/src/renderer/src/components/FirstRunBanner.vue),
[fresh-state scope](../work/phase-3-app-v1.md#rules-for-every-implementation-pr).

## Removal and data retention

First disable **Start at login** while the app is available, then choose **Exit
Odin** and wait for the shutdown outcome. Preserve unresolved cleanup evidence.
Removing the executable is not a cleanup/reconciliation operation.

For AppImage, remove the specific AppImage file you saved after clean Exit. This
does not remove its profile, caches or keyring credentials. For `.deb`, remove
the `odin-desktop` package through the package manager, not by deleting files
under `/opt/Odin` yourself. The stronger removal/ownership guarantees below
are pending, not validated for every earlier candidate.

Keep the configuration/data/cache folders if you may return to the app or need
recovery. This draft deliberately gives **no recursive profile-deletion recipe**:
those folders contain history and potentially unknown-effect/quarantine records.
Exporting a file elsewhere also leaves that separate user-owned copy in place.
Package removal or folder deletion **does not imply keyring credential deletion**.
Do not delete an entire shared system keyring to uninstall Desktop.

### Package removal and retained ownership evidence

**pending: #36**

The inspected pending implementation makes `.deb` remove/purge retain per-user
config, data, cache, credentials, receipts, backups and quarantine. Its hooks
neither start nor signal apps/cores/services. Busy or unresolved lifetimes refuse
replacement/removal; PID disappearance alone is not clean shutdown evidence.
Do not bypass a refusal by deleting locks or receipts.

The `.deb` also retains root-owned package lifetime/transaction evidence under
`/var/lib/odin-desktop/package-ownership`. AppImage lifetime/replacement evidence
uses `$XDG_STATE_HOME/odin-desktop/install-ownership/appimage`, defaulting to
`~/.local/state/odin-desktop/install-ownership/appimage`. These are not extra
folders to erase to force uninstall. The pending package contains
`/opt/Odin/odin-desktop` as its guarded launcher and
`/opt/Odin/odin-desktop.bin` as the Electron executable; users launch the former,
not the `.bin` to bypass admission.

Alongside acceptance uses a disposable second installation with sentinels, not
the real standalone service. Container evidence does not qualify native
keyring/login/FUSE behavior. See
[pending ownership and removal evidence](https://github.com/Calmingstorm/Odin-Desktop/blob/30402eb95154d9a4d3076fb5cae165771d4aee36/maintenance/phase4-packaging.md),
[package hooks](https://github.com/Calmingstorm/Odin-Desktop/blob/30402eb95154d9a4d3076fb5cae165771d4aee36/app/packaging/deb_transaction.py), and
[AppImage state paths](https://github.com/Calmingstorm/Odin-Desktop/blob/30402eb95154d9a4d3076fb5cae165771d4aee36/app/packaging/ownership.py).
