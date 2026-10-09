# Changelog

## [1.0.2]

- **Fixed:** the "unknown outcome" line under a task, and the status bar count, never went away. They now have a
  Dismiss button. Dismissing hides the notice only: the actions stay unknown and are never repeated.
- **Fixed:** Odin couldn't look at an image he had just generated. Each generated image is also saved privately in
  the workspace folder (`generated-images/`), and Odin is told where, so he can describe it or post it again.
- **Fixed:** a one-time schedule that had run stayed under Scheduled in Work, shown as still running. It now moves to
  Finished with its run's result. A deleted schedule moves to Finished too: `cancelled` if it never ran, otherwise
  its last run's result, or `unknown` when that result was never recorded. Schedules deleted, and one-time
  schedules that finished, before 1.0.2 show as `unknown`, because their last run can't be confirmed.
- **Fixed:** Settings, Records reported "unhealthy" with chat history, knowledge, the scheduler, loops and agents "not
  initialised" while all of them worked.
- **Fixed:** some tool calls, such as `schedule_task`, showed no details when expanded.
- **Fixed:** `/status` and Settings showed the engine as 0.1.0.dev1. They now show the release number.
- Notices, Steer and Stop lines and task outcome lines line up with the messages, and Steer and Stop lines go away
  when their task ends. A stopped task no longer says so twice.
- While Stop waits for a running step to finish, the button and the working line name the step and how long it has
  been running.
- Work cards show what each item is, a plain state, local times, the result or last error, and their buttons, without
  internal identifiers.
- The window no longer scrolls past the bottom of the app.
- Tool rows no longer repeat the tool name.
- Every line in the engine log starts with its date, time, level and source.

## [1.0.1]

- **Fixed:** a saved personality, such as one brought over with Import from Odin, applied only until the app
  restarted. After a restart Odin Desktop answered as Odin again. Saved personalities now apply from the first
  message after every start.
- The chat names the assistant after the active personality: replies, the message box, the empty chat, the working,
  Steer and resume text, and their screen-reader announcements use its name, for example Clippy. The window title
  and the tray still say Odin.
- Settings, Personality lists saved presets by their own names, so presets that share a display name can be told
  apart.
- Settings, Models: each automatic agent candidate has a description field, as in Odin's own settings. It tells
  automatic selection which tasks suit that model, and it saves with the other agent settings.

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
