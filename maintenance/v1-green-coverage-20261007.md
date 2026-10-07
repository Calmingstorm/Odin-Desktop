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

## Coverage baseline and first instrumented CI

Comparable pristine base measurement used an independent worktree, identical
sysmon/subprocess instrumentation, five unchanged classified shards plus extras:
**64,491 / 74,498 Python lines, 86.5674%**. It ran 19,888 cases:
19,884 passed, three skipped, one failed. The unchanged private portal socket test
disconnected at its final close (`test_computer_wayland_portal_r10.py:272`,
`EOFError: portal helper disconnected`). This measurement is not a green baseline
test receipt. Logs and initial CTracer failures are retained, not hidden or retried
until green. The first unchanged hosted PR run above was green.

App before: **4,941 / 7,326, 67.4447%**, unchanged existing unit corpus.

Instrumented CI at `40867040ecbc2bc9c9bb970b161b8e26fed44aa3`, run
`37692919080`: all eight original jobs passed. The new strict ratchet failed:
Python 64,522 / 74,498 versus the local initial ceiling's 64,525 covered lines;
`src/__main__.py`, `src/cli.py`, `src/tools/browser.py` lost locally covered paths.
The gate correctly refused them. Deterministic behavior tests cover those paths
instead of lowering the baseline or adding tolerance. App CI measured
**6,952 / 7,326, 94.8949%**. Every one of the 167 requested executable targets
was already above 80% in that run; no native/hardware exceptions are used.
