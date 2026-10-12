# Odin Desktop

<p>
  <a href="https://github.com/Calmingstorm/Odin-Desktop/releases/latest"><img src="https://img.shields.io/github/v/release/Calmingstorm/Odin-Desktop?label=release&color=c39448" alt="Latest release"></a>
  <img src="https://img.shields.io/badge/platforms-Linux%20%7C%20Windows%2011-c39448" alt="Linux and Windows 11">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
</p>

**[Odin](https://github.com/Calmingstorm/Odin), the self-hosted AI execution agent, as a desktop app for Linux
and Windows.**

Ask Odin to do something and it does the work on your own computer: shell commands locally or on your hosts
over SSH, file changes, browsing, schedules and sub-agents. Then it shows you exactly what ran. There's no
server to host, no Discord account to set up, and nothing listening on the network.

**[Download the latest release](https://github.com/Calmingstorm/Odin-Desktop/releases/latest)** for Linux
(`.deb` or AppImage) or Windows 11 (a signed installer).

## What you get

- **The same Odin.** Desktop runs Odin's own engine, with its tools, memory, knowledge base, background
  work (schedules, agents, loops and processes), managed SSH hosts, MCP servers and skills.
- **Your choice of model.** A ChatGPT subscription through Codex, any OpenAI-compatible endpoint, or Ollama.
- **An app, not a terminal.** Chats with live tool results, one view of everything running in the
  background, notifications, and an option to start at login.
- **Your data stays yours.** Chats, keys and settings live in your own user profile. The app talks to its
  engine over a private local connection, never a network port.
- **Bring your Odin setup.** If you already run Odin, *Import from Odin* previews its memory, skills, MCP
  servers, personality, hosts and model settings, and never overwrites anything already there.

## Install

| Platform | Get | Notes |
|---|---|---|
| **Linux** x86-64 | `.deb` or AppImage | Cinnamon/X11, GNOME/Wayland, KDE/Wayland and Hyprland. Computer use works on X11. [Install on Linux](docs/user/install.md) |
| **Windows 11** 64-bit | `odin-desktop-<version>-x64-setup.exe` | Installs for your account only, without administrator rights, and is signed by Aaron Charpentier. Computer use isn't available on Windows yet. [Install on Windows](docs/user/install-windows.md) |

Check each file's SHA-256 against `SHA256SUMS` on the release page before installing. macOS and ARM builds
aren't available.

## Odin or Odin Desktop?

[**Odin**](https://github.com/Calmingstorm/Odin) is the agent as a Discord bot with a web management UI,
for a server or a team. **Odin Desktop** is the same agent for one person, on their own computer. You can run
both side by side, and neither changes the other.

## Guides

Start with [First run](docs/user/first-run.md).

| Guide | Covers |
|---|---|
| [Chat and results](docs/user/chat-and-results.md) | Conversations, attachments and knowledge, steering and stopping, saving results, finding earlier messages |
| [Settings](docs/user/settings.md) | Models and providers, personality, tools, skills and MCP servers, SSH hosts and privacy |
| [Background work](docs/user/background-work.md) | Finding running work, schedules, close, sleep and Exit, stored results |
| [Recovery](docs/user/recovery.md) | Unknown outcomes, skills or servers that won't work, window or engine loss, rollback |
| [Updates](docs/user/updates.md) | Finding releases, upgrading and rolling back |
| [Accessibility](docs/user/accessibility.md) | Keyboard use and screen readers |
| [Command-line client](docs/user/command-line-client.md) | Sending a prompt to the running app from a script |

## Contributing, security and license

PRs are welcome: read [Contributing](CONTRIBUTING.md) first. Report security problems privately through
[Security](SECURITY.md), not a public issue. The [maintainer index](docs/development/README.md) covers the
development process and design decisions. Odin Desktop is [MIT licensed](LICENSE).
