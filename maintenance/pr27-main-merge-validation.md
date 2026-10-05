# PR #27: merge main after accessibility PR #29

Validated on 2026-10-05 in `/home/odin/desktop-p31-slice2` as unprivileged `odin`,
Node 22 and repository Python 3.12. This is a merge, not a rebase: first parent
`06294d67d46979861d91c30579e3b3aff0b0de7d`, main parent
`cbda9ba316c5f3460bed79ec311b55a5c8032bbd`. Main includes accessibility PR #29
(`f536fb34`) and the subsequently merged deferred-engine-suite PR #26.

## Integration decisions

- Preserve real-core handling together with accessibility in the four conflicting
  CodexAccounts, Hosts, State and Tools components. Keep account/load retries,
  accurate stopped-login wording, local-host fingerprint exclusion, authenticated
  memory scope labels, structured list items, restore disabling and pending-save
  draft protection. Preserve labels, announcements, disclosure IDs and error links.
- Add `-P` to the documented Python development override and actual real-core
  smoke/accessibility/harness launches. The smoke, contracts and real accessibility
  lane now launch from `app/`, exercising the original namespace-shadowing failure
  location rather than concealing it with a repository-root working directory.
  Isolation preflight also resolves the installed engine with `-P`.
- Adapt the accessibility real-core assertions from step-one absence to step-five
  behavior: real status and unknown/history-disabled usage, all eleven Settings
  sections, axe and full Chromium AX checks. No audit rules were disabled.
- Real accessibility launches omit the private session-bus address. Fixture lanes
  retain their private bus for native dialogs. The fresh real lane observes a
  missing vault rather than blocking on an unqualified Secret Service prompt.
- Axe found an existing reset-button visible-name mismatch when auditing actual
  schema fields. Use `Reset to default: <field label>` and add a structural
  regression; visible text remains unchanged.

## Final gates

Dependencies: `uv sync --frozen --extra dev`, `npm ci --ignore-scripts`, explicit
Electron installation. Final sequential run after all source/test changes:

| Gate | Result |
| --- | --- |
| `npm run check` | Typecheck/build passed; 609 tests, 64 files passed |
| `npm run smoke` | Fixture Electron smoke passed |
| `npm run test:real-core` | 19 contracts passed |
| `npm run smoke:real-core` | 23 checkpoints passed, including all eleven Settings sections |
| `npm run test:a11y` | 15 passed; zero failed, skipped or flaky |
| Exact inventory report | `errors: []`, byte-drift-clean-review-pending |
| `git diff --check` | Passed |

Earlier diagnostic runs exposed the private-vault prompt, reset-button accessible
name mismatch, and two new assertion mistakes (unknown usage wording and whitespace
in the reset-label structural test). All were corrected before the complete final
five-gate run. These are not unexplained passing reruns.

Logs/screenshots/Playwright reports remain outside Git. Final log SHA-256 values:

```text
42c6e6e2fd79c7c047fb076d7772d2f45efaa5c4c1e76d06c4585b00bc78b0c3  pr27-merge-main-final-check.log
aa49c13cf94aa214b685c501db8a1423476efa149f157512afe55d5f9358a990  pr27-merge-main-final-fixture-smoke.log
9a95ca077d363b1e373082b4f7194a4047daf813d5a7f951936e41c749cfa8bc  pr27-merge-main-final-real-tests.log
cc06a825d98585b3b947c3517ad24f69a1f93eeb8f7fe2a0c2dd6cb20a04f6dd  pr27-merge-main-final-real-smoke.log
de0ed881a01846fd4b4f3ccd5e2bd3f07cc037cf0a603f43b0cfcc44892b6a27  pr27-merge-main-final-a11y.log
0c875311a1b1ded6b375926b57640399215e7970b56ff7354b16354955b29ee0  pr27-merge-main-final-a11y-report.json
```

## Scope and limits

Graphical tests used isolated Xvfb/disposable HOME and XDG; real-core and
accessibility trees additionally used the owned unprivileged PID namespace.
No active workstation desktop, live service, installation, account or credential
was used or changed. Source-build checks do not qualify native Secret Service,
Orca/AT-SPI, Wayland, packaging or full Phase 3 exit. The full engine qualification
was not repeated for this app merge. Independent source review remains pending.
