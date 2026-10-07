# P4.2 package ownership, compatibility and unreleased upgrade acceptance

## Source and artifact identity

PR: https://github.com/Calmingstorm/Odin-Desktop/pull/36

Branch: `phase-4/p42-package-ownership`, based on P4.1 final head `2becee34`.
#24 merged as `5ba8d6df`; main onboarding #30 and lifecycle #32 are consumed.
Latest accepted main watermark is `0b7d596f7e870d06699722f151c4d9837c5433f1`.
The #32 branch was used as the approved pre-package lifecycle specification,
then accepted main was merged. No unreviewed lifecycle is described as accepted.

Fresh group-writable checkout: `/home/odin/desktop-p42-final-20261006`.
Candidate build source: `4bba01ec30a1d9d5261056fdf5b54be732f1f715`.
The subsequent main-ancestry merge and probe/qualification-plan corrections do
not change shipped source, locks, resources, launcher or maintainer bytes.

| Candidate | Bytes | SHA-256 |
|---|---:|---|
| `odin-desktop-0.1.0-candidate-amd64.deb` | 341683902 | `b1e0f377e59da91ca043ca6e1c999d6e3250398dde303f465f59c9ac156ab2f6` |
| `odin-desktop-0.1.0-candidate-x86_64.AppImage` | 489681684 | `acc536dd4f47be92c43394f6fea11cd78d7d51cd8e97f65ac5a2afb502e43ad5` |

Candidates remain local in the fresh checkout's `.packaging-candidates/`.
All extracted and actual disposable-dpkg-installed trees share the sealed
resource manifest: **8,485 files/links, 975,745,854 bytes**, SHA-256
`2697318aea1cbd37fc7c4524c70c83487d8b4cb0f60f776433c81931523441c0`.
Every package scan reports zero bundled PyMuPDF/MuPDF payload files.

## Implemented boundaries

### Package-owned versus per-user state

The `.deb` owns `/opt/Odin`, launcher/icons and its package-manager metadata.
It does not own the unrelated lowercase installation. User config/data/cache,
history, credentials, unknown receipts, backup and quarantine remain per-user.
Maintainer scripts never start, stop or signal an app, core, service or desktop.
They do not delete user state on removal or purge.

`deb_transaction.py` is embedded in all four hooks. Its persistent root-owned
lease inode and transaction marker live under
`/var/lib/odin-desktop/package-ownership`. Shared lifetime leases are retained
independently by the launcher, primary app guardian and actual core. Exclusive
preflight rejects replacement/removal while any lease survives. The pending
marker remains across unpack/configure, abort and interrupted transitions;
launchers cannot create a mixed-version writer while it exists. Configure
checks the marker's target version and inode, not merely absence of a PID.
Root reads lifetime receipts through no-follow descriptors and validates their
actual opened file identity. Clean evidence remains required after process exit.

Read-only compatibility runs under a provisional shared lease before role
admission or profile writes. An incompatible no-start publishes no dirty
lifetime record and therefore does not poison compatible package repair.
After admission, absent/newer/unresolved cleanup remains fenced. Source dev
launches remain source dev; installed code cannot opt out by unsetting an
environment variable or deleting its shipped helper.

### Previous P4.1 transition is deliberately not a live upgrade

P4.1 candidates predate lifetime fencing. A one-shot process scan cannot close
their launch race. **Direct P4.1-to-P4.2 dpkg upgrade is refused unchanged**.
Acceptance separately proves an externally fenced offline remove/install
transition in the disposable guest: stop the owned app/core first, remove
traverse permission from the exact package root, prove the ordinary owner
cannot execute it, then remove/install via dpkg. Per-user data is preserved.
This is not a suggested desktop chmod command, an in-app apply path, or a claim
that an already-open legacy executable can be retroactively fenced.

Guarded P4.2 candidates use ordinary dpkg ownership preflight. Both remain
unreleased version `0.1.0`; replacement is a real dpkg reinstall, not a fabricated
release version bump. Exact previous P4.1 stores are also seeded using its own
frozen bundled interpreter for upgrade/backup testing.

### User-managed AppImage

No app installer/updater/apply bridge exists. The explicitly user-run offline
`replace-appimage.py` helper accepts already-local bytes and an explicit hash.
It neither downloads, executes, quiesces nor signals. Under the stable per-user
exclusive lease, it requires clean app/core evidence, copies to a new inode,
fsyncs and validates before same-path atomic rename. Nonwritable/read-only
destinations and interruption remain honest refusals with durable recovery
identity. Old inode retention is not asserted to prove FUSE/native cleanup.

Autostart uses the stable `.deb` launcher or original AppImage path, never raw
Electron or a transient FUSE mount path. A relocated image detects the old
autostart command as stale/disabled; explicit enable repairs it. See
`app/packaging/APPIMAGE-REPLACEMENT.md` for the helper and recovery limitations.
This is cooperative owner tooling, not prevention of arbitrary owner shell
writes or atomic cross-file relocation/autostart transactions.

### Compatibility, backup and migration

`package_state.py` inspects actual protocol major/minor, transport domain/column
shape, turn schema/checkpoint codec and computer quarantine store before any
writable attachment or boot sweep. Future incompatible state refuses unchanged.
WAL is inspected through a private copied database, never ignored with an
immutable read of the original. Supported symlinked XDG ancestors are resolved
once; final state files retain no-follow ownership checks.

Under existing runtime/profile authority, a private hash-manifested backup is
durably published before existing migration owners run. Pending/committed state
is explicit; fsync/storage failure is not success. An interrupted compatible
candidate may retry idempotent owners, never effects. Another incompatible
candidate cannot claim its pending transaction. No automatic state rollback,
foreign import, receipt erasure or native-quarantine clearance is added.

## Observed acceptance

All logs and machine reports are under `/home/odin/desktop-p42-evidence/`.

| Gate | Observed evidence |
|---|---|
| Fresh app check | Typecheck/build and **703 tests passed** |
| Packaging behavior | **69 ordinary-user executions passed**; 12 root-only rows skipped there, then **12/12 passed** separately in a private root PID/mount namespace |
| Drift/lint/ownership plan | Zero drift errors, zero new lint findings, seven inherited; plan passes, not semantic review |
| Exact previous candidate stores | Its bundled interpreter seeds actual conversations, artifact bytes, config, schedules, unknown effect records and computer quarantine; the new backup/commit case passes |
| Real-core app contract | **21 tests passed**, private owned profiles and controlled auth service |
| Real Incus package acceptance | **13 rows passed**, normal dpkg with dependencies installed inside the guest; no `--force-depends` |
| Candidate lanes | Extracted `.deb`, extracted AppImage and real-dpkg-exported `.deb` pass scan/manifest, real-core transport/shutdown, offline D14 and sandbox-intact GUI |
| Actual packaged Exit | Every candidate GUI lane observes fresh **clean app and independent core lifetime receipts**, not only PID disappearance |
| Fixture smoke | Private Xvfb/bus/PID namespace, disposable profile, normal Exit; passed |
| Cleanup | Exact marked package container gracefully stopped/removed; cleanup report passes |

The real container rows cover ordinary-owner previous/current core, alongside
sentinels, direct legacy refusal, offline transition, durable migration, surviving
core busy install/removal refusal without signals, clean guarded replacement,
actual unpack/configure launch fencing, actual future-state no-write refusal,
same-path real AppImage replacement, nonwritable-destination recovery and
removal preserving user state. Sentinels include independent data/credential
fixtures, kernel lock inode, endpoint inode and an actual harmless responding
process. The workstation installation is never the alongside target.

Candidate clean-Exit report:
`final-clean-exit-candidates/qualification.json`, SHA-256
`e119907d58eb544ad3eff2a61444e447b49a3977febad73388209146b6aadd59`.
Actual Incus acceptance: `final-acceptance/run.json`, SHA-256
`73a3e4d199b1c146552b9f840df87c9359468d142941f84bb1177724ce2d0921`.
Exported installed-root archive SHA-256:
`12cedbe75f2819dacc20c83742b985ca9d002c443f26bada834bbafb38b1dffc`.

### Full qualification disposition

One full fresh qualification ran all **31 then-configured groups**:
**14,443 passed, one failed, zero errors, three skips**. The failure was the suite-accounting check's
required exact historical/main named-group set: adding a 31st group was not
allowed. The three package suites were moved into the existing Desktop boundary
group, preserving all historical group names/selectors. No assertion was
weakened. The affected Desktop-boundary and core-transport groups were rerun on
the corrected 30-group plan: **905 passed / one opt-in skip**, and **520 passed**.
The initial failed report remains retained, not relabeled a full pass. The
previous-candidate opt-in skip is discharged separately by its actual frozen
candidate execution. Existing inherited skips and coroutine/closed-loop warnings
remain visible.

The corrected core-transport group passes **520 cases**. The first corrected
Desktop-boundary rerun had **902 passes, three 3-second IPC timeouts and one
previous-candidate opt-in skip** while other diagnostic/native lane activity
was running. All three exact cases passed in a focused isolated retry; no
assertions/timeouts were changed. The serialized complete boundary rerun passes
**905 cases**, with only the separately discharged previous-candidate opt-in
skip. These transient failures remain evidence, not erased by retries.

The composed final 30-group evidence therefore covers **14,444 passing
executions, zero final failed/error cases and three visible skips**, using
unchanged passing groups from the single full run and the two corrected groups.
It is **not** a second monolithic full-green run. Two inherited skips remain;
the third opt-in candidate case passed separately against exact P4.1 bytes.
Logs: `full-qualification.log`, `qualification-corrected-groups.log`,
`qualification-boundary-serial.log` and the fresh checkout's JUnit XMLs.

## Review round 1: Electron AppArmor attachment

The reviewed head was `1944ab4682c6a1ba470a728af637547682b87f08`.
Fix/build source is `4b948cfedf7c775c965754837edf35f9ebbca364`, tested in a
fresh checkout at `/home/odin/desktop-pr36-r1-20261006`. The AppArmor resource
now attaches to the renamed Electron ELF, `/opt/Odin/odin-desktop.bin`, not
the shell/Python ownership launcher. The new regression executes the real
after-pack hook against an executable ELF fixture, resolves the attachment
inside its generated tree and checks ELF identity, executable mode and `userns`.
Merely accepting the executable shell wrapper would not pass that regression.

Both formats were rebuilt because the shipped AppArmor bytes changed. These
supersede the initial candidate pair above for this review; those original
Incus/install/full-qualification results remain evidence of their original
bytes, not a claim that every acceptance lane was repeated on this new pair.

| Review candidate | Bytes | SHA-256 |
|---|---:|---|
| `odin-desktop-0.1.0-candidate-amd64.deb` | 341673428 | `7e8d1865f752f3fd60cb6177ce13c3e8fd0a77afb05b529b8d684c44ef74d8b5` |
| `odin-desktop-0.1.0-candidate-x86_64.AppImage` | 489681528 | `0cbcbe2d716f8de744992ee834320865fc797ca70c2cae31bcff9eaed4a6b529` |

The new pair remains local in the review checkout's `.packaging-candidates/`.
Their identical verified resource manifest has **8,485 files/links,
975,746,015 bytes**, SHA-256
`1eedfc7f39c6106d6abb62f4b3e375fa66ccf8c4cbd0a2a5d598e72a2fac3961`.

| Repeated review gate | Observed result |
|---|---|
| Packaging, ordinary `odin` user | **70 passed, 12 reasoned skips**, zero failures/errors; 11 root transaction rows and one namespace read-only mount fixture skipped |
| Root transaction module | **12/12 passed**, private PID/mount namespace and temporary paths |
| Fresh app check | Typecheck/build and **703 tests passed** |
| Fixture smoke | Passed, private Xvfb/bus/profile/PID namespace |
| Real-core app contracts/onboarding | **21 contracts + 6 onboarding E2E passed** |
| Real-core smoke | **39 screens passed** |
| Short gates | Zero drift errors, seven inherited lint findings and zero new; ownership plan and lab Ruff pass |
| AppArmor | Syntax parses with kernel loading/cache writes disabled; actual extracted formats name an executable ELF distinct from their wrapper |
| Rebuilt extracted `.deb` and AppImage | Manifest/scans, real-core handshake/status/events/shutdown, offline D14 and sandbox-intact GUI passed; fresh clean app/core Exit receipts and zero bundled PDF payload files |

Evidence: `/home/odin/reviews/desktop-pr36-r1-evidence/`.
`extracted-candidates.json` SHA-256:
`a6fb050b32222d246b791bcabe58a22ac47380582c0b1039b9ada83b5d46c28d`.
No new installed-dpkg/container acceptance, full qualification or stock Ubuntu
AppArmor/native/FUSE gate is claimed for this candidate pair. No kernel profile
was loaded on the workstation. Repository-local dependencies were provisioned
with the frozen uv lock and npm lock; no dependency versions changed.

PR #41's root-user-namespace review fix was pushed separately at
`be7ca4bec5c9590d81acc0adc53e8528de176128`: 47 passed/one real-root-dpkg skip
as `calmingstorm`, 48/48 as real root, 48/48 as `odin`. Its real-root failure
was reproduced from a checkout inside another user's 0750 home before the fix.
#41 remains open and unmerged. Its portable tests have deliberately **not**
been imported into #36 ahead of approval. The requested main merge awaits the
reviewer's notification after #41 lands.

## Open gates and limitations

- **Ubuntu 24.04 restricted-user-namespace/headless Chromium and FUSE-mounted
  AppImage gate remains open**, as requested. No heavy VM was started by this lane.
  Review round 1 corrected the `.deb` AppArmor attachment to
  `/opt/Odin/odin-desktop.bin`, the actual Electron ELF image. The public
  `odin-desktop` path is the shell/Python ownership wrapper, not Electron.
  A behavior regression runs the real after-pack hook and checks that the
  shipped profile names the resulting executable ELF, with `userns` retained.
  This does not qualify AppArmor inheritance or sandbox admission on Ubuntu:
  the still-open stock Ubuntu 24.04 row must launch through the installed
  launcher, shell, bundled Python ownership helper and Electron `.bin`, keep
  `kernel.apparmor_restrict_unprivileged_userns=1`, and verify actual renderer
  sandbox plus headless Chromium behavior without weaker fallback flags.
- Containers prove ownership/package manager state, not native desktops, portal,
  keyring/login/autostart acceptance or FUSE lifetime. Private Xvfb proves actual
  packaged app/core and renderer sandbox, not those native rows.
- Read-only mount/relocation/independent lifetime and harmless fault tests are
  behavior evidence. User-managed replacement cannot undo external effects or
  erase unknown cleanup. Release/native R4 repeats exact-candidate rows later.
- Product license/third-party notice closure, final D11/R4 and supervised owner
  acceptance remain release gates. Locked npm reports 11 findings (ten high,
  one critical); no unrelated dependency update is hidden in this work.
- Exact ledger entries remain pending independent review. No publishing, tags,
  uploads, merge, deployment, live-service or active-desktop changes by this lane.

## Correction, 2026-10-07: the cleanup fence had no exit

Native lab evidence on `odq-cinnamon` showed the fence above could never lift.
Packaged Odin ran hidden in the tray, as Start at login leaves it, when the guest
was powered off normally. systemd stopped the app's scope within one second, and
SIGTERM killed the app's separate guardian before the app recorded its Exit, so
that app receipt stayed `running`. Every later app lifetime's `_clean` then failed
on the retained notice until acknowledged. After any core crash, the core's
`previous_unknown` would fail every later core lifetime the same way, and nothing
clears it. Even after a normal Exit, `dpkg -r odin-desktop` refused with "Previous
app/core cleanup is unresolved; package unchanged". The user could no longer
remove or upgrade the package, and a restart did not help.

The fence now works per lifetime and per boot:

- Each receipt records the kernel boot identity. A receipt from an earlier boot
  no longer fences `.deb` hooks or AppImage replacement, because no process or
  native resource of a lifetime survives the boot it ran in. Receipts without a
  boot identity, and every receipt while the current identity is unreadable,
  stay fenced.
- A lifetime is clean when its own Exit and resource evidence are clean and the
  profile retains no core unknown from the current boot. The core journal records
  each lifetime's boot, and the newest unresolved lifetime's boot separately from
  the first retained notice, so an older unknown cannot mask a new one (review
  finding R2.1). A missing binding (history from before boots were recorded,
  unreadable evidence, or a boot that could not be read) binds once to the boot
  that finds it. Only history from before the binding existed may use the boot
  stamped in its own notice, so a newer unknown never borrows an older boot
  (R3.1). The retained notice itself is never rewritten, so the app does not
  announce it twice. An unknown therefore fences every installation kind on that
  profile for the rest of its boot (review finding 89.2), and a later clean
  lifetime cannot erase that.
- Boot identities must be well-formed kernel UUIDs; a malformed one is not an
  earlier boot (review finding 89.1). Receipts are cooperative evidence the owner
  can already rewrite, so this guards against corruption, not a hostile owner.
- dpkg's error unwind (`abort-*` hooks) returns before taking the lease, so a
  refusal while Odin runs leaves the previous version installed.
- The app's guardian ignores SIGTERM, SIGINT and SIGHUP. Its lifetime ends at the
  app's stdin EOF, and SIGKILL still leaves its receipt unclean.
- A current-boot refusal now tells the user to restart the computer.

Unknown cleanup records, retained notices and quarantine are unchanged and
never cleared. The app still records a normal session end as an unconfirmed
Exit; that is P3.3 lifecycle work, tracked separately.
