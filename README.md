# Odin Desktop

A standalone desktop application for [Odin](https://github.com/Calmingstorm/Odin), the self-hosted AI execution agent.

**Status: design phase.** This repository holds design documents only. It contains no code, and none will be written
until Aaron approves a plan.

## What Odin Desktop is meant to be

- A desktop app that runs on your own machine and can start automatically at login.
- Installable on its own or alongside an existing Odin install, without conflicts.
- A chat experience at least as capable as talking to Odin on Discord, and ideally better.
- Linux first, with Windows and macOS clients later.
- Built mostly from Odin's existing code, at feature parity or better. It leaves out what doesn't apply on a personal
  desktop, such as multi-user access control and the Discord bot machinery.

## Layout

| Path | Contents |
|---|---|
| `docs/design/` | The living design. Each file is owned by one author and kept current. |
| `docs/discussion/` | Numbered discussion rounds between Claude and Odin (`NN-author-topic.md`). Each file is written once and not rewritten. |

Start with [`docs/design/00-brief.md`](docs/design/00-brief.md).

## How we work during design

- Documents only. No code, prototypes, dependency installs or build tooling.
- Each author commits only the files they own or the round file they are writing. Run `git pull --rebase` before
  pushing.
- Commit messages carry no attribution trailers.
