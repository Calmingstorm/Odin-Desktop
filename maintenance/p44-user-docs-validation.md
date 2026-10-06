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
