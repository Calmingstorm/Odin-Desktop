# Phase 2 step 7 validation

## Scope and source

Inbound generic/GitHub/Gitea schedule triggers, stacked on PR #37 at
`4ede9e75fb079a0a305c7b24f89700d7fb7c4416`. Frozen Odin v4.13.0 is the native
authentication, JSON response and message-formatting source. The core, scheduler,
settings/secrets, transcript and durable publication owners are composed rather
than replaced by a new executor or a management HTTP service.

Section 8 of `docs/design/core-contracts.md` is updated for the approved D17
clarification: identical sequential deliveries run twice, with independent
durable core-issued receipt identities. No freshness/rate/TLS requirement or
identical-body deduplication is added. Retained scheduler in-flight exclusion
still skips overlapping executions; this is not an ingress backlog.

## Targeted preflight

The final targeted run completed **242 passed, zero failures** in 50.30 seconds:

- New ingress tests and exact inherited webhook adapters.
- Existing settings, schedule recovery, core lifecycle, real background core,
  foundation config and runtime tests.
- Temporary profiles, ephemeral loopback only, sanitized PID namespace and
  throwaway HOME/config/data/cache. No LAN exposure or active desktop.

The ingress proofs cover per-trigger authentication and candidate isolation,
duplicates, known/unknown failure separation, immediate receipt-storage refusal,
unavailable keyring fencing, revocation, bounded JSON/header/body handling,
10 MiB boundary, delivery-only routes, same-conversation notices after callbacks,
notice repair without effects, actual profile reopen and actual core parent EOF.

The inherited adapter selection preserves **74 original functions**, expanding
to **104 inherited cases** plus six source/AST/real-graph checks. Exact selected
names, frozen hashes and partial-suite limitations are in
`docs/work/phase-2-step7-inherited-adapters.md`. Text/persistence helpers are
outbound YAML coverage, not proof of inbound receipt-storage behavior. Mixed
GitHub/persistence/scheduler suites are not falsely declared fully restored.

Preflight byte drift is clean under the explicit per-path adaptation plan;
lint has seven inherited findings and **zero new findings**. All implementation
records remain pending independent Claude review, not author-approved.

## Final fresh-checkout gate

The requested **single full qualification run** completed all **30 groups**
from fresh checkout `e8e5b27b820f1bd2f889e1fce524e016722f96b3`. Parent and checkout
were `2775`, owned by `odin:odin`; the runner used the sanitized PID namespace
and throwaway HOME/config/data/cache. Result: **14,707 passed, 11 failed,
2 skipped, zero errors**. Four groups failed; this is **not a green full gate**.

One failure was a genuine omitted settings subgroup description for
`webhook.triggers`. Commit `a653ac7e51daf6c041ecb90bffeb5ad2def07585` adds the
description and updates its exact drift record. The other ten failures were
existing 3/5/15-second IPC/startup/handoff/process-output deadlines. The full
run remains preserved, and no assertion, deadline or selection was weakened.
Concurrent host load was observed, but that observation does not prove the
cause of these failures.

A second **fresh targeted checkout**, not a second full run, exercised every
failed case and its parameter family, subgroup descriptions, all new ingress
cases and all inherited webhook adapters on `a653ac7e`: **166 passed, zero
failures**, in 80.92 seconds. The ten deadline failures did not reproduce in
this run. The subgroup failure is fixed and its original assertion passes.
All ingress/adapters had also passed in the single full run. This targeted
regression evidence is separate from, not a replacement for, full acceptance.

Final evidence:

- `/home/odin/desktop-step7-20261006/qualification-final.log`
- `/home/odin/desktop-step7-20261006/final/.test-state/qualification-*.xml`
- `/home/odin/desktop-step7-20261006/failed-case-regression.log`
- `/home/odin/desktop-step7-20261006/targeted-final.log`
- Fresh full tree: `/home/odin/desktop-step7-20261006/final/`
- Fresh regression tree: `/home/odin/desktop-step7-20261006/regression/`

Final byte drift, ownership/suite accounting and lint are clean with **zero new
lint findings**. The final evidence-only commit does not change tested source
or test bytes. Independent Claude review and full-gate acceptance remain
pending. No second full qualification was run, as requested.

## PR42 review round 1 follow-up

The ingress review findings are implemented without changing its authentication,
limits, matching or delivery-only surface:

- Unknown receipt recovery no longer mutates or pauses schedule definitions.
  Receipt settlement failures attempt a durable unknown marker; an already
  persisted dispatching marker becomes unknown on reopen if storage is still
  unavailable. Neither path admits internal replay.
- Status reports the durable unknown-delivery count. Lost handoff acknowledgement
  is covered through two actual scheduler reconstructions, with the original
  receipt still unknown and each new authenticated delivery executing once.
- Adopted scheduler/settings changes and worker-thread keyring hydration notify
  a coalescing listener watcher. Idle ingress does not scan/copy schedules.
  Missing owner events and cached availability/admission changes have a 1 Hz
  fallback. Failed binds share a bounded retry seam, including direct mutation
  hooks, and never broaden the address.
- Notification tests cover failed versus cancelled durable writes, rollback
  recovery, native scheduler edits, worker hydration, coalescing, close during
  bind, bounded retry and subscription cleanup.

Latest targeted run of ingress/adapters/settings/background/lifecycle/runtime/
schedule recovery: **243 passed, 1 failed**, under the sanitized namespace
runner. The sole failing case is
`test_cancelled_handoff_fences_and_recovers_notice_only`: the inherited #37
scheduler still quarantines an interrupted recurring run. The test is retained,
not weakened or excluded from acceptance. Its two-restart/new-delivery proof
cannot run past that assertion until lane 9's P2-1 base fix lands.

Earlier narrower pre-base runs were **265 passed, 1 deselected**, then
**48 passed, 1 deselected**; the dependency case was explicitly omitted only
from those diagnostics. Five durable-notification/rollback/bind edge tests also
passed. These numbers are separate evidence, not an aggregated gate result.

The short gates pass: exact byte drift has no errors, ownership and suite
accounting are clean, and lint has seven inherited findings with no new ones.

Required upstream state at the final check:

- PR37 remains open at `4ede9e75fb079a0a305c7b24f89700d7fb7c4416`.
- PR34 remains open at `78582fc86d53794bb60dd40f4870981327ae1a99`.

A bounded upstream watcher expired without either dependency becoming ready.
No replacement full qualification was run prematurely. The requested base/main
merges and single final fresh-checkout full gate remain **pending**, not green.
An exploratory merge of current main was aborted; no partial conflict resolution
is included in the published branch. No rebase or force-push.

Evidence under `/home/odin/desktop-step7-20261006/`:
`review1-targeted-final-prebase.log`, `review1-prebase-ingress.log`,
`review1-ingress-audit.log`, `review1-notification-edges.log`,
`review1-base-wait.log`. Independent review remains pending.

## Explicit limits

Headless loopback qualification does not prove real LAN/tailnet reachability,
native keyring prompts or graphical lifecycle. Malformed non-object/pathological
JSON receives bounded `400 invalid JSON` rather than upstream's incidental
handler failure. Success says the durable integration notice was published,
not that the configured task succeeded or a human received it. No GitLab ingress,
remote chat/settings/control API, app/protocol changes, deployment, live-service
change, `/opt/odin` write or active-desktop operation. No Phase 2 closure claim.
