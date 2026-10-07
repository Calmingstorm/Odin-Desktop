# Install Odin Desktop on Linux

Odin Desktop is a Linux app with its own local engine and profile. Start here,
then follow [First run](first-run.md). These guides describe the merged Linux
implementation, not a published release or final desktop-support certificate.

Based on Odin v4.13.0. Later Odin changes are included only when the release
notes list them.

## Choose a format

The available formats target **x86-64** computers. Windows, macOS and ARM builds
are not supported. Mint 22 and Ubuntu 24.04-based desktops are the initial Linux
targets, not a promise that every distribution or graphics driver works.

| Format | How you manage it |
|---|---|
| `.deb` (`amd64`) | Install, upgrade and remove the `odin-desktop` package with your distribution's package manager. |
| AppImage (`x86_64`) | Keep the executable at a stable path you own. Replace or remove it yourself after clean Exit. |

Run the app as your ordinary desktop user, not root. The `.deb` declares its
desktop-library and OpenSSH dependencies; let the package manager resolve them.
AppImage users need `ssh` and `ssh-keygen` on the host for managed SSH.

A working **Linux Secret Service keyring** is required to save credentials. There
is no plaintext fallback. The app bundles its normal Python runtime, engine
dependencies, tool browser and search resources; you do not need Python or Node
for normal use. PDF support downloads an optional component on first PDF use.
If that download fails, a later use can retry. Online providers and network tools
still need their respective services.

AppImage startup refuses systems whose user-namespace policy is restricted,
including stock Ubuntu 24.04's restriction. Its preflight does not attempt to
prove a local exception would work. Use the `.deb` where supported instead.
Native FUSE mounting and the exact installed sandbox paths still need final
candidate validation. Preserve startup errors; do not run as root, disable the
sandbox or weaken system security policy to make the app start.

## Download and check the file

1. Open [Odin Desktop Releases](https://github.com/Calmingstorm/Odin-Desktop/releases).
   If the repository is private, use your own GitHub browser login. If no release
   files are available, there is no release to install from that page.
2. Choose the format above and read its release notes. Check the version and
   architecture before installing.
3. Compare the file's SHA-256 with the value supplied for that exact file. In a
   terminal, run `sha256sum "/path/to/downloaded-file"` and compare all 64
   hexadecimal characters. A file manager's checksum feature can do the same.
   Do not use a file whose digest differs.

Release files are **unsigned**. A matching SHA-256 detects changed bytes; it is
not an independent signature or proof that the publisher is trustworthy. Obtain
both the file and expected digest from a trusted release record. Do not give
the app a GitHub token or set up an update feed.

## Install a `.deb`

1. Open the checked `.deb` with your distribution's package installer.
2. Review the package name `odin-desktop`, version and dependency changes. Install
   through that manager; do not force missing dependencies.
3. Launch **Odin** from the application menu as your ordinary user.
4. Follow [First run](first-run.md). You do not need a separate Odin server or
   background service.

The application resources live under `/opt/Odin` with an uppercase `O`. Do not
delete or modify those files by hand. Use the normal launcher, not the internal
`.bin` executable. An existing standalone Odin installation is separate and does
not need to be changed.

If replacing an existing installation, follow [Updates](updates.md) first.

## Run an AppImage

1. Save the checked AppImage at a stable location in a folder you own.
2. In your file manager's Properties or Permissions, allow that file to execute.
3. Open it as your ordinary user and follow [First run](first-run.md).

Keep that path stable if you enable start at login. Do not overwrite a running
or mounted AppImage; use the replacement procedure in [Updates](updates.md).
If mounting or sandbox startup fails, stop and report the error. An extracted
AppImage running successfully does not show that normal mounting will work.

## Start, close and Exit

Launching **Odin** again brings back the existing window, rather than starting a
second engine. **Start Odin when you log in** is optional and initially off.

A fresh manual launch shows the window, including on GNOME and KDE Wayland.
An enabled login launch starts hidden; reopen it with the application launcher
or tray. The hidden login start is deliberate, not a failed first window.

**Closing the window hides it and leaves the app running.** Reopen from the tray,
if present, or launch Odin again. You do not need a tray to reopen or exit.

To stop the app, choose **Odin → Exit Odin**, press **Ctrl+Q**, or use **Exit Odin**
in the tray or desktop launcher's menu. Wait for shutdown before changing files.
If cleanup is reported as unknown, follow [Recovery](recovery.md); Exit is not
proof that every earlier effect was undone.

Computer shutdown, reboot and actual logout also request Odin's normal bounded
Exit before the desktop session is torn down. Cancelling a logout query is not
an Exit request. This is best effort: an abrupt power loss, crash or unavailable
session integration can still leave unknown cleanup.

**pending: #96**: Exit during the core's initial startup can still record unknown
cleanup. Do not assume an early logout or Exit has the proposed startup fix yet.

## Your profile and privacy

Desktop creates its own profile. It does not import another Odin installation's
configuration, history, credentials, skills or browser profile. Managed SSH is
supported, but this is not a phone app or a client for an existing Odin server.

For the default profile and standard Linux locations:

| Content | Location |
|---|---|
| Configuration and app preferences | `~/.config/odin-desktop/default/` |
| History, drafts, logs, engine data and private downloads | `~/.local/share/odin-desktop/default/` |
| Cached artifacts | `~/.cache/odin-desktop/default/` |
| Cleanup notice | `~/.config/odin-desktop/default-cleanup-state.json` |
| Optional login launcher | `~/.config/autostart/odin-desktop.desktop` |

Custom XDG locations change those roots. Credentials are kept in the system
keyring, not the data folder's `secrets/` directory. A locked or missing keyring
needs the [first-run recovery steps](first-run.md#recover-the-keyring).

Local storage does **not** mean all processing stays local. Model providers and
requested network or SSH tools receive the inputs needed for their operations.
Choose what you send or keep as knowledge deliberately. Never share credentials
or private history in support screenshots.

## Uninstall without losing recovery records

1. Turn off **Start Odin when you log in** while the app is available.
2. Choose **Exit Odin** and wait for its shutdown outcome. After an unclean end,
   restart the computer before removal. If refusal remains, follow
   [Updates](updates.md#before-replacing-anything); do not delete evidence.
3. For `.deb`, remove or purge `odin-desktop` through the package manager. For
   AppImage, remove only the specific executable after clean Exit.

Package removal keeps per-user configuration, history, data, caches, credentials,
backups, receipts and quarantine records. Files you saved elsewhere also remain.
Removal may refuse when a lifetime is busy or unresolved. Missing PIDs are not
clean shutdown evidence; do not bypass a refusal by deleting locks or receipts.

Package ownership records remain under `/var/lib/odin-desktop/package-ownership`
for `.deb`. AppImage records use
`$XDG_STATE_HOME/odin-desktop/install-ownership/appimage`, normally
`~/.local/state/odin-desktop/install-ownership/appimage`.

Keep retained state if you may return or need recovery. There is no general
profile-wipe recipe here because it can destroy unknown-effect evidence. Removing
folders does not delete keyring credentials. Never delete a shared system keyring
to uninstall one app.
