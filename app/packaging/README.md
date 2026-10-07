# P4.1 local, unreleased Linux candidates

This is the early packaging lane, not release authorization. The candidate contains
the real Phase 2 step-one core from `main`: handshake, status, events, ping and
supervised shutdown. Later conversation, execution, settings, skill-worker and
native-computer admission services are **not** invented or replaced by the fixture.
The development fixture and `ODIN_DESKTOP_CORE_CMD` never select a packaged core.

## Build

Linux x86-64, Node 22, build-time Python 3.12+, npm, `readelf`, a C compiler,
`pkg-config`, `wayland-scanner` and the exact preinstalled library inputs in
`python/helpers.py` are required. No host packages are installed by these scripts.
Use a disposable build environment if those pinned inputs are unavailable.

From `app/`, run `npm ci --ignore-scripts`, provision the pinned Electron binary
with `node node_modules/electron/install.js`, then `npm run check` and
`npm run package:candidate`. Candidate construction never publishes. Engine CI
runs on pull requests and main pushes using separate self-hosted short-gate and
full-suite runner labels. P4.3 adds a self-hosted release workflow whose default
dispatch is a nonpublishing dry-run; publication remains separately guarded.

Build-time downloads are hash checked: standalone CPython 3.12.15, build-only uv,
the wheel-only production closure from `uv.lock`, Chromium Headless Shell,
the quantized BGE model, Electron, and electron-builder's fpm/AppImage tooling.
`app-inputs.json`, `runtime-lock.json`, the resource locks and `package-lock.json`
are the input authorities. Repeated builds verify cached inputs. These are pinned
input builds, not a claim of bit-for-bit installer reproducibility across hosts.

Both formats consume one sealed unpacked resource tree. A pre-staged AppArmor
resource and explicit build umask `022` keep electron-builder's deb-only late
profile copy identical to the sealed inventory. The after-pack hook canonicalizes
all resource files to `0644` (non-executable) or `0755` (executable), directories to
`0755`, including the unpacked app root and resources root, and preserves
symlinks before sealing. Fpm explicitly packages root-owned entries; a real
fpm/dpkg extraction regression checks `/opt`, `/opt/Odin` and resources as `0755`.
This includes builder-created ASAR
and ownership files, not only the earlier runtime stage. Qualification still
rejects any subsequent mode, content, size, inventory or link-target mismatch;
it never rewrites the manifest to match extracted candidates. The `.deb` uses identity
`odin-desktop`, installs application resources
under `/opt/Odin`, and has an independent launcher/icon/state namespace. That path
is not the unrelated `/opt/odin` live service. Nothing is installed on this host.

## Immutable runtime layout

`resources/runtime/python` contains standalone CPython and the noneditable engine
with production dependencies. `runtime/browser`, `runtime/models` and
`runtime/helpers` contain D14 assets. The app invokes an absolute interpreter with
`-I -B -m src`, ignores development overrides and ambient Python configuration,
and supplies install-relative resource paths. No PATH lookup, editable source,
runtime installer, pip or ensurepip is required. PDF is the explicit exception to
offline-first bundled capabilities: `runtime/pdf.lock.json` pins its automatic
first-use download. PyMuPDF is an optional `[pdf]` extra and is not in the
production closure. Its wheel, MuPDF native libraries and license notice are not
distributed. The resolver installs verified bytes in private user data outside
the read-only application and retries after failed downloads.

`resources/bundle-manifest.json` inventories **every file and symlink under
resources**, including `app.asar`, legal notices and the AppArmor asset. It records
byte digests, link targets and modes. The manifest excludes itself. Both formats
must have the same manifest digest. Top-level Electron/app launcher files are
separately scanned and the whole installer receives a SHA-256. This is an
inventory, not a signed trust anchor, update feed or self-updater.

## Qualification

`npm run test:packaging` runs behavior tests for closure, tampering, archive parsing,
credential-pattern scanning and namespace isolation. Engine/resource pytest cases
must run inside the PID namespace prescribed by `CONTRIBUTING.md`.

The behavior tests use the invoking account for isolation and real first-start
OpenSSH key generation. Ordinary users use a private unprivileged user namespace;
real root uses the privileged sandbox without `--unshare-user`, retaining access
to checkout inputs in another user's private home until they are bound. No named
workstation account, checkout location or passwordless sudo is needed for these
rows. Missing namespace support/tools produces an explicit prerequisite skip;
once the prerequisite succeeds, sandbox failures remain failures. The disposable
real-dpkg/maintainer-script row still needs real root, and skips with a plain
reason if neither root nor `sudo -n true` is available. This does not qualify
user-namespace dpkg as real installation or replace the privileged candidate
and installed-root acceptance lanes below.

Run `sudo -n python3 -B app/packaging/qualify.py --deb <candidate.deb>
--appimage <candidate.AppImage> --pdf-wheel <local-pinned-wheel.whl>
--output <evidence-dir> --install --gui --user
<isolated-unprivileged-user>` from the repository root. It extracts both formats,
installs with real dpkg into a disposable chroot tree inside a private mount/PID/
network namespace, and executes candidate code only as the selected nonroot user.
System Python and the checkout are absent. Every candidate is mounted read-only at
`/candidate with spaces`. Private Xvfb and `/dev/shm` never expose the workstation
display, bus or credentials. Chromium keeps its sandbox; no disabling switches
are accepted. Use the already-qualified isolated user on this workstation, not
the active desktop owner.

The installed-root lane uses `dpkg --force-depends` because its tiny chroot contains
only maintainer-script tools. It proves dpkg/maintainer-script behavior and package
execution, **not dependency resolution on a clean distro**. Native graphics,
portal/keyring, login lifecycle, AppImage FUSE mounting and oldest-distro acceptance
remain later gates. Do not mistake Xvfb for native desktop qualification.

Before export/chown, the disposable installer audits real root-owned `0755`
application directories and checks the installed AppArmor profile and ownership
digest against the source. A generated-hook fixture also proves pre-existing
`0777` install directories are refused, not repaired. Dpkg can retain permissions
on existing directories; after-pack normalization does not authorize chmod of a
live installation. The minimal chroot lacks `apparmor_parser`, so profile install
and receipt proof is **not kernel loading/attachment proof**. Root-only fixtures
with a recording parser cover transaction behavior, not an actual AppArmor kernel.

The candidate probes real core transport and clean shutdown, actual offline
Chromium rendering with renderer seccomp/no-new-privileges evidence, 384-dimensional
semantic embeddings, PDF first-use installation/extraction, installed computer assets and
native helpers' pre-input usage refusal. Helpers are bundled but existing native
install/trust defaults, compositor plugin ABI and Phase 2 admission are still
pending. No input is sent to a desktop. User-skill loader/dependency isolation
waits on the Phase 2 runtime/skill graph, not merely a separate venv.

PDF qualification begins with PyMuPDF absent. A separate read-only fixture wheel,
verified against the original download SHA-256, replaces only the resolver's
download transport inside the network-disabled namespace. The real resolver
verifies/extracts it into disposable user state and the actual `analyze_pdf`
handler extracts a locally generated document. The second resolution reuses the
install with exactly one fixture download. Package scanning rejects PyMuPDF,
MuPDF, legacy `fitz`, wheel, native library and license payload paths, including
ASAR entries; the immutable runtime contains the pin only. This proves offline
installation from known bytes, not a successful internet download.

The `.deb` declares `openssh-client`. AppImage users need host `ssh` and
`ssh-keygen`; those host tools are not bundled.

### Restricted user namespaces

The shared ownership launcher performs an **AppImage-only** preflight before
creating an install lease or starting Electron. It refuses with exit code 78 when
`kernel.apparmor_restrict_unprivileged_userns` is nonzero (including Ubuntu 24.04's
default 1), `kernel.unprivileged_userns_clone` is not 1, or
`user.max_user_namespaces` is zero/negative. Unreadable or malformed values are
also refused; absent optional sysctls are tolerated. There is no environment or
CLI bypass. The Python sysctl-root argument exists solely for behavior-test fixtures.

This is deliberately conservative: a site-specific AppArmor exception may permit
an AppImage despite the global restriction, but this launcher still refuses it.
Passing the preflight does not prove sandbox availability: other LSM policies,
namespace quotas, mount settings or kernel support may still prevent startup.
Refusal prints a plain explanation and recommends the `.deb`, without running
Electron, adding sandbox-disabling flags, or changing system settings. On a
graphical session, `/usr/bin/zenity`, if installed, additionally shows the same
message in a native error dialog (15-second dismissal, 20-second process timeout).
Without zenity/display support, or if the dialog fails, stderr remains the only
delivery; graphical visibility is not guaranteed in that case.

The `.deb` launch branch does **not** perform this preflight. Its AppArmor asset
attaches `userns` permission separately to the actual Electron ELF
`/opt/Odin/odin-desktop.bin` and the bundled D14 Headless Shell ELF
`/opt/Odin/resources/runtime/browser/chromium/chrome-headless-shell-linux64/chrome-headless-shell`.
These paths follow the renamed executable and pinned Chromium staging layout,
not the shell/Python launcher or a Playwright download cache. The profiles are
unconfined compatibility attachments, not a claim of additional confinement.
Profile installation/loading and real sandbox execution still require disposable
Ubuntu guest qualification; unit fixtures alone do not establish native success.

## Legal and release boundaries

Each resource records provenance, digests and available license notices. Electron
and tool Chromium are distinct update obligations. The headless Chromium build
avoids proprietary Widevine redistribution. Upstream MIT notices are retained;
the Desktop product distribution license remains an owner decision. PyMuPDF/MuPDF
is AGPL-3.0-or-later or commercially licensed and is **not distributed in these
candidates**. Its download provenance remains pinned for user-initiated PDF use;
this packaging change does not assert that downloading resolves every licensing
question. Other distributed third-party notice closure remains a release gate.

These local packaging commands create no tag, GitHub Release, asset upload or
update service. Candidates stay local. The separately guarded P4.3 workflow is
documented in [`maintenance/phase4-releases.md`](../../maintenance/phase4-releases.md).
P4.2 ownership/upgrades and alongside evidence
are recorded in [`maintenance/phase4-packaging.md`](../../maintenance/phase4-packaging.md).
The `.deb` now uses explicit self-contained preinst/postinst/prerm/postrm hooks
with `python3` predependency. The hooks import JSON, which Debian's
`python3-minimal` alone does not provide. Disposable install qualification stages
the system interpreter, matching distro stdlib (without site-packages or
sitecustomize), and ELF closure, then checks hook imports inside the isolated
dpkg root before installing. This install-only Python is removed before exporting
the tree for candidate runtime probes; workstation Python remains masked there.
`--force-depends` remains an explicit dependency-resolution proof limitation.
They fence replacement without starting
or signalling any application/service and preserve all user state. The shared
lease-bearing launcher and independent app/core lifetimes remain active through
authoritative cleanup. Each lifetime receipt records the boot it ran in and judges
its own Exit, plus any core unknown the shared profile retains from that boot,
since `.deb` and AppImage keep separate receipts. A lifetime that ended without
confirmed cleanup fences replacement and removal until the computer restarts,
since nothing it held survives that boot; the refusal says to restart. Receipts
with a missing or malformed boot identity, as from older candidates, stay fenced. The app's guardian ignores stop signals, so a
logout or system stop cannot end it before the app's own Exit is recorded.
Nothing here clears or acknowledges unknown cleanup or quarantine.
AppImage replacement is explicitly user-managed and
offline; see [`APPIMAGE-REPLACEMENT.md`](APPIMAGE-REPLACEMENT.md). No app apply
path exists. Legacy unguarded P4.1 direct upgrade is refused; its isolated
offline transition is qualified separately, not mislabeled a normal upgrade.
Native/FUSE/restricted-Ubuntu gates and final supervised owner acceptance/release
handoff remain open for P4.5/P4.6.
