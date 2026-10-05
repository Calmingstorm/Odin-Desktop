# Phase 2 work order: the desktop engine (Odin)

**Status:** proposed, pending Aaron's OK. Nothing here is built until he says go.
**Owner:** Odin builds; Claude reviews every PR and owns [`protocol.md`](../design/protocol.md).

## Goal

Odin's real engine runs as Odin Desktop's core process and speaks the protocol the app already uses. Everything gated
in Phase 1 works again with Odin's own behaviour (D2, D17). It is proven headless: a test harness supervises the core,
and nothing runs on an active desktop.

## Rules (carried from Phase 1)

- **D17:** nothing stricter than Odin. **D19:** mechanical wording swaps go to Claude; anything that changes what Odin
  is told to do goes to Aaron.
- Every change ships with tests that exercise real code, never document wording. Suites run only in the isolated PID
  namespace (`CONTRIBUTING.md`). No destructive or attack test inputs. Never `/opt/odin`, live config or live data.
- Pull `main` before branching. One PR per step below, in order. Claude reviews each; nothing merges without that.
  No attribution trailers.
- The protocol is the contract with the app. A change to it goes through Claude as a `protocol.md` minor bump, and the
  development fixture follows it.

## Steps (one PR each)

0. **File plan.** For each step below, the modules added or changed, from the reuse map's Phase 2 rows (the 34
   `replace` files and the Phase 2 parts of `keep with adaptation`). Claude reviews it; Aaron gets a short summary.
1. **Core process and local transport.** The core entry point the app starts in place of the fixture
   (`ODIN_DESKTOP_CORE_CMD`): the owner-only socket, `SO_PEERCRED`, the profile token, `hello`/`welcome`, parent-link
   shutdown on stdin EOF, one core per profile, framing, ping. The durable event journal (sequence, cursor, retention,
   `reset_required`) and durable command identity (receipts, tombstones, `id_conflict`, `receipt_expired`).
2. **Conversations.** The durable conversation store and transcript, child conversations (inherited and labeled),
   history paging, `conversation.snapshot` with its watermark, `conversations.list` with activity,
   `read_conversation` and `search_history` over the transcript.
3. **Requests and delivery.** `submission.send` admission (durable, deduplicated) into the existing turn runner, with
   anti-hedging, continuation, the completion judge and nudges unchanged. Committed-only replies (D9), tool events,
   artifacts (the files Odin posts), notification intents, and follow-up queueing.
4. **Controls.** Stop and Steer with receipts, guarded resume, and unknown-outcome handling on the existing turn state.
5. **Runtime.** Keyring secrets, settings over the protocol, fresh-profile provisioning with Odin's local host and
   default host, Codex device-code login, `runtime.shutdown` and `status.get`.
6. **Background work.** Agents, loops, schedules with D12's missed-run policy, background tasks, skills (delivery and
   dependency installation), MCP startup, computer-use admission, and the browser with bundled Chromium.
7. **Webhook triggers** (D10, [`core-contracts.md`](../design/core-contracts.md) section 8).
8. **Closure.** The roadmap's Phase 2 exit criteria: all 326 deferred suites back (adapted, never dropped), every
   section-4 wording row dispositioned, fresh-profile host parity proven at runtime, and the core-contract gate
   scenarios passing headless. Maintenance accounting updated.

## The gate

The roadmap's Phase 2 gate, unchanged: two conversations and a child; stop and steer during a long tool call; a
disconnect and catch-up during a workflow; a restart after compaction; lost receipts with no duplicate execution;
unknown dispatch and outbox recovery; resume with spent budgets; storage failure; revocation; loss of the core or the
app; running alongside a server install with fresh data; and the webhook acceptance cases.

## Claude during Phase 2

- Reviews every PR and keeps `protocol.md` and the fixture in step.
- Points the app at the real core (in place of the fixture) for an end-to-end smoke as each step lands.
- Builds the app's v1 interface in parallel ([`app-v1-plan.md`](app-v1-plan.md)).
