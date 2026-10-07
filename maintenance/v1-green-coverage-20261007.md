# B3: CI green and coverage ratchet

Base: `bbbe0b47d340b2bf499e168751030bf8459ed7d7` (latest main at task start).

The first PR workflow run is the unchanged baseline. Coverage instrumentation,
before/after measurements, added tests and final exact-head CI receipts will be
recorded here. No VM, lab, real desktop or service changes are authorized.

## Unchanged CI baseline

First PR head `87d8451319792361822e2cf0c212c35d37a7a663`, run
`37687696609`: all eight original jobs passed. No retry.

## Instrumentation and tests

Python uses coverage.py line measurement with Python 3.12 `sys.monitoring`,
preserving the D19 tests' independent exact code-object/line spies. The initial
CTracer measurement failed 11 positive controls and eight fixtures because
`sys.gettrace()` was already occupied. Switching the measurement core, not
loosening the tests, passes all 53 unchanged D19 cases. Child-interpreter
measurement is explicitly enabled and proved using harmless protocol encoding.

App measurement uses pinned Vitest V8 coverage, includes every executable TS/Vue
file, and retains JSON, LCOV and HTML. Added inert Electron wiring, lifecycle,
driver and real compiled component tests. Mock driver coverage does not establish
native desktop acceptance.

The new gate checks complete executable inventories, changed-since-October-4
targets, total and per-file exact percentage non-regression, missed-line ceilings,
and 80% new/target-file floors. Explicit reviewed baseline updates print previous
totals. CI never updates its baseline. Every named shard artifact is required;
persistent measurement/report data is cleared before use. Raw reports are uploaded.

Coverage exposed a wall-clock-dependent reminder test: two ticks crossed a real
cron minute and legitimately produced a second scheduled run. The test now fixes
the cohort clock. No scheduler semantics or time limit changed. It also exposed
MCP numeric v-model values reaching `.trim()`: input normalization now supports
the actual numeric value and the test types through the rendered control.

Aaron explicitly overrode the brief's no-agent restriction. Focused agents wrote
disjoint test files and audited the instrumentation. No VM or lab work occurred.
