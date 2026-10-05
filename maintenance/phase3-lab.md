# Phase 3 qualification lab: Decision A

## Status at 2026-10-05

**Partial build, runtime blocked. Not a completed qualification lab.** Branched
from pulled `main@a3eca761f53713daeb8a329357f6aab3e63624f9`. Four image/guest
lanes were built in parallel; integration and checks are recorded below.

The host preflight found:

- Incus client/server **7.5.1**, QEMU driver **11.1.2**; `/dev/kvm` present.
- Existing `default` ZFS storage pool reports **Unavailable**. Its configured
  source is `incus`; the `incus` zpool is exported, not imported.
- `/mnt/storage/incus/incus.img` is **107,374,182,400 bytes (100 GiB)**.
  Read-only `zpool import -d /mnt/storage/incus` discovers it ONLINE; this was
  discovery only, **not** `zpool import incus`.
- Offline `zdb -e -p /mnt/storage/incus -d incus` reports the existing
  `incus/containers/bots` dataset as **44.2 GiB**. No bots files were opened.
- Read-only metaslab inspection estimates **55.84 GiB free**, rounded from
  199 metaslabs. This is **not** imported ZFS `available`, does not account for
  all reservations/slop, and does not make Incus usable.
- Backing filesystem `/mnt/storage`: **214 GiB available** at inspection.
  Host memory had approximately **44 GiB available** by `free -h`.
- Only existing instance: `bots`, **Stopped**. It remains untouched. The
  managed `incusbr0` bridge already has IPv4 and IPv6 NAT. No forwarded lab
  services, profiles or instances were created.

**Required external decision before runtime:** restore availability of the
existing pool without altering `bots`, and provide sufficient storage. The
tool conservatively requires **180 GiB available** before the first creation:
four 40 GiB disks plus 20 GiB image/snapshot/headroom budget. It uses Incus
`zfs.reserve_space=true` on each lab volume rather than silently overcommitting
the pool. Current offline free estimate is approximately **124 GiB short**,
before ZFS slop. A roughly **256 GiB total pool** would be a reasonable target,
subject to operator validation of real imported availability and backing-disk
headroom. **No import, resize, replacement pool, host package installation,
Incus restart or bots cleanup was attempted.**

Reducing the disks or accepting thin overcommit requires a separate decision;
the scripts do neither. The existing 100 GiB pool cannot meet the chosen
conservative capacity gate even if restored.

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
The tool fails rather than substitute a moving image alias. The image pins
have been checked against public metadata, but not imported or boot-verified.

## Resource and ownership boundaries

- Each VM: **4 vCPU, 8 GiB RAM, 40 GiB disk**. `boot.autostart=false`.
- Empty profile list, explicit root disk in `default`, one NIC on the existing
  `incusbr0` NAT bridge. **No shared host directory, physical GPU/display,
  input or audio device, proxy device, raw QEMU override or host credential.**
- Unique `user.odq.owner=odin-desktop-qualification-v1` marker; commands also
  validate VM type, exact caps and expanded devices. Names alone confer no
  removal authority. `bots` is not an accepted CLI target.
- One VM at a time: operations refuse another non-stopped VM, including a VM
  outside this lab. Commands take a same-operator cross-checkout lock; manual
  Incus actions bypass that lock, so operators must not race the lab runner.
- At least 12 GiB host memory headroom before create/start/provision/smoke.
- Only graceful stop, bounded agent waits; no automatic force, replay,
  background start, storage repair or global profile mutation.
- Guest-only user `odq`, locked password, explicit graphical autologin,
  Orca/accessibility startup. SSH, discovery, printing and RPC network
  listeners are masked in the guest. Smoke rejects non-loopback listeners,
  apart from DHCP client ports required for NAT networking.
- Repository files and evidence/lock scratch are the only non-Incus files
  written by the host-side workflow. No service or active desktop is changed.

## Operator commands

Use Python 3.12 or the repository `.venv/bin/python`. The host must already
have Incus, KVM, ZFS, sufficient storage and non-interactive Incus access via
`sudo -n`. No script installs host prerequisites.

```bash
python3 scripts/qualification/lab/lab.py preflight
# Currently exits 1 with BLOCKED: default ZFS pool is unavailable.
```

After external storage restoration/capacity approval, run this lifecycle
**for one named VM at a time**, substituting each of the four accepted names.
The first start is only for the Incus guest agent and provisioning. Provision
stops the VM; the second start exercises the configured graphical autologin.

```bash
python3 scripts/qualification/lab/lab.py create odq-cinnamon
python3 scripts/qualification/lab/lab.py start odq-cinnamon
python3 scripts/qualification/lab/lab.py provision odq-cinnamon
python3 scripts/qualification/lab/lab.py snapshot odq-cinnamon --label configured
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
packages; then gracefully stops. Failure leaves an explicit error and may
leave the VM running, so inspect and stop it with the named lab command before
continuing. `snapshot` and `remove` require stopped, marked instances. Scripts
are sourceable/generated-fixture capable for offline tests; **never execute
guest provisioning directly on the workstation**.

The `smoke` command requires a running owned VM. It verifies active `odq`
logind session identity and X11/Wayland type, reads that guest session's
environment, checks Orca under the guest UID, invokes the desktop's guest
capture helper, decodes/non-uniformity checks the PNG, and pulls `guest.png`,
`proof.json`, `packages.tsv` and listener evidence. The record includes source
SHA and screenshot hash. **Open and inspect the screenshot before describing
its pixels.** Failed captures cannot write a passing proof. Existing evidence
directories are refused, not overwritten.

GNOME/KDE capture can be denied by native policy or require guest interaction.
No unsafe GNOME mode, caller spoof, X11 fallback for a Wayland desktop, or
synthetic headless screenshot is allowed. GDM may refuse Wayland autologin
despite preferences; this is a failed smoke, not permission to claim X11 as
Wayland.

## Smoke evidence, current PR

| VM | Graphical boot | Orca starts | Guest screenshot | Verdict |
|---|---|---|---|---|
| `odq-cinnamon` | Not run | Not run | None | **BLOCKED: unavailable/undersized storage** |
| `odq-gnome` | Not run | Not run | None | **BLOCKED: unavailable/undersized storage** |
| `odq-kde` | Not run | Not run | None | **BLOCKED: unavailable/undersized storage** |
| `odq-hyprland` | Not run | Not run | None | **BLOCKED: unavailable/undersized storage** |

No screenshots are attached because no guest was created. Offline behavioral
tests are not smoke proofs. This PR delivers scripts/recipes/preflight evidence,
**not P3.3-P3.6 runtime acceptance**. Resume with approved external storage work.

## Virtual GPU meaning

No `gpu` device is added. Incus/QEMU's emulated display is rendered in the
guest using requested Mesa llvmpipe. Runtime must still establish virtual
DRM/KMS/GBM/EGL compatibility, especially Hyprland/Aquamarine. Environment
switches, source compilation and VM existence alone prove nothing about that.

A passing future smoke can prove graphical session startup, an Orca process,
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
gates and existing qualification groups are rerun from a fresh checkout. No
merge, deployment, restart, host package installation or active-session input.
