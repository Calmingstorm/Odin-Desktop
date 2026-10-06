# P4.4 first-draft documentation validation

Date: 2026-10-06. This is documentation evidence, **not P4.5/P4.6 acceptance**, an installer/native matrix pass,
or authorization to publish. The changes add eight user guides, a Linux release checklist and README navigation/status
corrections. No product code, test assertions, protocol, release workflow or dependency pins changed relative to main.

## Source and review watermarks

- Initial main inspected: `0b7d596f7e870d06699722f151c4d9837c5433f1`.
- Main advanced while drafting. Incorporated `288ce7b4bec4774885dde6c0d76aa38fff4f7744` (#25 and #41) with a
  two-parent development-branch merge; no GitHub PR was merged by this work. Its delta is isolation/CI/test-wait and
  packaging-test portability work, not a user-feature release. The docs explain both watermarks.
- Final fresh-checkout execution source: `9ea63666106bd7d912cf95871af98db23fddc6c0`.
  The subsequent commits add this evidence only.
- Open service/ownership/notice branches were read, not merged into a combined test candidate:
  #28 `2d91071a692a646b6d8c466daa5711a37cd8c93f`, #37 `4ede9e75fb079a0a305c7b24f89700d7fb7c4416`,
  #36 `30402eb95154d9a4d3076fb5cae165771d4aee36`, #39 `1c48529b0af3ad18d9c413882166cb6ee40702d1`,
  #40 `6321eec26e1c87dd5b9682e902723818a5fdda03`.
- #28 advanced to `dda129d8f0597d12dbb16837baa5b84ec1c866dc` while drafting. Inspected its lifecycle/MCP teardown
  delta; retained the guide's explicitly pinned earlier feature snapshot, without adopting its qualification claims.
- #42 advanced from `5f6d38fe9d74c2ed3af1461721003b971d6bb911` to
  `50f90306176dd2abd724a1a2d5b97199d294b9c8`. Re-read its changed receipt recovery and updated all #42 source links
  and affected prose. Unknown handoff stays receipt-local and does not pause valid future authenticated deliveries;
  retries/identical bodies can execute again. No body-deduplication or exactly-once guarantee is documented.
- Upstream remains the recorded v4.13.0 baseline `cd7530906e9cfa10a0fa900247d7ce2a8bb33e25`, review watermark
  **baseline only**. No claim of identical engine or current upstream parity follows from these tests.

## Documentation/source review

The guides were traced to actual UI/core/package code rather than the stale app README. Corrected that README's
real chat/request composition, integrated packaged resolver, durability wording, fixture-notification limitations
and onboarding source accounting (six tests/seven launches). Independent read-only source review found the onboarding
accounting issue; it was corrected before the final checkout.

Particular boundaries kept explicit:

- `main` composes real requests/conversations/attachments/results/controls; a fixture is never its unavailable-service fallback.
- The Add to knowledge checkbox is visible but the default engine has no attachment-ingestion handler. The docs
  recommend leaving it unchecked for ordinary attachments, distinguish manual knowledge management, and mark
  shared model-side knowledge wiring pending #40 without claiming that wiring adds the missing handler.
- Report management/page routes remain pending #37. Reports have no documented universal expiry interval;
  retained full tool evidence has a separate fixed 24-hour lifetime and quotas/read authorization.
- Sent/confirmed/consumed/queued/unknown, process/host acknowledgment and receiver/native release proof are separate.
  Acknowledging cleanup does not clear native quarantine or undo effects.
- D12 sleep/Exit/missed actions, native backend limits, unsigned manual update paths, private-repo can't-check,
  unavailable services, uninstall retention and compatibility/rollback limits are not hidden behind passing counts.
- The checklist leaves final native/package/provider procedures open and requires P4.5, P4.6, immediate Aaron
  authorization for supervised active-desktop use and separate publication/version/license/audience approval.

No prose-wording tests were added. Link structure and generated metadata were checked as data:

- Final 11 requested guide/README documents: **267 links**, **zero invalid** local targets/headings/pinned source objects.
  This consists of 201 local targets/anchors, 56 exact pinned GitHub source objects verified through Git,
  and 10 external non-source URLs checked for syntax. Anonymous HTTP access to private GitHub was not claimed.
- `python scripts/docs/generate_tool_reference.py --check`: byte-current generated reference, also checked in the final clone.
- Package/lock/input versions agree: product 0.1.0, Electron 44.5.1, builder 26.0.12, bundled Python 3.12.15,
  Linux x86-64. Source SHA-256 fields were checked for shape, and the acquired Electron executable matches its pin:
  `9155dd17c16f0edeaadb74db4fd91e2730511cca83e8b130d59bab57aa4d4e4b`.
- `git diff --check`: clean. Final source clone stayed tracked-clean after gates.

## Final fresh-checkout gates

Fresh checkout: `/home/odin/desktop-p44-final-20261006`, detached at the execution source above.
Provisioned its own `.venv` with `uv sync --frozen --extra dev`, then `npm ci --ignore-scripts` and the explicit pinned
Electron install procedure. Node 22.23.3, npm 10.9.9, development Python 3.12.3 (not the bundled production interpreter).
No system packages were installed.

All engine/app tests used the reviewed isolated launchers. App/core imports, HOME/XDG, display and bus were private;
the sandbox was retained, tests stayed non-root, and the active workstation display/session/credentials were not inherited.

| Gate | Observed result |
|---|---|
| `launchIsolated('/usr/bin/npm', ['run', 'check'])` | Typecheck/build pass; **737 tests, 76 files passed** |
| `npm run test:real-core` | **21 contract tests passed**, then **6 onboarding tests passed** |
| `npm run smoke:real-core` | Pass; actual real-core diagnostics and **39 screen checkpoints**, honest missing keyring/provider and uncomposed services |
| `npm run smoke` | Fixture regression smoke passed on isolated Xvfb |
| `npm run test:a11y` | **15 passed**, isolated keyboard/axe/Chromium AX; not Orca/native Wayland qualification |
| `npm run test:e2e` | **28 passed, 1 failed**; see failure below. **Not a clean lifecycle qualification** |
| Isolated `tests/test_packaging_runtime.py tests/test_packaging_models.py` | **21 passed** |
| Isolated `python -m unittest discover -s packaging/tests -v` | **48 discovered, 47 passed, 1 skipped**; root dpkg case unavailable under no-new-privileges. No installer proof claimed |

Final lifecycle failure: `admitted-work.spec.ts:40`, initial `waitForCore()` at line 48 exceeded its existing bounded
wait. Snapshot had a running child core, app link connecting and no authenticated incarnation. It failed **before**
the harmless HTTP effect was admitted. The failure is observed startup readiness timing, not proof of a product
regression or a clean no-replay pass. No deadline/assertion changed and no retry is counted as qualification.
The launcher reported failure and verified owned process cleanup. Final native/installed-candidate gates remain open.

After preserving that failure, an unchanged, isolated **diagnostic-only** invocation selected the one failed case
through the existing lifecycle wrapper: `node scripts/lifecycle-e2e.mjs admitted-work.spec.ts --grep 'completes while hidden'`.
It passed **1 case in 9.9 seconds**, with retained evidence under
`/home/odin/desktop-p44-diagnostic-lifecycle-evidence/`. This suggests timing sensitivity, not a demonstrated root
cause. It is not a clean full gate, not an automatic command replay and is not combined into a 29-pass qualification.

The successful a11y gate emitted private-session portal/FUSE/GVFS and bus warnings. They were not suppressed or
presented as successful real portal/keyring evidence. The final package suite's dpkg skip is explicitly not a pass.

## Earlier attempts, retained rather than combined

On the initial `0b7d596f` tree, app check had 693 passes, real-core 21/onboarding 6, both smokes, a11y 15 and lifecycle
29 passed. Those are earlier-tree evidence only; they do **not** replace or repair the final lifecycle failure.

An exploratory inherited Python selection included `tests/test_packaging_behavior.py` and failed collection:
`src.config.package_migrations` is absent on Desktop main. Removing that unadapted suite from a separate explicit
selection produced **28 passed, 2 failed**. The failures were the inherited generated-reference registry-order
assertion and the literal 67-tool count assertion. The generator's exact-byte check passed. No tests, generated
reference or registry were modified to obtain a green result. These attempts are not full qualification and not
combined with the final 21 selected metadata cases.

One initial launcher invocation accidentally supplied an unsupported `--run` CLI argument and exited without doing
work. It is not counted as a gate; the real app check called the exported `launchIsolated()` API.

`npm audit --json` observed **11 locked-graph findings: 10 high, 1 critical**. The checklist and Updates guide require
exact-candidate maintainer/reviewer triage before release. This documentation task neither changes dependency pins
nor waives findings with an unreviewed audit fix.

## Logs and integrity

Full streamed logs remain outside the repository; no credentials/private-history screenshots are attached.
Temporary synthetic smoke images were discarded by the runners. Final log SHA-256 values:

| `/home/odin/` file | SHA-256 |
|---|---|
| `desktop-p44-final-dependencies.log` | `c81d22e9e9386f4dcf70e24be46debda9d4fb5fef8963fa2ab893867c2a9ad5b` |
| `desktop-p44-final-check.log` | `c1a3c6fcbbb83026ef84e1e58e61180ef581b3189a8b083f2fc19a8de1acdebe` |
| `desktop-p44-final-real-core.log` | `80d892b55786350626ba272a928c752c9083255415a9752639015a3577e399d0` |
| `desktop-p44-final-real-smoke.log` | `9414ed71217bc16171f439028b0012b506a690337fceca177fa1c84fbdd5aa4d` |
| `desktop-p44-final-fixture-smoke.log` | `4efe160c43ec69a2e9d47624e355c2894d2d33cef64da3174c5cd55bf1da03b7` |
| `desktop-p44-final-a11y.log` | `7df01ccec2124142fc5a50d01380010fc98c58268f4d9dd03bffdbb4a6177978` |
| `desktop-p44-final-lifecycle.log` | `e3b250e8dd1230fa99cc6d338a180156494124e37893eecad224d0ac343ba274` |
| `desktop-p44-final-metadata-tests.log` | `bf2b69f6fdb1f85cb19d0ea08285fdc67d9e28af9525caadc2378fa56dd2d233` |
| `desktop-p44-final-packaging-tests.log` | `82b11af6a258575111a5a17448196302727d8e376a9276f5074786a864d2a7cf` |
| `desktop-p44-final-lifecycle-diagnostic.log` | `2828fe1300b137de5342a4bde64f59a3831d35d46c9bd58e814f5016cb91ff27` |

Earlier exploratory logs: `desktop-p44-data-tests.log` SHA-256
`6dcec17b40826829a5b83be8341ecbbcc1395d4d968ca2ab179a4e77a9ab54ac`, and
`desktop-p44-data-tests-rerun.log` SHA-256
`2d2c2da7ea695ec08f172d6987f105412ae637ac376b6c69a1b108668e68fbc0`.

## Limits and handoff

This is a complete **first draft**, with source-backed procedures and honest unavailable/pending boundaries.
No new final `.deb`/AppImage was built, no native installer/manual-upgrade/uninstall walkthrough was performed,
no production provider sign-in or generation was attempted, and no native keyring/Orca/login/tray/portal matrix
acceptance is claimed. Reading package metadata is not installed-candidate acceptance. P4.4 procedure validation
against immutable candidates remains an explicit checklist item for the integrated release candidate.

No live service, `/opt/odin`, active desktop session, production credential, installer, repository visibility,
tag, release publication or GitHub merge was changed. PR is for review; no attribution trailers.

## PR #44 review round 1: separate user guidance from provenance

Work order: `/home/odin/reviews/desktop-pr44-review.md`, reviewed original head
`3a83d7f5d0cd3c2294d6958f5e3d62242ad439e1`. Date: 2026-10-06.
The preceding sections remain historical first-draft evidence, not repeated
qualification or current feature claims.

The eight `docs/user/*.md` guides now use task-first language and describe only
merged `main` behavior. Commit identities, source/PR links, pending markers,
review-lane terminology and qualification bookkeeping are kept here and in
maintainer documentation. The only user-facing upstream watermark is the short
paragraph in `install.md`: based on Odin v4.13.0; later changes require release-note
disclosure. That is not current-upstream parity or identical-engine approval.

### Initial integrated source and scope

- Re-read and merged `origin/main` at
  `ed0069674533c23e70a0302652a2fb76901ff385` with two-parent merge
  `d7c245618c42245f46edad3c7eb870c77f55987c`. No PR was merged on GitHub.
- #36 merged at `dbc9ef0322211f653b0fbc28303b6060164e81dd` and is no longer
  pending. User installation/removal, guarded `.deb` upgrades, offline AppImage
  replacement and compatibility/backup/refusal guidance use its actual merged
  code, including the reviewed AppArmor correction. The historical first-draft
  links at `30402eb95154d9a4d3076fb5cae165771d4aee36` are not its final identity.
- #46 merged at `7c3d6fe0acd412a7d76f40769b09a96856a774a4`. Removed the obsolete
  claim that checking Add to knowledge calls a missing attachment-ingestion
  handler and fails processing. It now selects the existing per-attachment intent;
  retention remains a model-tool operation, not an automatic knowledge write.
  Default model-side knowledge-store composition is still absent. Neither that
  fix nor this documentation claims actual knowledge ingestion succeeded.
- #45 changes bundled-component laboratory isolation; #51 and #53 change CI
  routing. Their presence in main is not new user-facing functionality or a
  substitute for the original/final native acceptance gates.
- README navigation and the maintainer release checklist were aligned. #36's
  merge requirement was replaced with final-candidate acceptance requirements.
  P4.5/P4.6, Aaron's immediate active-desktop consent and separate publication,
  audience/license/version approvals remain required, not implied.
- No product code, dependency, test, workflow or ledger edits were made by this
  documentation revision. Changes inherited from main are its already-merged
  work, not new product changes authored in this PR.

### Claim-to-source map for the user guides

Every link below is pinned to the initial integrated main source
`ed0069674533c23e70a0302652a2fb76901ff385`. The subsequent #28 merge/promotion
overrides the absent-service rows as detailed below. This map records source inspection,
not native procedure execution. Existing historical gate results above retain
their original source identities and limits.

| User guide / claims | Checked against |
|---|---|
| Install: x86-64 formats, package identity/dependencies and resource paths | [builder configuration](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/electron-builder.yml), [resource layout/qualification](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/packaging/README.md), [launcher](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/packaging/odin-desktop.desktop), [runtime selection](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/main/core-command.ts) |
| Install: first-use PDF dependency; normal runtime bundled versus external helper Python | [resource downloader](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/src/runtime/pdf_resources.py), [approved Decision F](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/docs/work/phase-3-app-v1.md), [manual replacement procedure](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/packaging/APPIMAGE-REPLACEMENT.md) |
| Install/First run/Background: opt-in login, single instance, Close versus Exit and no-tray paths | [startup/lifecycle integration](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/main/index.ts), [lifecycle rules](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/main/lifecycle.ts), [autostart](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/main/autostart.ts) |
| Install: profile locations, retained data and profile-keyring identity | [app paths](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/main/paths.ts), [core paths](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/src/desktop/paths.py), [keyring namespace](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/src/desktop/secrets.py) |
| First run: real banner states, explicit Retry, write-only credentials and provider/account controls | [readiness banner](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/renderer/src/components/FirstRunBanner.vue), [accounts](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/renderer/src/components/CodexAccounts.vue), [schema controls](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/renderer/src/components/SchemaForm.vue), [model reference parser](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/src/llm/model_ref.py), [runtime readiness](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/src/desktop/runtime.py) |
| Settings: save/apply labels, sections, notification privacy and follow/pin intent | [settings form](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/renderer/src/settings-form.ts), [navigation](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/renderer/src/views/Settings.vue), [General](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/renderer/src/views/settings/General.vue), [settings transactions](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/src/desktop/settings.py) |
| Settings: Personality, built-in tool availability and timeouts | [Personality](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/renderer/src/views/settings/Personality.vue), [Tools](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/renderer/src/views/settings/Tools.vue), [request/tool owners and readiness](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/src/desktop/services.py) |
| Settings: managed SSH enrollment, trust/default target and uncertain host controls | [Hosts](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/renderer/src/views/settings/Hosts.vue), [management composition](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/src/desktop/management.py) |
| Settings/First run/Chat: memory/list/knowledge operations and absent default model-side store wiring | [State](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/renderer/src/views/settings/State.vue), [knowledge management](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/src/desktop/knowledge.py), [core/runtime composition](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/src/desktop/core.py), [model-side store dependency](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/src/desktop/services.py) |
| Chat: drafts/conversations/search/Thread/attachment Queue and controls | [composer](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/renderer/src/components/Composer.vue), [conversation store](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/renderer/src/store.ts), [controls](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/src/desktop/controls.py), [slash commands](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/renderer/src/commands.ts) |
| Chat: attachment limits/expiry and checked Add to knowledge intent (not successful ingestion) | [uploads](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/src/desktop/attachments.py), [fresh request processing](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/src/desktop/requests.py), [merged fix evidence/limits](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/maintenance/attachment-knowledge-intent-validation.md) |
| Chat/Background: Copy/file actions, unavailable bytes, evidence TTL/quotas/read scope, unavailable report paging | [message/file views](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/renderer/src/components/Message.vue), [tool output](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/renderer/src/components/ToolActivity.vue), [artifacts](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/src/desktop/artifacts.py), [retained evidence](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/src/tools/output_retention.py), core composition above |
| Settings/Background/Recovery: unavailable Skills/MCP/computer/work/schedule services; no pending workflows taught as current | [management composition](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/src/desktop/management.py), core composition above |
| Recovery: Records, Resume, bounded core restart and cleanup Acknowledge semantics | [Records](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/renderer/src/views/settings/Records.vue), [record observer](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/src/desktop/records.py), [Resume](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/renderer/src/components/ResumeBanner.vue), [cleanup notice](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/renderer/src/components/CleanupNotice.vue), [supervisor](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/main/core-supervisor.ts), [shutdown](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/main/shutdown.ts) |
| Install/Updates/Recovery: package lifetime/removal retention, guarded upgrades, offline same-path AppImage helper/refusals | [package transactions](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/packaging/deb_transaction.py), [ownership records](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/packaging/ownership.py), [helper arguments/recovery](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/packaging/replace-appimage.py), [manual procedure](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/packaging/APPIMAGE-REPLACEMENT.md), [actual packaging evidence and limits](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/maintenance/phase4-packaging.md) |
| Updates/Recovery: compatibility before writes, backups/exclusions, pending migration identity, no automatic rollback | [state inspection/backup/migration](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/src/desktop/package_state.py), [behavior tests](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/tests/test_desktop_package_state.py) |
| Install/Updates: unsigned GitHub releases/manual installation and no in-app apply; upstream watermark | [approved release decisions](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/docs/work/phase-3-app-v1.md), [recorded baseline](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/maintenance/baseline.md), [maintenance policy](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/docs/design/maintenance.md) |
| Accessibility: actual keys/focus/menu/zoom; native Orca/dialog/Wayland limits | [app shortcuts](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/app/src/renderer/src/App.vue), composer and native menu above, [accessibility evidence](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/maintenance/phase3-accessibility.md) |
| Install/Updates: stock Ubuntu 24.04 restricted namespaces and mounted-AppImage gate still open | [P4.1 open gate](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/maintenance/p41-packaging.md), [P4.2 final reviewed AppArmor/open gate](https://github.com/Calmingstorm/Odin-Desktop/blob/ed0069674533c23e70a0302652a2fb76901ff385/maintenance/phase4-packaging.md) |

The SHA-256 procedure uses the ordinary checksum tool as user guidance. It
establishes byte equality, not signatures or provenance. No credential/private
history screenshots or new acceptance claims were introduced.

### Initial pending-section tracking, now maintainer-only

Original task prose and pinned branch references are preserved in
[`docs/release/pending-user-docs.md`](../docs/release/pending-user-docs.md).
These historical snapshots were not updated to imply current-head review or a
combined candidate. Promote a section only after its prerequisite merges,
checking actual integration behavior, then removing development provenance from
the user-facing copy.

| Open PR | Historical inspected source | Draft topics awaiting integration |
|---|---|---|
| #28 | `2d91071a692a646b6d8c466daa5711a37cd8c93f` (later lifecycle-only inspection `dda129d8f0597d12dbb16837baa5b84ec1c866dc`) | Skills/MCP/browser/computer services, workspace diagnostics, native recovery limits |
| #37 | `4ede9e75fb079a0a305c7b24f89700d7fb7c4416` | Work owners/controls, schedules, D12 missed-run behavior, stored reports and recovery |
| #39 | `1c48529b0af3ad18d9c413882166cb6ee40702d1` | Manual notice-only update check and private-repo Can't check; release rehearsal stays maintainer-only |
| #40 | `6321eec26e1c87dd5b9682e902723818a5fdda03` | Account refresh, OpenRouter, shared knowledge, learned context, extended records/observability |
| #42 | `50f90306176dd2abd724a1a2d5b97199d294b9c8` | Incoming integrations, receipt-local uncertainty, new-delivery/no-deduplication limits and privacy |

### Review-round validation boundaries

This round is a structural documentation correction with link checking as data,
not a new application qualification. No Markdown-wording tests were added, no
full suite rerun was requested, and no action was taken on the separately rerunning
CI qualification. Native provider/keyring/Orca/portal, stock Ubuntu and actual FUSE
acceptance remain open in the maintainer checklist. No system installation,
running service, active desktop, production profile or release was changed.

Observed round-1 checks:

- Link checker covers the eight guides, both READMEs, the release checklist,
  preserved pending drafts and this validation record. It validates local targets
  and heading fragments, checks pinned Git objects through `git cat-file`, and
  checks other external URLs for syntax only. No anonymous private-GitHub access
  or live release availability is asserted.
- `env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS .venv/bin/python
  scripts/docs/generate_tool_reference.py --check`: generated reference is current.
  This checks generated catalog data, not human-written Markdown wording.
- `git diff --check`: passed. Documentation-only changed-path review against
  integrated main: passed. Manual user-guide structural review: no commit IDs,
  PR/source links, pending markers, author/lane mentions or qualification records.
- Independent read-only user-guide audit found no concrete factual/scope defect
  in the checked knowledge intent, unavailable-service, secret clearing, shortcut,
  accessibility and package/helper descriptions. Separate package-source review
  confirmed the helper is not installed in either package and stock Ubuntu/FUSE
  acceptance remains open. Neither review is native procedure execution.
- Root filesystem admission measured 123 GB available initially and 120 GB during
  this small documentation run; no heavy qualification checkout was created.
- After pushing and verifying the remote head, remove this lane's inactive
  reference worktrees. Keep committed evidence, external evidence directories
  and small logs; do not touch other lanes. Activity inspection found another
  lane's live pytest mapping dependency files from both the historical fresh
  clone and development checkout. Those in-use copies must be retained until
  their consumer exits, not removed under the cleanup rule.

The small artifact manifest is
[`p44-user-docs-round1-artifacts.json`](p44-user-docs-round1-artifacts.json).
Raw link results and the bounded checker stay under
`/mnt/storage/odin-desktop-evidence/p44-r1-req-c55cf225/`, outside Git.

### Main advanced during round 1: #28 promotion

Before pushing, main advanced to
`cd52a8e2b055a9c4abc051a49566b9daf3e1bd79` with #28. Incorporated it with the
two-parent merge `f14dcebcc24e097b75f842c6f1a778e2d6f84446`. Main's executable
changes remain inherited work, not authored documentation fixes. Did not run a
new full qualification or disturb its separately rerunning CI.

Rechecked actual integrated code, not just the archive's original #28 pins:

- [management composition](https://github.com/Calmingstorm/Odin-Desktop/blob/cd52a8e2b055a9c4abc051a49566b9daf3e1bd79/src/desktop/management.py),
  [Skills service](https://github.com/Calmingstorm/Odin-Desktop/blob/cd52a8e2b055a9c4abc051a49566b9daf3e1bd79/src/desktop/skills.py),
  [MCP service](https://github.com/Calmingstorm/Odin-Desktop/blob/cd52a8e2b055a9c4abc051a49566b9daf3e1bd79/src/desktop/mcp.py),
  [Skills controls](https://github.com/Calmingstorm/Odin-Desktop/blob/cd52a8e2b055a9c4abc051a49566b9daf3e1bd79/app/src/renderer/src/views/settings/Skills.vue)
  and [MCP controls](https://github.com/Calmingstorm/Odin-Desktop/blob/cd52a8e2b055a9c4abc051a49566b9daf3e1bd79/app/src/renderer/src/views/settings/Mcp.vue).
  These are no longer documented as unavailable by default. User task guidance
  now distinguishes validation, loading code and effectful Test, and external
  connection/configuration/inventory reads.
- [browser runtime](https://github.com/Calmingstorm/Odin-Desktop/blob/cd52a8e2b055a9c4abc051a49566b9daf3e1bd79/src/desktop/browser_runtime.py)
  is composed. Browser restart/boot-snapshot and missing-resource repair limits
  replace the obsolete blanket absent-service statement.
- [computer binding](https://github.com/Calmingstorm/Odin-Desktop/blob/cd52a8e2b055a9c4abc051a49566b9daf3e1bd79/src/desktop/computer_binding.py)
  supports retained management/status but explicitly reports foreground/input
  unavailable, `dispatch:none`, and no native qualification. No current user
  guide grants new input authority. [Records controls](https://github.com/Calmingstorm/Odin-Desktop/blob/cd52a8e2b055a9c4abc051a49566b9daf3e1bd79/app/src/renderer/src/views/settings/Records.vue)
  and [recovery receipts](https://github.com/Calmingstorm/Odin-Desktop/blob/cd52a8e2b055a9c4abc051a49566b9daf3e1bd79/app/src/renderer/src/stores/records.ts)
  determine what the actual UI can say; RPC success alone remains insufficient.
- [workspace diagnosis](https://github.com/Calmingstorm/Odin-Desktop/blob/cd52a8e2b055a9c4abc051a49566b9daf3e1bd79/src/desktop/workspace_diagnostics.py)
  is a real read-only service, not an invented graphical repair/export wizard.
- #37, #39, #40 and #42 remained open at this final source snapshot. Their drafted
  procedures remain maintainer-only. Work/schedules/report paging and default
  shared knowledge wiring are not inferred from #28's composition.

Original #28 draft text stays explicitly historical in the maintainer archive;
its integrated guidance is promoted and it is no longer listed as an open
pending dependency. Final documentation source watermark is the `cd52a8e` main
above. Other initial claim-map links remain valid for their unchanged paths.

Two current source boundaries found while promoting, and kept plain in the guides:
`SkillsService.handle` refuses `skills.test` even though the UI offers Test, and
`ComputerBindingService._params` does not accept the acknowledgment attached by
the Records screen's Release request. These are documented limits, not silently
fixed product code or claimed successful tests/recovery. Validate/save and retained
status remain separate from those refused operations.
