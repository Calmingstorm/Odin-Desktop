# PR48 round 2: accepted round 1, current-main integration

Acceptance and requested action: `/home/odin/reviews/desktop-pr48-round2.md`.
Accepted head: `0a8d42dfd5a2c8b00f85de27f8ad8959e27f1313`.
Merged main: `da2d3d4adbc7864ed78ffb972e3792f8557fbcb2`.

## Integration

Main conflicted only in `maintenance/desktop-deltas.json`, in the core byte
patch. The recursive merge has two merge bases; its virtual-base ledger is not
parseable JSON, so accounting uses the actual stage-2/stage-3 JSON objects.

The union retains all 384 unique paths. Main has no path absent from the
accepted PR48 ledger. Every main reason, contract, invariant and named test is
already included in the accepted PR48 records; these inclusions were checked
explicitly before resolving the conflicting duplicate patch member.

`inventory.py record` regenerated the actual merged bytes for all six paths
whose byte patches differ between the two sides:

- `scripts/maintenance/phase2_suites.py`
- `src/desktop/core.py`
- `src/desktop/management.py`
- `src/desktop/runtime.py`
- `src/desktop/services.py`
- `tests/test_desktop_engine_services.py`

Both-side contracts, invariants and test unions are preserved. The remaining
378 records are unchanged from the accepted head. Records remain pending;
byte recording is not represented as new independent approval.

All engine, test, script and dependency bytes are unchanged from the accepted
PR48 head after the automatic main merge. New main changes are documentation
and CI workflow integration. No additional deferred suite was restored.

## Observed gates

- Post-merge production/parity/accounting/ownership and hermetic Cinnamon/GNOME
  subset: **268 passed**, zero skips, failures or errors.
- Maintenance/ledger behaviour: **26 passed**, zero skips, failures or errors.
- Drift: **zero errors**, 384 exact ledger records.
- Lint: **zero new findings**, seven inherited findings.
- Phase-2 ownership plan and `git diff --check` passed.
- Full classified qualification was not rerun locally; marking the PR ready
  enables the repository CI gates. This document does not claim CI completion.

The first subset invocation referenced a nonexistent maintenance filename and
collected no tests. The corrected subset and actual maintenance suites passed
as reported above. No production/test change was made to address that typo.

All pytest work used the repository's restricted non-root PID/mount isolation
helper, invoking UID 1003, sanitized environment and temporary HOME/XDG roots.
No graphical session or host-native lifecycle test was exercised.

## Evidence and boundaries

Raw evidence remains outside Git under
`/mnt/storage/odin-desktop-evidence/pr48-r2/`; the adjacent committed artifact
manifest pins its paths, sizes and SHA-256 values.

Root reserve was checked before environment provisioning and after tests:
120 GB and 119 GB respectively, above the 60 GB floor. The task's sole fresh
worktree and virtual environment are removed after evidence preservation and
inactivity checks. Other lanes, protected cache and evidence are not touched.

The integration is a two-parent merge, not a rebase or force-push. No PR merge,
deployment, running-service change, attribution trailer or active-desktop input
is authorized by this task. The remaining 58 deferred suites await the separate
post-6B restoration request.
