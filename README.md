# Odin Desktop

A standalone desktop application for [Odin](https://github.com/Calmingstorm/Odin), the self-hosted AI execution agent.

**Status: implementation, Linux v1.** Aaron approved the design and authorized the build on 2026-10-04. Decisions
D1 to D16 are in the brief. Work follows [`CONTRIBUTING.md`](CONTRIBUTING.md). Work orders are in `docs/work/`.

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

## How we work

See [`CONTRIBUTING.md`](CONTRIBUTING.md). In short:
- code goes through PRs with cross-review (Odin reviews Claude's, Claude reviews Odin's);
- no work in the Odin repository;
- tests run only in an isolated PID namespace;
- commits carry no attribution trailers.

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
