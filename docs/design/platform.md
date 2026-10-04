# Platform: shell, packaging, startup and cross-platform

Owner: Claude. Draft 1, 2026-10-04. "Verify" marks facts to re-check against current releases before any build.

## What this has to satisfy

- **R1:** a real desktop app.
- **R2:** it can run at startup.
- **R3:** it can be installed instead of, or alongside, an existing Odin.
- **R5:** Linux first, Windows and macOS later, without a rewrite.
- **R6/R7:** reuse Odin's Python core. Odin is about 150K lines of Python. Rewriting the core in another language is out
  of scope.

## 1. Process model (platform view)

There are two moving parts. The agent core is Python and holds the tool loop, providers, tools, schedules, agents and
data. The user interface is a separate process.

**Proposed shape for discussion:**

- **Core daemon (per user, background).**
  - It owns all work and data.
  - It starts at login when the user opts in, keeps running when the window is closed, and has no UI of its own.
  - Schedules, agents and long turns therefore never depend on a window being open. Discord-Odin has this property
    today because it is a service.
- **Desktop UI (client).** The chat window, management screens, tray icon, notifications and global hotkey. It talks
  to the core over a local, authenticated channel, never a TCP port open to the network.
  - Closing the window minimizes to the tray.
  - Quitting the tray quits the UI but leaves the core running.
  - A separate "Stop Odin" control stops the core.
- **One core, many windows.** The UI is single-instance and can open more than one window.

**Alternative:** a single process with the core embedded in the UI. It is simpler to ship, but schedules die with the
window and a UI crash takes the agent down. Odin's round-1 view will weigh in.

## 2. UI shell options

The chat UI is the product, and it is rich: live Markdown, code highlighting, diffs, tool timelines, inline media and
large outputs. Web technology is the natural fit. Odin's management UI is already a Vue 3 app, so a web-based shell can
reuse it.

| | Electron | Tauri 2 | Qt / PySide6 | Browser "app mode" |
|---|---|---|---|---|
| Rendering engine | Bundled Chromium, the same on every OS | System webview: WebKitGTK (Linux), WebView2 / Chromium (Windows), WKWebView (macOS) | QtWebEngine (Chromium) for rich content, or QML | The user's browser |
| Linux reliability for a heavy, streaming UI | Strong; the same engine as Chrome | **Main risk.** WebKitGTK still has a record of instability and performance gaps. Tauri's Chromium backend was still experimental as of 2026. | Good with QtWebEngine; packaging is fiddly | Depends on the browser |
| Reuse of Odin's Vue WebUI | Direct | Direct | Through an embedded web view | Direct |
| Tray, notifications, autostart, global hotkey, single instance, updater | Built in or mature modules. Linux autostart is an XDG file the app writes. | Official plugins (tray, notification, autostart, global-shortcut, single-instance, updater) | Qt has tray and notifications; autostart and hotkeys are per-OS code | Weak: no tray, limited notifications, needs a helper |
| Languages and toolchains | JS/TS + Node, plus Python for the core | Rust + JS/TS, plus Python for the core | Python only (the same language as the core) | JS/TS + Python |
| Footprint | About 100–150 MB installed; higher RAM | About 10 MB shell; low RAM | About 150 MB+ with QtWebEngine | Smallest |
| Packaging (Linux / Windows / macOS) | electron-builder: deb, rpm, AppImage / NSIS, MSIX / dmg, signing, notarization | Tauri bundler: deb, rpm, AppImage / MSI, NSIS / dmg | PyInstaller, Nuitka or pyside6-deploy; per-OS work | Whatever the core uses |
| Security model | Needs care: context isolation, no `nodeIntegration` in the renderer, strict CSP | Strong by default: capability-scoped IPC | Native | Browser sandbox |

**Leaning, for discussion:**

- **Electron for v1.** Linux is the first and primary target, and Aaron's desktop is Linux. Electron gives the most
  predictable rendering there, and the same engine later on Windows and macOS.
- **Tauri is the strong alternative.** It is lighter and has a tighter security model, but its Linux engine is the
  weak point exactly where we start. Reconsider it if Tauri's Chromium backend becomes stable.
- **Qt and app mode come third.** Qt is viable if a single language matters more than UI velocity. App mode fails R1
  and R2 on its own.

**What would change the leaning:**
- a requirement for a small download;
- a measured WebKitGTK result that is good enough for our UI on Aaron's Cinnamon/X11 desktop and on GNOME/Wayland.

A rendering spike would settle the second point, after approval.

## 3. Shipping the Python core

The core needs CPython 3.12 and Odin's dependencies. It also needs a real environment, because user skills are Python
modules loaded at runtime and some need their own dependencies.

| Option | Notes |
|---|---|
| **Relocatable CPython (python-build-standalone, the builds uv uses) + a locked venv inside the app** | A full interpreter, pip-capable, with the same behaviour as Odin's own venv. **Preferred.** |
| PyInstaller or Nuitka frozen binary | Smaller and faster to start, but it breaks runtime-installed dependencies and dynamic imports. Poor fit for skills. |
| Depend on the system Python | Fragile across distros. Odin's `.deb` does this today with `python3-venv`. Acceptable on Linux, not on Windows or macOS. |

**Large optional downloads.** These should be fetched on first use with visible progress, not shipped in the installer:
- Playwright's Chromium for browser tools, about 150 MB;
- the fastembed model for semantic search;
- PyMuPDF for PDF analysis.

## 4. Per-OS integration

| Concern | Linux (v1) | Windows (later) | macOS (later) |
|---|---|---|---|
| Start at login: core | systemd user unit (`systemctl --user enable`); optional `loginctl enable-linger` to run without a graphical login | Task Scheduler "at logon" task, or a `Run` registry key | LaunchAgent, registered with `SMAppService` |
| Start at login: UI (tray, minimized) | XDG autostart entry in `~/.config/autostart/` | `HKCU\…\Run`, or the app's login-item API | Login item (`SMAppService`) |
| Tray | StatusNotifierItem / AppIndicator. Works on KDE and Cinnamon; **GNOME needs the AppIndicator extension** (verify). | Notification area | Menu bar extra |
| Notifications | `org.freedesktop.Notifications` (libnotify) | Toast notifications (need an AppUserModelID) | UserNotifications (needs permission) |
| Global hotkey | X11: an XGrabKey equivalent. **Wayland: the xdg-desktop-portal GlobalShortcuts portal**, whose support varies by desktop (verify GNOME, KDE, Cinnamon). | RegisterHotKey | Carbon or Cocoa hotkey API |
| Secrets (OAuth tokens, API keys) | Secret Service (GNOME Keyring, KWallet), with an encrypted-file fallback for headless sessions | Credential Manager / DPAPI | Keychain |
| Local IPC, UI to core | Unix domain socket in `$XDG_RUNTIME_DIR`, mode 0600, plus a per-install token | Named pipe with an ACL for the user, plus a token | Unix domain socket in the user's container or temp dir, plus a token |
| Data location | `~/.local/share/odin-desktop`, `~/.config/odin-desktop`, `~/.cache/odin-desktop` (XDG) | `%APPDATA%\Odin Desktop`, `%LOCALAPPDATA%` | `~/Library/Application Support/Odin Desktop` |
| Packaging | `.deb` (Mint, Ubuntu, Debian), `.rpm`, AppImage | MSIX or NSIS installer, signed | `.dmg`, Developer ID signed and **notarized** |
| Updates | The in-app updater channel; apt or rpm repos later | The in-app updater | The in-app updater (Sparkle-style) |

### Linux packaging notes

- **Flatpak and Snap are poor fits for an execution agent.** Odin runs host commands, manages processes, drives the
  desktop and SSHes to hosts. A sandbox would need host escapes (`flatpak-spawn --host`, broad filesystem access),
  which defeats it. Defer both.
- **The `.deb` path already exists in Odin** (nfpm plus a disposable-container smoke gate). Reuse it for the
  `odin-desktop` package.

## 5. Coexisting with a server install (R3)

| Resource | Odin (server) today | Odin Desktop |
|---|---|---|
| Package and binary names | `odin`, `odin-server`, `/opt/odin`, `odin.service` (system) | `odin-desktop`; installs per user or into `/opt/odin-desktop`; never touches `/opt/odin` |
| Service | system unit, user `odin` | systemd **user** unit for the desktop user |
| Network | HTTP on port 3002 (configurable), optionally on the LAN | No TCP listener by default. A Unix socket, plus optional remote access as a separate, explicit feature (see the chat-experience gaps). |
| Data | `/opt/odin/data`, `config.yml` | XDG paths above, an own config schema version |
| Codex auth | `data/codex_auth_*.json` | Its own store (keyring). One-time import from an Odin install is opt-in. |

"Instead of": Odin Desktop is a complete Odin for one user. "Alongside": both can run on one machine with no shared
state unless the user imports it.

A third reading is a desktop client for an existing server. Whether the app should also connect to an existing Odin
server is a question for Aaron. Odin's round-1 view will weigh in.

## 6. Portability seams in the core (for Windows and macOS)

These are Linux assumptions in today's Odin that the core must isolate behind interfaces before Windows or macOS work.
Odin's reuse map is expected to confirm and extend the list.

- **Shell:**
  - `run_command` and `run_script` assume bash or sh;
  - the command governor parses POSIX shell structurally.

  Windows needs PowerShell (and a governor that understands it), or an explicit Git Bash / WSL policy.
- **Process supervision:** POSIX process groups, signals and pidfds. Windows needs Job Objects. macOS lacks pidfd.
- **Computer use:**
  - X11, Wayland portal and Hyprland backends exist today;
  - Windows needs SendInput and UI Automation, with desktop duplication for capture;
  - macOS needs CGEvent, ScreenCaptureKit and Accessibility, plus TCC permission prompts.
- **Files and permissions:** 0600 secret files become ACLs and the keychain; path conventions change.
- **SSH:** the OpenSSH client exists on Windows 10+ and macOS. Verify its behaviour parity for multiplexing.

## 7. To verify before any build

- WebKitGTK rendering and performance for our chat UI, if Tauri stays in play.
- GlobalShortcuts portal support on the target desktops.
- Tray support on GNOME without the extension.
- Notarization and signing costs and accounts: an Apple Developer ID, and a Windows code-signing certificate.
