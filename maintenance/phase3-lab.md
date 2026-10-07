# Phase 3 qualification lab: Decision A

## Status at 2026-10-05

**Four-VM lab smoke passed. Not P3.3-P3.6 acceptance.** Branched
from pulled `main@a3eca761f53713daeb8a329357f6aab3e63624f9`. The lab-only Incus
directory pool is available. All four guests have booted into their required
sessions with Orca running and guest screenshots captured and inspected.
The later packaged application and native P3/P4 gates remain separate.

The host preflight and subsequent setup found:

- Incus client/server **7.5.1**, QEMU driver **11.1.2**; `/dev/kvm` present.
- The existing `default` ZFS pool and `bots` instance were left unchanged; the
  former offline pool is not used or repaired by this lab.
- Created the lab-only Incus `dir` pool `odq-lab`, sourced from
  `/mnt/storage/odq-lab`. Incus refused the proposed custom loop-file command
  `incus storage create odq-lab zfs source=/mnt/storage/odq-lab.img size=100GiB`.
  The directory driver avoids the hand-managed loop attachment/reboot problem.
  No reboot or service restart test has been performed.
- Each VM has a **thin 40 GiB** root disk. Admission uses a **150 GiB aggregate
  allocated-space budget** (raised from 100 GiB on 2026-10-07). It reserves the
  remaining growth of every guest that may run during the operation: each
  running guest and the one being started, up to its 40 GiB cap, plus 10 GiB
  overhead each; a new guest or snapshot reserves a full 40 + 10 GiB. It keeps
  a **50 GiB free filesystem floor after that reserved growth** (stopped guests
  cannot grow, and every operation that adds data runs the preflight first).
  Optional snapshots are not the default; rebuild disposable guests instead.
- The existing managed `incusbr0` NAT bridge remains in use. `bots` was not
  modified; its Incus metadata was compared before/after, not its files.

Thin disks are logical caps, not reservations. Capacity checks fail closed if
the aggregate allocation budget, running-guest growth reserve, filesystem floor,
two-VM limit, or host-memory preconditions are not met. The lab tool does
not create, import, repair, resize or replace storage.

## Pinned images and guest recipes

All are real **x86-64 virtual-machine** image products, not container rootfs
images. Remote `images` is the existing
`https://images.linuxcontainers.org` SimpleStreams remote. Full manifests,
metadata/QCOW2 SHA-256s and public provenance are in
`scripts/qualification/lab/images/*.json`.

| VM | Base | Image serial | Graphical target | Capture |
|---|---|---|---|---|
| `odq-cinnamon` | Ubuntu 24.04 noble default | `20261005_07:42` | Cinnamon, LightDM, X11 | guest `scrot` |
| `odq-gnome` | Ubuntu 24.04 noble default | `20261005_07:42` | GNOME 46 family, GDM, Wayland, extensions disabled | guest `gnome-screenshot`, then Shell D-Bus |
| `odq-kde` | Ubuntu 24.04 noble default | `20261005_07:42` | Plasma 5.27 family, SDDM, Wayland | guest Spectacle/KWin |
| `odq-hyprland` | Ubuntu 26.04 resolute default | `20261005_07:42` | `hyprland=0.53.3+ds-4`, SDDM, native Wayland | guest `grim` |

Noble VM fingerprint, shared by the first three:

```text
7420d4416f4d8bfb3ad6098d2395f86ca5aaf298c2696283ee61200d0b5c9714
```

Resolute VM fingerprint:

```text
beff715a10e50946d610c1e47f6411c41fd50e6d56927019e76810665c847d49
```

Mint 22-series products inspected did not offer a VM disk, so Cinnamon uses
the explicitly permitted Ubuntu fallback. Noble/trixie do not provide the
required packaged Hyprland; resolute supplies the pinned release without a
PPA or source-build substitution.

**Reproduction boundary:** these fingerprints pin the base metadata/disk,
not the whole apt dependency closure. Except Hyprland's explicit package
version, packages resolve through the guest's distro repositories. Installed
versions are captured in `packages.tsv`; exact post-provision reproduction
requires keeping the configured VM snapshot. Daily upstream images can expire.
The tool fails rather than substitute a moving image alias. Image pins have
been checked against public metadata; Noble has now been booted for Cinnamon
GNOME and KDE smoke. Resolute has been imported and boot-verified for Hyprland.

## Resource and ownership boundaries

- Each VM: **4 vCPU, 8 GiB RAM, thin 40 GiB disk**. `boot.autostart=false`.
- Empty profile list, explicit root disk in `odq-lab`, one NIC on the existing
  `incusbr0` NAT bridge. **No shared host directory, physical GPU/display,
  input or audio device, proxy device, raw QEMU override or host credential.**
- Unique `user.odq.owner=odin-desktop-qualification-v1` marker; commands also
  validate VM type, exact caps and expanded devices. Names alone confer no
  removal authority. `bots` is not an accepted CLI target.
- At most two VMs at once (Decision H): operations refuse when two other VMs
  are not stopped, counting VMs outside this lab. Commands take a same-operator
  cross-checkout lock and wait up to 15 minutes for another lane's command to
  finish; manual Incus actions bypass that lock, so operators must not race the
  lab runner.
- At least 12 GiB host memory headroom before create/start/provision/smoke.
- 150 GiB aggregate allocation budget; each guest that may run reserves its
  remaining growth to the 40 GiB cap plus 10 GiB, and the 50 GiB filesystem
  floor holds after that growth. No snapshots by default; rebuild disposable
  guests.
- Graceful guest-agent poweroff and bounded agent waits; no automatic force,
  replay, background start, storage repair or global profile mutation.
- Guest-only user `odq`, no known password, explicit graphical autologin,
  Orca/accessibility startup. SSH, discovery, printing and RPC network
  listeners are masked in the guest. Smoke rejects non-loopback listeners,
  apart from DHCP client ports required for NAT networking. Cinnamon/GNOME use
  a locked password; KDE/Hyprland use a random unexposed password hash because
  SDDM's PAM account checks can reject locked accounts even for autologin.
- Repository files and evidence/lock scratch are the only non-Incus files
  written by the host-side workflow. No service or active desktop is changed.

## Operator commands

Use Python 3.12 or the repository `.venv/bin/python`. The host must already
have Incus, KVM, the pre-created `odq-lab` directory pool, sufficient storage
and non-interactive Incus access via `sudo -n`. No script installs host
prerequisites. The lab tool never accesses the old `default` pool.

```bash
python3 scripts/qualification/lab/lab.py preflight
# Reports the odq-lab pool and current capacity preflight.
```

Run this lifecycle **for one named VM at a time**, substituting each of the
four accepted names. The first start is only for the Incus guest agent and
provisioning. Provision stops the VM; the second start exercises graphical
autologin. Snapshots are optional and omitted by default; rebuild guests unless
there is a specific reason to retain one.

```bash
python3 scripts/qualification/lab/lab.py create odq-cinnamon
python3 scripts/qualification/lab/lab.py start odq-cinnamon
python3 scripts/qualification/lab/lab.py provision odq-cinnamon
python3 scripts/qualification/lab/lab.py start odq-cinnamon
# Allow session startup, then run once with a NEW evidence directory.
python3 scripts/qualification/lab/lab.py smoke odq-cinnamon \
  --evidence /home/odin/reviews/odq-cinnamon-smoke-20261005
python3 scripts/qualification/lab/lab.py stop odq-cinnamon
# Only if discarding this lab VM deliberately:
python3 scripts/qualification/lab/lab.py remove odq-cinnamon
```

`provision` uploads only the common/desktop recipe and smoke helper through
Incus file transport; runs apt and configuration **inside the guest**; records
packages; then requests `systemctl poweroff --no-block` through the guest agent
and polls Incus state for up to 180 seconds. It does not use Incus ACPI stop,
which can suspend Cinnamon, and never automatically force-stops, replays, or
falls back to ACPI if poweroff is unconfirmed. On timeout inspect the disposable
guest before explicit recovery. One manual emergency force-stop was needed for
the exact disposable `odq-cinnamon` after its first ACPI stop suspended it; a
subsequent agent poweroff stopped it cleanly. This was exceptional recovery,
not routine lifecycle policy. `snapshot` and `remove` require stopped, marked
instances. Scripts are sourceable/generated-fixture capable for offline tests;
**never execute guest provisioning directly on the workstation**.

The `smoke` command requires a running owned VM. It verifies active `odq`
logind session identity and X11/Wayland type, reads that guest session's
environment, checks Orca under the guest UID, invokes the desktop's guest
capture helper, decodes/non-uniformity checks the PNG, and pulls `guest.png`,
`proof.json`, `packages.tsv` and listener evidence. The record includes source
SHA and screenshot hash. **Open and inspect the screenshot before describing
its pixels.** Failed captures cannot write a passing proof. Existing evidence
directories are refused, not overwritten.

`source_sha` identifies the checkout's base commit; `source_dirty` says whether
that checkout had local changes. Host source digests cover the runner, uploaded
recipes/smoke and image manifest. Guest digests cover the actual uploaded
scripts and generated capture helper. Stale uploaded scripts record a failed
proof and require reprovision. The initial proof paths below were development
runs at base `3337716` with working-tree fixes; they do not claim that base
commit alone contains the successful implementation. Final committed-source
reprovision/smoke evidence is added separately, preserving these originals.

GNOME/KDE capture can be denied by native policy or require guest interaction.
No unsafe GNOME mode, caller spoof, X11 fallback for a Wayland desktop, or
synthetic headless screenshot is allowed. GDM may refuse Wayland autologin
despite preferences; this is a failed smoke, not permission to claim X11 as
Wayland.

## Smoke evidence, current PR

Final evidence is checked in under
`maintenance/evidence/phase3-lab-20261005/{cinnamon,gnome,kde,hyprland}/`:
`proof.json`, the actual guest PNG, installed `packages.tsv`, and listener
evidence. These runs used committed sources and hash-matched uploaded scripts.
Cinnamon/GNOME ran at `dcb2d349`; KDE/Hyprland ran at `ff347abb` after KDE's native
screen-reader setting fix. The original development paths below are retained
for incident provenance, not substituted for the final evidence.

| VM | Graphical boot | Orca starts | Guest screenshot | Verdict |
|---|---|---|---|---|
| `odq-cinnamon` | 1280x800 X11 active | Orca process present | Captured and visually inspected: `/home/odin/reviews/desktop-lab-storage-20261005/cinnamon-smoke/guest.png` | **Smoke passed** |
| `odq-gnome` | 1280x800 Wayland active; GNOME identity verified | Orca process present | Captured: `/home/odin/reviews/desktop-lab-storage-20261005/gnome-smoke-3/guest.png` | **Smoke passed** |
| `odq-kde` | 1280x800 Wayland active; KWin/Plasma | Orca process present | Captured and visually inspected: `/home/odin/reviews/desktop-lab-storage-20261005/kde-smoke-2/guest.png` | **Smoke passed** |
| `odq-hyprland` | 1280x800 native Wayland, Virtual-1 | Orca process present; accessibility bus responds | Captured and visually inspected: `/home/odin/reviews/desktop-lab-storage-20261005/hyprland-smoke-2/guest.png` | **Smoke passed** |

The proof directories contain guest `proof.json`, screenshot, package list and
listener evidence. Smoke proves guest session identity/type, Orca process
presence and a decodable guest capture; it does **not** prove spoken output or
application accessibility. GNOME setup required typed dconf arrays
(`enabled-extensions` as `@as []`) and disabling extensions; no tray extension
is installed. Its native EGL startup segfault was fixed by removing
`LIBGL_ALWAYS_SOFTWARE` while retaining `GALLIUM_DRIVER=llvmpipe`; the actual
session and capture then passed. Keep runtime implementation detail here, not
in image pin manifests.

Shared guest smoke uses systemd 255, which does not provide the prior JSON
`loginctl` output. It parses supported output and can identify a session using
the actual guest environment and owned compositor when logind's `Desktop`
field is empty. Listener checks allow the complete loopback `127.0.0.0/8`, not
only selected resolver addresses. These observations do not claim any unrun
desktop lane. KDE also needed writable intermediate `.config` directories and
the same software-device flag correction. Hyprland needed those directory
ownership fixes, explicit GLib command packages, and activation on its actual
nested D-Bus without `--systemd`. Its screenshot shows the native Foot terminal;
no XWayland process was present. Privileged file pulls now precreate private
operator-owned files, preserving access to grim's mode-0600 PNG.

A repeated KDE boot exposed an Orca startup conflict: native KAccess loaded
its default disabled screen-reader setting and reset GSettings to false;
Orca then exited cleanly. The KDE recipe now writes user-owned `kaccessrc`
`[ScreenReader] Enabled=true`, verified against Plasma 5.27.12. The shared
desktop wrapper also serializes settings followed
by a single Orca launch, disables the builtin duplicate autostart using standard
XDG `Hidden=true`, and waits at most 30 checks for Plasma's bus name. A fresh
KDE boot retained Orca without manual restart once the native setting agreed.
KAccess itself may invoke `orca --replace`; this is native desktop behavior,
not an additional custom restart loop. The readiness check is bounded and
actual spoken output remains untested.

After the first four smokes all guests were stopped. Actual pool allocation was
**15.04 GiB**, with **198.56 GiB** free on `/mnt/storage`. The workflow
budget (100 GiB then, 150 GiB since 2026-10-07) is an admission check, **not a kernel quota or continuous monitor**.
Do not race this runner with manual Incus changes or unrelated storage writers.
No snapshots were retained. These are lab smoke proofs, not P3.3-P3.6 acceptance.

Final retained four-VM pool allocation is **15.91 GiB**, with **197.69 GiB**
free on `/mnt/storage`. All four VMs are stopped with no snapshots. The old
`default` pool remains Unavailable; its configuration and `bots` metadata match
the original before-state byte-for-byte. No reboot was induced to test pool
startup; the dir source is persistent Incus configuration, with no loop device
to recreate or custom host startup service.

## Virtual GPU meaning

No `gpu` device is added. Incus/QEMU's emulated display is rendered in the
guest using Mesa llvmpipe configuration appropriate to each compositor. GNOME's
native Wayland EGL path unsets `LIBGL_ALWAYS_SOFTWARE` and sets
`GALLIUM_DRIVER=llvmpipe`; blindly forcing that variable caused a native EGL
startup failure. KWin logs explicitly reported llvmpipe and DRM presentation.
Hyprland/Aquamarine enumerated virtio_gpu and Virtual-1, and grim captured its
native terminal. Its clean-source screenshot also shows startup notices for
missing `hyprland-guiutils` and the direct Hyprland launcher; the terminal,
Orca and capture work, but these notices are not hidden or called full session
qualification. EGL device-query warnings remain; smoke success is not a
blanket renderer qualification or hardware-performance claim.

A passing smoke can prove graphical session startup, an Orca process,
guest capture and the inspected pixels under this virtual hardware. It cannot
prove physical GPU drivers/performance, Aaron's monitor layout, host input or
audio, actual spoken Orca output, Electron accessibility trees, real portal
consent, backend containment/recovery, native receiver delivery or the later
packaged qualification matrix. Those need their named P3/P4 gates.

## Validation

Offline tests execute orchestration against simulated Incus and emitted guest
helpers/configuration against temporary fixtures. They cover capacity refusal,
one-VM enforcement, ownership/caps/devices, no forced deletion, preserved
evidence, wrong desktop/session rejection, capture-denial paths and package
service-policy restoration. Every engine/test invocation uses the repository's
PID-namespace launcher; no VM/native receiver is involved in these tests.

Final source and test counts are recorded in the PR. The engine drift/lint
gates and existing qualification groups ran from a fresh checkout at `ff347abb`:
**225 lab tests passed**, **28/28 engine groups passed** with **13,145 passing
executions and 2 skips**. Drift has zero errors (review remains pending), lint
has zero new findings, Ruff and ShellCheck are clean. App sources are unchanged
from `f6d649a8`; a fresh checkout there passed typecheck, **281 tests**, build,
and the isolated Xvfb fixture smoke. That fixture is not a VM/native proof.
Evidence-only commits following those source commits do not alter executable
code. No
merge, deployment, host-service restart, host package installation or
active-session input. Guest installs, graphical restarts and guest shutdowns
are part of the isolated lab lifecycle.
