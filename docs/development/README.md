# Odin Desktop maintainer index

This index separates development process and historical qualification status from the
[product README](../../README.md) and [user guides](../user/install.md).

## Authorization and decisions

Aaron approved the Linux v1 design and authorized the build on 2026-10-04.
Decisions D1 to D16 are recorded in the [brief](../design/00-brief.md).
Work orders live in [`docs/work/`](../work/); the living design is in
[`docs/design/`](../design/). Named authors keep their design files current.
Numbered discussion rounds between Claude and Odin live in [`docs/discussion/`](../discussion/)
as `NN-author-topic.md`; each round is written once, not rewritten.

## Repository layout and maintenance ownership

| Path | Contents | Maintainer ownership |
|---|---|---|
| `src/`, `tests/` | Engine at Odin's module paths so upstream fixes port as the same diff | Odin |
| `maintenance/` | Baseline, source manifest, port ledger, safety manifest and retained summaries | Odin |
| `scripts/maintenance/` | Drift-report and manifest tooling | Odin |
| `app/` | Electron main process, preload bridge and renderer | Claude |
| `docs/design/` | Living approved design | Per-file owner |
| `docs/discussion/` | Immutable numbered discussion rounds | Round author |
| `docs/work/` | Work orders and acceptance decisions | Task owner |

## Maintainer process

The public contribution and test-safety rules are in [CONTRIBUTING.md](../../CONTRIBUTING.md).
For the named-agent workflow, Odin reviews Claude's PRs and Claude reviews Odin's.
Nothing merges without cross-review. Design documents may be edited directly on `master`
only by their owner. Commits have no attribution trailers or session footers.
All product work stays in this repository; it does not authorize changes to the upstream
Odin repository, a live install, or an active desktop session.

CI uses the maintainer's self-hosted infrastructure. Fork PRs never enter these runners.
After review and maintainer approval, a maintainer may bring reviewed changes onto an
in-repository branch; non-draft PRs from this repository and pushes to `master` can run CI.
A workflow condition alone is not an approval record. Draft PRs remain outside the runner lane.
Release dispatches, including dry-run, are Calmingstorm-only. Repository visibility and
GitHub protection settings remain a separate operator action, not a consequence of these docs.

## Documentation and qualification status

User guides describe merged behavior with plain limitations rather than development provenance.
Source watermarks, pinned references, claim checks and historical gate results live in
[P4.4 validation](../../maintenance/p44-user-docs-validation.md).
The [documentation status](../release/pending-user-docs.md) records promoted guidance
and remaining dependencies. Background work, schedules/reports, provider/knowledge/record
administration, ingress, manual release notices, orderly shutdown/reboot/logout, fresh Wayland
launch, boot-scoped package-change fences and bounded Exit during core startup (#96) have
merged guidance. Import from Odin is also part of the 1.0 user interface.

The upstream review remains **baseline only** at Odin v4.13.0; later changes are not implied.
Full identities remain in the validation and [baseline record](../../maintenance/baseline.md).
A green test count does not prove an identical engine, current upstream parity, native
qualification or release approval.

The [Linux release checklist](../release/linux-v1-checklist.md) supersedes the earlier Phase 3/4
release blockers under [Decision I](../work/phase-3-app-v1.md#decision-i-lean-v1-release-gate).
It requires evidence for the exact candidate and Aaron's separate publication approval.
Historical qualification reports do not certify a later package. Do not fill evidence boxes
from earlier test counts or treat documentation as authorization for active-desktop testing.
