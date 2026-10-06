# Focused native-file probes, not full Orca qualification

These are source-bound development probes. The complete originals remain under
`/home/odin/reviews/`; copied JSON/log/PNG evidence is unchanged. Large Orca and
host proof JSON logs are losslessly compressed with `gzip -n`. Each directory
has `SHA256SUMS`. `guest-proof.json` binds the actual artifact manifest and records
guest session identity, private speech sink and descendant/input cleanup.
They are not clean builds of the final PR head and do not qualify seven tasks.

| Desktop | Original evidence | Manifest SHA-256 | Result |
|---|---|---|---|
| Cinnamon/X11 | `p34-native-files-cinnamon-v22` | `0e6a31e8d0797cfebab43556f6ac251416e33e16e7fac27615ea1ffd3a8f0c31` | PASS: cancellation, positive Attach, attachment UI, native Save exact bytes |
| GNOME/Wayland | `p34-native-files-gnome-v26` | `10257a707af739c5e0a29f72f35705c47ca5c41cfff72c22f84f323badb61328` | PASS: same positive native operations and actual dialog speech |
| KDE/Wayland | `p34-kde-prepared-native-v30` | `930c3098c8337f95181832e0b3366f8b9ab091b6dd0048aab0c500264b372d83` | FAIL: native portal chooser is visible but absent from AT-SPI; no input authorized |

Cinnamon and GNOME saved the exact 25-byte generated notes, SHA-256
`f27a17c0d6373abdf66692172534d178dccfd2204d2b9c46bf3a2f9b60f8b380`.
Returned Open-dialog paths, actual attachment adoption and actual saved bytes
are checked separately from focused-field readback. No dialog return is mocked.
Their completed screenshots were inspected: notes.txt, 25 B, and Saved notes.txt.

KDE's inspected screenshot shows the actual Attach files portal dialog with
Name, Open and Cancel. Its accessible snapshot shows only the similarly named
plasmashell task button, not an accessible chooser. That foreign process remains
rejected. Both accessibility status properties were true; the exact backend was
restarted after Orca/collector readiness with both Qt accessibility flags set,
matching graphical environment and unchanged accessibility bus. The prior
user-manager values were restored. This did not repair native accessibility.
No KDE chooser speech, cancel, selection or Save success is claimed.

All three runs confirm owned descendants exited, cgroups and sandbox runtimes
removed, and original uinput metadata restored. VMs were gracefully stopped.

The probes exposed a harness defect: keypad Enter used as a screen-reader
description command can activate the default Save button. Description is now
observation-only; speech is marked before opening the chooser. Further review
closed partial-input replay, foreign-activation revocation and collector
exhaustion defects before the final committed-source matrix.
