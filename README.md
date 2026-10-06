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
| [Chat and results](docs/user/chat-and-results.md) | Conversations, attachments versus knowledge, control receipts, files and expiry |
| [Settings](docs/user/settings.md) | Providers, models, tools, managed SSH, state and privacy |
| [Background work](docs/user/background-work.md) | Current work visibility, receipts, close/sleep/Exit and evidence expiry |
| [Recovery](docs/user/recovery.md) | Missing receipts, keyring/core failures, unknown effects and quarantine |
| [Updates](docs/user/updates.md) | GitHub Releases, manual upgrades, compatibility and maintenance |
| [Accessibility](docs/user/accessibility.md) | Keyboard tasks, screen-reader expectations and desktop limits |
| [Linux release checklist](docs/release/linux-v1-checklist.md) | P4.5/P4.6 gates and required owner approvals |

Desktop runs its own local engine and profile. Managed SSH is supported; a phone client, client for an existing
Odin server, and import of an Odin installation are **not** Linux v1 features. An alongside install does not adopt
the other installation's configuration, history or credentials. Windows/macOS remain future-platform work.

## Documentation watermark

The user guides describe merged `main` behavior, with plain limitations rather
than development provenance. Maintainer source watermarks, pinned references,
claim checks and historical gate results live in
[P4.4 validation](maintenance/p44-user-docs-validation.md).
Drafted guidance for still-open integrations is kept separately in
[pending user docs](docs/release/pending-user-docs.md), not presented as usable
features in `docs/user/`. Ownership/upgrades/removal from #36, attachment intent
from #46, and #28 service management are now included from merged main. Computer
management still does not grant foreground input authority.

The upstream review remains **baseline only** at Odin v4.13.0; later changes are
not implied. Full internal identities are in the validation and
[baseline record](maintenance/baseline.md). A green test count does not prove an
identical engine, current upstream parity, native qualification or release approval.

Final procedures still require immutable isolated candidates under
[P4.4 to P4.6](docs/work/phase-3-app-v1.md), and the
[release checklist](docs/release/linux-v1-checklist.md) retains Aaron's approvals.
This draft does not authorize active-desktop testing or publication.

## How we work

See [`CONTRIBUTING.md`](CONTRIBUTING.md). In short:
- code goes through PRs with cross-review (Odin reviews Claude's, Claude reviews Odin's);
- no work in the Odin repository;
- tests run only in an isolated PID namespace;
- commits carry no attribution trailers.
