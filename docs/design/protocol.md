# Protocol v0: app ↔ core

Owner: Claude (draft); reviewer: Odin, who implements the core side in Phase 2. This is the concrete encoding of
[`core-contracts.md`](core-contracts.md) sections 3, 4 and 7. Where this file and the contracts disagree, the contracts
win, and this file is fixed.

**Who talks to the core.** Only the app's main process. The window never connects to the core.

## Transport

- **Socket.** A Unix domain socket at `$XDG_RUNTIME_DIR/odin-desktop/<profile_id>/core.sock`. The directory is `0700`
  and the socket is `0600`, both owned by the user.
- **Who creates it.** The core creates it. Before replacing an existing socket file, the core probes it: if a live core
  answers, the new core refuses to start.
- **Peer check.** The core verifies the connecting peer's uid (`SO_PEERCRED`) equals its own.
- **Credential.**
  - **What:** a profile-scoped token, 32 random bytes in hex.
  - **Where:** `$XDG_CONFIG_HOME/odin-desktop/<profile_id>/ipc.token`, mode `0600`.
  - **Created by** the app (main process) on the profile's first start. The core is started with the token file's path,
    never the token itself.
  - **Exposure:** it never appears in arguments, environment variables, logs or the window.
- **Parent link.**
  - The core's stdin is a pipe held by the app. End-of-file on stdin means the app is gone: the core then shuts down in
    order and exits.
  - The core never daemonizes or detaches. That is the parent-loss containment baseline. Qualified containment is
    added in Phase 3.

## Framing

- **Frame format.** A 4-byte unsigned big-endian length `N`, then `N` bytes of UTF-8 JSON encoding one object.
- **Size limit.** `N` must not exceed `max_frame` (default 4 MiB, announced by the core in `welcome`). A larger frame is a
  protocol error, and the connection closes.
- **No binary data in frames.** Files move as core-issued references fetched by bounded commands. Those commands arrive
  in later minors.

## Messages

Every message has a type field `t`. An unknown `t` is a protocol error. Unknown fields are ignored.

**App → core:**

| `t` | Fields |
|---|---|
| `hello` | `protocol: {major, minor}`, `client: {name, version}`, `profile_id`, `token`, `features: []` |
| `req` | `id` (client command ID, a UUIDv4), `method`, `params` |
| `ping` | `n` |

**Core → app:**

| `t` | Fields |
|---|---|
| `welcome` | `protocol: {major, minor}`, `core: {instance_id, version}`, `profile_id`, `capabilities: []`, `features: []`, `max_frame`, `event_high: <cursor>` |
| `res` | `id`, then either `ok: true, result` or `ok: false, error: {code, message, disposition}` |
| `evt` | `seq`, `cursor`, `type`, `entity: {kind, id, rev?}`, `at` (UTC ISO-8601), `payload` |
| `pong` | `n` |
| `bye` | `reason`. Sent before the core closes a connection on purpose. |

## Handshake

1. The app connects and sends `hello` within 5 seconds.
2. The core checks four things: the peer uid, the token (in constant time), the protocol major, and the `profile_id`.
   - **If all pass,** it answers `welcome`.
   - **Otherwise,** it sends `bye` with a reason (`unauthorized`, `incompatible` or `wrong_profile`) and closes.
3. After `welcome`, the app may send `req` frames. Events flow only after `events.subscribe`.

## Methods (minor 2)

| Method | Params | Result |
|---|---|---|
| `status.get` | `{}` | `{phase, core_instance_id, version, capabilities}`. Phase is one of `starting`, `ready`, `degraded`, `quiescing`. |
| `events.subscribe` | `{after: cursor or null}` | `{event_high, reset_required}`. If `after` is unknown or expired, `reset_required` is true: see **Reset** under the delivery rules. |
| `conversations.list` | `{}` | `{items, watermark}`. Each item is `{id, title, rev, parent_id, updated_at, unread, archived, activity}`, where `activity` is `{running: {request_id, generation} or null, queued: [{request_id, generation}]}`. The list is complete through `watermark`, under the same snapshot rules as below. |
| `conversations.create` | `{title?, parent_id?}` | `{conversation}`. A `parent_id` makes a child seeded from the parent's current context. |
| `conversations.update` | `{id, expected_rev, title?, archived?}` | `{conversation}`, or the error `stale_binding` if `expected_rev` doesn't match |
| `messages.list` | `{conversation_id, before?, limit}` | `{items, has_more, watermark}`. Committed messages only, newest last. `limit` is at most 100. Used for older pages; the current state comes from `conversation.snapshot`. |
| `conversation.snapshot` | `{conversation_id, limit?}` | The conversation's authoritative state at `watermark`: see **Snapshots** below. |
| `submission.send` | `{client_submission_id, conversation_id, text}` | `{disposition, request_id?, message_id?}`, where disposition is `accepted` or `rejected`. Sending the same `client_submission_id` again returns the original answer and never admits a second request. |
| `control.stop` | `{control_command_id, conversation_id, request_id, generation}` | `{disposition}`: `requested`, `not_running` or `stale_binding`. Settlement arrives as events. |
| `control.steer` | `{control_command_id, conversation_id, request_id, generation, text}` | `{disposition, sequence?}`: `queued`, `closed` or `stale_binding` |
| `runtime.shutdown` | `{reason}` | `{disposition: "accepted"}`. The core then stops admitting work, settles or cancels it, persists, and exits. Pending or unknown work is reported as events, and again at the next start. |

Attachments, artifacts, settings, schedules and the rest of the management surface arrive in later minors.

### Snapshots

`conversation.snapshot` returns everything a conversation view shows, so the app can rebuild it exactly after a
reconnect, a reset or a window reload, without relying on events it may have missed:

| Field | Contents |
|---|---|
| `watermark` | The profile cursor through which the snapshot is complete |
| `conversation` | The conversation record |
| `messages` | `{items, has_more}`: the latest committed messages (at most `limit`, default 100), newest last |
| `running` | `{request_id, generation, started_at}` or `null`. The only valid Stop and Steer target. |
| `queued` | `[{request_id, generation, message_id}]`, oldest first. Follow-ups waiting behind `running`. |
| `recent` | The latest terminal outcomes, newest last, at most 20: `[{request_id, generation, outcome, unknown_effects, at}]`. `outcome` is `completed`, `failed`, `cancelled`, `interrupted` or `suspended`. |
| `unresolved` | Every terminal outcome in the conversation whose unknown effects are not reconciled yet, oldest first, in the same shape as `recent`. Never trimmed and never cleared by later outcomes: a later success is not a reconciliation. An entry leaves only through `effects.resolved`. |
| `tools` | `{<request_id>: [{invocation_id, tool, target?, summary, outcome?, exit_code?, duration_ms?}]}` for the running request and the requests behind the listed messages |
| `controls` | `[{control_command_id, kind, request_id, generation, disposition, sequence?}]`: every Stop and Steer bound to the running or queued requests, with its latest disposition. It replaces the app's projection of those controls. |

## Events

| `type` | Payload |
|---|---|
| `runtime.status` | `{phase, …}` |
| `conversation.created`, `conversation.updated` | `{conversation}` |
| `message.committed` | `{conversation_id, message: {id, role, text, created_at, request_id?, client_submission_id?}}`. `role` is one of `user`, `assistant`, `notice`. For `assistant`, `text` is the guarded, committed reply. A `user` message carries the `client_submission_id` it was admitted under, so the app reconciles exactly. |
| `request.queued`, `request.started` | `{conversation_id, request_id, generation}` |
| `request.completed`, `request.failed`, `request.cancelled`, `request.interrupted`, `request.suspended` | `{conversation_id, request_id, generation, unknown_effects}` |
| `tool.started` | `{conversation_id, request_id, invocation_id, tool, target?, summary}` (scrubbed) |
| `tool.settled` | `{conversation_id, request_id, invocation_id, outcome, exit_code?, duration_ms, evidence_ref?}`. `outcome` is one of `success`, `failure`, `unknown`. |
| `control.receipt` | `{conversation_id, request_id, generation, control_command_id, kind, disposition}`. `kind` is `stop` or `steer`. `disposition` is one of `requested`, `confirmed`, `queued`, `consumed`, `closed`, `stale_binding`. |
| `effects.resolved` | `{conversation_id, request_id, generation, remaining}`. Unknown effects of that request were reconciled; when `remaining` is 0 it leaves `unresolved`. How effects are reconciled is defined in Phase 2. |

**No event ever carries reply text that the guards have not accepted** (D9).

## Delivery rules

- **Ordering.** `seq` is monotonic across the whole profile. `cursor` is opaque; in v0 it is the decimal `seq`. Gaps are
  normal, so the app never assumes events are contiguous.
- **Duplicates.** Events reach the app at least once, so the app deduplicates by `seq`.
- **Reconnect.** The app sends `hello`, then `events.subscribe` with `after` set to the last cursor it received.
- **Snapshot and tail.** A snapshot is complete through its `watermark`: every event with `seq` at or below it is
  already reflected. The app applies a snapshot, then only events above its watermark. While a snapshot is in flight,
  the app holds that conversation's events and replays the ones above the watermark when it arrives. A snapshot older
  than state the app has already applied is discarded, and so is the answer to a superseded snapshot request.
- **Reset.** `reset_required` means the interval since the app's cursor is unknown, never empty. The app's event
  cursor moves to `event_high`, every conversation projection is discarded, the conversation list is reloaded, and
  each open view fetches a fresh snapshot. Nothing from the old projections survives a reset.
- **Subscriptions are stream control, not commands.** The answer to `events.subscribe` is applied whenever it arrives,
  even after the request timed out, and before any event that follows it. A subscription is never re-sent as an
  unreceipted command: each connection makes exactly one new one.
- **Acting on a view.** The app sends a message, Steer or Stop for a conversation only while that conversation's
  projection is authoritative (its snapshot has arrived). While it loads, drafts are kept and nothing is routed.
- **A lost receipt.** If a `req` gets no `res` (a timeout or disconnect), the app re-sends the **same `id`** after
  reconnecting. It never invents a new one. The core answers a known `id` with its original result. Until then the
  outcome is unknown, which the app shows as "waiting for confirmation", never as a failure.
- **Core restart.** A new `core.instance_id` means a new incarnation. The app handshakes again and catches up from its
  cursor. Work interrupted by the crash is reported by the core as `request.interrupted`, never replayed.

## Command identity

- **Binding.** A command ID (`req.id`) is bound to the profile, the method and the canonical params (JSON with sorted
  keys). The same ID with the same method and params returns the original result. The same ID with a different method
  or params is refused with `id_conflict` and runs nothing.
- **Durability.** Receipts for commands that admit or change something (`submission.send`, `control.*`,
  `conversations.create`, `conversations.update`, `runtime.shutdown`) are durable and survive core restarts. Read
  methods (`status.get`, `*.list`, `conversation.snapshot`, `events.subscribe`) are not cached.
- **Expiry.** When a receipt's body is pruned, a tombstone of its binding stays for the profile's lifetime. Re-sending
  that ID returns `receipt_expired` with disposition `outcome_unknown`. An expired ID is never admitted as new.
- **The development fixture** keeps receipts in memory only, so it doesn't meet the durability rule across its own
  restarts. The real core (Phase 2) must.

## Errors

| `code` | Meaning |
|---|---|
| `bad_request` | Malformed or out-of-bounds parameters |
| `unauthorized` | The handshake hasn't completed, or the credential doesn't match |
| `incompatible` | The protocol or a required feature isn't supported |
| `not_found` | The entity doesn't exist |
| `stale_binding` | The expected revision, request or generation doesn't match. The command is refused and never retargeted. |
| `capability_unavailable` | The feature isn't available or qualified |
| `storage_unavailable` | Durable admission couldn't be established |
| `busy` | Temporarily refused; retry with the same `id` |
| `id_conflict` | The command ID is already bound to a different method or params. Nothing ran. |
| `receipt_expired` | The ID was used before and its receipt was pruned. Its outcome is unknown; it is never re-admitted. |
| `internal` | A bounded, scrubbed description of a core fault |

`disposition` uses the core-contracts vocabulary: `rejected`, `not_dispatched`, `accepted`, `outcome_unknown` and so on.

## Versions

Major `0` is pre-release, and any change may break compatibility. From `1.0`, a major mismatch is `incompatible`. Minor
features are negotiated through `features`.
