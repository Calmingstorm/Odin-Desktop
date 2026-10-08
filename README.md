# Odin Desktop

A Linux desktop app for [Odin](https://github.com/Calmingstorm/Odin), the self-hosted AI execution agent.
Chat with your configured model, run tools locally or over managed SSH, and keep conversations,
knowledge and background work in your own Desktop profile. Desktop runs its own local engine;
it does not require a separate Odin server or Discord account.

## Install

Download an **x86-64 `.deb` or AppImage** from
[Releases](https://github.com/Calmingstorm/Odin-Desktop/releases), read the release notes,
and compare the file's **SHA-256** with the published value for that exact file before installing.
The packages are **unsigned**: a matching checksum detects changed bytes, not an independent
publisher signature. Follow [Installation](docs/user/install.md) for package, keyring and sandbox requirements.

Supported sessions are **Cinnamon/X11, GNOME/Wayland, KDE/Wayland and Hyprland**.
**Computer use is X11 only**; Wayland computer use is planned for **1.1**.
Windows, macOS and ARM builds are not supported in 1.0.

Desktop can be installed alongside Odin without adopting its state automatically.
**Import from Odin** previews selected supported settings, memory and skills from an existing
installation; it is not a history or credential migration. See [Settings](docs/user/settings.md).

## User guide

Start with [Installation](docs/user/install.md), then [First run](docs/user/first-run.md).
These guides cover **1.0.0**; release-specific limitations belong to that version's release notes.

| Guide | Covers |
|---|---|
| [Chat and results](docs/user/chat-and-results.md) | Conversations, attachments versus knowledge, control receipts, files and expiry |
| [Settings](docs/user/settings.md) | Providers, models, tools, managed SSH, state and privacy |
| [Background work](docs/user/background-work.md) | Current work visibility, receipts, close/sleep/Exit and evidence expiry |
| [Recovery](docs/user/recovery.md) | Missing receipts, keyring/core failures, unknown effects and quarantine |
| [Updates](docs/user/updates.md) | GitHub Releases, manual upgrades, compatibility and maintenance |
| [Accessibility](docs/user/accessibility.md) | Keyboard tasks, screen-reader expectations and desktop limits |
| [Linux release checklist](docs/release/linux-v1-checklist.md) | 1.0.0 release checks, supported scope and publication approval |

## Contribute and report problems

PRs are welcome. Read [Contributing](CONTRIBUTING.md) before running tests; process tests
require isolation, and fork PRs do not run on the maintainer's self-hosted runners.
Report security problems privately using [Security](SECURITY.md), not a public issue.
The [maintainer index](docs/development/README.md) holds development process, design decisions,
repository layout and qualification status. Desktop is [MIT licensed](LICENSE).

## Optional local prompt client

The client connects to an already-running selected profile. It never starts a
core, authenticates through that profile's private Unix socket and token file,
and prints only a committed guarded reply. Supply `--socket`, `--token-file`,
and `--profile`, then a positional prompt or `--prompt`. With no prompt argument,
noninteractive stdin supplies piped text. `--conversation` continues an existing
conversation; otherwise the client creates one. `--timeout` bounds the wait and
`--json` emits structured outcome, conversation/request IDs and response text.
Timeout is not cancellation and never retries admitted work.

Use `--method status.get` for diagnostics. Positional `status.get` remains the
legacy diagnostic spelling; use `--prompt status.get` to submit that exact text.
The optional client is `python -m src.cli`; it is not the core's supervised
`python -m src` entry. No HTTP listener, URL token, Discord gateway or daemon
argument compatibility is reintroduced.
