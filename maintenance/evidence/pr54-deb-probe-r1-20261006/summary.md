# PR #54 round 1: one fixed-probe installed `.deb` row

Requested artifact: a recorded installed `.deb` GUI row with the fixed probe,
updated `maintenance/p41-packaging.md`, and a follow-up PR because #54 merged.

**Result: FAIL, exit 1; Ubuntu GUI gate OPEN. Renderer sandbox directly observed.**
One launch only, 2026-10-06 10:48:11–10:48:58 UTC. Browser, AppImage and P3.3
lifecycle cases were not rerun. No production code changed or package rebuilt.

## Identity and method

- Follow-up base: `541d29e7ad53ec4cd231a371774aa8fbb8f5500c`.
- Original package source: `d142968a3533c9a930f7e3147ef8cca6c79183e7`.
- Installed `.deb`: 341,776,612 bytes, SHA-256
  `41b8a927bd06d45ed0c1403d153ca038b33b31c11ea65f614a527bacc9609551`.
  Guest package archive agrees with retained host candidate; `dpkg -V` is empty.
- Installed Electron image SHA-256:
  `9155dd17c16f0edeaadb74db4fd91e2730511cca83e8b130d59bab57aa4d4e4b`.
- Exact merged `scripts/packaging/ubuntu_userns_probe.py` SHA-256:
  `74d68b9d9c8c342bcab4f87a60561d559abe7c336641c7542455b200449eec30`.
  Probe contents and candidate arguments unchanged. Driver differs only in a
  fresh proof/config/data/cache root and its reference to the exact fixed probe.
- Guarded read-only root collector sampled process status and namespace links
  concurrently. It neither launched nor altered the candidate or its renderer.
- `odq-gnome`, KVM, Ubuntu 24.04, kernel `6.8.0-146-generic`, nonroot UID 1001,
  verified active GNOME Wayland. No other heavy VM ran. Both AppArmor restrictions
  were 1 at launch. The second had reset to 0 on reboot and was restored before
  the row; policy/session/probe validation passed before any candidate launch.
  Unprofiled namespace control was actually denied. Restored-policy limitations
  from the original run remain; this is not untouched-stock desktop evidence.

## Saved witnesses

`deb/observations.json` retains **285 samples** of renderer **1378**. Every sample
has UID 1001, `NoNewPrivs: 1`, `Seccomp: 2`, `Seccomp_filters: 1`, zero effective
capabilities and `--enable-sandbox`, with neither renderer sandbox-disable flag.
The AppArmor exception reads `odin-desktop (unconfined)`, intentionally not
enforcing application confinement.

The concurrent root witness corroborates:

| Namespace | Guest PID 1 | Renderer 1378 | Different |
|---|---|---|---|
| user | `user:[4026531837]` | `user:[4026532708]` | yes |
| pid | `pid:[4026531836]` | `pid:[4026532709]` | yes |
| net | `net:[4026531840]` | `net:[4026532712]` | yes |
| mount | `mnt:[4026531841]` | `mnt:[4026531841]` | no |

Renderer `NSpid: 1378 4 1` independently corroborates nested PID namespaces.
The collector's early GPU/zygote snapshots are **not** final GPU sandbox proof;
the acceptance statement here is scoped to the renderer.

## Failure attribution and limits

The launch log again records `smoke: timed out`, followed by an unhandled
`UnknownVizError`. Screenshot absent, success marker absent, row exit 1. The
merged probe now preserves its observations before this failed assertion.

Pinned Electron 44.5.1 source maps the exact error to
`CopyFromSurfaceError::kUnknownVizError` and rejects the capture promise in
`OnCapturePageDone`:
https://github.com/electron/electron/blob/v44.5.1/shell/browser/api/electron_api_web_contents.cc

The unchanged candidate's smoke path calls `webContents.capturePage()` only
after broker readiness, then writes the screenshot and success marker. Thus
the error identifies the Viz surface-copy/capture path; it is not evidence that
the renderer failed to establish its sandbox. Renderer sandbox establishment
is positively witnessed above, but does not prove rendering or end-to-end GUI
acceptance.

The error is logged after the timeout. It may be a surface-copy rejection
caused by deadline-driven `app.exit(1)`, rather than the original cause of the
capture stall. No event trace resolves that ambiguity in this one measurement.

The journal records virtio GPU without virgl/capability sets, EGL dri2 failure,
`kms_swrast` fallback and unavailable accelerated framebuffer sharing. A
VM/Electron Wayland graphics incompatibility is a supported hypothesis, **not
a conclusively isolated root cause**. No relevant candidate AppArmor/SECCOMP
denial is retained; the deliberate unprofiled `unshare` control is the only
namespace-related denial. No graphics flags, sandbox relaxation, comparative
launch or additional retry was used to force a passing screenshot. Gate stays
OPEN on the exact observed Viz capture failure pending separately authorized
graphics-path qualification.

## Validation, retention and cleanup

- Inventory report: **0 errors**, static byte-drift clean; independent review
  remains pending, not release qualification.
- Lint gate: **0 new findings**, 7 inherited. The first attempt found no checkout
  `.venv/bin/ruff`; installed only `ruff==0.16.10` in the disposable worktree's
  venv and reran the static gate successfully. No app/engine suite claimed.
- Initial evidence-access check failed because pulled proof directory belonged
  to guest UID 1001. Its retained copy was ownership-corrected to `odin`, kept
  mode 0700, and evidence/readiness plus VM-stop checks then passed. No row retry.
- Raw proof/journals and their SHA-256s are outside Git. The artifact manifest
  deliberately excludes generated profile secrets, key files and caches.
- Guest had no remaining candidate processes after the row; all `odq-*` VMs
  **STOPPED**. Host `/` stayed above the 60 GB floor, about 123 GB free.
- Own follow-up worktree is removed after push/report; original evidence,
  candidates, other lanes and `/home/odin/desktop-p41-cache` are untouched.

No attribution trailers, PR merge, release, host deployment, live Odin service
change or active-workstation input.
