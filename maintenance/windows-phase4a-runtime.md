# Windows phase 4a runtime lanes

Branch: `windows/phase4a-runtime`, stacked on PR #136 at
`d85217a117e7c377aab8a8b30acccc541758c01d`. Only this branch's phase-4a commits
are for review. No merge, install, public release or existing-profile operation
is authorized by this implementation.

## Implemented artifact

P1-P6 runtime staging, consumers and sealing:

- Windows CPython 3.12.15, build-time uv and pinned pip; marker/extras-evaluated
  production wheel closure from `uv.lock`, strict wheel identity/metadata/RECORD,
  license and provenance validation, transactional publication.
- Windows archive semantics, explicit PE normal/delay import audit and app-local
  CRT payload. OS inbox imports are explicitly listed; PATH/System32 never
  substitutes for a missing third-party dependency.
- Pinned Playwright driver and Chromium Windows DLL/data closure; browser runtime
  resolves the pinned `.exe` and refuses external Node overrides.
- Unchanged model/tokenizer resources and actual offline inference harness;
  existing Windows PDF first-use lock shipped under the runtime name.
- Client-only bundled Microsoft OpenSSH and official curl, without service or
  supplier installer scripts. Packaged missing files refuse instead of falling
  back to System32. Source behavior remains the OS copies.
- curl's pinned LibreSSL distribution uses an install-relative pinned Mozilla CA
  bundle, `--disable --no-ca-native --cacert`, and clears CA environment overrides
  in both `http_probe` and HTTP validation routes.
- Exact-set Windows inventory and reparse/alias refusal; platform resources and
  clean Git-object release source provenance, with development worktree mode
  separate. The shared builder's `win` and `nsis` sections are untouched.

## Actual supplier blocker, not a waived refusal

All 72 selected Windows wheel artifacts were downloaded and their size/hash
verified. The pinned `playwright-1.63.0-py3-none-win_amd64.whl` declares
`Tag: py3-none-any` inside WHEEL. Filename and metadata tags disagree. P1 expressly
requires refusing tag mismatches. The stage therefore fails closed with
`wheel_tag_mismatch` for Playwright; it is **not a completed native runtime**.
Resolving this requires a corrected supplier artifact or an explicitly reviewed
change to the acceptance contract. No generic exemption was added.

The source can safely inspect/spread the bytes for structural audit without
admitting them as a valid stage. This is how the missing ONNX Runtime MSVC DLLs
were found. `WINDOWS-RUNTIME.md` separates those static inspections from native
execution.

## Additional publication conditions

- OpenSSH `10.0.0.0p2-Preview` is upstream's **non-production-ready preview**,
  regardless of `prerelease: false`. Phase-5 supplier acceptance remains required.
- The app-local Microsoft CRT pin records its redistribution/license prerequisite
  as unverified. No public distribution authorization is claimed.
- curl's upstream detached signature was verified with the upstream allowed
  signers pinned to a specific commit. Self-signed Windows code signatures are
  not presented as Windows-trusted publisher proof.

## Hosted evidence and remaining Legion work

The PR's separate `windows staged runtime (Server 2025)` job builds from the
clean immutable revision, then invokes the staged interpreter with `-I -B` from
private paths outside the checkout, sanitized PATH, and cold caches. The harness
executes cryptography/SQLite/sqlite-vec/ONNX loads, actual BrowserRuntime rendering,
offline semantic inference, real PDF first-use download/extraction, and both real
curl routes. TLS checks require trusted HTTPS success, local untrusted-certificate
refusal and a verified hostname-mismatch refusal. The latter uses a public HTTPS
fixture, and cannot pass on an unrelated network failure. No trust store is
modified. SSH version/keygen/private-key restriction/readback are also included.

Until the Playwright blocker is resolved, downstream hosted consumer evidence
cannot be obtained from an admitted stage. Registered tests are not passes.
The job retains manifest/provenance and a structured failure report.

Legion review still needs Windows 11 clean standard-user loading, strict-host-key
SSH success and incorrect-host-key refusal against the disposable Linux target,
negative cross-user private-key ACL behavior, and supplier Authenticode evidence.
Installer, app lease/tray/toast/login and whole-candidate acceptance belong to
4b/4c; existing-install/publication safety remains phase 5.

## Local evidence

The actual pre-pip Linux runtime was copied from
`/home/odin/desktop-p41-final-stage/runtime` into disposable scratch without
editing its source. Seven pip regression tests passed without skips. The exact
comparison measured 8,904 original filesystem objects and 552 changes restricted
to pinned pip payload paths and its derived record; no other object changed.

Focused tests and full-gate totals are recorded in
`maintenance/windows-phase4a-results.json` after the final run. Four record gates
must remain clean before each push: inventory errors empty, no new lint findings,
D19 errors empty, and closure ready with valid fresh-profile parity. Exact source
ledger entries retain prior lineage and stay pending independent review.

The complete local qualification passed all 38 groups: 19,899 passing executions
and three conditional skips, with zero failed groups. Isolated real-core app
contracts passed all four shards (66 tests), plus six onboarding cases.
The additional-boundary gate passed 922 cases, and source app check passed
1,898 tests with one conditional skip plus typechecks/build. None of these Linux
results supplies the blocked Windows native stage evidence.

No installed app, live services or active desktop session were changed. Only this
lane's temporary caches/checkouts are cleanup candidates; committed evidence and
small logs are retained. Disk checks remained above the 60 GB floor.
