# Public-readiness draft implementation

Task: `/home/odin/reviews/desktop-public/implement-brief.md`, 2026-10-08.
Branch: `public/readiness`. Base: merged master
`155f0b4d967fbcf9f7a0f602488d54bf974346bf` (PR #120).
This is repository preparation, not approval to publish or change repository visibility.

## Delivered scope

- Product-facing README with Odin link, Releases installation, unsigned SHA-256 verification,
  supported sessions, X11-only computer use, Import from Odin, and the retained `## User guide` anchor/table.
- Maintainer index at `docs/development/README.md` holds authorization, decisions, discussion rounds,
  layout, named-agent process and qualification status formerly mixed into public entry points.
- Public CONTRIBUTING rules welcome PRs, require maintainer approval before self-hosted admission,
  exclude fork/draft PRs from those runners and forbid credentials/profile dumps. Existing namespace,
  runner-isolation, dependency-install and live-install safety rules remain.
- SECURITY policy supports 1.0.x and uses GitHub private vulnerability reporting, with sanitized
  reproduction guidance and no invented mailbox or response-time promise.
- Bug and feature issue forms request version, distribution/session, package format and steps/use case.
  Both warn against credentials and profile data; the bug form routes vulnerabilities privately.
- Every engine-workflow job, including the coverage dependency job, has explicit own-repository
  master-push or own-repository non-draft PR admission. Fork PRs cannot enter the runner lane.
  Every third-party action is pinned to a full commit SHA. Existing runner labels, commands,
  isolation helper, qualification selection and time bounds are unchanged.
- Every release dispatch mode, including dry-run, is Calmingstorm-only; unknown modes are refused.
  Existing publication/provenance/environment constraints remain.
- Environment audit consumes GitHub's actual `can_admins_bypass` response and requires literal
  `False`; true, absent, null, numeric/string coercions and the old fake field alone are refused.
  `prevent_admin_bypass: true` remains only the internal audit receipt summary, not an API lookup.
- Install/update/checklist public wording is updated; checklist evidence boxes and results are untouched.
  Installation privacy wording now distinguishes optional selected import from automatic state adoption.
- Maintenance README and generated upstream LICENSE provenance reflect adopted MIT licensing.
  `maintenance/baseline.md`, archived upstream bytes, notice hash and LICENSE strip selection remain unchanged.

## Validation

Final local isolated run: **214 passed**, zero failures/skips. Selection:

```
.venv/bin/python scripts/run-phase1-tests.py scripts/release/tests \
  tests/test_desktop_isolated_runner.py tests/test_desktop_coverage_ratchet.py \
  tests/test_desktop_maintenance.py tests/test_desktop_maintenance_review.py \
  tests/test_lab_orca_ci.py tests/test_desktop_ci_interpreter.py \
  tests/test_desktop_default_selection.py tests/test_desktop_qualification_once.py \
  tests/test_desktop_qualified_runner.py -q -rA
```

The workflow tests evaluate the actual YAML job conditions across 128 engine contexts for all four
jobs, plus pushes without a PR payload. Release tests cover 72 dispatch contexts including invalid
modes, foreign repositories/refs and non-owner actors. These are offline expression/API fixtures,
not a claim of hosted Actions execution or GitHub settings qualification.

Five maintenance gates passed:

| Gate | Observed result |
|---|---|
| `inventory.py report` | No errors; byte-drift-clean-review-pending |
| `lint_gate.py` | No new findings |
| `phase2_plan.py` | Exit 0; ownership inventory, not runtime qualification |
| `d19.py report` | No errors; 50 disposition rows |
| `phase2_closure.py report` | No errors; ready true, report-only inventory |

Additional checks: 47 local Markdown link targets resolve; both issue-form YAML documents parse;
`git diff --check` passes. Full engine/app CI, packaging and native graphical qualification were
not run: this is intentionally a draft PR while the release owns the self-hosted build lane.

## Ledger and provenance

Seven changed engine/tool/test files have refreshed exact-byte pending records. Sixteen unchanged
source/test records only refresh associated test digests; their source patches, hashes and prior
review metadata are preserved. Runtime `src/` bytes do not change. The manifest changes only the
upstream LICENSE reason. Independent review is still required; no ledger entry is self-approved.

Action pins reuse release.yml's checkout/upload pins. setup-python v5 and download-artifact v4
were resolved from their official GitHub action repositories to full commit objects:

- `actions/checkout`: `11d5960a326750d5838078e36cf38b85af677262`
- `actions/setup-python`: `a26af69be951a213d495a4c3e4e4022e16d87065`
- `actions/upload-artifact`: `ea165f8d65b6e75b540449e92b4886f43607fa02`
- `actions/download-artifact`: `d3f86a106a0bac45b974a628896c90dbdf5c8093`

Retained raw evidence:

| Artifact | SHA-256 |
|---|---|
| `/home/odin/reviews/desktop-public/evidence/implementation-final-tests.log` | `55fe8fc5e30cd088a6184a628b3f5635ff338f294d5a38e7888f1e729fb3dabb` |
| `/home/odin/reviews/desktop-public/evidence/implementation-final-five-gates.log` | `614e72986517badf7f2de1ed3803d4b60c20b29366999b85af7b6ce58ec886da` |

## Corrections and limits

The first affected run had one new-test failure: the generated manifest field is `reuse_verdict`,
not `verdict`. Corrected the assertion, then 129 affected cases passed. The first short-gate run
also found three overlong new test lines; those were formatted without suppressions before the
final 214-case run and all five gates passed. The initial uv venv attempt rejected an unsupported
`--copies` flag; repository-local Python venv creation with copies plus locked uv sync succeeded.
Patch-context errors made no partial file changes. No failed test was hidden, retried inside a gate,
or converted to a skip.

Started from campaign while #120 was open, then rebased onto merged master before final validation.
No GitHub settings/visibility changes, release dispatch, notice-generation change, history rewrite,
dependency-distribution change, Odin repository change, service operation, VM or active-desktop input.
Repository-local locked Python development dependencies were installed in this checkout's `.venv`.
The draft PR must not be marked ready by this task.

## PR #121 review corrections

Review: `/home/odin/reviews/desktop-public/review-pr121.md`, 2026-10-08.

- R1: restored master reason/contract/invariant text for all seven re-recorded entries,
  appending each public-readiness addition with the dated delimiter requested by review.
  Restored inventory.py's complete master merge_lineage and merge_resolution. Verified
  after_sha256, patch, test_sha256 and tests remain unchanged for every corrected entry;
  all other entries are unchanged. The ledger is canonical sorted-key, indent-2 JSON.
- R2: README and installation guide now enumerate memory, skills, MCP servers, personality,
  managed hosts and model settings, state that import never replaces existing content,
  and explain that withheld secrets must be entered again.
- All five maintenance gates passed again; inventory reports no errors and
  byte-drift-clean-review-pending. Focused isolated maintenance tests: **27 passed**.
  `git diff --check` passed. No production source or test behavior changed.
- Raw validation evidence:
  `/home/odin/reviews/desktop-public/evidence/pr121-review-fixes-gates.log`.
  Full engine/app CI and graphical/package qualification were not rerun for these
  provenance/documentation-only corrections. PR remains draft; no settings or live changes.
