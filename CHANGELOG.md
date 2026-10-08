# Changelog

## [1.0.0]

The first release of Odin Desktop, a desktop app for [Odin](https://github.com/Calmingstorm/Odin),
the self-hosted AI execution agent. It runs Odin's engine on your own computer with a
profile of its own, with or without an existing Odin install.

- Chat with Odin's local engine, search conversations, attach files, keep knowledge,
  and save results. Follow tool activity and use Stop, Steer or Resume with explicit
  outcomes rather than treating a submitted request as completed work.
- Manage providers and models, tools, managed SSH hosts, skills and MCP servers,
  memory and records. Run background work, schedules and stored reports from the app.
- Settings are plain-language pages rather than raw configuration keys. Switch the
  main model and its reasoning level from the header. The window remembers its size
  and position, and first-run setup appears only until it is done or skipped.
- **Import from Odin** (Settings, General, Support and advanced) brings memory, skills,
  MCP servers, personality, managed hosts and model settings over from an Odin install,
  using its admin API token for that import only. It never replaces anything that
  already exists. Skills that are off in Odin arrive off and MCP servers arrive switched
  off. Secrets Odin never returns, such as API keys and MCP environment and header
  values, have to be entered again. A host is added once Odin Desktop's own SSH key
  can sign in to it.
- The app is supported on **Cinnamon/X11, GNOME/Wayland, KDE/Wayland and Hyprland**.
  Closing the window leaves Odin running; use Exit Odin to stop it. Login startup
  is optional, and shutdown, reboot and logout request bounded orderly Exit.
- **Computer use is supported on X11 only, at parity with Odin.** Wayland computer
  use is planned for **1.1**; until then the app refuses it with guidance. App
  support on a Wayland desktop does not imply mouse/keyboard automation support.
- Linux x86-64 **unsigned `.deb` and AppImage** packages bundle the normal runtime;
  on Arch and other distributions without `.deb` support, use the AppImage.
  Verify the supplied SHA-256; it is not a publisher signature. AppImage still
  requires compatible FUSE and user-namespace/sandbox policy; use the `.deb` where
  supported if AppImage startup is refused. Do not disable the sandbox.
- PDF support is downloaded automatically on first use, pinned by hash. If that
  download fails, a later use can retry.
- Install and upgrade manually through your package manager or by replacing the
  AppImage after clean Exit. The app can check for release notices, but does not
  download or install updates, restart itself, or replay work after an upgrade.
  Its profile stays separate from an existing Odin installation.
- Planned for **1.1**: Wayland computer-use integration and the remaining native
  harness follow-ups. The [user guides](https://github.com/Calmingstorm/Odin-Desktop#user-guide)
  cover installation and recovery limits.

## [0.1.0]

Unreleased desktop candidate. These are curated rehearsal notes, not acceptance
or publication authorization.

- Electron desktop application with local core integration and explicit settings.
- Linux x86-64 `.deb` and AppImage candidates with a bundled runtime.
- Ownership and alongside-installation boundaries separate this product from an
  existing Odin installation.
- Installation and upgrades remain manual user actions. No in-app downloader,
  installer, update feed or automatic restart is introduced.

The current publication gate is the
[Linux release checklist](docs/release/linux-v1-checklist.md), which supersedes
the earlier Phase 3/4 release procedure.
