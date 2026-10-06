# Final single-run Orca task matrix

Frozen implementation commit: `587242b3960f14db69711dc5c16e2433394a00c8`.
One invocation per desktop, seven task groups per invocation, one attempt per
group, retry 0. No skips, flaky results, reruns or failure waivers.

| Task group | Cinnamon/X11 | GNOME/Wayland | KDE/Wayland |
|---|---|---|---|
| Bridge, named Message and native button role | PASS | PASS | PASS |
| Chat/results, Attach/cancel, Save/copy/report | PASS | PASS | FAIL |
| Conversation, child/modal/search | PASS | PASS | PASS |
| Busy, Steer, consumed/queued, Stop/Resume, unknown/no-flood | PASS | PASS | PASS |
| All eleven settings, names/roles/states/errors/secret | PASS | PASS | PASS |
| Delayed history/search retains focused message | PASS | PASS | PASS |
| Explicitly provisioned real-core services | PASS | PASS | PASS |
| Total | 7/7 | 7/7 | 6/7 |

KDE's combined group fails at native Attach observation, before cancellation,
selection and Save. The actual chooser is visible, but no eligible active
portal AT-SPI dialog is found. Its taskbar proxy is not an input target. The
failing screenshot was inspected and shows Attach files, Name, Open and Cancel.
The corresponding Cinnamon and GNOME screenshots show Saved notes.txt and the
copied Health report. Speech assertions and returned file data, not screenshot
pixels, determine the passing groups. KDE's partial result is not acceptance.

The same artifact served all three desktops:

- Artifact SHA-256: `53459f087a9d930e44c4af3d67b0c0d5da4fed184ce22661065468e3e9c10c28`.
- Manifest SHA-256: `88fc373562c2d6c16925873390edfc955cd21a3cbd3d104ee6c36c1c79fe2b36`.
- `source_dirty: true` records concurrent ledger/docs/evidence updates honestly.
  Runtime source was verified identical to the frozen implementation commit.
- App, fixtures, E2E code and bundled real engine source came from that commit.
  Only prepared runtime/dependencies were reused; no host profile/config/secret.

Complete originals and the reproducible archive remain at
`/home/odin/reviews/p34-final-once-20261006.RwUpLn/`. This checked-in directory
contains unchanged task JSON, guest proofs, task attachments/failure trace,
native screenshots, events and logs. Large host proof JSON and Orca debug logs
are losslessly compressed with `gzip -n`. Per-desktop SHA256SUMS checks every
retained file; the root original SHA256SUMS refers to the complete external
evidence, including the archive, rather than pretending it is all copied here.

Every guest proof confirms children and descendants exited, cgroup and sandbox
removed, and original uinput metadata restored. All host proofs report confirmed
cleanup. Lifecycle logs confirm graceful stops. One heavy VM ran at a time.
Final capacity preflight passed: about 29 GiB allocated of 100 GiB, 174 GiB
filesystem free, with the conservative 50 GiB floor maintained.

This qualifies the specified source-build tasks only on Cinnamon and GNOME.
It is not packaged-app, arbitrary-toolkit, audible-output or physical-braille
qualification. KDE's native chooser remains an explicit blocker.
