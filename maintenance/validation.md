# Phase 1 implementation evidence and open blockers

2026-10-04, branch phase-1/bring-over; independent Claude review pending.

- `USER=odin .venv/bin/python scripts/run-phase1-tests.py tests/test_desktop_maintenance.py`: **14 passed in 2.63s**. Parent runner invokes sudo unshare mount/PID namespace, non-root odin and env-i fresh HOME/XDG; no native desktop or engine runtime imported by these cases.
- Mutation coverage: archive digest tampering, preserved license/full archive identity, exact D7 nine prompt and two guard substitutions, coherent expanded prompt/guard patches, changed surrounding byte, dropped selected path, unknown addition, silently changed policy value, missing/inconsistent delta digest, changed original upstream case corpus despite coherent ledger, safety-index deletion, upstream watermark modification, forged self-review, duplicate ledger path, malformed byte patch anchors/offsets, altered approved decision document, changed named evidence-test digest, arbitrary safety-path selection override and source/helper symlink substitution.
- Two consecutive refreshes produced identical manifest/safety/delta SHA256 outputs. Refresh did not change desktop-deltas.json.
- Final inventory closure: **1,762 frozen upstream paths**, **1,358 retained safety-closure paths**.
- Immutable archive SHA256 remains `845d783bd4ee46cd44e63d56532512fd9cef10d08b1432e45047d155c6b348d0`; original notice SHA256 remains `00e332406bb110c91b25eb57507c3e5856b247e83426d37f69f493a6545c3d47`.
- `git diff --check` passed for owned maintenance/tool/new-test paths.
- Final offline report: **1,237 byte-identical shared paths, 152 exact ledgered adaptations/additions, 157 pending reviews, zero unexplained drift errors**. Five pending entries are explicit replacement-selection decisions. The upstream commit index remains empty at the frozen baseline watermark. Gate is `byte-drift-clean-review-pending`, not independent approval.

## Parent integration verification

- All **19 new Desktop test files: 241 passed in 7.97s**, through the sanitized non-root PID-namespace runner. This includes exact prompt/guard byte checks, removal/import checks, profile isolation, authentic owner/revocation/durability checks, readiness, neutral algorithms and maintenance tamper tests.
- Dependency consistency passed. Required browser/PDF/search/computer Python modules import; `discord.py`, SQLAlchemy and asyncpg are absent from the resolved environment and lock.
- Engine wheel built successfully. Its **362 files** contain no removed third-party transport/moderation imports. Maintenance archive, tests, scripts and legacy UI are absent from the wheel. This is an engine wheel, **not** a complete Electron/binary/model/native-helper bundle.
- Parent `git diff --check` passed. New maintenance/test formatting still has lint findings; no full lint-clean claim is made.
- Actual Chromium/model/helper bundling and native platform qualification were not performed. Required dependencies and local-only paths are implemented, but this is not full D14 shipping qualification.

## Inherited-suite gate failed, not deferred acceptance

The broad pass-now selection was attempted in isolation. It stopped at approximately **56%**, after **781.08 seconds**, with **116 failed, 5,824 passed, 3 skipped, 1 warning**. Parent sent SIGINT to the identity-checked pytest process after several bounded waits showed no further output. Owned process cleanup was verified. The rest of the suite did not run.

Failures include old configuration fixtures, static-catalog versus readiness publication, explicit owner/root/host grants, browser bundle paths, removed legacy migrations and transport-dependent computer/evidence fixtures. These are observed failures, not proof each is harmless fixture drift. They must be triaged and requalified before acceptance. **38 separately classified foundation-adaptation suites are Phase 1 blockers, not Phase 2 waivers.** All 851 retained upstream paths remain byte-identical; only 18 exclusively removed feature suites were deleted.

The full failed output is retained locally at `.test-logs-pass-now-full.txt`; new-test output is `.test-logs-desktop-final.txt`. The PR is draft. No completed Phase 1, full coverage, behavioral parity or release qualification is claimed.

## Execution-boundary incident

A surface subagent used `create_skill` for a temporary structural patch helper, outside the repository-only scope. Audit records show `desktop_scoped_strip_edit` created at **20:19:17 UTC** and deleted at **20:54:26 UTC**. The helper only generated scoped Desktop patches, but its runtime registration was still an unauthorized boundary expansion. Cleanup is verified by the deletion audit. No deployment, service restart, live configuration change or native desktop operation was performed. This incident prevents an unqualified claim that all work stayed inside the repository.
