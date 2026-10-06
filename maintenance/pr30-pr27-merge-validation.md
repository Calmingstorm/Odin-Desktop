# PR #30: merge the updated PR #27 into P3.2

Validated on 2026-10-05 in `/home/odin/desktop-p32-onboarding`, unprivileged `odin`,
Node 22 and repository Python 3.12. Merge, not rebase: first parent
`3dee6f391962f4f3023f2d189b9f6dd041c3642c`, PR #27 parent
`8b88120e2c990d654a8520f7446ed149f25e872a`. The latter merges main after
accessibility PR #29 and deferred-engine-suite PR #26.

## Integration decisions

- Keep P3.2 core-authoritative readiness, banner, remembered Settings section and
  route re-entry alongside accessibility focus restoration, modal-aware shortcuts,
  main/navigation/content landmarks and error announcements.
- Preserve the named, no-URL `codexOpenVerification()` operation and renderer-safe
  local login IDs. Retain incoming copy-code support, contextual account labels and
  code-free status announcements. No renderer hyperlink opener was reintroduced.
- Preserve both first-run and accessibility styling, documentation and package
  scripts. `test:real-core` still includes the separate Vitest onboarding runner;
  `test:a11y` remains the owned Playwright isolation gate.
- Carry PR #27's `-P` development override, smoke/harness/accessibility launches and
  app-directory regression coverage. Add `-P` and `app/` working directory to the
  onboarding Electron launch as well.
- Update onboarding's actual-renderer field selectors to the collision-free
  accessibility DOM IDs. Keep main and renderer TypeScript project boundaries.
- Adapt imported structural fixtures to the P3.2 local-login/schema contract.
- Scope Playwright discovery to its accessibility suite; onboarding is a Vitest
  suite under the same directory and remains exercised by `test:real-core`.

## Final gates

Installed only repository dependencies with `uv sync --frozen --extra dev`,
`npm ci --ignore-scripts` and explicit Electron installation. A complete final
sequential run after all code/test/config changes passed:

| Gate | Result |
| --- | --- |
| `npm run check` | Typecheck/build passed; 630 tests, 66 files passed |
| `npm run smoke` | Fixture Electron smoke passed |
| `npm run test:real-core` | 19 real-core contracts and 5 onboarding E2E passed |
| `npm run smoke:real-core` | 23 checkpoints, all eleven Settings sections passed |
| `npm run test:a11y` | 15 passed; zero failures, skips or flaky tests |
| Exact inventory report | `errors: []`, byte-drift-clean-review-pending |
| `git diff --check` | Passed |

Pre-final runs found an incomplete imported schema fixture, an invalid
main-to-renderer helper import, and Playwright trying to import the Vitest
onboarding suite. Fixtures, selector implementation and explicit suite discovery
were corrected before the complete final five-gate run. No accessibility rules
or onboarding tests were disabled.

Evidence outside Git under `/home/odin`, final SHA-256:

```text
cd6ca165895d2f28ebcff7e0565c95e6152aa860e7b0afeaed56ea2ecc3b4d68  pr30-merge-pr27-final-check.log
c0bee3a5f508e7be6d310e3b975c22d05a245caa905259af56c4efcbfe9b2675  pr30-merge-pr27-final-fixture-smoke.log
692ee1089decabf46e796262730cb3ff9c1d3dadc8518ae56727d8714a17b1fa  pr30-merge-pr27-final-real-tests.log
072d050ff7c007d94055503c4fc1c58df30e3911bdfe94d0efb43563dc95007e  pr30-merge-pr27-final-real-smoke.log
6ffa415b92718c547c082c61cef105cb619eb2a426f90ab95c1a99f1c903e735  pr30-merge-pr27-final-a11y.log
c2bd7cce8ec6e8b77896cc9edd797823354e532b18f338edd662ca28f313d26d  pr30-merge-pr27-final-a11y-report.json
```

Graphical tests used isolated Xvfb and disposable HOME/XDG, real-core/onboarding/
accessibility trees additionally used the owned unprivileged PID namespace.
No active workstation desktop, live install/service, production account or
credential was used or changed. These source-build behavioral gates do not
qualify native Secret Service, production OAuth/generation, Orca/AT-SPI, Wayland,
packaging or full Phase 3 exit. Full engine qualification was not repeated.
