# PR38 round 1: restore real owner skill Test

## Source and prerequisite

- Review: `/home/odin/reviews/desktop-pr38-review.md`, P2/D2.
- Qualified executable/app/test/ledger tree:
  `7c82dbc523390a033e104ff845c6fcbf3227489b`.
- Merged prerequisite PR28 head:
  `2d91071a692a646b6d8c466daa5711a37cd8c93f`.
- Two-parent merge, never a rebase or force-push. PR28 and PR38 were not merged
  through GitHub by this task. PR38 remains based on `phase-2/services-part-a`;
  reviewer owns its eventual retarget after PR28 merges.
- Fresh detached checkout: `/home/odin/desktop-pr38-review1-final`, mode 0775.
- Raw logs, screenshots and JSON: `/home/odin/desktop-pr38-review1-evidence/`.
- This evidence commit changes documentation only after qualification.

`skills.test` is now in the 6A service's advertised methods and outside its read
methods. The sealed transport owner is required before the retained
`SkillManager.execute(name, {}, requester_id=owner)` runs. Chat's execution
scope preserves inherited tool and live host authorizers; no caller parameter
grants identity/scope and no conversation delivery admission is fabricated.

Unknown skills return `not_found`. Disabled skills return the retained disabled
result without execution. Successful and failed results return `result` and
`is_error`, using exactly Odin's two prefixes (`Skill error:` or `Skill '`).
Responses, including exceptions, are scrubbed and bounded to 50,000 characters;
no traceback is returned. Cancellation propagates with scope cleanup. Durable
command receipts prevent a same-ID repeat from executing again.

The app's existing capability-based unavailable notice remains for a core that
does not publish `skills.test`. It is absent for this capable core; other Skills
management stays usable in either case.

## Fresh post-merge gates

Setup: Python 3.12.3, `uv sync --frozen --extra dev` with copy link mode; Node
22.23.3, `npm ci --ignore-scripts`, explicit pinned Electron installation. No
system packages installed. Each engine gate ran as unprivileged `odin` in a
separate PID/mount namespace with private HOME/XDG and no live credentials or
desktop environment. Electron used Xvfb; accessibility/onboarding additionally
used private session buses. Tracked checkout remained clean afterward and a
post-gate process check found no checkout-owned Electron/core/MCP child.

| Gate | Observed result |
| --- | --- |
| `npm run check` | typecheck/build pass, **669 tests in 69 files passed** |
| `npm run smoke` | fixture smoke passed, PNG retained |
| `npm run test:real-core` | **26 real-core contract tests passed**, plus inherited **6 onboarding tests passed** |
| `npm run smoke:real-core` | passed, ready real core, **20 rendered checkpoints** |
| `npm run test:a11y` | **16 passed**, no skipped/flaky/unexpected tests |
| Reviewed step-6A qualification group | **181 passed** |
| Receipt-retention and phase-2 plan suites | **50 passed**: 20 receipt, 30 plan |
| Drift / lint / ownership / suite map | zero drift errors; zero new lint findings, seven inherited; ownership and suite accounting pass |

The full 31-group engine qualification was not rerun by this slice-4 fix. Lane7's
fresh base qualification is separate evidence, not substituted for these gates.
335 exact-byte record reviews remain pending; no independent approval is forged.

## What Test actually showed

The smoke validates/saves/reads `slice4_constant`, observes zero executions, then
tests through the named preload bridge. The response is exactly
`{"result":"harmless constant","is_error":false}` and execution count becomes
one. It then opens the real editor and clicks its enabled Test button. The
rendered result is `harmless constant`, no warning class or unavailable notice,
and the card shows **2 runs**. Readback confirms exactly two executions, not a
fixture response or an automatic retry. The log records:

`skills.test result="harmless constant" is_error=false rendered="harmless constant" runs=2`

`final-real-evidence.json` retains the bridge response, final skill readback and
the complete Skills rendered text. The final screenshot visibly verifies the
Loaded card, enabled Test control and 2 runs; the editor result lies below that
viewport and is verified by DOM/text assertions and the retained JSON, not by
claiming unseen screenshot pixels. Accessibility also invokes Test by keyboard
and checks its output and one genuine execution.

The local stdio MCP handshake/discovery/refresh still succeeds. Browser remains
disabled/not-ready for this disposable profile. Computer reports no session,
unsupported/unqualified input, and `dispatch:none`. The profile keyring is
unavailable and provider generation is not qualified; that does not block this
harmless local skill. Smoke deletes its skill/MCP fixtures before normal exit.

## Earlier failures and limits

Premerge initial real-core runs exceeded the old complete-suite 120-second
runner deadline. A focused attempt also received `no_receipt` for disabled Test
under the harness's three-second durable-write wait. Retained logs:
`premerge-real-core-retry.log`, `premerge-real-services.log`; the first initial
tool result is retained by tool evidence. Test-only bounds were changed to a
300-second whole-suite deadline and ten-second receipt wait. Production Broker
timeouts and no-replay behavior did not change. The premerge full contract run
then passed 26/26; all fresh post-merge gates above passed on their first run.

Dependency installation reports inherited packaging dev-dependency audit
findings: **11 vulnerabilities (10 high, 1 critical)**, plus deprecation and
git-integrity warnings. These are not a clean security-audit claim; no blind
`npm audit fix` or lockfile upgrade was performed in this feature correction.
Isolated portal/FUSE/session-bus diagnostics remain in graphical logs without
skips or failed cases. No full P3.1, native input, packaged browser, spoken
screen-reader/Orca/Wayland or successful provider-generation claim is made.

Read-only independent review found no blocking regression in the fix, while
noting two narrower coverage limits: no new admitted nested host-read withdrawal
case, and no new Test-specific pending/interrupted receipt case beyond shared
journal protections. Existing owner/scope/cancellation and completed receipt
replay coverage is concrete, not substituted with documentation assertions.

No deployment, service restart, active-desktop change, `/opt/odin` write, live
account, remote MCP endpoint or upstream-repository modification occurred.

## Final artifact hashes

| Artifact | SHA-256 |
| --- | --- |
| `final-check.log` | `7ba7c814c8f17d0e041df0acf1b20df599d3eec881de127364c4db04808a577d` |
| `final-fixture-smoke.log` | `7a4b128ae5b9f3cf469ea87afa6b41f164cc2f4e652e213c06c3cc7963b6b4e6` |
| `final-real-core.log` | `de17c557b6ca46cc34f480ca9d76f87bde01a58c17cae937453b40cd6cc3f5a1` |
| `final-real-smoke.log` | `53bc4dd290c56ee34f925bbfaf6f3b731252b69b36339bece513e83f49b13cde` |
| `final-a11y.log` | `f83c452448e3dc0be630d771621e63b6d245f054a6610fdef34e37d9281ed10c` |
| `final-6a.log` | `420f16da6e9693da300b6bbe5cb1e22ff780f3756897d69acfa9f3ceb09e6c9c` |
| `final-receipts-plan.log` | `ad67b7c9da938c70d1f64f623e4d6f55c8420744e62c9789e44f7802d2a14772` |
| `final-real-evidence.json` | `59516f16a7f2326bcd8db72c5afb37a3975c76f3ed554d6208dbd8fb27163ee3` |
