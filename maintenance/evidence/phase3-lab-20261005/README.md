# Actual guest smoke evidence, 2026-10-05

These are guest captures, not host viewer images or synthesized fixtures.
Each directory contains the captured PNG, proof JSON, installed package list
and provisioning-time listener list. Runtime listener inspection is also in
`proof.json`. All screenshots were decoded and visually inspected.

| Guest | Required session | Orca PID at capture | Source commit | Capture result |
|---|---|---|---|---|
| Cinnamon | active X11/Cinnamon | 887 | `dcb2d349f5fadd012f25b30eca3d6d054057fc7d` | 1280x800 desktop and panel |
| GNOME | active Wayland/GNOME | 747 | `dcb2d349f5fadd012f25b30eca3d6d054057fc7d` | 1280x800 GNOME overview |
| KDE | active Wayland/KDE | 1186 | `ff347abbbc4ea7ece168f49689e6e74bb50fd27f` | 1280x800 Plasma desktop and panel |
| Hyprland | active native Wayland/Hyprland | recorded in proof | `ff347abbbc4ea7ece168f49689e6e74bb50fd27f` | 1280x800 native Foot terminal on Virtual-1 |

Every final proof reports `source_dirty=false`, `source_matches=true`, exact
host and guest SHA256s, and screenshot SHA256. The relevant executable source
digests also match the final PR tree; later evidence/documentation commits
do not change those sources. Generated capture helpers are hashed as actual
guest artifacts, not falsely compared to a byte-identical host script.

GNOME has no tray extension installed/enabled; the earlier direct runtime
query returned `@as []` and `disable-user-extensions=true`. Hyprland had no
XWayland process and its capture used the actual nested session bus. The final
Hyprland PNG shows notices for missing `hyprland-guiutils` and its direct
launcher; they are retained as limitations, not hidden. EGL query warnings
also remain. No physical GPU/display/input/audio passthrough was configured.

Orca process startup is demonstrated, not actual speech, accessibility trees,
native input containment, packaged app qualification, or P3.3-P3.6 acceptance.
All four guests were gracefully stopped after final proof, with no snapshots.

Storage: Incus-managed `dir` pool `odq-lab`, source `/mnt/storage/odq-lab`.
Four logical 40GiB thin disks; final measured allocation 17,080,340,480 bytes
(15.91GiB), filesystem available 212,264,521,728 bytes (197.69GiB).
The 100GiB allocation budget is admission policy, not a filesystem quota.
No reboot was induced. No host packages or host-service restarts occurred.
The old unavailable `default` pool and `bots` metadata were byte-identical
before/after. One initial Cinnamon ACPI stop suspended the disposable guest;
one exact-guest manual emergency force recovery was required. The runner now
uses one guest-agent poweroff and bounded state polling, never automatic force.

Fresh-checkout checks at executable-source commit `ff347abb`: 225 lab tests,
28/28 engine qualification groups, 13,145 passing executions, 2 skips,
zero failures/errors. Ruff, ShellCheck and exact drift passed, no new lint.
Unchanged app sources: fresh typecheck/build, 281 tests and isolated Xvfb
fixture smoke passed. The app fixture smoke is not one of these VM proofs.
