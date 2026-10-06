# PR #31: merge main and repair chat smoke for #25's launcher

Request: `/home/odin/reviews/desktop-pr31-merge-main.md`.

## Integration and fix

- True merge `c774cc524552bd6204944369bb27784dc85568bc` has parents
  `5201dc7454a07d311e0757d038c966eee5e64a85` (original #31 head) and
  `f597c1af3e6b3796d7f6753d4d3b455be2f57b3c` (main). No rebase or force-push.
- Main had advanced beyond the review's local merge. The two textual conflicts were in
  `real-core-smoke.mjs` and `real-core-test.mjs`. Resolution retains both independent smoke profiles,
  all three real contract files, onboarding, and main's 600-second whole-gate bounds. Individual
  test/checkpoint deadlines and single-run/no-retry behavior are unchanged.
- #25 correctly owns namespace PID 1 in `real-core-isolation.mjs`. The chat smoke script is a
  child, not PID 1. Its call to the runner-only assertion was therefore the wrong assertion.
- Both management and chat still enter through `launchIsolated`. Chat now calls the existing
  real harness descendant assertion exported by the seed bundle before opening its canned
  provider or launching a real core. It verifies private PID namespace, the PID-1 isolation
  runner, and throwaway HOME/XDG. No separate launcher or privileged engine path was added.
- Added one real contract regression: the smoke assertion accepts an actual runner descendant,
  the namespace and preserved UID/GID are measured, and the unchanged exact PID-1 assertion
  continues to reject that descendant. This is behavior/proc evidence, not a source-text test.
- `real-core-isolation.mjs`, its declaration, and the installed restricted helper are unchanged.
  No engine production change, live-service action, active-desktop input, or deployment.

## Fresh-checkout qualification

Tested source: `12073633e141d6f406954f503fc5ffa3c93679aa`.

Fresh clone: `/home/odin/desktop-pr31-main-isolation-fresh-20261006`, created with
`git clone --no-hardlinks`. Clean before and after all gates. Repository-local locked dependencies
were installed with `uv sync --frozen`, `npm ci --ignore-scripts`, and explicit pinned Electron
installation. Node 22.23.3, Python 3.12.3, uv 0.11.26. No lockfile or dependency changes.
The pinned npm audit reports 11 findings (10 high, 1 critical); this task does not qualify dependency security.

All five requested gates ran sequentially, once, as ordinary `odin` UID/GID 1003, from
2026-10-06T06:59:47Z through 2026-10-06T07:05:41Z. All passed; no qualification failures or reruns.

| Gate | Result |
|---|---|
| `npm run check` | Typecheck, 770 tests in 80 files, build: PASS |
| `npm run smoke` | Isolated fixture Electron: PASS |
| `npm run test:real-core` | 39 contracts in 3 files plus 6 onboarding cases: PASS, no skips |
| `npm run smoke:real-core` | 39 management + 11 provider-chat checkpoints, 4 output pages: PASS |
| `npm run test:a11y` | 15 expected; zero unexpected, skipped, or flaky: PASS |

### CI-style restricted-helper evidence

This was a local CI-style invocation, not a claim that a GitHub Actions graphical smoke job ran.
The sudo journal records the actual selected command for both smoke lanes as
`/usr/local/sbin/odin-desktop-isolate`, including helper probes, preserved UID/GID 1003,
the exact isolation runner's `--inside-run`, and the chat child's `--inside-smoke` argv.
There was no generic sudo/unshare fallback for these lanes. The ordinary `odin` account also has
full sudo available, but that path was not selected; the restricted helper drops to its invoking user.

Smoke output:

```text
real-core-smoke: management ok link=ready screens=39
real-core-smoke: ok link=ready version=0.1.0.dev1 screens=11 output-pages=4
real-core smoke PASSED management + provider chat
```

The retained chat evidence still proves typed generation-2 Resume on the original request
`r_896374237db14729931d98d7f14302d8` with one user message, ordinary `continue` afterward,
guarded reply, real tool output, a 700,000-byte attachment, posted-file download/image decode,
committed request-bound failure notice, Stop/Steer/queued follow-up, search/reset and conversation lifecycle.
Native chooser selections remain injected under isolation; native chooser UI, real-account/vault,
packaged runtime, and desktop/Orca qualification are not claimed.

## Evidence and cleanup

Evidence root: `/home/odin/desktop-pr31-main-isolation-evidence-20261006/`.
Contains `qualify.sh`, exact source/identity/version and clean-status records, `gates.tsv`,
dependency and five gate logs, screenshots, `real-evidence.json`, `real-management-evidence.json`,
`a11y/accessibility.json`, `smoke-helper-journal.log`, and `artifact-sha256.txt`.
The earlier review's failing smoke is the input diagnosis; it is not represented as a passing run here.

Post-gate `validate_action` passed 5/5: exact clean tested checkout, five zero exit codes,
all five recorded private HOME trees removed, no checkout test executable/script retained,
and unchanged main launcher/installed restricted helper. No cleanup kills were needed.

Main was rechecked after qualification at `f597c1af3e6b3796d7f6753d4d3b455be2f57b3c`.
The final evidence commit changes only this document and the adjacent result JSON, not tested source.
