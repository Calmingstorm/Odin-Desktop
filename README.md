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

## User guide, first draft

These are **unreleased implementation docs**, not a release announcement or final acceptance certificate.
Start with [Installation](docs/user/install.md), then [First run](docs/user/first-run.md).

| Guide | Covers |
|---|---|
| [Chat and results](docs/user/chat-and-results.md) | Conversations, attachments versus knowledge, control receipts, files, reports and expiry |
| [Settings](docs/user/settings.md) | Providers, models, tools, managed SSH, state and privacy |
| [Background work](docs/user/background-work.md) | Work owners, schedules, sleep/Exit and inbound integrations |
| [Recovery](docs/user/recovery.md) | Missing receipts, keyring/core failures, unknown effects and quarantine |
| [Updates](docs/user/updates.md) | GitHub Releases, notice-only checks, manual upgrades and maintenance |
| [Accessibility](docs/user/accessibility.md) | Keyboard tasks, screen-reader expectations and unqualified native rows |
| [Linux release checklist](docs/release/linux-v1-checklist.md) | P4.5/P4.6 gates and required owner approvals |

Desktop runs its own local engine and profile. Managed SSH is supported; a phone client, client for an existing
Odin server, and import of an Odin installation are **not** Linux v1 features. An alongside install does not adopt
the other installation's configuration, history or credentials. Windows/macOS remain future-platform work.

## Documentation watermark

Inspected **2026-10-06**. Main source: `0b7d596f7e870d06699722f151c4d9837c5433f1`.
Behavior from the following open review branches is labeled **pending: #N** in the relevant guide sections.
A pending section is not shipped behavior or proof that its PR will be approved unchanged.

| Pending PR | Inspected head | Sections affected |
|---|---|---|
| [#28](https://github.com/Calmingstorm/Odin-Desktop/pull/28) | `2d91071a692a646b6d8c466daa5711a37cd8c93f` | Skills/MCP/browser/computer services and recovery limits |
| [#37](https://github.com/Calmingstorm/Odin-Desktop/pull/37) | `4ede9e75fb079a0a305c7b24f89700d7fb7c4416` | Background work, schedules, stored reports and expiry |
| [#42](https://github.com/Calmingstorm/Odin-Desktop/pull/42) | `50f90306176dd2abd724a1a2d5b97199d294b9c8` | Inbound webhook-triggered schedules; receipt-local uncertainty, not a trigger-wide pause |
| [#36](https://github.com/Calmingstorm/Odin-Desktop/pull/36) | `30402eb95154d9a4d3076fb5cae165771d4aee36` | Ownership, compatibility, upgrades/rollback and removal |
| [#39](https://github.com/Calmingstorm/Odin-Desktop/pull/39) | `1c48529b0af3ad18d9c413882166cb6ee40702d1` | Release notice, private-repo checks and publication handoff |
| [#40](https://github.com/Calmingstorm/Odin-Desktop/pull/40) | `6321eec26e1c87dd5b9682e902723818a5fdda03` | Step-five settings/management completion |

#28 advanced during drafting to `dda129d8f0597d12dbb16837baa5b84ec1c866dc`, integrating main's lifecycle
and retaining MCP teardown failures. This guide keeps its explicitly cited earlier #28 feature snapshot;
the new integration qualification is not inherited by the draft. #42's changed receipt-recovery semantics
were re-read and its documentation watermark updated above. These sources are not a merged combined candidate.

The frozen upstream baseline is **Odin v4.13.0**, source
`cd7530906e9cfa10a0fa900247d7ce2a8bb33e25`. The last upstream review watermark is **baseline only**:
no post-baseline port decisions are recorded in [the baseline](maintenance/baseline.md).
Desktop adaptations and retained/deferred/retired contracts require their own reviewed evidence. A green test
count never establishes an "identical engine", current upstream parity, native qualification or release approval.

Final procedures must be followed on immutable candidates in isolation under
[P4.4 to P4.6](docs/work/phase-3-app-v1.md). This first draft does not authorize active-desktop testing,
publication, repository visibility changes, migration of a real profile or service replacement.

## How we work

See [`CONTRIBUTING.md`](CONTRIBUTING.md). In short:
- code goes through PRs with cross-review (Odin reviews Claude's, Claude reviews Odin's);
- no work in the Odin repository;
- tests run only in an isolated PID namespace;
- commits carry no attribution trailers.
