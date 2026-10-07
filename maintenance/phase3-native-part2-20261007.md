# P3.3 part 2 continuation, 2026-10-07

## Evidence boundary

Raw evidence: `/mnt/storage/odin-desktop-evidence/p33-finish-20261007/`.
Prior measurements copied unchanged from
`/home/calmingstorm/odin-desktop-evidence/fence-session-end-20261007/` and
`d12-20261007/`. These are Claude's measurements, not new reruns. The complete
Cinnamon D12 log was recopied after Claude finished it.

Source was fetched before work. Main `aa3d61b3` was merged, ledger union used
`/home/odin/reviews/merge_ledger.py`, and the inventory initially reported no
errors. Main `90d0f1df` was subsequently merged without conflict, including #93.
Only inventory-flagged entries were re-recorded using the supported command.

## Candidate provenance

| Candidate | Exact source | deb SHA256 | AppImage SHA256 |
|---|---|---|---|
| prior v3 | `103335d5b0d3d4c986cd1f5e699e8fc9753bd3c5`, main `0ed8ca6` + #89 `2a479b5` + #90 `71b315a` + #91 `f0f446f` | `6d1ddcee96a9c59c00e864fa825d601c0b7400245e3218aabb4c3402f7b0fd00` | `960023bfae3df225365ac0574b8becf6b39d6bb1e7d28971dbb8cf168fb90009` |
| prior v5 | `fd459aedc62da74c6dbd72e6331f2df1b8206799`, main `61d70cb` + #89 `0cd7e9b` + desktop-name `23d8f07` | `91c976ae95f54fff83cc4cd212f31ad3a8eb05dbbb0d65c7a1ad5bfef63f5fc8` | `462d4d450400cfcf37c0c67537650f37efdfbbd971d5830e62f2d459cb043e82` |
| prior v6 | `6e17cf61baee7248654b670b124c92e5b54b2bc3`, main `61d70cb` + #89 `b88744d` + #95 `45fcd0c` + #94 `f6d6dfd` | `e87e6ed3184bde1bde26aa9d7e4d021b89ac0165673d52421bc89327e7b77914` | `60f77abbff9fc350ff96b25348bb7156a86682140ffcb98b46be47b5992dc34e` |
| new 0.1.0 | clean main `aa3d61b3`, full SHA in `candidates/current-main-source.txt` | `64910abe672063e076f85ca1d725a9463a44f90720264ff8e7a247c34d9f54ea` | `b1be0738953c52744c57b17d0ffd2a5934071c361d4a741eed4968332c21f370` |
| new 0.1.1 | same main with **only** disposable `app/package.json` version bump | `bc5d332fd70311a7c7df603f1117609f6f4f4e9b7f452a30f5ed2fc6b830f6b7` | `8da6ae26974fe8a13a03147166e5e5af7218ff181a28d62c15cc6c920bd5f7f0` |

The release version on main/PR remains 0.1.0. Both candidates built successfully;
build success is not full package qualification. The new notification proof is
current-main application source, not a packaged debug capability: fixture
conversation/ack core, real native GNOME daemon, actual Wayland session, sandbox
enabled. Real-core provider delivery is not claimed by that fixture.

## Current row table

| Row | Cinnamon/X11 | GNOME/Wayland, no extensions/tray | KDE/Wayland 5.27 |
|---|---|---|---|
| bounded poweroff/reboot Exit | pass, prior v3 | pass, prior v3 | pass, prior v3 |
| bounded logout Exit | pass, prior v6 | pass, prior v6 | pass, prior v6 |
| busy package refusal, installed package preserved | pass, prior v3 | pass, new 0.1.0, `gnome/busy-refusal.txt` | pass, prior v6 incidental |
| unclean-end same-boot fence, restart recovery | pass, prior v3 | pending | pending |
| tray Open/Exit | pass, October 6 corrected native run | n/a, no tray | pass, prior v3 |
| no-tray relaunch/launcher Exit | n/a | pass, prior v3 | n/a |
| native Ctrl+Q/window-menu Exit | n/a | pass, new 0.1.0, focused native Mutter keys, clean app/core receipts and zero processes | n/a |
| one-time no-tray notice | n/a | pass, new 0.1.0: persisted false -> true, visible native banner; second close retains true | n/a |
| login hidden, one core | observed every boot; prior explicit pass | observed every boot | pass, prior v3 |
| autostart disable/enable then real login | pending new toggle | pending new toggle | pending new toggle |
| D12 sleep/wake | pass, prior v6 complete D12 log | pass, prior native D12 | pass, prior v6 |
| fresh launch window | pass, prior | pass, prior v5 | pass, prior v5 |
| native notification acceptance/appearance/exact click/read watermark | pending | pass, source fixture: `gnome/native-notification-v9.json`, native keyboard activation of visibly focused marker; reads unchanged | pending |
| different-version deb upgrade | pending | pass 0.1.0 -> 0.1.1; `gnome/version-upgrade.txt` | pending |
| relocated AppImage | pending | pending | pending |
| logout query then cancel | Cinnamon inhibited no-prompt logout hangs even without Odin; known external limitation | native query/dialog/Escape pass with identical running app/core; `gnome/logout-cancel.txt` | not requested |

## Harness corrections and failures retained

GNOME daemon absence was a guest prerequisite defect: the no-recommends recipe
omitted `gjs`, required by its stock notification forwarding service. Installed
guest-only `gjs`, validated real `GetCapabilities`, and added a behavior test
against the recipe's actual package invocation. No host package install.

GNOME's D-Bus daemon is `/usr/bin/gjs-console`, while visible notification nodes
belong to the separately named `gnome-shell`. The collector now resolves that
presenter from its bus owner, verifies UID/executable/identity, and still refuses
arbitrary same-UID app trees. Behavior tests cover forwarder/presenter distinction,
foreign UID, wrong executable and no-daemon cases. Native AT-SPI discovery remains
unreliable in this guest. All failed attempts are retained. No acceptance pass is
inferred from those failures.

The successful GNOME proof uses the source harness's explicit external input
mode: real native Super+V opened the notification list, a capture identified the
unique marker and visible keyboard focus, Return activated it, Escape dismissed
the Shell popup. The application then proved exact old-message highlight,
viewport/jump banner, acknowledged `shown`, and unchanged read receipts.
The collector did not observe a broadcast `ActionInvoked`; GNOME can deliver
destination-scoped signals. Actual native activation and DOM route, not synthetic
signals, provide the click evidence. Prior broadcast-dependent failures remain.

Lab work used the external lock and guest-only commands. No computer tools, host
desktop input/capture, VM disk/snapshot/removal, Odin service or CI runner changes.
The inactive lane7 cache was preserved on `/home/odin` with a resolving symlink at
its old path to recover lab admission headroom. No cache or evidence was deleted.

## Gates after merging main 90d0f1df

- Full classified engine qualification ran once: **38 groups, 19,313 passed,
  3 skipped, zero failed groups**. Additional Desktop boundaries: **477 passed**.
  Preserved warnings include pending asyncio teardown and inherited mock/aiohttp
  warnings. Skips are not native acceptance.
- `npm run check`: initially 1,054 passed; after adding the harness-race behavior
  regression, **1,055 passed**, typecheck and build pass.
- Isolated real-core contracts/settings/skills/work: **66 passed**; onboarding **6 passed**;
  fixture smoke passed. The initial process spool retains these results because
  the combined command's tee covered only its final E2E subcommand.
- Initial lifecycle E2E: **35 passed, 1 failed**. The failing admission helper read
  an intentionally reserved empty `admitted.json` before its producer published
  JSON. This is a measured harness race, not a product containment failure.
  Added behavior coverage for empty/partial/missing/complete receipts and bounded
  polling for publication. Corrected-source lifecycle gate: **36 passed**. Both
  initial and corrected runs retained; no assertion waived or unchanged retry.
- Native helper selection: **55 passed**. Fixed offline lab fixture corpus:
  **160 passed, 4 explicit subordinate-mapping skips**. Node display guards:
  passed. Packaging behavior: **139 cases, 109 passed, 30 prerequisite skips**;
  these skips do not qualify native/package lanes.
- Exact-byte inventory: zero errors, independent review pending. Lint: zero new,
  seven inherited. Broad lab/helper Ruff and source Node syntax: passed.

Final native completion still requires the rows marked pending. Other lanes
owned the lab after GNOME; no foreign VM or lock was changed to accelerate this.
At 18:50 UTC P33 acquired the released lock, verified all guests STOPPED, and
requested Cinnamon start. The unchanged lab guard refused: **54.5 GiB allocated
pool usage + 50 GiB growth/reserve exceeds the 100 GiB aggregate budget**.
No guest started. The lock was released. The requested safety rules forbid VM
removal or disk/snapshot changes, so completing the remaining rows is blocked
on an operator-resolved lab capacity plan, not permission to weaken the guard.

Final main synchronization: `058aca86` (documentation-only decisions G/H) merged.
No executable source changed relative to the recorded final gates. New candidates'
extracted sealed inventories both pass: 8,507 entries / 976,644,502 bytes, common
manifest `b907b143efa2df1c70054e712fef591ade1dbd8ec75e074ff2cc0d01e680c575`.
This corrects the October 6 mode-mismatch gate, not full native qualification.
