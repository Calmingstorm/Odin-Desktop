# P4.1 early candidate packaging evidence, 2026-10-05

## Review round 1 changes and open Ubuntu gate

PR #24 is rebased onto `main@566b7954`, including #19's validated development
override/visible launch failure and #21's selected-profile runtime management.
Packaged resolution retains the immutable absolute interpreter, isolated flags
and no development fallback. PR #22 is still open at this rebase watermark;
its additional `analyze_pdf` readiness check remains with that lane.

**Aaron's Decision F:** PyMuPDF/MuPDF is not distributed in either candidate.
The optional `[pdf]` extra is retained; `pdf.lock.json` pins automatic first-use
download, shared by analyze-PDF, attachments and knowledge import, into private
user data outside the immutable runtime. No confirmation prompt is added and
the offered tool description remains Odin's. Failed downloads install nothing
and retry on the next use. The previous bundled-PDF evidence below is historical,
not the revised candidate policy. Both formats must be rebuilt because shipped
engine/dependency/resource bytes change, not merely because the branch rebased.

`.deb` dependencies now include `openssh-client` for `ssh` and `ssh-keygen`.
**AppImage:** those executables come from the host system and are not bundled.

**Open P2 lab gate, nonblocking for this candidate PR:** stock Ubuntu 24.04
with `kernel.apparmor_restrict_unprivileged_userns=1` must prove both the bundled
headless Chromium launch and FUSE-mounted AppImage Electron startup in #20's VM.
This workstation is observed at `0`; its isolated Xvfb/extracted-package passes
do not qualify the restricted Ubuntu cases. No host sysctl is changed for tests.
If the browser fails, add an AppArmor profile for its installed headless-shell
path. If AppImage sandbox startup fails, present a plain message recommending
the `.deb` on Ubuntu 24.04 instead of a crash. Never silently disable the sandbox.
The gate stays open until actual default-setting VM execution passes.

## Historical pre-review candidate evidence

## Source and boundary

- Candidate build source: `bda44259f17c8bf60561e9f0482ca9ff372663a2`.
- Fresh checkout: `/home/odin/desktop-p41-fresh`, rebased onto
  `main@7d919f0c`, including merged Phase 2 transport #14 and app settings #13/#15/#16.
- Documentation/evidence commits after that build do not change shipped bytes.
- Runtime: standalone CPython **3.12.15**, 60 locked production dependencies,
  noneditable engine wheel and assets. Product remains `0.1.0`, unreleased candidate.
- Local outputs: `/home/odin/desktop-p41-fresh/.packaging-candidates/`.
- Detailed local logs, screenshots and machine evidence:
  `/home/odin/desktop-p41-evidence/final-bda44259/`.
- Six agents handled CPython, Chromium, models, PDF, helpers and behavior tests.
  Integration, rebase, final fresh checks, build and final qualification were parent-owned.

## Exact candidate identity

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `odin-desktop-0.1.0-candidate-amd64.deb` | 357228232 | `00acb38e5bbb352022bd90971974a39aebd4336ca43908df6c42468908ab25db` |
| `odin-desktop-0.1.0-candidate-x86_64.AppImage` | 510194643 | `e6b00f46c0366bf1fea1190a3382d75dcda22253cc1aa2562d16b85da245a8c4` |

Both formats and the disposable installed tree have the same complete resources
manifest: **8,271 inventoried files/links, 1,020,158,140 bytes**. Manifest SHA-256:
`569524e09ddb8a1f2f046c292d1aa63dbbb9327be7190f0471bf78a5292116b9`.
The unpacked app's `du -sb` measurement is **1,318,562,260 bytes** including
directory entries, the Electron executable/resources, runtime and legal notices.

Final qualification JSON SHA-256:
`d170a932ee919dfd397d2544087348f4fbc3930525172db449ae912939443d52`.
Whole-app ABI evidence JSON SHA-256:
`18de1dbd68c5eef928a5f6d0879ecf46e82507a56ca42533d3797036baed6d95`.

## Observed final gates

1. Fresh `npm ci --ignore-scripts`, then the pinned Electron install procedure.
2. `npm run check`: **48 test files, 471 tests passed**, typecheck and production
   build passed. Repeated after the final implementation commit.
3. `npm run test:packaging`: **32 behavior tests passed**. Tests reject digest,
   mode, missing/unlisted-file, link, ASAR and credential-pattern failures; actual
   namespace masking and disposable dpkg maintainer-script behavior are exercised.
4. Focused engine/resource tests in a PID/mount namespace: **115 passed**.
   Includes runtime, model, helper, Chromium, core search/readiness, entry and lifecycle.
5. Engine lint gate: **zero new findings**, seven inherited findings retained.
   Ownership-plan checker passed; byte-drift report has no errors with independent
   review still pending. Original upstream browser/embedder cases were not rewritten.
6. `npm run package:candidate` built **both formats**, nonpublishing, using the
   same stage, pinned Electron bytes and hash-checked builder binaries.
7. Extracted `.deb`, extracted AppImage and real disposable-dpkg-installed `.deb`:
   **all manifest, scan, core and GUI lanes PASS**, final driver exit 0.
8. Fresh development-fixture smoke separately passed under private Xvfb, PID,
   mount and network isolation with Chromium sandbox intact. The fixture is absent
   from candidates and a poisoned development override is ignored by packaged GUI.
9. Cleanup: no surviving candidate/Xvfb processes found; no Incus instance or
   operation was created. No active desktop, live profile or service was touched.

### Candidate behavior actually proved

Every lane ran from **`/candidate with spaces`**, read-only resources, empty private
HOME/XDG, no checkout/live install, masked system Python and no external network.
Candidate code ran as nonroot `hyprlab`, never the active graphical desktop owner.

- Real packaged core: authenticated welcome/handshake, ready status, ping,
  ready/quiescing events, shutdown exit 0 and socket removal.
- Packaged Electron main/renderer: private Xvfb screenshot, real-core `link=ready`,
  ordinary Exit path, development override ignored. No `--no-sandbox` workaround.
- Chromium **153.0.8010.12**, Playwright **1.63.0**: data-page render and PNG,
  renderer **Seccomp 2 / NoNewPrivs 1**, no sandbox-disable switches.
- BGE small EN v1.5: actual local **384-dimensional** finite embeddings from pinned
  model resources, with no first-use download. Separate model proof also intercepted
  network/download calls and verified unchanged model bytes.
- PyMuPDF **1.28.2**: actual offline PDF creation/reopen/text extraction. A separate
  lane also exercised the engine's analyze-PDF handler with controlled local bytes.
- Computer helpers: actual installed package-resource/config loading and all three
  native helpers loading bundled DSOs, then refusing missing arguments before input.
- Complete package plus ASAR contents scanned for fixture, development/review
  artifacts, bytecode, checkout/live-secret paths and credential-shaped content.
  This is a bounded credential-signature scan, not a universal secret-absence proof.

### Final commands

Build from fresh checkout `app/`: `npm ci --ignore-scripts`,
`node node_modules/electron/install.js`, `npm run check`,
`npm run test:packaging`, then
`ODIN_PACKAGING_CACHE=/home/odin/desktop-p41-cache npm run package:candidate`.

Qualification from fresh checkout root:

`sudo -n /usr/bin/python3 -B app/packaging/qualify.py --deb
/home/odin/desktop-p41-fresh/.packaging-candidates/odin-desktop-0.1.0-candidate-amd64.deb
--appimage /home/odin/desktop-p41-fresh/.packaging-candidates/odin-desktop-0.1.0-candidate-x86_64.AppImage
--output /home/odin/desktop-p41-evidence/final-bda44259 --install --gui --user hyprlab`.

Focused pytest used `sudo -n unshare --mount --pid --fork --mount-proc --kill-child`,
dropped to `odin`, removed DISPLAY/Wayland/session-bus/runtime-dir variables and
used the development interpreter, never `/opt/odin` or live state. Test list:
`tests/test_packaging_runtime.py tests/test_packaging_models.py
tests/test_desktop_helper_bundle.py tests/packaging/test_chromium_runtime.py
tests/packaging/test_chromium_staging.py tests/test_desktop_core_search.py
tests/test_desktop_core_entry.py tests/test_desktop_core_lifecycle.py`.

## Measured ABI floor and limitations

Whole unpacked app: **108 ELF files**, imported GLIBC symbol floor **2.38**.
The limiting bundled libraries are `libwayland-client.so.0` and `libxkbcommon.so.0`.
Standalone Python/dependency ELF floor is 2.28; that is **not** the product floor.
This measurement is static required-symbol evidence, not oldest-distro execution
qualification. Observed host glibc: 2.39; kernel: `7.0.0-31-generic`; architecture x86-64.
CPU baseline, memory/latency budgets and wider distro/compositor ABI matrices were
not independently measured by this early lane.

- Disposable installed-root proof uses real **dpkg with `--force-depends`**, not
  installation on the workstation. It is not clean-distro dependency resolution.
  Incus image acquisition stalled without an operation/container; stopped its exact
  owned process and used the approved disposable extracted-root namespace instead.
- Xvfb proves ordinary packaged GUI behavior, not native login, portal consent,
  keyring integration, compositor input containment or R4. AppImage extraction is
  proved; FUSE-mounted execution/ownership/upgrade remains later qualification.
- The main core is still step-one transport. Conversations/tools/reports, runtime
  settings, user-skill worker/dependency isolation and native backend admission await
  later Phase 2/P3.1. Direct offline resource probes are not claims that those
  services are already admitted by the desktop graph.
- Native helpers and sources are present, but absolute install-path/trust defaults,
  AppImage helper trust policy, compositor plugin ABI and GI/AT-SPI/X11 closure
  remain Phase 2/P3.5 acceptance work. No input was attempted.
- MIT/Chromium/model notices are retained. Desktop product licensing and complete
  third-party notice closure remain pending. The historical build below included
  PyMuPDF/MuPDF, but Decision F removes it from the revised distribution entirely;
  only lock metadata remains. These are private local candidates.
- Input hashes are pinned; bit-for-bit installer reproducibility across build hosts
  is not claimed. No custom update feed, self-updater, signing scheme or release
  authorization is introduced.
- No release, tag, asset upload or merge. No packaging CI. The pre-existing hosted
  engine workflow is now **manual-dispatch only**, so the PR does not spend minutes
  automatically. `/opt/odin`, live services and the active desktop are unchanged.
