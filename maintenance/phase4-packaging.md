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

## Open gates and limitations

- **Ubuntu 24.04 restricted-user-namespace/headless Chromium and FUSE-mounted
  AppImage gate remains open**, as requested. No heavy VM was started by this lane.
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
