# PR34 round 5: real app enrollment and readable unverified records

Request: `/home/odin/reviews/desktop-pr34-round5.md`. Execution evidence, not
independent merge approval or installed-product acceptance.

## Exact requested base and fixes

Built on the supplied two-parent merged head
`6fd542d53e57b59b382044bca271c1283b247372`, including #25 and #41. Execution
commit: `be5f926a5c3608929b5e180112d6b15053d9931b`. No rebase, further main
merge, production deadline change or attribution trailer.

### P2-1: legacy trusted-key enrollment through the app

- `hosts.import_legacy` is now in the shared API, strict alias-only admission
  schema and command mapping. The existing generated preload and main-process
  request path carry it without an unrestricted renderer RPC escape.
- Capability expectations and real-core handshake count now include the served
  method. The fixture implements the untested pinned-candidate contract and
  detects changes to the original host definition before commit.
- The Hosts screen has a named native **Enroll trusted key** button for remote
  legacy hosts. Import opens an untested candidate with its fingerprints,
  preserves the prior enabled/disabled intent and requires Test before Save.
- Back discards the token before re-preparation. A command lock prevents fresh
  identity replay after an uncertain outcome. Late import completion cannot
  overwrite a subsequently opened/closed wizard.
- Regression coverage includes strict schema/admission, fixture Broker flow,
  renderer state/uncertainty ownership, disabled intent and real isolated
  Chromium keyboard entry, Test navigation, Back and Close.

### P2-2: missing signing authority does not hide records

- Both asynchronous records reads and the synchronous inspection property catch
  only `SecretStoreError` from profile signing-key resolution. They construct an
  unsigned reader instead of reusing cached/config signing authority after a
  failed resolution. Unexpected reader/manager failures remain unavailable and
  cancellation remains cancellation.
- Query/search stay readable. Integrity reports remain explicitly unverified:
  `valid:false`, `verified:0`, `availability:not_enabled`. Successful key
  resolution still verifies signed history, including after restart; altered
  history is still detected. Wholly unsigned records never become verified.
- Tests cover an unavailable injected keyring, absent credentials, genuinely
  unreadable disposable credential files, signed/unsigned history, key loss and
  recovery, no audit bytes/writer-chain mutation and off-loop key resolution.
- The real Broker/core retained-corpus test now explicitly pins unavailable
  keyring status while retaining its original query/search/unverified assertions.
- The two newly authored Desktop fail-closed assertions were corrected to the
  requested contract. Frozen inherited assertions and suite dispositions are
  unchanged. Exact pending ledger patches/evidence hashes were applied through
  native context-checked `apply_patch`, not direct tracked-file recapture.

## Short gates and ordinary-user app gates

- Restricted-helper Python short gate: **425 passed**, no failures/errors/skips.
- Final `npm run check`: typecheck, **76 suites / 750 tests**, production build.
- `npm run test:real-core`: **21 passed**, plus **6 onboarding cases passed**.
- Latest complete `npm run test:a11y`: **15 passed**, including the new keyboard
  legacy-enrollment path. This is Chromium AX/keyboard evidence, not Orca/AT-SPI.
- Packaging unit gate: **48 passed**.
- Byte drift: **zero errors**. No-new-lint: **zero new findings**, seven inherited.
- Historical accounting unchanged: **326 = 28 restored + 42 retired + 256 deferred**.

Both requested app gates ran as ordinary `odin` UID1003 through the root-owned
restricted helper. It preserved numeric identity, cleared privilege and used
private mount/PID namespaces with sanitized throwaway HOME/XDG. Graphical
tests created their own Xvfb and bus, never the active workstation session.

### Earlier diagnostics are retained, not erased

- An early app check overlapped unfinished fixture work: 748 passed / one newly
  added fixture regression failed. Final completed-tree check has 750 passed.
- The audit lane initially invoked frozen legacy tests without their required
  adapter: 140 passed / eight constructor/removed-REST failures. The subsequent
  complete qualified adapter plus records gate passed 222 cases. This is not
  substituted for the full qualification.
- Root filesystem exhaustion interrupted a Ruff cache write and coincided with
  an Electron launch timeout in the first a11y invocation: 14 passed / one
  failed. After storage was restored, the unchanged entire gate passed all 15.
  No timeout/assertion change or automatic failure retry was introduced.

## Exactly one full invocation: not clean

To avoid the exhausted root filesystem, I incorrectly chose a fresh checkout
under `/mnt/storage/odin-pr34-round5/qualification/fresh`. Although its own
directories were group-writable 2775 and owner `odin`, `/mnt/storage` belongs
to another user. The unchanged private-profile ancestry guard correctly refused
that ancestor. A 2775 leaf does not make its ancestors trusted. This setup error
is mine; it is not a demonstrated product regression.

That single complete `scripts/run-qualified-tests.py` invocation ran all
**30 groups** and returned **14,979 passed, 231 failed, 79 errors, 2 existing
skips; exit 1**. Of the 310 failure/error messages, 309 explicitly name the
foreign ancestor; one state-operation wrapper sanitizes the underlying failure.
No guard was relaxed and no failed count was hidden.

Only the **12 affected complete groups** were rerun as separate diagnostics
from a second fresh, locked checkout under the correctly owned
`/home/odin/desktop-phase2-step8-part2/round5/qualification-repair/fresh`, at the
same unchanged execution commit. Their result is recorded separately in the
machine-readable receipt: **4,641 passed, 0 failed, 0 errors, 1 existing skip**.
No second full invocation or combined clean-full
claim is made. Full qualification remains not clean.

`phase2-step8-part2-round5-result.json` records the actual single-invocation
counts, each JUnit digest, failures, skips, short gates, later diagnostics and
limitations. Inherited coroutine/collection/subprocess-finalizer warnings remain
visible. Counts include overlapping selectors, not unique inherited cases.

## Limits and safety

Main advanced during execution with #45 and #36 to
`f597c1af3e6b3796d7f6753d4d3b455be2f57b3c`. Those changes were not merged into
this requested-base fix and are not covered by this qualification. Final receipt
files are maintenance-only; product/test bytes remain those of the execution
commit. No deployment, live service/configuration changes, real signing keyring
or provider access, active-desktop operations, PR merge, shipping publication or
upstream Odin changes occurred. Fixture enrollment is not real SSH qualification.
