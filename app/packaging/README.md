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
`npm run package:candidate`. Candidate construction never publishes. No packaging
workflow is added; the pre-existing engine workflow is now manual-dispatch only
so opening this private-repository PR does not spend hosted-runner minutes.

Build-time downloads are hash checked: standalone CPython 3.12.15, build-only uv,
the wheel-only production closure from `uv.lock`, Chromium Headless Shell,
the quantized BGE model, Electron, and electron-builder's fpm/AppImage tooling.
`app-inputs.json`, `runtime-lock.json`, the resource locks and `package-lock.json`
are the input authorities. Repeated builds verify cached inputs. These are pinned
input builds, not a claim of bit-for-bit installer reproducibility across hosts.

Both formats consume one sealed unpacked resource tree. A pre-staged AppArmor
resource prevents electron-builder's deb-only late write from changing the
inventory. The `.deb` uses identity `odin-desktop`, installs application resources
under `/opt/Odin`, and has an independent launcher/icon/state namespace. That path
is not the unrelated `/opt/odin` live service. Nothing is installed on this host.

## Immutable runtime layout

`resources/runtime/python` contains standalone CPython and the noneditable engine
with production dependencies. `runtime/browser`, `runtime/models` and
`runtime/helpers` contain D14 assets. The app invokes an absolute interpreter with
`-I -B -m src`, ignores development overrides and ambient Python configuration,
and supplies install-relative resource paths. No PATH lookup, editable source,
runtime installer, pip, ensurepip or first-use downloader is required.

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

Run `sudo -n python3 -B app/packaging/qualify.py --deb <candidate.deb>
--appimage <candidate.AppImage> --output <evidence-dir> --install --gui --user
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

The candidate probes real core transport and clean shutdown, actual offline
Chromium rendering with renderer seccomp/no-new-privileges evidence, 384-dimensional
semantic embeddings, PDF creation/extraction, installed computer assets and
native helpers' pre-input usage refusal. Helpers are bundled but existing native
install/trust defaults, compositor plugin ABI and Phase 2 admission are still
pending. No input is sent to a desktop. User-skill loader/dependency isolation
waits on the Phase 2 runtime/skill graph, not merely a separate venv.

## Legal and release boundaries

Each resource records provenance, digests and available license notices. Electron
and tool Chromium are distinct update obligations. The headless Chromium build
avoids proprietary Widevine redistribution. Upstream MIT notices are retained;
the Desktop product distribution license remains an owner decision. PyMuPDF/MuPDF
is AGPL-3.0-or-later or commercially licensed: the applicable terms and complete
third-party notice closure must be resolved **before any public distribution**.

No tag, GitHub Release, asset upload, update service or publishing workflow is
created. Candidates stay local. Ownership/upgrades and along-side installation
are P4.2; final supervised owner acceptance and release handoff are P4.6.
