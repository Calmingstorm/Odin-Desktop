# P3.5 candidate native input, containment and quarantine

Status: **qualification in progress; D11 release gate not closed**.

This lane composes the retained controller/store/adapters. No production guard,
controller replacement, runtime qualification flag, workstation input, host
package install or live service change is part of this PR.

## Reproduction and boundaries

`scripts/qualification/computer.py --backend {x11,gnome,kde,hyprland}
--candidate <absolute candidate.deb> --output <new external directory>` runs
only while the caller holds `/run/odq-lab.lock` with its `p35` owner record.
It requires the exact owned VM running alone and reuses `lab.py`'s device/cap
validation. The operator starts/stops the named VM through `lab.py`; this driver
neither starts another guest nor removes disks, snapshots or storage.

The host driver never imports engine/native adapters. Guest probes import the
installed candidate's interpreter/modules under `/opt/Odin/resources`, not a
checkout. The guest launcher reuses the lab's credential-allowlisted graphical
session environment discovery. `DISPLAY=:0` inside a checked VM is that guest's
own display, never Aaron's display. No host computer tools are used.

Install uses `odin-desktop --exit` and ordinary `dpkg -i` inside the owned guest.
Package ownership fences are not bypassed. No `--no-sandbox`, compositor unsafe
mode, portal impersonation, extension enabling, stale helper substitution,
untrusted interpreter receiver or environment trust override is allowed.

Native screenshots/logs, installed module paths, package/compositor versions,
source SHA, candidate SHA-256, corpus digests and VM configuration stay under
`/mnt/storage/odin-desktop-evidence/p35-20261007/`. Candidate construction is
nonpublishing. Evidence from another candidate/environment cannot fill a row.

## Exact corpus accounting

The driver records digests of each reference corpus. Reuse means composition of
its measurement/ownership patterns, not copying an earlier passing verdict:

| Backend | Retained corpus | P3.5 mapping |
|---|---|---|
| X11 | `controller-gui.py` | Real controller/store start, observation image validation and exact delivery, action binding, cleanup |
| X11 | `x11-owned-guardian-corpus.py`, `x11-owned-evidence-check.py` | Separate receiver press/motion/release observations; guardian vs controller loss; receipts are not receiver proof |
| GNOME | `wayland-portal.py`, `wayland-r8-evidence.py` | Real portal consent/capture/input remain separate; EOF/release semantics and native scope prerequisites |
| KDE | `wayland-r8-evidence.py` and retained KWin scope provider | Per-desktop scope/ABI qualification, never replacing KDE with Hyprland proof |
| Hyprland | `hyprland-live-qualification.py`, `hyprland-recovery-qualification.py`, `hyprland-wire-receiver.c` | Exact compositor/resource identity, original-owner release-only recovery, receiver barriers/held-state evidence |

The retained reference scripts have hard-coded container/guest identities and
paths. They are not repointed at a running desktop or silently called with fake
environments. P3.5's compiled harmless GTK receiver reproduces their independent
event/held-state measurement shape. It accepts only its private EOF/geometry
fixture control, not commands, credentials or external documents.

### Headless regression mapping, not native evidence

| Cases | Exact reused tests |
|---|---|
| Fresh observations, stale generations and geometry | `test_computer_freshness_r1.py`, `test_computer_geometry_r1.py` |
| Native semantic/postcondition/modal contracts | `test_computer_native_gui_r5.py` |
| Action validation | `test_computer_actions_r4.py` |
| Desktop foreground admission, cancellation, management and restart/recovery fences | `test_desktop_computer_binding.py` |
| Durable receipt/recovery | `test_computer_class1_receipt_recovery.py` |
| Packaged helper/managed-plugin contract | `test_computer_hyprland_packaging_r32.py`, `test_hyprland_plugin_campaign.py` |
| New VM admission, nonempty receiver corpus, post-motion release ordering and receipts-only rejection | `test_desktop_native_qualification.py` |

Two inherited native-regression entry points were inspected but could not collect:
`test_computer_hyprland_durable_fence_r42.py` and
`test_computer_native_keyboard_focus_class.py` import the removed gateway
`ApiTokenIdentity` through `test_computer_operator_auth_r5.py`. These are not
passing qualification. The driver maps active Desktop admission/recovery tests
instead; it does not restore the removed gateway identity or weaken guards.

## Acceptance discipline

No empty corpus, mocked adapter, successful helper usage refusal, controller
receipt or unrelated screenshot can turn a backend into `proven`. Native receiver
cases, discovery/ABI checks, app/core restart and Exit evidence are distinct.
The classification is conservative: complete required receiver/platform evidence
and no blockers are necessary. Partial measured subsets are `limited`.

Unknown release stops all input and replacement. A later successful close,
RELEASE-ALL, process death, another backend or local drained ledger does not
prove native release or erase durable quarantine. The X11 fault corpus kills
only its exact owned guardian after receiver button-down; it attempts no global
release, replacement receiver or replay outside the durable refusal checks.
Controller/store reconstruction is explicitly not Electron/core process restart.

## Required decisions

Unresolved candidate helper path/ABI closure, GNOME scope opt-in prerequisites,
KDE companion build support and Hyprland exact-version availability remain D11
blockers until measured. Correct tool absence is not backend support. Aaron must
decide the supported release subset or authorize the missing backend work; this
PR never silently waives the promised desktop rows.
