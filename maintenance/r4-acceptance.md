# P4.5 groundwork: R4/CC acceptance inventory

Evidence watermark: `main@cd52a8e2b055a9c4abc051a49566b9daf3e1bd79`,
2026-10-06. This is a map of existing component evidence and missing acceptance,
not a final run or release authorization. **No case is passed or ready for the
final run: 25 partial, 4 no_evidence.**

`r4-acceptance.json` preserves all 29 section-5 scenarios verbatim. CC-19 is
the entire original prose paragraph, including line breaks, with its gate owner
derived from that paragraph. Environment lists describe requirements, not
environments already qualified. Headless fixtures, integrated original-core
tests, private-Xvfb native receivers, actual desktop sessions and packages remain
distinct. Empty lanes are visible gaps, not automatically required for every row.

**Pending is not evidence accepted on main.** Only exact `pending: #N` pointers
identify open PRs. A pending-only record remains `no_evidence`; `partial` needs
at least one current tree/manifest pointer. `ready_for_final_run` requires current
evidence and no pending pointers/unresolved notes; it still never means passed.
The reporter refuses `passed` even if a hash is supplied. Actual passes belong
to the later final candidate run with hashes and environment, not this schema.

## Gap list

| Case | Status | Principal outstanding qualification |
|---|---|---|
| R4-01 | partial | Real-app attachment/type/input/progress/cancel matrix; final D14 PDF cases |
| R4-02 | partial | Visible concurrent conversation isolation and immutable child cutoff on packages |
| R4-03 | partial | Real-app Steer/Stop/unknown receipts and stale successor controls |
| R4-04 | partial | Workflow/report/artifact catch-up and packaged lifecycle loss matrix |
| R4-05 | partial | Actual combined compaction/reload/restart, files and expiry/history distinction |
| R4-06 | no_evidence | Pending #37/#47; closed-window schedules, VM sleep/wake/exited native delivery |
| R4-07 | partial | Lost-ack submission/reconnect and report paging with one counted effect |
| R4-08 | partial | Rerun actual upgrades/replacement/alongside acceptance on final hashes/bases |
| R4-09 | partial | Complete original corpus/D19/admin closure and final bundle/native scans |
| R4-10 | partial | Windows/macOS remain deferred under D15; Linux absent-capability package evidence |
| CC-01 | partial | Real-app lost/expired-ack identity reconciliation on final candidates |
| CC-02 | partial | Visible stale app Stop/Steer against successor request/generation |
| CC-03 | partial | Final packaged crash-after-dispatch, visible unknown and unchanged effect count |
| CC-04 | partial | Visible real-app outbox repair without tool invocation |
| CC-05 | partial | Packaged Resume budgets/checkpoint/current-policy and missing-input refusals |
| CC-06 | partial | Real-app immutable inheritance after parent mutation/deletion |
| CC-07 | partial | Actual compaction/restart with visible file/history preservation |
| CC-08 | no_evidence | Pending #37/#47; durable closed-window schedule destinations |
| CC-09 | partial | D11 packaged descendant/native-input loss, helpers and release receiver proof |
| CC-10 | partial | Actual native tray/no-tray, login startup and all installed Exit routes |
| CC-11 | no_evidence | Pending #37; D12 VM sleep/offline/exited deadline/lease recovery |
| CC-12 | partial | Combined slow-client reset/snapshot, no stale optimistic state/effect replay |
| CC-13 | partial | Final app/native scope revocation and cursor/alias target continuity |
| CC-14 | partial | Integrated management unavailable reasons and final bundle/backend readiness |
| CC-15 | partial | Final real credentials/default-host/no-import alongside proof on supported bases |
| CC-16 | partial | Final incompatibility/upgrade matrix and pending #39 can't-check rehearsal |
| CC-17 | partial | Full inherited suites/D19 prompt/request/result/guard/data/budget closure |
| CC-18 | partial | Pending #50 KDE Attach/Save 6/7; Ubuntu 24.04 user-namespace gate; D11 final native/security matrix |
| CC-19 | no_evidence | Pending #42; isolated peers and packaged D10 bind/auth/replay/lifecycle/settings |

Every applicable row also needs the final hash-bound Linux candidate execution.
The complete notes and per-lane pending pointers are emitted by
`python scripts/qualification/release.py report`; `--root <checkout>` selects
an offline tree. Exit 0 means **valid inventory**, never passing acceptance.
Invalid ID coverage, source text, evidence path/test selector/manifest, premature
pass or inconsistent status returns 1 before printing any gaps.

Test selectors resolve Python declaration node paths or literal JS/TS test
declaration titles, including source templates. They are source mappings, not
collected runtime parameter IDs or executed test results. Manifest selectors use
`manifest.json::artifact-id`, requiring one matching artifact with path/SHA-256.
Bare tree files can identify an evidence-manifest path. External raw artifacts
are never opened by the report, and their mere presence is not a fresh run.

`r4-evidence-manifest.json` preserves pointers to merged #36's actual earlier
P4.2 Incus/package and clean-Exit reports. Their SHA-256s were checked against
the retained files while preparing this inventory; no package gate was rerun.
They are neither final P4.5 candidates nor native D11 acceptance. Pending #49's
fixture ownership changes are separate from pending #54's Ubuntu guest sandbox
qualification. #54's installed deb GUI launch timed out with UnknownVizError;
its AppImage refusal is honest, not a successful GUI launch. Ubuntu stays open.
Pending #50's independent KDE portal comparison supports a guest/system-side
registration limitation; its precise cause and general KDE behavior remain
unproved. Neither gap is waived.

`app/test/e2e/r4.spec.ts` and `desktop-acceptance.yml` are intentionally not added.
No native/VM/package run, listener, publication, install, service change or
active-desktop input belongs to this groundwork.
