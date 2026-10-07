# P4.4 merged user-doc promotion, 2026-10-07

Task: `/home/odin/reviews/desktop-p44-docs.md`, request `req-0120eb63`.
Branch: `docs/p44-user-docs-update`. Pulled main before branching:
`aa3d61b3043ea47805686c185133a53c54b127fc`.
This is a docs-only update, not P4.5/P4.6 acceptance, publication permission or a
new native/candidate walkthrough. Product code, test assertions, dependencies,
protocols, CI and the parallel #59/#96/#97/#98 lane files are unchanged.

## Integrated claim map

All source links below name the integrated main watermark, not former branch
heads. Exact route/control/source review does not establish new native execution.

| Promoted claim | Integrated source and boundary |
|---|---|
| Real Work column, schedules and reports (#37) | [Core composition](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/src/desktop/core.py), [Work column](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/app/src/renderer/src/components/WorkPanel.vue), [schedule controls](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/app/src/renderer/src/views/settings/Work.vue), [stored reports](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/src/desktop/reports.py). Current history distinguishes Unknown/Not run. Deleted schedule history is retained despite the dialog's wording; report reads are profile-owner authorized, not a promise of the archive's broader tool/host-scope model. |
| D12 missed-run policy | [Recovery](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/src/desktop/schedule_recovery.py), [scheduler](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/src/scheduler/scheduler.py). Coalesced reminders, explicit missed-action run, no local execution while exited. Native evidence limits below. |
| Account/provider administration and shared knowledge (#40) | [Service wiring](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/src/desktop/services.py), [management](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/src/desktop/management.py), [knowledge UI](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/app/src/renderer/src/components/KnowledgeDetails.vue). Settings/model tools share a store; attachment intent is not automatic ingestion or guaranteed later retrieval. Merge deletes the other source without copying content. |
| Records and observability (#40) | [Record controls](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/app/src/renderer/src/components/RecordDetails.vue), [observability](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/app/src/renderer/src/components/ObservabilityDetails.vue). Tails are bounded reads; pool close affects SSH connections, not host trust or prior effects. |
| Ingress and privacy (#42) | [Ingress UI](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/app/src/renderer/src/components/WebhookIngress.vue), [handoff recovery](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/src/desktop/webhooks.py). Source/secret save separately; drafts clear; unknown is receipt-local, not identical-body deduplication or exactly-once effects. |
| Manual notice (#39) | [Notice service](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/app/src/main/release-notice.ts), [UI](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/app/src/renderer/src/components/ReleaseNotice.vue). Manual anonymous request, truthful private-repo refusal; never download/install/apply. |
| Boot-scoped package fence (#89) | [deb hooks](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/app/packaging/deb_transaction.py), [shared ownership](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/app/packaging/ownership.py). Busy refusal leaves package installed; restart lifts valid earlier-boot ownership fences, not missing evidence, interrupted transactions, effect history or native quarantine. Exact restart message is deb-specific; AppImage may report unresolved lifetime evidence. |
| Shutdown/reboot/logout (#90/#94), fresh window (#95) | [App lifecycle](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/app/src/main/index.ts), [logout adapters](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/app/src/main/session-logout.ts), [session monitor](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/src/desktop/session_end.py). Bounded Exit before teardown, query/cancel does not Exit, integrations fail open. Manual launch shows; login start stays hidden. Initial-startup Exit fix remains **pending: #96**. |
| Raven controls and Orca limits | [Rail](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/app/src/renderer/src/components/IconRail.vue), [conversation controls](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/app/src/renderer/src/components/ConversationList.vue), [accessibility evidence](phase3-accessibility.md). Native Raven: Cinnamon 7/7, GNOME 7/7, KDE 6/7; KDE Attach/Save remains unqualified. |
| Actual Skill Test, retained computer management | [Skill service](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/src/desktop/skills.py), [computer binding](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/src/desktop/computer_binding.py). Test executes loaded skill with empty input and can have effects; it is not validation. Foreground owner binding does not publish usable native input or turn background work into input authority. |

Former pending #37/#39/#40/#42 drafts are moved to the
[historical archive](../docs/release/p44-user-docs-historical-drafts.md).
The [current status](../docs/release/pending-user-docs.md) and
[release checklist](../docs/release/linux-v1-checklist.md) distinguish feature
promotion from unfinished acceptance. No historical assertion is silently
upgraded into current runtime proof.

## Native evidence reused, not rerun

Read `/home/odin/reviews/p33-native-results-20261007.md` and retained copies of
the three D12 logs: Cinnamon, KDE and the GNOME `gnome-check` run that includes
checks, not just reminders. All logs show normal check firing, a 240-second
VM freeze/thaw, one catch-up reminder and checks only at subsequent normal slots,
then zero Odin processes after Exit and a later reminder catch-up on relaunch.
Their freeze/thaw is a VM sleep/wake approximation, not proof of every actual
guest suspend path. They do not qualify a fresh package from current main.

The cited native report identifies prior compositions: v3 `0ed8ca6` plus
#89/#90/#91 for shutdown; v5 `61d70cb` plus #89/desktop-name for first-window
and GNOME D12; v6 `61d70cb` plus #89/#95/#94 for logout, KDE/Cinnamon D12.
Exact candidate source/hashes remain in the original
`/home/calmingstorm/odin-desktop-evidence/fence-session-end-20261007/`
candidate receipts. No recomposed main candidate is claimed from those results.

Native walkthrough was not attempted: the shared lab lock belonged to
`p33 2026-10-07T16:26:57Z GNOME missing rows req-7747a619`, and read-only
`sudo -n incus list` showed only `odq-gnome` running. The checklist contains
ready-to-run install, first-run, no-tray/login, keyboard/results/privacy,
recovery/update/uninstall and notification procedures, left unchecked.
No acquisition/release of another lane's lock or VM state change.

## Pending items

- **pending: #96**: initial core-startup Exit, still under review.
- **pending: #59**: remaining real notifications/click-through, GNOME controls,
  different-version upgrade and query/cancel logout rows.
- **pending: #98**: P3.5 native receiver/loss/release/quarantine/helper gate;
  PR opened during this update and reports a blocked native gate.
- **pending: #97**: D11 matrix and Phase 3 closure/final immutable candidates.
- **pending: #59 / #97**: candidate-bound P4.4 walkthrough. Provider acceptance
  also requires a separately authorized test account.
- Final FUSE/sandbox paths, KDE native chooser, dependency/security disposition,
  external release protection/rehearsal and Aaron's acceptance/publication
  approvals remain checklist gates, not unmerged-feature claims.

## Checks and evidence

Repository-local dependencies: `uv sync --frozen --extra dev`, Python 3.12.3.
No Node/Electron acquisition or system package installation was needed.
Short gates from main, run once on the updated docs tree:

- Inventory: zero errors. Lint: zero new findings, seven inherited.
- Phase-2 planned ownership and D19 reports passed; all 50 D19 rows dispositioned.
- Phase-2 closure report: ready, zero errors; 150 named inherited-suite deferrals
  remain, not fabricated passes. Static closure is not native/release acceptance.
- Generated tool reference: current exact bytes.
- Cinnamon/GNOME hermetic fixtures: **38 passed**, ordinary UID 1003 behind the
  restricted PID-isolation helper; no graphical session.
- Link-data checker validates local paths/headings and pinned Git objects;
  other external URLs are syntax-only, not anonymous private-repo access.
  Final result: **280 links across 15 files, zero errors** (132 local targets,
  144 pinned Git objects, four external syntax checks). File digests are in the
  external `links.json` receipt.
- Package/lock/input version consistency and docs-only changed paths are data
  checks, not prose assertions. `git diff --check` passed.
- Independent read-only final factual audit: zero actionable findings. Verified
  Raven labels and default MCP wiring: `src/__main__.py` uses no runtime provider;
  the optional runtime manager in `services.py` is absent and management's own
  manager is not published to default chat. This is source inspection, not new
  provider/MCP execution or immutable-candidate acceptance.

No Markdown wording tests or full runtime-suite/native rerun is claimed for this
docs-only change. The first gate invocation could not create its external
evidence directory and ran no gates; creating just this lane's private directory
with authorized sudo resolved the permission issue. Protected D12 logs were
copied read-only to lane evidence after read_file permission refusal. Source
evidence and original ownership were not changed. Several draft patches failed
exact context/envelope validation before applying any writes; no partial edits.

Raw logs, checker, links and borrowed D12 evidence copies live under
`/mnt/storage/odin-desktop-evidence/p44-update-req-0120eb63/`.
The small [artifact manifest](p44-user-docs-update-artifacts.json) records paths,
sizes and SHA-256. Root disk had 206 GB free at admission, above the 60 GB floor.
Only this lane's inactive fresh checkout is removed after push/remote verification;
committed evidence, small logs and other lanes remain. No merge, deploy, restart,
live profile access, active desktop input or attribution trailers.
