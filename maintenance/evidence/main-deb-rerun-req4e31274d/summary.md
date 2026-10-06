# req-4e31274d: fresh current-main packaging and one native `.deb` GUI row

Requested artifact delivered: fresh `.deb`/AppImage candidates, one installed
fixed-probe GUI measurement, `maintenance/p41-packaging.md` update and small
evidence-only follow-up PR. No attribution trailers or production code edits.

## Source and candidates

Fetched-main source: `b276b0b34c44c553ed1aa9042e716bf06395694f`.
Includes merged #54 `64d94ba0fce090d353f1dccc43495d6bce91b35a` and #65's
historical report at `53048159a819d29fd8aa7046072a6e2077ed316d`.
No old candidate was reused. #59 head observed:
`8d980f10d0bd2a6a522d6ac7216b5c5ca4c5f09c`.

External root `E`:
`/mnt/storage/odin-desktop-evidence/req-4e31274d-main-rerun-20261006/`.

| File beneath E | Bytes | SHA-256 |
|---|---:|---|
| `candidates/odin-desktop-0.1.0-candidate-amd64.deb` | 341790224 | `c403cfc3727e13b66a8a6fda41fcd9ac3d164ef8dd4d2e6a055656e674a8527b` |
| `candidates/odin-desktop-0.1.0-candidate-x86_64.AppImage` | 489730884 | `f0ceae7f04d072bb9743c772609b28543e83f0c52f199c03631bb02164699303` |

Sealed candidate resource manifest:
`27027e423f61545647899722138671f67d36e638e58852219d4eb85e9d0c2903`,
8,493 entries / 975,918,800 bytes, identical in both extracted formats and the
installed tree. The earlier runtime-stage manifest has a different digest and
is not the final application inventory. Source/engine wheel provenance is in
`source-git.txt`, `source-files.sha256` and the chained build manifest.

Build environment initially symlinked the small `app/out` directory externally;
electron-builder's ASAR allowlist omitted it and the first build failed before
installers. Correcting only that environment to an actual build directory and
freshly sealing both formats succeeded. That failed build log is retained.
Shared caches were only read/copied; no manifest expectations were weakened.
`manage_process` start hit its existing 20-process limit; builds/qualifier used
owned bounded timeout scripts with tee logs and exit markers. No other process
was killed or process registry changed.

## Prerequisite qualification PASS

Real P4.1 qualifier: `.deb` extracted, AppImage extracted and `.deb` installed
all pass manifest/scan, real core handshake/status/events/ping/clean shutdown,
offline sandboxed bundled Chromium, embedding/PDF/native-helper checks, and
sandbox-intact private-Xvfb GUI screenshots with clean app/core receipts.
`qualification/qualification.json`: gate `pass`, errors `[]`.
No AppArmor profile or ASAR mismatch; preinstall Python available.
Installed-root audit proves root-owned 0755 application paths and exact owned
profile/receipt. Its chroot has no parser and does not prove kernel loading.
It uses dpkg force-depends, not clean distro dependency resolution. Extracted
AppImage is not FUSE qualification. No active-workstation display/bus/input.

Real-root isolated tests: hooks 22 pass, preflight 9 pass, prerequisites 8 pass.
They cover foreign/local-profile preservation, symlink/untrusted-directory
refusal, parser failure fencing and ownership boundaries, not a live foreign
profile replacement. Fresh native guest install adds real kernel-load evidence.

## One installed native GUI row FAIL, gate OPEN

One launch only, 2026-10-06 13:15:38–13:16:26 UTC. The exact merged fixed probe
SHA is `74d68b9d9c8c342bcab4f87a60561d559abe7c336641c7542455b200449eec30`.
Only the driver proof/config/data/cache root changed. Read-only guest-root
collector sampled namespaces concurrently, without launching candidate code.

`odq-gnome`: KVM, Ubuntu 24.04.5, kernel 6.8.0-146-generic, active GNOME
Wayland, odq UID/GID 1001. All other odq VMs stopped throughout. AppArmor active;
both `apparmor_restrict_unprivileged_userns` and
`apparmor_restrict_unprivileged_unconfined` are 1 at measurement. The latter
reset to 0 at reboot and was restored first. This is a restored-policy minimal
Noble lab, not untouched stock-desktop evidence. Unprofiled unshare is denied.

Actual postinst installs `/etc/apparmor.d/odin-desktop`, matching immutable
resource bytes and root-owned 0644 single-link ownership receipt with SHA
`6f974f7403762ac6b2e39e5e77d3f2b0ac0a1b39ac3fb5d640cfdf4745d7972e`.
Both `odin-desktop` and `odin-desktop-headless` are loaded in the real guest
kernel. Profiles intentionally use unconfined plus userns. `dpkg -V` clean;
archive SHA and installed manifest match the fresh qualified candidate.

284 saved renderer samples, PID 1505: Seccomp 2, NoNewPrivs 1, zero effective
capabilities, enable-sandbox, no no-sandbox/disable-setuid-sandbox switches,
`odin-desktop (unconfined)` attachment. Concurrent root witness:

| Namespace | Guest init | Renderer | Distinct |
|---|---|---|---|
| user | `user:[4026531837]` | `user:[4026532707]` | yes |
| pid | `pid:[4026531836]` | `pid:[4026532708]` | yes |
| net | `net:[4026531840]` | `net:[4026532711]` | yes |
| mount | `mnt:[4026531841]` | `mnt:[4026531841]` | no |

`NSpid: 1505 4 1` corroborates nested PID namespaces. This proves renderer
sandbox establishment, not final GPU-process confinement or GUI acceptance.

Exit 1: `smoke: timed out`, then `UnknownVizError`. No screenshot or ready
success marker. Source smoke calls capturePage after readiness and kills the
app at 45 seconds. Electron 44.5.1 maps UnknownVizError to Viz surface-copy
failure (see historical #65 analysis). The fresh one-shot journal shows virtio
GPU -virgl, failed EGL dri2, kms_swrast fallback and unavailable accelerated
framebuffer sharing. Private Xvfb works; native Wayland capture does not.
Graphics-path incompatibility is supported but not conclusively isolated;
the Viz error follows timeout and may be teardown-induced. No relevant
candidate AppArmor/SECCOMP denial retained, only deliberate unshare control.
No graphics overrides, sandbox weakening, comparative launch or retry.

## Lab reset, validation, deferred scope and cleanup

Historic app running receipts from prior timeout rows correctly fenced old
package removal despite no PIDs. The full old registry/profile/maintainer
metadata and unresolved receipts were preserved unchanged in guest quarantine
`/var/tmp/req4e31274d-old-install-quarantine/` under an exclusive package lease.
An explicitly offline disposable-lab registry reset then allowed owned profile
unload/removal and a clean candidate installation. No receipt was changed to
clean; no foreign profile touched. This is NOT upgrade acceptance. The new
failed row also leaves app receipt running/core clean; no processes remained.
No subsequent install or receipt rewrite. VM stopped normally afterward.

Operational validate_action bundles all passed after VM start, restriction/helper
staging, removal refusal, offline removal, fresh install, row execution and stop.
Inventory 0 errors / byte-drift-clean-review-pending; lint 0 new, 7 inherited.
Only ruff 0.16.10 added to disposable checkout venv for the lint gate. No full
application/engine suite or release/native matrix acceptance claimed.

No Cinnamon rerun/full matrix, no later GNOME/KDE lifecycle, native browser or
FUSE AppImage row. Both candidates remain reusable for separately authorized
#59 work. All odq VMs STOPPED; root about124GB free, storage116GB. Raw >100KB
proofs remain external; Git contains only small summary/log/digest manifest.
Private generated credentials, keys and caches excluded from public manifest.
Own fresh checkout removed after push/internal result; candidates/evidence and
all other lanes, including `/home/odin/desktop-p41-cache`, retained untouched.
No host policy changes, live deployment, /opt/odin development/restart, active
graphical desktop input, release or PR merge.
