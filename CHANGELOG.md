# Changelog

## [1.0.5]

- **Fixed:** once an agent, task, loop or process had finished, the engine kept one CPU core at 100% until the app
  restarted. It now goes idle when the work ends.
- **Fixed:** an MCP server's tools never reached Odin in chats, even while Settings showed the server connected. Odin
  now sees and uses them.
- **Fixed:** knowledge search matched literal words only. It now uses the bundled search model and a full-text index,
  as Odin does. Documents saved before 1.0.5 are added to the full-text index at the first start, in one quick step.
  If the search model can't load, search still matches words.
- **Fixed:** the auxiliary (background) model didn't start with the app, so summaries and background follow-ups ran
  on the main model until its setting was saved again. It now starts with the app.
- **Fixed:** reminders, finished background tasks and loop alerts never raised a desktop notification. They now do,
  under the same settings as replies: off, quiet hours, muted chats and the focused window.
- **Fixed:** a text attachment over 4 MiB failed the whole message. The message now goes through with the part of the
  file that fits, as in Odin.
- **Settings → Models:** the auxiliary model is chosen from the model list, like the main model. New profiles start
  it on gpt-6.1-sol; existing profiles keep their choice.
- **Fixed:** a cron schedule with no time zone runs on UTC, but Settings → Work called it "Odin's time zone", and its
  Next preview ignored the zone you picked. It now says UTC, the preview uses your zone, and a new schedule starts in
  Odin's time zone (Settings → General).
- A refused schedule or outbound webhook says why (a bad time zone, cron or run time; an unknown event or a blocked
  address) instead of "Invalid method parameters" or "invalid webhook configuration". A password in a pasted URL is
  masked in that reason.
- **Fixed:** `analyze_pdf` was never offered, so its PDF reader never downloaded. It is offered now and downloads the
  reader the first time it runs.
- **Fixed:** Odin couldn't open his own browser screenshots. Each one is also saved privately in the workspace
  folder (`screenshots/`), as generated images are.
- **Fixed:** failed image, file, screenshot, knowledge, scheduling and agent tool calls showed a green check. They
  now show as failures.
- **Fixed:** after Stop, an interrupted wait stayed "running" in the chat. It now shows as stopped.
- **Fixed:** a background task left a frozen progress post and posted its results twice. Its result now comes once;
  its Work card shows the progress.
- **Fixed:** after a restart, a finished process in Work showed "(retained output)" instead of its command.
- Work keeps the newest 50 finished items of each kind and drops the finished items of a deleted chat. Older finished
  items are removed; an item whose outcome isn't confirmed stays until it is.
- A webhook-triggered schedule's Work card says which webhook it waits for, and why it can't run while incoming
  webhooks are off.
- Each day of a chat starts with its date (Today, Yesterday or the date), and a message's time shows its full date
  on hover.
- Chat titles are one line: line breaks and control characters become spaces, and a blank rename is refused.
- Turning a skill off says what happened ("Turned off. Odin can't use it until it's turned on again.") instead of
  Odin's tool advice.
- On Linux, Odin is listed under Development (Programming in most menus) instead of Utility (Accessories), so docks
  and window lists that pick an icon by category show a coding icon.
- **Settings:** every page now follows the layout of General and Models. Data and privacy, Work, Tools, Hosts, MCP
  and Skills use labelled rows with a visible label for every control, put their actions in the section header,
  and show Save or Cancel only when something changed.
  - Knowledge details: pick documents from menus instead of typing their names, with readable results and the full
    record a click away. Adding a document is its own section.
  - Learned context lists its entries, with Edit and Delete in place.
  - Memory lists keys and values in aligned columns, and its editor is a bordered form.
  - Records lists trajectory files by name; choosing one fills in the file name. Closing SSH connection pools says
    what it closed.
  - Settings that can be left unset offer Default, so you can go back to the default.
  - Counts read "1 chunk", not "1 chunks". Tables no longer squeeze short cells to a letter per line.

## [1.0.4]

- **Fixed:** a schedule Odin set up in chat didn't appear in Work until its first run (or until Settings → Work was
  opened), so it had no Pause or Cancel there. Work now shows it as soon as Odin creates it, and a schedule Odin
  pauses or deletes in chat changes in Work right away. Schedules saved before 1.0.4 appear when the app starts.
- **Fixed:** the `/status`, `/usage` and `/reload` reports showed Markdown marks such as `**`. Their headings are bold
  and file names show as code, as in Odin's replies on Discord, and each line keeps its layout.

## [1.0.3]

- **Your name and picture in chat:** Settings → General → Your profile. Your messages show them instead of "You",
  and Odin calls you by that name.
- **A picture for each personality:** Settings → Personality. Replies show the active personality's picture, so a
  custom personality such as Clippy can have its own face. Without a picture, the Odin mark stays.
- Pictures stay on this computer. The app crops a PNG, JPEG or WebP image (up to 2 MB) to its centred square and keeps
  a 256 × 256 copy in your profile. Odin and the model never see your pictures.

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
