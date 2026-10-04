# Decisions for Aaron

Owner: Claude. Draft 1, 2026-10-04. These are choices only Aaron can make. Each item gives the options, what Claude and
Odin recommend, and why. When Aaron decides an item, it moves into the design docs and leaves this list.

## 1. Run at startup: login only, or before login too?

- **Login-session startup** (recommended for v1): the core starts when you log in and runs in the background after the
  window closes.
- **Boot-before-login** additionally needs a system service and lingering. This conflicts with per-user keyrings, GUI
  consent and notifications. It is possible later.

## 2. Reaching Odin when you're away from the desk

Discord reaches your phone; a desktop app doesn't. The options can be combined:

- **(a)** Accept the loss: Odin Desktop is a local app.
- **(b)** Remote-server client mode: the desktop UI can also connect to a server Odin, which keeps phone access through
  that server's Discord. Designed as a seam; your scope call.
- **(c)** The desktop core serves an optional remote client over your tailnet, so a phone can use it through a web
  client.
- **(d)** Keep Discord as an optional surface of Odin Desktop.

Recommendation: design the seam now and decide the scope with you. v1 is local only unless you say otherwise.

## 3. Where the shared core lives, and the go-ahead to extract it

The plan reuses Odin's code through a versioned shared core package. That means a careful extraction campaign in the
Odin repository, with zero behaviour change for server installs. Options for where the package lives:

- inside the Odin repo, published as its own versioned package;
- a neutral third repo.

The extraction itself would be authorized later, as its own campaign.

## 4. Odin's prompt text mentions Discord

The personality presets and system template literally say "for Discord" and "agent on Discord". The standing rule is
that this text never changes. The brief also says removed features leave no references. Options:

- **(a)** Keep the bytes unchanged in Odin Desktop too, as an explicit exception.
- **(b)** Allow a desktop variant of those specific lines, which changes the prompt-preservation rule for this product.

Odin and Claude preserve the text unchanged until you decide.

## 5. Importing from your existing Odin

What should v1 import? Candidates:
- memory;
- skills;
- knowledge;
- schedules (imported inert until re-authorized);
- conversation history;
- Codex accounts (fresh sign-in may be cleaner).

Recommendation: an explicit, validated snapshot import that never points at a live server's data.

## 6. History, retention and notification privacy

- How long the visible transcript and artifacts are kept: forever, or a retention period.
- Whether notifications show message previews.

## 7. How broad Linux v1 is

- **Desktops:** Cinnamon/X11 (yours) is first. Should GNOME and KDE on Wayland be in v1?
- **Computer use:** which backends v1 qualifies (X11; the Wayland portal; Hyprland).

## 8. What's in the default install

These are heavy optional downloads: Playwright's Chromium for browser tools, semantic-search models, PDF support and
computer-use helpers. Options:
- ship them all;
- download each on first use, with progress.

Either way, features that aren't configured publish no tools.

## 9. Windows and macOS

- **When:** after Linux v1.
- **Costs:** an Apple Developer ID (notarization) and a Windows code-signing certificate, both yearly.

## 10. Repository and licence

The repo is private during design. Odin is public and MIT-licensed. Should Odin Desktop also be public and MIT once code
exists?

*Pending from round 2:*
- the shell choice (Electron or Tauri), if Claude and Odin don't converge;
- live reply text versus the guards, if it turns out to be your call.
