# Step 8 part 2: batch D

Base: `b74056c4c9a16071426cb832db361cf86c84989a`. Allocation is the 21 sorted
step-5 paths at indices `[3::4]`. The JSON companion records every original SHA,
disposition, concrete blocker and test/source reference. No shared map, ledger,
test plan, checker or qualification plan was edited.

## Restorations

* **Knowledge snapshot campaign:** all 2 functions / 5 parametrized cases and 6
  assertion nodes. Real private Unix socket, `IpcServer` / `LocalClient` handshake,
  OS-peer credential validation, actual `CoreService.dispatch`, durable command
  receipts and an injected actual `KnowledgeService` / `KnowledgeStore`. The
  inherited HTTP response carrier alone is projected: success becomes 200 and an
  actual domain `conflict` becomes 409. No snapshot, error, result or outcome is
  manufactured. Unknown domain codes fail closed.
* **Process tail correctness:** all 6 functions / 9 cases and 48 assertion nodes,
  including helper settlement assertions and both local/remote parameter values.
  Actual authenticated temporary owner, private protected workspace, executor,
  process handler, local supervision, remote supervisor/controller, capture,
  settlement and delivery engines. The original hermetic remote helper replaces
  SSH transport only; it still runs the real remote supervisor locally. Readiness
  is advertised only for the actually wired process handler, with current owner,
  host and workspace checks. No globally-ready policy or process/security method
  replacements.

`tests/desktop_adapters/step8_runtime_d.py` contains the exact setup-hunk seals.
Every original node must match once by line, type and AST SHA; source bytes are
pinned against the immutable archive and unchanged inherited file. Corpus equality
protects every assertion/signature/decorator/parameter. Reverse replay requires
the **entire module AST** to equal the frozen original before compilation and
whole-module export. The test module also proves both static parent-checker
full-suite associations, provenance/hunk drift rejection, owner and bad-handshake
denial, durable real results, unmapped projection refusal and workspace/readiness
fail-closed behavior.

## Deferred and delegated

**18 deferred suites** remain honestly deferred. These include removed bearer,
Discord, listener and WebSocket contracts, plus real missing management behavior:
failure aggregates, legacy timeout normalization, capacity-breaker observation and
structured affordance output. Image transaction/cancellation and Codex backup-file
assertions also cannot be replaced by superficially similar Desktop features.
None was partially exported or counted passing. Full per-suite evidence is in
`step8-part2-batch-d.json`; audits `b149e4a9` and `139a3a1e` supplied static evidence,
not runtime passing claims.

**Subsystem guard is delegated** to its separately assigned agent. Batch D makes
no duplicate edit, product fix or passing claim. The parent overlays that result.

## Validation and safety

Inspected `CONTRIBUTING.md`, the PR26 review, runner isolation, actual process
cleanup, remote helper and command fixtures before execution. Process-group kill
cleanup is why the PID boundary is mandatory, not an optional inconvenience.

Final targeted invocation:

```text
USER=odin .venv/bin/python scripts/run-phase1-tests.py tests/test_desktop_phase2_runtime_d.py
22 passed in 7.51s
```

That is **14 inherited cases plus 8 adapter proof cases**. The runner uses `env -i`,
nonroot `odin`, private disposable XDG/HOME state and PID/mount namespaces. Evidence:
`/home/odin/desktop-phase2-step8-part2/batch-d-runtime-final.log`.

Development failures were limited to adapter setup: omitted process readiness,
new-test SQLite Row comparison and non-UUID IDs rejected by real IPC. Each was
fixed without weakening inherited assertions or changing product code; the JSON
records these iterations rather than hiding them.

No full qualification, native desktop, graphical lifecycle test, live installation
access, service modification, push or deployment was performed.
