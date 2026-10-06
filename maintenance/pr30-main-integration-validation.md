# PR30: integrate accepted conversations, requests and controls from main

Validated 2026-10-05/06 in `/home/odin/desktop-p32-onboarding` as
unprivileged `odin`, repository Python 3.12 and Node 22. Merges, not rebases.
Original head `cae0b3c8826419806c70276eca6723c82e11ce10` was merged with
main `d546c44c29388225015f20747c55930413b03f75` in merge commit
`c78586c2f93c31e0ebf4394b60d5efe180e8b93c`. Main advanced during gates:
the subsequent merge includes PR23 controls/resume at
`4ea7aa0f3b423a301854a9f0bdd2a46bc92d9d7b`.

## Integration decisions

- Preserve main's conversations, transcript/search, attachments, results,
  request execution, durable delivery and ordered publication. Management and
  request execution share the same settings, gateway, executor and owners.
- Preserve onboarding's core-authoritative readiness and prompt-free background
  keyring access. Hydration remains off-loop before consumer composition. Startup
  Codex vault reads and client construction use an awaited worker; publication and
  callback wiring return to the event loop. No whole-graph thread construction or
  cross-thread SQLite access was introduced.
- Preserve explicit-only `secrets.unlock`, same-socket responsiveness and durable
  no-replay outcomes. Initial status/publication precede listener exposure. The
  merged special `status.get` route now refreshes async readiness before returning
  the synchronous shared runtime projection and diagnostics.
- Preserve main23's generation-bound Stop/Steer, guarded original-request resume,
  durable asynchronous command envelopes and reset/auto-resume fencing.
- Update smoke assertions to observe real persisted conversation creation,
  snapshots, attachment readiness and successful empty search rather than asserting
  now-obsolete service refusals. All 23 existing checkpoint roles remain.
- Main's provider composition now genuinely adopts a configured startup Codex
  client. Onboarding tests separately prove healthy persisted startup is
  effective-ready and an injected constructor refusal remains saved until actual
  owner adoption on retry. No successful network generation is claimed.
- Use `/home/odin/reviews/merge_ledger.py` for key-based ledger union. Its refusal
  identified doubly changed entries. Those entries alone were excluded from the
  union inputs and regenerated with `inventory.py record` against resolved bytes,
  combining both parents' contracts, invariants and evidence paths. Changed
  evidence digests were explicitly re-recorded; independent approval stays pending.

## Final gates on main23 integration

| Gate | Result |
| --- | --- |
| Drift | `errors: []`, byte-drift-clean-review-pending |
| Lint | 7 inherited findings, zero new findings |
| Phase 2 plan | Passed, 122 planned modules; ownership coverage only |
| `npm run check` | Typecheck/build passed, 638 tests in 67 files |
| `npm run smoke` | Fixture Electron smoke passed |
| `npm run test:real-core` | 20 contracts and 6 actual Electron onboarding E2E passed |
| `npm run smoke:real-core` | 23 checkpoints, all eleven Settings sections passed |
| `npm run test:a11y` | 15/15, zero failed/skipped/flaky tests |
| Desktop Python + phase2 runner characterization | 4207 passed, 1 inherited skip, 4 inherited cleanup warnings, 573.37 seconds |
| Diff checks | Clean relative to latest merged main and for integration edits |

The broad Python run includes all `tests/test_desktop_*.py` and
`tests/desktop_adapters/test_phase2_runner_characterization.py`, covering the
core, conversation/request/delivery, controls/resume and keyring suites touched
by both merges. It is not a repeated full 30-group engine qualification.
The earlier focused pass was 149 tests; the complete pre23 integration pass was
4124 passed, one skip and four warnings.

Pre-final gates caught synchronous incoming startup vault reads, stale readiness
on the new special status path, obsolete saved-on-healthy-startup onboarding
expectations, the new synthetic flag missing from the strict test adapter schema,
and obsolete conversation/search smoke refusals. Fixed the production paths and
behavioral assertions, then repeated all requested app gates. No rules/tests were
disabled. A read-only independent technical inspection found no merge blocker,
including the controls/keyring interaction; Claude's cross-review remains the
approval boundary.

## Evidence and limitations

Evidence outside Git: `/home/odin/pr30-main-evidence/`.

```text
c09af21c8cfd7f2b5a6bbe3b047c06fbd2639c3924046cb1c02cc54f344dc0f2  latest-check.log
8c2a054581c7b00ddb90d1fa3c649169ef34666bffc5ba165c2040880641a5b4  latest-smoke.log
c8fc6db933271f8184581a96ce71d960c023cb200f2e775f63c51e44fe1e6ac8  latest-real-tests.log
173295b4548fe727336b01e0fa57e720edeabf2bc0ddd6962f7f09d0f0a4f3fd  latest-real-smoke.log
3626e7a5500e54ac61b656d3c2024c436cc9a92371e1714a03e8d6fe56c98e32  latest-a11y.log
448dd80371ba71d0bdcfc3d282192b7c104f8d013d8fe8558ca87ee2579363eb  final-python-desktop.log
0640cc6745a42098b99d9ef67172819cf28f3ba0e26fab71dc0fd9e3dc0da6a4  latest-drift.json
9d34ab5bc2efad4fadb7e30a2f0674d4426c54769eed8fb7fe58b6cfe61c4584  latest-lint.json
ee20850a561b355e8240ab57ec1ff604439ca4f5322807e31a00dbd9139f2a48  latest-plan.json
```

Python tests used an isolated PID/mount namespace and disposable HOME/XDG,
with a real PID1 shell and harmless PID2 spacer for retained identity tests.
Graphical tests used isolated Xvfb/disposable HOME/XDG; accessibility used a
private D-Bus. The four raw lab listener header trailing-space findings inherited
from main were preserved byte-for-byte, not edited to cosmetically clean evidence.
`git diff 4ea7aa0f --check` is clean. Routine isolated Electron D-Bus/portal/FUSE
warnings did not fail the gates.

No active workstation display/session bus, live installation/service, production
account or credential was used or modified. Native prompt acceptance remains
PR20's VM work. No production OAuth/generation, native Orca qualification,
Wayland/packaging or full Phase 3 exit is claimed. No PR merge or deployment was
performed, and commits carry no attribution trailers.
