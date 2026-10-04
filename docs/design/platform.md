# Platform: shell, packaging, startup and cross-platform

Owner: Claude. Draft 3, 2026-10-04 (Odin's round-2 and round-3 reviews folded in; Aaron's decisions D3 to D6 applied). "Verify" marks facts to re-check against current releases before any build.

## What this has to satisfy

- **R1:** a real desktop app.
- **R2:** it can run at startup.
- **R3:** it can be installed instead of, or alongside, an existing Odin.
- **R5:** Linux first, Windows and macOS later, without a rewrite.
- **R6/R7:** reuse Odin's Python core. Odin is about 150K lines of Python. Rewriting the core in another language is out
  of scope.

## 1. Process model (platform view, D3)

**Odin runs while the application runs.**
- The app's main process owns the tray, windows, notifications, autostart and quick prompt.
- It starts the Odin core (Python) as a supervised child process. The renderer is separate again.
- **Closing the window** hides it and Odin keeps working.
- **Right-click the tray and choose Exit:** Odin shuts down safely, then the app exits.
- See [`architecture.md`](architecture.md#2-lifecycle-d3).

**When there is no tray.** Odin pointed this out in round 2: GNOME has no tray without an extension, and basic
operation must not need one. So:
- relaunching the app always focuses the running instance;
- the window's menu has **Exit Odin**;
- the `.desktop` launcher has an **Exit Odin** action (right-click in docks and menus);
- notifications open the conversation.

Closing the window on a desktop with no tray shows a one-time notice that Odin is still running and how to reach it.

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

**Recommendation (Claude and Odin, round 2): Electron for v1, conditionally.**

- **Electron for v1.** Linux is the first and primary target, and Aaron's desktop is Linux. Electron gives the most
  predictable rendering there, and the same engine later on Windows and macOS.
- **Conditions.** Nothing here is measured yet. Rendering, accessibility and security still need qualification on
  Cinnamon/X11 and GNOME/Wayland before release.
- **Renderer lockdown** (Odin's list, [round 2, section A](../discussion/04-odin-round2.md#required-renderer-lockdown)):
  - a sandboxed renderer with context isolation and no Node integration;
  - a narrow preload bridge of individually named, schema-checked methods, with sender and origin validated;
  - the packaged UI served from a custom app origin;
  - a strict CSP;
  - sanitized Markdown with active HTML disabled;
  - navigation and pop-ups blocked;
  - files reached only through core-issued references, with native dialogs for save locations;
  - no secrets or IPC token in the renderer;
  - a bundled-Chromium security update obligation.
- **Tauri is the strong alternative.** It is lighter and has a tighter security model, but its Linux engine is the
  weak point exactly where we start. Reconsider it if Tauri's Chromium backend becomes stable.
- **Qt and app mode come third.** Qt is viable if a single language matters more than UI velocity. App mode fails R1
  and R2 on its own.

**What would change it:**
- a requirement for a small download;
- a measured WebKitGTK result that is good enough for our UI on Aaron's Cinnamon/X11 desktop and on GNOME/Wayland.

A rendering spike would settle the second point, after approval.

## 3. Shipping the Python core

The core needs CPython 3.12 and Odin's dependencies. It also needs a real environment, because user skills are Python
modules loaded at runtime and some need their own dependencies.

| Option | Notes |
|---|---|
| **Relocatable CPython (python-build-standalone, the builds uv uses) + a locked venv inside the app** | A full interpreter with the same behaviour as Odin's own venv. **Preferred.** The core's environment is immutable. User skills that need dependencies get their own writable environments, so a skill install can never break the executor (Odin, round 2). |
| PyInstaller or Nuitka frozen binary | Smaller and faster to start, but it breaks runtime-installed dependencies and dynamic imports. Poor fit for skills. |
| Depend on the system Python | Fragile across distros. Odin's `.deb` does this today with `python3-venv`. Acceptable on Linux, not on Windows or macOS. |

**User skills need their own runtime boundary.** A separate writable environment does not help by itself: today's
skills are imported into the core's own process, so they would not see packages installed elsewhere. The build design
must therefore specify one of these:
- a skill worker process with its own environment, reached through the bounded SkillContext bridge;
- another loader strategy that is qualified to keep the executor's environment immutable.

**Everything is bundled (D14).** These ship in the installer and are always available, never downloaded on demand:
- browser automation (Playwright's Chromium);
- the semantic-search models;
- PDF support;
- the computer-use helpers.

Their provenance is pinned and verified at build time. Features that need the user's own credentials (email, MCP
servers, hosts) still expose no tools until they are configured.

## 4. Per-OS integration

| Concern | Linux (v1) | Windows (later) | macOS (later) |
|---|---|---|---|
| Start at login (the app, minimized to the tray; it starts the core) | XDG autostart entry in `~/.config/autostart/` | `HKCU\…\Run`, or the app's login-item API | Login item (`SMAppService`) |
| Tray | StatusNotifierItem / AppIndicator. Works on KDE and Cinnamon; **GNOME needs the AppIndicator extension** (verify). | Notification area | Menu bar extra |
| Notifications | `org.freedesktop.Notifications` (libnotify) | Toast notifications (need an AppUserModelID) | UserNotifications (needs permission) |
| Global hotkey | X11: an XGrabKey equivalent. **Wayland: the xdg-desktop-portal GlobalShortcuts portal**, whose support varies by desktop (verify GNOME, KDE, Cinnamon). | RegisterHotKey | Carbon or Cocoa hotkey API |
| Secrets (OAuth tokens, API keys) | Secret Service (GNOME Keyring, KWallet). An encrypted-file fallback needs a real key-unlock design; a key stored beside the ciphertext is not one. | Credential Manager / DPAPI | Keychain |
| Local IPC, app to core | Unix domain socket in `$XDG_RUNTIME_DIR` with owner-only permissions and peer checks, plus a profile-scoped, rotatable credential. The app's main process (the broker) holds the connection, never the renderer. | Named pipe with an owner ACL, plus a credential | Unix domain socket in a private directory, plus a credential |
| Data location | `~/.local/share/odin-desktop`, `~/.config/odin-desktop`, `~/.cache/odin-desktop` (XDG) | `%APPDATA%\Odin Desktop`, `%LOCALAPPDATA%` | `~/Library/Application Support/Odin Desktop` |
| Packaging | `.deb` (Mint, Ubuntu, Debian), `.rpm`, AppImage | MSIX or NSIS installer, signed | `.dmg`, Developer ID signed and **notarized** |
| Updates | **The owner depends on how it was installed.** A package-manager install (`.deb`, `.rpm`) is updated by the package manager, never by an in-app updater writing to package-owned files. An AppImage uses a signed in-app update channel and manifest. Either way, Odin quiesces first and checks ownership and schema compatibility. | Signed in-app updater | Signed in-app updater (Sparkle-style) |

### Linux packaging notes

- **Flatpak and Snap are poor fits for an execution agent.** Odin runs host commands, manages processes, drives the
  desktop and SSHes to hosts. A sandbox would need host escapes (`flatpak-spawn --host`, broad filesystem access),
  which defeats it. Defer both.
- **The `.deb` path already exists in Odin** (nfpm plus a disposable-container smoke gate). The workflow can be reused
  for `odin-desktop`, but that doesn't qualify the Electron and Python bundle; that needs its own gates.
- **Every Electron figure in this document is an estimate,** not a measurement. Qualification covers renderer security,
  no-tray reopen and Exit, and parent-loss containment, not just visual performance. It covers only the Linux scope
  Aaron approves.

## 5. Coexisting with a server install (R3)

| Resource | Odin (server) today | Odin Desktop |
|---|---|---|
| Package and binary names | `odin`, `odin-server`, `/opt/odin`, `odin.service` (system) | `odin-desktop`; never touches `/opt/odin` |
| Service | system unit, user `odin` | No service. Odin is a supervised child of the app's main process (D3). Start at login is an XDG autostart entry for the app. |
| Network | HTTP on port 3002 (configurable), optionally on the LAN | Local IPC is an owner-only socket. App/core and chat/control IPC have no TCP listener. A separately activated, scoped inbound webhook integration listener may exist only under [core-contracts section 8](core-contracts.md#8-inbound-webhook-integration-ingress) and Aaron's selected option; it exposes no general client/control API. |
| Data | `/opt/odin/data`, `config.yml` | Fresh per-user XDG paths and its own config schema version |
| Credentials | `data/codex_auth_*.json` | Its own keyring entries, with fresh sign-in |

"Instead of": Odin Desktop is a complete Odin for one user. "Alongside": both run on one machine with nothing shared:
- no imports (D5);
- no remote client and no attaching to a server (D6).

SSH to the user's configured managed hosts is an ordinary Odin execution capability and is unaffected.

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
