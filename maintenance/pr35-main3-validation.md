# PR35 main integration, req-cb82eaf7

Requested artifact: merged PR35 head plus honest gate results and external receipt hashes.

## Merge lineage and resolution

- Original PR35 head: `58549927e1ae86a565d9992591b81d6ecc756fdf`.
- Original merge base: `f597c1af3e6b3796d7f6753d4d3b455be2f57b3c`.
- First main: `189bb77769a89a44fe308b65d6ab808f25882952`, merged as
  `22217b7ec5466eb58ee19303043a42e2e329752d`.
- Main advanced during the passing first gate invocation to
  `b276b0b34c44c553ed1aa9042e716bf06395694f` (#61 and #71).
  Merged again, never rebased, as tested source
  `85f5fca72ddb51b04a6fce68f4cbc298f1d9f315`.
- #34 remained open at final main fetch. This work does not merge that PR.
- `phase2_suites.py` permits restoration additions and STEP6A_GROUP together,
  retaining the exact 6A file and reason check.
- Qualification groups preserve main and restoration selectors; #46 attachment
  knowledge belongs in desktop-boundary-tests. Suite-map top-level main case
  dispositions and all both-side entries are preserved without new disposition changes.
- Desktop deltas use path union and current exact bytes, combined reasons,
  contracts, invariants and test sets. `inventory.record` explicitly re-recorded
  changed bytes/cited tests. Main's removal of three obsolete container-lab files
  is preserved rather than resurrecting their records.
- Historical merged ledger provenance is external, hashed and entry-addressed;
  current exact records remain in desktop-deltas.json. No approval was invented.

## Executed gates

All requested gates executed as ordinary `odin`, UID 1003. Pytest used the
repository launcher with verified PID/mount isolation and sanitized HOME/XDG.
No live desktop, service, deployment, assertion or deadline change occurred.

| Gate | Latest-main result |
| --- | --- |
| inventory report | zero errors, pending independent review |
| lint, phase2 plan, D19 report, closure report, fresh-profile report | pass |
| phase2 suite checker | valid, zero errors; historical population 326 |
| pip check | pass |
| Cinnamon/GNOME hermetic fixtures | 38 passed, zero failures/errors/skips |
| restored steps2/3/4, request, attachment, suite-map and PR35 accounting selection | 1297 passed, zero failures/errors/skips |
| npm run check: typecheck, unit tests, build | 87 files, 835 tests passed |
| real-core contracts/services/settings | 3 files, 28 tests passed |
| real-core onboarding | 1 file, 6 tests passed |

The initial merged source also passed all its requested gates with the same test
counts. The second execution was required by changed main source, not a retry of
any failure. Attachment test `test_real_request_uses_exact_per_attachment_note`
passed in both selections unchanged. No test failure is concealed or waived.

No full classified qualification or native/VM/product-release qualification was
requested or claimed here. Existing historical failed qualification remains intact.

## Evidence and operational limitations

Raw receipts are outside Git at
`/mnt/storage/odin-desktop-evidence/pr35-main3-reqcb82eaf7/`, with latest-main
receipts in its `latest-main/` directory. Adjacent result and artifact manifest
JSON files contain exact commands, exit codes, tested SHA, durations, paths,
sizes and SHA-256s. This final evidence/provenance commit does not alter runtime,
tests, selectors or safety checks after the tested source.

`manage_process` rejected starts because all 20 global slots were occupied.
The gate driver therefore ran synchronously, recording every invocation once.
Whole-merge `git diff --check` initially reported inherited main speech/log
trailing whitespace. The request-owned resolution diff is clean; inherited raw
evidence was not rewritten to disguise that diagnostic.

Disk checks stayed at 123-125 GB free, above the required 60 GB reserve.
Only the request-owned clone is eligible for post-push inactivity-verified cleanup.
