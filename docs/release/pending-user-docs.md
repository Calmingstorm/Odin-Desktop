# User-documentation status and remaining gates

Documentation source: main `aa3d61b3043ea47805686c185133a53c54b127fc`,
2026-10-07. This is not a release announcement or P4.5/P4.6 acceptance.
The [historical drafts](p44-user-docs-historical-drafts.md) preserve earlier
watermarks and pending prose; they are not today's feature list.

## Promoted merged behavior

| Former pending item | Current guidance |
|---|---|
| #37: work, schedules, reports and foreground binding | [Background work](../user/background-work.md), [Recovery](../user/recovery.md). Native backend qualification is separate from having the binding. |
| #39: manual release notice | [Updates](../user/updates.md#check-for-a-release-notice). Manual anonymous check, private-repo can't-check, notice only. External release protections and rehearsal remain gate work, not an unmerged notice feature. |
| #40: provider administration, shared knowledge, learned context and records | [Settings](../user/settings.md), [First run](../user/first-run.md), [Chat/results](../user/chat-and-results.md). A shared store is not guaranteed retrieval or automatic attachment ingestion. |
| #42: incoming integrations and outgoing privacy | [Settings](../user/settings.md), [Recovery](../user/recovery.md). Unknown handoff is receipt-local; new deliveries can execute again. |
| #89: package-change fencing | [Updates](../user/updates.md#before-replacing-anything), [Uninstall](../user/install.md#uninstall-without-losing-recovery-records). Busy lifetimes refuse; valid earlier-boot evidence no longer fences after restart. History/quarantine remain. |
| #90/#94: shutdown, reboot and logout | [Install](../user/install.md#start-close-and-exit), [Background work](../user/background-work.md). Normal bounded Exit; query cancellation does not stop Odin. |
| #95: first Wayland window | [Install](../user/install.md#start-close-and-exit). Manual fresh launch shows; opted-in login start stays hidden. |
| D12 native sleep/wake observations | [Background work](../user/background-work.md). One catch-up reminder; missed checks/actions wait for the owner. Prior candidate evidence is not a current-candidate pass. |

## Still pending

- **pending: #96**: bounded Exit during initial core startup is under review.
  Current docs warn about unknown cleanup rather than describing the fix as shipped.
- **pending: #59**: remaining P3.3 native notifications/click-through, GNOME
  no-tray/Exit controls, different-version upgrades and query/cancel logout rows.
  The [release checklist](linux-v1-checklist.md) lists ready-to-run procedures.
- **pending: #97**: P3.6 D11 matrix/Phase 3 closure and immutable candidate evidence.
  A harness or historical passing row is not completed release qualification.
- **pending: #98**: P3.5 native receiver, release/loss, containment/quarantine
  and packaged-helper qualification. The PR opened during this docs update with
  its native gate blocked; no native-input procedure is promoted from unfinished
  lane work.
- **pending: #59 / #97**: P4.4 isolated candidate walkthrough. The lab was owned
  by P3.3 at this update, so procedures are ready, not newly executed. Provider
  acceptance additionally needs a separately authorized real test account.
- Final candidate AppImage FUSE/sandbox paths, KDE native chooser accessibility,
  dependency/security disposition and external publication protections remain
  explicit checklist gates. Merged feature code does not close these gates.

## Verification boundary

Promotions were checked against integrated source/UI labels and service wiring,
not against the archived branch heads. Links and generated metadata are checked
as data. No Markdown-wording tests, live-desktop input, VM interference,
deployment or publication. Exact evidence and source mapping are in
[P4.4 validation](../../maintenance/p44-user-docs-validation.md).
