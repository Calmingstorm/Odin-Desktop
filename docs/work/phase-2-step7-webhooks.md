# Phase 2 step 7: inbound webhook triggers

This slice is stacked on step 6B's `phase-2/services-part-b`, initially
`4ede9e75fb079a0a305c7b24f89700d7fb7c4416`. It implements only the core's
schedule-trigger ingress. There is no app, remote management API, daemon,
deployment or native desktop qualification in this slice.

## Approved parity and adaptations

The parity source is the frozen Odin v4.13.0 archive, especially
`src/health/server.py`'s generic/GitHub/Gitea handlers, `_notify_triggers` and
`_send`, plus the integration management transaction conventions in
`src/web/api/integrations.py`. Desktop's old health/API stubs are not a runtime
parity source.

- Generic uses `X-Webhook-Secret`; GitHub/Gitea use body HMAC-SHA256 with their
  native headers. Preserve source normalization, message formatting, JSON
  response semantics and the 10 MiB body ceiling.
- Native generic events have no repository field. Source/event/repository
  filters retain Odin's AND matching, including case-insensitive repository
  substring matching. Payload text cannot change the schedule action or input.
- Each authenticated delivery gets a separate core-issued durable identity.
  Identical sequential deliveries can execute twice. There is no digest/nonce
  deduplication, timestamp gate, rate limit or TLS prerequisite under D17.
- D10 requires explicit activation, one owner-selected nonwildcard address,
  and an independent secret per trigger. Only a bound schedule is a candidate
  for that credential. No eligible webhook schedule means no accepting
  listener. Outbound webhooks remain a separate retained owner.
- Receipt persistence precedes effects. Interrupted or uncertain internal
  handoffs are never automatically dispatched again after restart. Provider
  retries are distinct new authenticated deliveries, not internal replay.
  Unknown receipts remain visible in status without pausing future deliveries
  or re-pausing the trigger on successive restarts. Interrupted scheduled runs
  follow the scheduler's one-time/recurring recovery policy.
- The integration message goes to the bound schedule's existing conversation,
  separately from task results, using the durable transcript/event path. A
  delivery response does not claim task success or human receipt.
- The receiver shares the supervised core lifetime. Exit, ingress disablement
  and parent loss stop admission and close its owned listener. No request can
  start the app or forward chat/settings/control methods.
- Adopted settings/schedule changes and keyring hydration/transaction settlement
  invalidate listener readiness through coalesced, thread-safe notifications.
  Idle ingress does not copy/scan schedules. Missing owner events, cached keyring
  state/admission transitions and failed binds use at most a 1 Hz fallback.
  This does not newly prove detection of an external native keyring relock.

## Evidence discipline

`tests/test_desktop_webhooks.py` exercises the new receiver and its actual
composition. Safe inherited adapters retain selected frozen assertions and
parameter data; mixed source suites are not silently declared fully restored.
The source/text/persistence utilities unrelated to inbound HTTP remain retained
and are composed or tested without rewriting their algorithms.

All runtime tests use temporary profiles and ephemeral loopback ports behind
the sanitized PID-namespace runner. No test binds a LAN/tailnet interface or
touches live data, live services, `/opt/odin` or the active desktop. Real LAN
reachability, native keyring prompts and graphical lifecycle are not proved by
these headless tests.

Final qualification evidence is recorded in
`maintenance/phase2-step7-validation.md` after the final fresh-checkout run.
Review remains independent and pending; this document is not approval.
