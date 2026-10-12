# Install Odin Desktop on Windows

Odin Desktop for Windows is a per-user app for **64-bit Windows 11**. It runs the same local engine as
the Linux app, with the same chats, tools, memory, knowledge, background work, hosts, MCP servers and
skills. Computer use isn't available on Windows yet. Windows 10 and ARM computers aren't supported.

## Download and check the file

Download `odin-desktop-<version>-x64-setup.exe` and `SHA256SUMS` from
[Releases](https://github.com/Calmingstorm/Odin-Desktop/releases), and read the release notes.
Before you run the installer, compare its SHA-256 with the value in `SHA256SUMS`, in PowerShell:

```powershell
(Get-FileHash .\odin-desktop-1.0.6-x64-setup.exe -Algorithm SHA256).Hash
```

The two must match exactly. The installer and the app are **unsigned** for now: a matching checksum
shows the bytes are the published ones, not who published them.

## Install

Double-click the installer.

- **SmartScreen** shows "Windows protected your PC" for an unsigned app. Choose **More info**, then
  **Run anyway**.
- **Smart App Control**, when it's turned on, blocks unsigned apps and offers no way past it. Odin can't
  be installed on that computer until it's signed.

The installer needs no administrator rights and asks for none. It installs for your account only, into
`%LOCALAPPDATA%\Programs\Odin`, adds **Odin** to the Start menu (no desktop shortcut) and starts nothing
when it finishes. Don't run it as administrator: it refuses an elevated start, and so does the app.

## Start, close and Exit

Open **Odin** from the Start menu. Closing the window keeps Odin running in the notification area, where
background work and schedules carry on. Choose **Exit Odin** from its tray icon to stop it.

**Start Odin when you log in** is in Settings → General. Odin then starts hidden, in the notification
area, and opens when you choose it there or from the Start menu.

## Your profile and privacy

Your chats, settings, keys and records live in `%LOCALAPPDATA%\odin-desktop\default`, readable only by
your account. Odin's working folder for tools is under `%LOCALAPPDATA%\odin-desktop` as well.

## Update

Download the newer installer, check it the same way, and run it. It installs over the current version
and keeps your profile.

- **Odin is running:** the installer refuses and changes nothing. Choose **Exit Odin** from the tray
  icon, wait for it to close, then run the installer again.
- **"An Odin session ended without confirmed cleanup since this computer started":** Odin ended
  without confirming its cleanup, after a crash or a power cut. Restart the computer, then run the
  installer again.

## Uninstall

Open Settings → Apps → Installed apps, find **Odin**, and choose **Uninstall**. This removes the app and
its Start menu entry and keeps your profile, as on Linux. To remove the profile as well, delete
`%LOCALAPPDATA%\odin-desktop` after uninstalling.

## Known limits

The limits accepted for this first Windows release are listed in
[Windows install safety](../design/windows-install-safety.md#accepted-limits).
