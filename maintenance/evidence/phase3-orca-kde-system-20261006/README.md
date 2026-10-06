# PR #50 review: one direct KDE portal comparison

This is a focused system comparison, not another Orca task-matrix run or a
passing KDE qualification. One direct
`org.freedesktop.portal.FileChooser.OpenFile("", "Attach files", options)`
request used `modal=true`, `multiple=true` and token `pr50directprobe`, without
launching Odin or Electron. The native KDE screenshot was inspected: the
`Attach files — Portal` dialog, Places/file list, Name field, Open and Cancel
are visible.

The unfiltered AT-SPI registry desktop had **685 nodes before, 688 while open,
686 after Request.Close**, with no node-call errors or traversal truncation.
The chooser did not appear as a portal application/dialog. Its title appeared
only on plasmashell's task button, which was not accepted as the chooser.
Orca **46.1** spoke its startup and desktop baseline, then emitted **zero
opening speech records** during the eight-second direct-chooser observation.

The KDE backend was present on the accessibility bus and emitted a selected
state event. This evidence does **not** claim that every individual accessible
object was uncallable. Initial unique-peer identity mapping failed; direct
post-close PID/starttime reconciliation identified the same peer incarnation.
Accessible-root/cache queries were made only after close and are not evidence
of while-open object behavior.

Backend identity: UID1001, PID1483/start18977, session peer `:1.50`, accessibility
peer `:1.16`, exact executable
`/usr/lib/x86_64-linux-gnu/libexec/xdg-desktop-portal-kde`. Both Qt accessibility
flags, graphical environment and accessibility bus matched. Versions: KDE
portal **5.27.11**, Qt **5.15.13**, portal frontend **1.18.4**, AT-SPI **2.52.0**.
Support bytes are bound to PR #50 head
`e67f8fd7b4035e5b641b7b6ce044200e9d593c7c`, before the merge.

**Judgment:** the failure reproduces without Odin/Electron, supporting a KDE
guest/system-side registration/accessibility limitation, not an Odin-specific
portal invocation defect. Precise cause, universal KDE behavior, direct-object
callability while open, KWrite behavior and keyboard traversal are not proved.
KDE remains **6/7**; acceptance belongs to Aaron, with no waiver in this PR.

Raw artifacts remain outside Git at
`/mnt/storage/odin-desktop-evidence/pr50-kde-direct-portal-20261006T0800Z/`.
`artifact-manifest.json` maps every retained artifact to its root-relative path
and SHA-256. The external `SHA256SUMS.txt` was verified before recording this
summary. `task-result.json` is the small comparison result, not task acceptance.

Request.Close succeeded. Owned children and descendants exited, the cgroup was
empty and removed, and exact guest scratch/transport were retired. Orca's
recorded exit was -9, not a normal exit; no cgroup kill escalation was used.
Guest-only Qt manager values were restored. No uinput permission changes or
host graphical interaction occurred. The lab tool gracefully stopped KDE;
validation confirmed KDE STOPPED and zero active Incus VMs. Root remained at
71G free. No second chooser sample, retries, other VM or matrix rerun.
