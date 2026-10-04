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

## Methods (minor 1)

| Method | Params | Result |
|---|---|---|
| `status.get` | `{}` | `{phase, core_instance_id, version, capabilities}`. Phase is one of `starting`, `ready`, `degraded`, `quiescing`. |
| `events.subscribe` | `{after: cursor or null}` | `{event_high, reset_required}`. If `after` is unknown or expired, `reset_required` is true: the app reloads state with the list methods, then subscribes from `event_high`. |
| `conversations.list` | `{}` | `{items: [{id, title, rev, parent_id, updated_at, unread, archived}]}` |
| `conversations.create` | `{title?, parent_id?}` | `{conversation}`. A `parent_id` makes a child seeded from the parent's current context. |
| `conversations.update` | `{id, expected_rev, title?, archived?}` | `{conversation}`, or the error `stale_binding` if `expected_rev` doesn't match |
| `messages.list` | `{conversation_id, before?, limit}` | `{items, has_more}`. Committed messages only, newest last. `limit` is at most 100. |
| `submission.send` | `{client_submission_id, conversation_id, text}` | `{disposition, request_id?, message_id?}`, where disposition is `accepted` or `rejected`. Sending the same `client_submission_id` again returns the original answer and never admits a second request. |
| `control.stop` | `{control_command_id, conversation_id, request_id, generation}` | `{disposition}`: `requested`, `not_running` or `stale_binding`. Settlement arrives as events. |
| `control.steer` | `{control_command_id, conversation_id, request_id, generation, text}` | `{disposition, sequence?}`: `queued`, `closed` or `stale_binding` |
| `runtime.shutdown` | `{reason}` | `{disposition: "accepted"}`. The core then stops admitting work, settles or cancels it, persists, and exits. Pending or unknown work is reported as events, and again at the next start. |

Attachments, artifacts, settings, schedules and the rest of the management surface arrive in later minors.

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
| `control.receipt` | `{control_command_id, kind, disposition}`. `kind` is `stop` or `steer`. `disposition` is one of `requested`, `confirmed`, `queued`, `consumed`, `closed`, `stale_binding`. |

**No event ever carries reply text that the guards have not accepted** (D9).

## Delivery rules

- **Ordering.** `seq` is monotonic across the whole profile. `cursor` is opaque; in v0 it is the decimal `seq`. Gaps are
  normal, so the app never assumes events are contiguous.
- **Duplicates.** Events reach the app at least once, so the app deduplicates by `seq`.
- **Reconnect.** The app sends `hello`, then `events.subscribe` with `after` set to the last cursor it applied.
- **A lost receipt.** If a `req` gets no `res` (a timeout or disconnect), the app re-sends the **same `id`** after
  reconnecting. It never invents a new one. The core answers a known `id` with its original result.
- **Core restart.** A new `core.instance_id` means a new incarnation. The app handshakes again and catches up from its
  cursor. Work interrupted by the crash is reported by the core as `request.interrupted`, never replayed.

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
| `internal` | A bounded, scrubbed description of a core fault |

`disposition` uses the core-contracts vocabulary: `rejected`, `not_dispatched`, `accepted`, `outcome_unknown` and so on.

## Versions

Major `0` is pre-release, and any change may break compatibility. From `1.0`, a major mismatch is `incompatible`. Minor
features are negotiated through `features`.
