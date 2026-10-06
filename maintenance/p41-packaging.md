# P4.1 early candidate packaging evidence, 2026-10-05

## Ubuntu 24.04 restricted-userns Task 1, 2026-10-06

**Disposition: partially qualified, overall gate remains OPEN.** The one-shot
installed `.deb` GUI row failed its rendered/core-handshake checkpoint. It is
not converted into a sandbox pass, and was not retried. The installed browser
and actual FUSE-mounted AppImage safe-refusal rows passed. Task 2 was not run.
Full result and artifact digests are in
`maintenance/evidence/lane7-userns-20261006/`.

Fresh base: `ed0069674533c23e70a0302652a2fb76901ff385`. Final candidates built
with P4.1 scripts at `d142968a3533c9a930f7e3147ef8cca6c79183e7`:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `.deb` | 341776612 | `41b8a927bd06d45ed0c1403d153ca038b33b31c11ea65f614a527bacc9609551` |
| AppImage | 489685623 | `b61f9f92d47a66cf5cbe6362b987246dfe9e204132fba2e71fe0adf9f7772981` |

Guest: owned `odq-gnome`, Ubuntu 24.04.5, kernel `6.8.0-146-generic`, nonroot
`odq` UID/GID 1001, GNOME Wayland. **The pre-existing minimal Noble image was
initially sysctl=0 with AppArmor absent/inactive.** Guest-only distro AppArmor
packages were installed and enabled; both
`apparmor_restrict_unprivileged_userns` and
`apparmor_restrict_unprivileged_unconfined` were set to **1** before any candidate
launch. This is restored restricted-policy execution, not an untouched stock
desktop-image claim. No host policy was changed. `unprivileged_userns (enforce)`
was loaded and unprofiled `odq` `unshare -Ur true` was actually denied.

The first candidate install exposed a maintainer-hook integration defect:
custom P4.2 hooks replaced electron-builder's AppArmor installation. Neither
profile was installed. No application/browser case had run. The fix installs
and loads the immutable profile through the real postinst, with digest-owned
removal and failure fencing; rebuilt candidate installation loaded both exact
Electron and headless-shell attachments. The shipped attachments intentionally
remain `flags=(unconfined)` plus `userns`, as Ubuntu's application exceptions do;
they are not described as enforcing application confinement.

- `.deb`, one launch: **FAIL**. `smoke: timed out`, then `UnknownVizError` during
  capture. No screenshot or saved Electron renderer witness survived this failed
  harness row, so Electron sandbox acceptance is **unproven**, not inferred from
  loaded policy or a running core. Follow-up qualification is required.
- Browser, one launch: **PASS**. Actual installed `BrowserManager`, bundled
  Chromium **153.0.8010.12**, real HTML title/screenshot, renderer UID 1001,
  `Seccomp: 2`, `NoNewPrivs: 1`, nested PID/user namespace and
  `odin-desktop-headless` attachment. No sandbox-disable switches.
- AppImage, one launch: **PASS safe-refusal branch**, not Electron startup.
  Actual read-only `fuse.lane7.AppImage` mount observed. Preflight exits **78**
  before Electron/lease creation; stderr and native Zenity plain error recommend
  `.deb` without weakening security. Refusal is deliberately conservative even
  if a site exception might permit user namespaces. Native dialog invocation
  and its exact text were observed, not screen-reader acceptance or a screenshot.

Gates: final app check **747 tests**, typecheck/build pass; private-Xvfb fixture
smoke, real-core tests plus **6 onboarding**, real-core smoke and **15 a11y**
cases pass. Full lifecycle gate **28 pass / 1 fail** at
`lifecycle.spec.ts:333`, core not ready within its deadline; no retry. Packaging
ordinary-owner suite **109 run / 22 prerequisite skips**, no failures; privileged
targeted hook **21** and preflight **9** cases pass separately. Engine applicable
resource selection **21 pass** in the prescribed PID namespace. Failed preliminary
inherited packaging selections and an incorrectly root-run ordinary-owner suite
are preserved, not relabelled as passes. No full inherited engine qualification
or native Task 2 lifecycle acceptance is claimed.

`odq-gnome` was powered off through its guest agent; all odq VMs were confirmed
**STOPPED**. Raw files/candidates remain outside Git under
`/mnt/storage/odin-desktop-evidence/lane7-userns-20261006/`.

## Last main merge, 2026-10-06

**Moving-main addendum:** #23 landed while #22's rebuilt candidates completed
all three extracted/installed real-core and sandbox-intact GUI lanes. A second
two-parent merge therefore adopts
`main@4ea7aa0f3b423a301854a9f0bdd2a46bc92d9d7b`. Only the ledger conflicted,
with one same-source providers entry regenerated to combine exact witnesses.
The ledger now retains 307 entries. Drift/lint/plan and the same 143 focused /
39 packaging cases pass again. #23 changes six shipped engine files; both
formats were rebuilt again. No full qualification is claimed for this step.

Latest candidates supersede the #22-only identity below:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `odin-desktop-0.1.0-candidate-amd64.deb` | 341802466 | `aab1f16f2321956256c908e72fede5ba792b19b5340952c6bf799e1fe86e63d2` |
| `odin-desktop-0.1.0-candidate-x86_64.AppImage` | 489644585 | `febeeacad714ca276be222985ef7405c3322830a85f0a13d594d55cc3d8c6889` |

Latest resource manifest: 8,481 files/links, 975,600,311 bytes, SHA-256
`046716680976d48c7a3fc1ab0e5ea327f257cfbad9f926d9ceb4e634267ae6f7`.
Additional evidence is `last-main-20261006/controls-merge/`.

Two-parent merge of `main@d546c44c29388225015f20747c55930413b03f75`
(#22 request/delivery composition) into the previous head `8907b96a`.
Only the delta ledger conflicted. The supplied key-based merge retained 299
entries; five doubly-changed entries were explicitly regenerated with drift
tooling. Four have identical source bytes; `src/desktop/providers.py` adopts
#22's injectable gateway dependencies. Combined witnesses retain Decision F's
first-use PDF policy and the new request-service evidence. Independent review
remains pending, not self-approved.

Drift reports zero errors, lint reports zero new findings and seven inherited,
and the ownership-plan checker passes. Focused PDF/resource/runtime/core tests
pass **143 cases** in an isolated PID/mount namespace. Packaging behavior tests
pass **39 cases**. Two preliminary selections named nonexistent files and ran
no cases; their failed logs are retained, not counted. No full qualification
was repeated in this merge-only step; P4.2 runs it once after final integration.

Both formats were rebuilt because #22 changes **16 shipped engine files**,
not merely Git history. A stale build stage correctly refused changed locks;
it was preserved and a fresh stage used. App source and dependency lock bytes
are unchanged. Candidates remain local in this worktree's
`.packaging-candidates/` directory.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `odin-desktop-0.1.0-candidate-amd64.deb` | 341715736 | `e964d3a295bd117948fa69bde19d3f98011df5a658d10a356d2263fe0ab5e755` |
| `odin-desktop-0.1.0-candidate-x86_64.AppImage` | 489636352 | `f6bc5ecbcc75b5e20ff8885380b2ce56272f36fefb57ea4faa7f26dc3c4379f4` |

Sealed resource manifest: 8,480 files/links, 975,561,143 bytes, SHA-256
`f1193d134144f635e4c90e8c1ee861c840bce1b59a0ea5216804daa40a0a9a07`.
Evidence is `/home/odin/desktop-p41-evidence/last-main-20261006/`.
The Ubuntu 24.04 restricted-user-namespace/mounted-AppImage gate remains
**open**. No heavy VM, live service, active desktop, publishing or release work.

## Review round 1 changes and open Ubuntu gate

PR #24 is rebased onto `main@caa871cd`, including #19's validated development
override/visible launch failure and #21's selected-profile runtime management.
Packaged resolution retains the immutable absolute interpreter, isolated flags
and no development fallback, #29's accessibility app and #26's inherited-suite
qualification corrections and #27's real-core settings slice. PR #22 is still open at this rebase watermark;
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

### Revised candidate identity and final gates

Shipped-byte build source: `63b78a8b95eb1b370318f0e23a81c1685d05f7da`.
Fresh checkout: `/home/odin/desktop-pr24-r1-fresh`; candidates remain local in
its `.packaging-candidates/` directory. Subsequent changes preserve original
test corpus, record exact deltas and correct qualification isolation only;
they do not change shipped bytes and therefore require no further rebuild.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `odin-desktop-0.1.0-candidate-amd64.deb` | 341628054 | `de3a7a78ce10d8f9ba572458eacca85823600433f2bd4e664907f461b5b5a650` |
| `odin-desktop-0.1.0-candidate-x86_64.AppImage` | 489579074 | `70c39066e564e60b98322bc51e8abb9e1e2e9b95639ae01b0ebbe352a7d62779` |

All three extracted/installed resource trees have **8,469 inventoried files/links,
975,355,412 bytes**, with identical manifest SHA-256
`98bd8492fa843abfad20e0d3718db9becb8edd46e896942f32d1ce34eb1e3b97`.

- Fresh `npm ci --ignore-scripts`, pinned Electron provisioning and
  `npm run check`: **611 tests**, typecheck and production build passed,
  repeated at `7291e8f6a60058d399f4b4a2d7300229492f7010`.
- `npm run test:packaging`: **39 behavior tests passed**, including real namespace
  identity and first-start `ssh-keygen`. An initial sanitized PATH omitted uv;
  rerunning with the existing build uv supplied removes that skip.
- Focused engine/resource/PDF cases: **131 passed** in the prescribed isolated
  PID namespace. Local HTTP fixtures cover absence, digest mismatch, thread and
  process concurrency, shared failure, retry, all three call sites and unchanged
  offered tool wording. A separate real pinned-wheel proof executes every PDF
  call site with network disconnected and private user state.
- Full inherited-corpus qualification at `7291e8f6`: **all 30 groups passed,
  14,047 passing executions, zero failures/errors and two existing skips**.
  The review's 29 groups became 30 after #21; #26 added inherited process cases.
  No original test bytes/assertions/hashes were changed to manufacture a pass.
  The obsolete hide-PDF case is explicitly replaced under Decision F, not passed.
- Engine lint: zero new findings, seven inherited findings. Exact byte-drift
  inventory: zero errors, independent review still pending. Ownership-plan
  checker and diff checks passed.
- Extracted `.deb`, extracted AppImage and disposable-installed `.deb`: all
  manifest, complete package/ASAR scan, real-core and GUI checks passed. Scans
  report **zero PyMuPDF/MuPDF payload files**. Each lane proves real first-start
  config, private ed25519 SSH key and default workspace provisioning, authenticated
  core status/events/shutdown, browser sandbox, model embeddings and one verified
  PDF first-use installation outside immutable runtime. Fixture wheel is a separate
  read-only test input, never part of the candidates; external networking is off.
- Private bwrap/Xvfb/DBus development-fixture smoke passed; packaged GUI ignored
  the poisoned development override. No sandbox-disabling flags were used.

Final package evidence: `/home/odin/desktop-p41-evidence/review1-final-rebase-candidates/`
and `review1-final-rebase-qualification.log`. Final package report SHA-256:
`6df4bf7114ed65af1f8f4b337a178e909372ce4c7a9e7d04463cd44488250dc3`.
Fresh app/packaging gate logs are `review1-final-rebase-7291-*`;
focused/full-suite log is `review1-rebased-final-full-focused.log`. Fixture proof
is `review1-final-rebase-fixture-smoke-private-glxoff.log` and its PNG.
Cleanup receipt: `review1-final-rebase-cleanup.log`; no residual owned processes,
mounts or profiles, and no host Desktop package install. Later commits change
only test import formatting, pending evidence digests and documentation, so the
build source remains shipped-byte identical. Earlier revised candidate identities
remain in historical local logs; #27's shipped changes required the final rebuild.
Failed provisional logs remain: missing development pip was installed into the
private venv; obsolete Desktop PDF assertions were updated while frozen inherited
tests were restored. The first rebuilt candidate run exposed a harness omission:
OpenSSH needs a UID entry. The corrected namespace supplies only synthetic,
read-only passwd/group identities, not workstation account data, and proves real
key generation. No core startup guard or secret backend was bypassed.

Dependency-install output reports **11 npm audit findings (10 high, one critical)**
in the locked dependency graph; no broad dependency upgrade or audit fix is
smuggled into this review. Clean-distro dependency resolution, restricted Ubuntu
user namespaces, mounted AppImage behavior and native acceptance remain open.

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
