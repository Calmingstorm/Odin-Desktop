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

Pending the one final full qualification run from a new group-writable checkout.
The final evidence will be appended here without changing tested source bytes.

## Explicit limits

Headless loopback qualification does not prove real LAN/tailnet reachability,
native keyring prompts or graphical lifecycle. Malformed non-object/pathological
JSON receives bounded `400 invalid JSON` rather than upstream's incidental
handler failure. Success says the durable integration notice was published,
not that the configured task succeeded or a human received it. No GitLab ingress,
remote chat/settings/control API, app/protocol changes, deployment, live-service
change, `/opt/odin` write or active-desktop operation. No Phase 2 closure claim.
