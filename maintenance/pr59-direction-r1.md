# PR59 direction correction and one native measurement per failed row

Request: `/home/odin/reviews/desktop-pr59-direction.md`, 2026-10-06.
Original failed rows remain retained; this report supersedes neither their logs
nor the OPEN verdict. Harness fixes were applied before these measurements.
No attribution trailers, production test authority, sandbox weakening, host
desktop input, service deployment or VM concurrent execution.

## Harness changes

- Tray discovery searches the showing GTK menu inside the app's accessible
  subtree. The collector resolves inner namespace identity through kernel
  `NSpid`, start ticks, UID, executable and namespace, not an arbitrary outer PID.
  Accessibility identity uses the native accessibility-bus peer. X11 fallback
  observes the app's XEmbed icon and newly opened popup with XRes peer identity,
  then sends actual Home/End and Return only after observing that popup's focus.
  No Electron tray callback is invoked; Wayland has no coordinate fallback.
- Explicit `--cases` permits only the failed rows to be measured. Cinnamon's
  previously passing autostart and close cases were not rerun.
- Source archive includes the missing `app/fixture-core/fixture_core.py`, its
  notification/private-server dependencies and the display/session helpers.
  Offline tests derive local import and launch references from the actual
  helpers and assert archive closure, rather than just comparing an allowlist
  to itself. Built app, node_modules and Python remain separately provisioned.
- An absent real notification service no longer blocks unrelated lifecycle
  discovery. It still explicitly fails the notification row.

## Cinnamon/X11 corrected failed rows, once each

| Row | Observed result |
| --- | --- |
| Open from native tray | PASS. Real app-owned XEmbed right-click opened a native GTK popup. Focused Home/Return made the hidden window visible; exact main/core identities survived. |
| Exit from native tray | PASS. Focused End/Return in the observed popup exited app and core; accepted shutdown, `unsaved=false`, `unreceipted=0`, and owned socket removal witnessed. |
| Notification fixture | FAIL. Corrected archive reaches fixture core-ready, actual Cinnamon notification owner and OS acceptance (`shown`). The bounded native accessible marker search fails. Appearance, click, daemon `ActionInvoked` and exact DOM jump remain unqualified. |

Only source development Electron was used for these three corrected rows.
Native notification transport is real; conversation and acknowledgment service
are fixtures, not production scheduling or conversation-delivery acceptance.
The fixture was normally closed after failure, not counted as native Exit.

## Freeze/thaw, real gap but D12 remains BLOCKED

The installed app/core were frozen with `incus pause odq-cinnamon`, observed
FROZEN, then resumed after 125 seconds. The same exact process start ticks
survived. Host timestamps span 125.174 seconds. Guest wall clock advances across
the gap. This is real process freeze/thaw, **not ACPI S3 sleep**.

Guest chrony was installed explicitly. Immediate post-thaw `makestep`/waitsync
did not yet regain synchronization. A bounded diagnostic `online`, `burst`,
then `makestep`/waitsync regained `Leap status: Normal`; contemporaneous guest
and host timestamps differed by about 7 milliseconds. The initial failure is
retained. Normal launcher Ctrl+Q later left clean app/core receipts.

The implementation cannot qualify the requested scheduling behavior:

- `src/desktop/services.py` composes a Scheduler but never starts its tick loop
  or binds a scheduled-delivery callback.
- `src/discord/native_tools/scheduling.py` refuses schedule creation with
  `Phase 2 scheduled destination admission is not implemented.`
- `src/discord/scheduled_events.py` refuses execution/publication pending
  durable admission and conversation authority; schedule management is absent
  from advertised core capabilities.
- This remains true on inspected current main `efc5e20c`, not just PR59's base.

No schedules were inserted behind admission, callback fabricated, clock mocked
or owner graph manually started. Reminder coalescing, missed-action owner
approval and exited-app scheduling semantics remain **BLOCKED**. A process gap
does not transform absent scheduling into a pass.

## Package causes and separate fix PR67

PR67: <https://github.com/Calmingstorm/Odin-Desktop/pull/67>.
The original `.deb` profile and AppImage ASAR content hashes matched their sealed
manifest. Mode differences caused the failures: a late fpm copy made the profile
0664, and extraction normalized an ASAR sealed as 0664 to 0644. No ASAR content
non-reproducibility or stale content digest was demonstrated.

PR67 canonicalizes resource modes before sealing, fixes the qualifier's omitted
Python standard-library/ELF closure and private proc/dev, and requires distro
`python3` rather than insufficient `python3-minimal` for hook imports. Strict
mode/content/link verification remains intact. First corrected candidate build
passed the existing isolated extracted and disposable-dpkg qualification.

Candidate source `d57b76cbe60877be13f71cc787c265793db6d76f`:

- deb SHA-256 `62529a3f86f40e558b7126f09c2602ace16f8a94f561bbd1623867bdab0e08a9`
- AppImage SHA-256 `14e219f350341adbe202eac31903b86e10fa8df99f5fd98adde9baad24d19f3d`

**Native KDE then exposed an unsafe existing-directory integration case:**
`/opt/Odin` and its `resources` directory were 0775, so the strict AppArmor
postinst refused them as mutable. Package is half-configured. No chmod repair,
postinst retry or launch of that failed install occurred. Subsequent read-only
inspection proves the exact deb archives these directories as root:root 0755;
dpkg preserving pre-existing directory modes reproduces the rejection. Native
0775 is therefore not proof of defective archived modes. The earlier isolated
PASS lacked an AppArmor parser and does not prove native loading/attachment.

PR67 merged while this work ran. Separate follow-up PR70, also merged upstream
while evidence was being finalized:
<https://github.com/Calmingstorm/Odin-Desktop/pull/70>, head
`0eac35796b27a24e8b2513989943580da73b7581`. It normalizes full construction
directory trees, makes fpm root/root explicit, and adds an install audit plus
fresh-root acceptance/stale-0777 refusal regressions. Packaging tests: 123
discovered, 100 pass and 23 explicit skips; root fixtures 8/8, root transactions
22/22; pinned-fpm archive/extraction fixture passes; inventory zero errors.
Production immutable-directory guards remain unchanged. No candidate rebuild
or native reinstall rerun. A future authorized build cannot itself waive unsafe
guest directories. Native install acceptance remains unqualified.
PR70 short CI lanes pass; full-suites was cancelled, not passed.

## GNOME and KDE continuation after initial candidate qualification

One guest at a time, Cinnamon stopped before GNOME, GNOME before KDE.

- **GNOME Wayland/no-tray:** actual native Wayland socket, no tray watcher and
  absent notification owner. Qualified deb replacement refuses the previous
  unresolved cleanup journal. It is not erased. Corrected source collector now
  runs without a notification owner, but sandbox-intact source Electron fails
  launch. Kernel records userns transition and AppArmor `sys_admin` denial for
  the unprofiled source executable. No profile exception, fake DISPLAY or sandbox
  relaxation was applied. Hide/reopen/Exit and notification remain unqualified.
- **KDE Wayland:** corrected candidate installs payload but strict AppArmor
  postinst fails on 0775 source directories, as above. Native lifecycle remains
  blocked. The real FUSE-mounted AppImage performs its preflight and returns
  **78**, with the plain recommendation to install `.deb`; Electron is not
  started. No crash, sandbox disable or leaked mount/process. This is successful
  safe-refusal behavior, **not native KDE app lifecycle acceptance**.

No new login/upgrade/relocation coverage is claimed. Original Cinnamon login
and same-version replacement observations remain unchanged.

## Offline validation and evidence

- App `npm run check`: 78 files / **747 passed**, typecheck/build pass.
- Guest Python helpers: **54 passed**; safe display helper Node tests: **16 passed**.
- Touched helper Ruff and Node syntax: pass; final inventory report has **zero
  errors**, `byte-drift-clean-review-pending`. Independent implementation review pending.
- Internal read-only review found no blocker in the corrected helper scope and
  checked native report claims. Archive edge discovery is deliberately heuristic
  for dynamic/shell dependencies, not a complete general module resolver.
  Claude's independent review remains pending.
- Locked npm audit still reports 10 high and one critical issue; no upgrade.

Raw logs, native reports, archive, frozen-process records and clocks remain at
`/mnt/storage/odin-desktop-evidence/pr59-direction-req9133/`.
Compact SHA-256 manifest pointer: `pr59-direction-r1-artifacts.json`.
Package raw evidence remains in its distinct PR67 evidence root. All odq VMs
are STOPPED. Request-owned worktrees are removed after pushed results; retained
evidence and candidates are not deleted. P3.3 remains **OPEN**.
