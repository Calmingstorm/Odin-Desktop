# PR28 lane 7: main integration

Merged main `ddd054fe399fef46dd64b6e8ec95b2676af8f09f` into the approved
step-6A head `964482858ba7b9f11fa0a6ee34d0f1ee01d1abce`, without rebase or
force-push. This record describes branch integration, not a GitHub PR merge,
deployment or native-platform qualification.

## Resolved contracts

- Browser retains main's bundle-root executable fallback and enabled Chromium
  sandbox, with no no-sandbox/setuid-sandbox bypass flags. Step 6A's explicit
  launch environment, Playwright launch deadline and bounded start/launch remain.
- Core retains early parent/signal observation, off-loop initial and post-compose
  secret hydration, profile provider initialization and management startup. The
  listener starts once, after initial readiness/status publication.
- Composite reload remains async, prepares providers off-loop, and includes MCP
  and computer tokens. MCP preparation uses the same settled daemon worker as
  keyring operations. A later preparation failure discards its provider token.
- All MCP async startup, reconnect and credential transaction accesses now run
  off-loop. The shared settings gate and transaction flag remain held while vault
  workers settle. Config/runtime adoption stays on the loop and await-free. Close
  fences are rechecked after hydration. Repeated cancellation drains rollback,
  and settled worker failure takes precedence over cancellation so uncertain
  restoration cannot silently clear the credential-presence fence.
- Regressions exercise slow and locked actual settings reload, loop liveness,
  cancellation before apply, failed-worker cancellation races, repeated write
  rollback cancellation, close during hydration, and reconnect serialization.
- App real-core capability expectations now include served step-6A methods and
  actual empty skill/MCP reads. Part-B methods remain refused; computer status
  still reports no foreground/input dispatch. No product renderer surface added.
- Ledger union used `merge_ledger.py`; 25 joint entries were regenerated with
  `inventory.py record`, preserving both sides' rationale/test provenance.
  Subsequent changed evidence digests were explicitly regenerated. Product pip
  stays in the approved step-6A dependency set for its engine-local installer;
  optional first-use PDF provisioning from main remains optional.

## Targeted evidence before fresh qualification

Workspace: `/home/odin/desktop-pr28-main-lane7-20261006/work`.
Evidence: adjacent `evidence/`, and work `.test-state/` XML.

- Exact drift: no errors; 335 pending independent-review records.
- Lint: no new findings; seven inherited findings.
- Ownership and suite-map checks pass, retaining honest planned/not-implemented
  accounting rather than claiming runtime closure.
- Step-6A group: 172 passed.
- Core transport: 567 passed, one inherited process-transport event-loop-close
  warning. Profile management: 303 passed. Request/async/plan selection: 84 passed.
- App check: 640 passed plus typecheck/build. Real-core: 20 contracts and six
  actual isolated Electron onboarding tests passed.
- Independent technical reviews found async yield races and the failed-worker
  cancellation precedence issue; both were corrected. Final narrowly scoped
  read-only settlement review reports no blocker. Claude acceptance still pending.

## Failed and diagnostic runs retained

Initial test construction added a server through whole-config reload, triggering
the legitimate credential-container refusal. Corrected setup uses the dedicated
MCP save owner. An initial same-socket runtime.reload responsiveness assertion
incorrectly assumed concurrent ordinary management dispatch; that transport is
deliberately serial. The final test exercises the actual settings transaction
directly and checks loop/socket liveness, without changing IPC concurrency.

The initial app real-core run failed two exact capability assertions because the
main-only expected list omitted served step-6A methods. Explicit list/read
expectations were updated, not weakened to accept arbitrary capabilities.

Repeated core subprocess checks hit varying listener deadlines before lifecycle
assertions: initially three seconds, and twice after adopting the app harness's
eight-second budget. Diagnostic failure now closes the owned parent pipe and
reports child stdout/stderr. The final full core transport recheck passed. This
remains a startup timing sensitivity, not proof of its underlying cause being
eliminated. No unrelated process or active desktop was signalled.

One targeted command misspelled the management group name, selected no files and
accidentally invoked the launcher's default broad selection. It was cancelled;
the process tool could not confirm cleanup, but subsequent exact PID/process-group
and command checks found no remaining owned processes. That incomplete run is not
qualification evidence. The correct named 303-case group subsequently passed.

## Fresh qualification

Pending the sole full qualification from a new copied-interpreter locked Python
3.12 checkout under a mode-0775 parent. Results will be appended only after the
runner finishes. All engine tests use isolated PID/mount namespaces, disposable
HOME/XDG and no live session/credentials. App native lifecycle tests use their
existing isolated runner/Xvfb, never the active desktop.

No attribution trailers, PR merge, deployment, live service/data change, native
keyring prompt acceptance, actual MCP endpoint or bundled-browser execution.
