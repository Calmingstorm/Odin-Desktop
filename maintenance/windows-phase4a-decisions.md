# PR #139: reviewed blocker decisions, 2026-10-11

Authority: `/home/odin/reviews/desktop-windows/63-decisions-4a.md`.
Base head: `f6b1a08d344e69f2fab3a639b52e84d1c8e4f3f4`.

The Playwright exception is bound to the exact Windows artifact's name, version,
SHA-256 and size. The Windows Chromium lock records both tags and the supplier
reason. Before admitting the discrepancy, the validator requires the exact Node
bytes, parses the executable as AMD64 PE, checks driver CLI/browser registry,
and refuses foreign native driver payloads. Accepted evidence enters runtime
dependency provenance. All other wheel validation remains in force.

Tests inspect the actual pinned artifact successfully, refuse a changed ZIP
comment/hash, refuse another package, and exercise missing/foreign/malformed
driver content through the `wheel_tag_mismatch` boundary. Content negative tests
explicitly bypass only the separately tested artifact identity boundary to
reach the content checks; altered bytes are never production-admissible.

The two Microsoft CRT DLL pins, data-only extraction, app-local resolution,
provenance and `license_prerequisite_verified: false` publication blocker are
unchanged. Private qualification is authorized, not public distribution.

## Local final-source validation

Command selection: `app/packaging/tests/test_windows*.py`,
`app/packaging/tests/test_linux_pip_exception.py`, and
`tests/test_windows_runtime_acceptance_harness.py` with pytest `-q -rs`.

- 252 passed, 12 subtests passed, 3 conditional skips, 31.15 seconds.
- Skips: native Windows junction, provisioned Electron builder, and actual
  existing Linux packaged-runtime comparison. No native acceptance claim.
- Focused runtime suite: 42 passed before final formatting-only changes;
  final combined selection includes all 42 cases.
- Changed Python files: Ruff clean; patch whitespace clean.
- Inventory: errors empty; lint gate: seven inherited findings, none new.
- D19: errors empty; closure: ready, errors empty, parity valid.
- No Linux builder change; CRT lock/helper diff empty.

The original failed hosted stage is preserved in the prior evidence. The new
hosted run must independently qualify the admitted runtime and real consumers.
No installed app, active desktop or running service was modified.

## First new-head hosted result and backend follow-up

Run `38109866877` on `04eb426e17528f06fdb31c84cfabab0616fba501`
passed Playwright admission and advanced to the build-only setuptools backend.
It then refused `wheel_metadata`: the supplier includes multiple nested vendored
dist-info directories. The validator now requires exactly one top-level owning
dist-info; nested supplier metadata remains covered by the outer RECORD.
Multiple top-level metadata directories still refuse.

The actual locked backend also includes `distutils-precedence.pth`. It remains
forbidden for runtime dependencies. An explicit build-backend mode permits only
that path for the exact locked setuptools artifact; `-I` plus manual sys.path
insertion does not process its .pth, and the backend never enters the shipped
runtime. No general path-injection relaxation was made.

Final follow-up source: 255 passed, 12 subtests passed, the same three conditional
skips, 31.25 seconds. The actual locked backend now passes its complete wheel
inspection; default runtime inspection still refuses its .pth. Another backend
artifact and extra top-level metadata refuse. Earlier 252-case receipt and failed
253-case follow-up are retained in small logs, not relabelled as clean passes.

Run `38110248538` on `d2301eeb06d4354bc98e7393386a593cf2dd4990`
completed Python staging and reached Windows platform sealing, which correctly
refused the inert `tqdm/completion.sh` supplier shell-completion resource. This
one named foreign-platform payload is now removed with its hash in the existing
pruning provenance; no generic shell-file exemption or weakened seal.
