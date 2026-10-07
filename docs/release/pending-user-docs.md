# User-documentation status and v1 scope

Scope source: main `1e5c069f`, Decision I merged in #104, 2026-10-07.
This is not a release announcement or a claim that candidate checks passed.
The [historical drafts](p44-user-docs-historical-drafts.md) preserve earlier
watermarks and pending prose; they are not today's feature list.

## Promoted merged behavior

| Former pending item | Current guidance |
|---|---|
| #37: work, schedules, reports and foreground binding | [Background work](../user/background-work.md), [Recovery](../user/recovery.md). Native backend qualification is separate from having the binding. |
| #39: manual release notice | [Updates](../user/updates.md#check-for-a-release-notice). Manual anonymous check, private-repo can't-check, notice only. Publication follows the current checklist, not an unmerged notice feature. |
| #40: provider administration, shared knowledge, learned context and records | [Settings](../user/settings.md), [First run](../user/first-run.md), [Chat/results](../user/chat-and-results.md). A shared store is not guaranteed retrieval or automatic attachment ingestion. |
| #42: incoming integrations and outgoing privacy | [Settings](../user/settings.md), [Recovery](../user/recovery.md). Unknown handoff is receipt-local; new deliveries can execute again. |
| #89: package-change fencing | [Updates](../user/updates.md#before-replacing-anything), [Uninstall](../user/install.md#uninstall-without-losing-recovery-records). Busy lifetimes refuse; valid earlier-boot evidence no longer fences after restart. History/quarantine remain. |
| #90/#94: shutdown, reboot and logout | [Install](../user/install.md#start-close-and-exit), [Background work](../user/background-work.md). Normal bounded Exit; query cancellation does not stop Odin. |
| #95: first Wayland window | [Install](../user/install.md#start-close-and-exit). Manual fresh launch shows; opted-in login start stays hidden. |
| D12 native sleep/wake observations | [Background work](../user/background-work.md). One catch-up reminder; missed checks/actions wait for the owner. Prior candidate evidence is not a current-candidate pass. |

## Current release gate and planned follow-ups

- **1.0.0 app:** Cinnamon/X11, GNOME/Wayland, KDE/Wayland and Hyprland.
- **Computer use:** X11 only, at parity with Odin. Wayland computer use is
  planned for **1.1**; until then the app refuses it with guidance.
- The [release checklist](linux-v1-checklist.md) replaces the earlier Phase 3,
  P3.6/D11 matrix and P4.4 walkthrough blockers under
  [Decision I](../work/phase-3-app-v1.md#decision-i-lean-v1-release-gate).
  It requires CI, R4/CC acceptance evidence, dependency/security checks, an exact
  release-workflow candidate, smoke checks on all four desktops, Aaron's real-use
  check, release notes and separate publication approval. None is checked by
  this documentation update.
- #97/#98 harness follow-ups and Wayland computer-use integration move to 1.1.
  Retained #59 lifecycle evidence and historical passing rows are not a final
  candidate pass or extra v1 blockers. Accessibility observations, including
  the KDE chooser limitation, remain documented without inventing new results.
- Packages remain unsigned x86-64 `.deb` and AppImage, installed and upgraded
  manually. PDF support downloads on first use, pinned by hash. AppImage
  FUSE/sandbox restrictions still apply; the scope decision does not bypass them.

## Verification boundary

Earlier feature promotions and source mapping are retained in
[P4.4 validation](../../maintenance/p44-user-docs-validation.md) as historical
evidence. This update aligns the user guides and release notes with Decision I;
it performs no native qualification, live-desktop input, VM work, deployment or
publication, and does not bump a product version.
