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

## Methods (minor 1 and 2)

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

## Methods (minor 3): the v1 interface surface

Minor 3 adds what the app's v1 interface needs ([`chat-experience.md`](chat-experience.md), v1 column). Everything
Odin can do today stays reachable (D2, D17). The app is a display and control surface for the same engine, never a
second policy layer.

### Conventions

- **Names** are `<domain>.<verb>`. A method that changes nothing (listing, getting, searching, reading, paging,
  validating, checking status) is a read and is answered fresh. Every other method is a command and follows **Command
  identity** (durable receipt, `id_conflict`, `receipt_expired`), including `skills.test` and `codex.login.poll`,
  which can have effects. Upload chunks are the one exception: `attachments.chunk` is idempotent by offset and keeps
  no durable receipt.
- **"Odin shape"** means the same request and result fields as the named route of Odin v4.13.0's web API. The core
  adapts those handlers rather than inventing a parallel model, so the app and Odin stay at parity. A field that only
  made sense for Discord or for multiple users is omitted.
- **Revisions.** A mutation of a revisioned record takes `expected_rev`. A mismatch is `stale_binding`, and nothing is
  applied.
- **Secrets are write-only.** No result, event or log ever carries a secret value. Reads show `{set: true|false}`.
- **Bytes move in bounded chunks** of at most `limits.chunk_bytes` (from `status.get`), base64-encoded, so a frame
  never exceeds `max_frame`.
- **Paths never come from the window.** File content reaches the core only through the upload methods below. The app's
  main process reads only files the user picked or dropped.

### Conversations

| Method | Params | Result |
|---|---|---|
| `conversations.create` | `{title?, parent_id?, from_message_id?}` | `{conversation}`. With `parent_id`, a child seeded from the parent's context through `from_message_id` (default: its latest message), and labeled as inherited. |
| `conversations.delete` | `{id, expected_rev}` | `{disposition: "deleted"}`, or `busy` while a request in it is running or queued (stop it first). The visible transcript and its artifacts go; admitted-ID tombstones stay. |
| `conversations.reset_context` | `{id, expected_rev}` | `{conversation}`. Odin's model context restarts; the visible transcript stays. A `notice` message records it. |
| `conversations.mark_read` | `{id, through_message_id}` | `{conversation}` with its new `unread` |

### Search and jump

| Method | Params | Result |
|---|---|---|
| `search.query` | `{query, conversation_id?, limit (max 50), cursor?}` | `{hits: [{conversation_id, message_id, role, snippet, created_at}], next_cursor?, watermark}`. The visible transcript and artifact names, deletion-aware. A malformed query is `bad_request`, never an empty result. |
| `messages.around` | `{conversation_id, message_id, before (max 50), after (max 50)}` | `{items, has_before, has_after}`, newest last |

### Attachments

| Method | Params | Result |
|---|---|---|
| `attachments.begin` | `{client_attachment_id, conversation_id, name, size, mime}` | `{upload_id, chunk_bytes, expires_at}`, or `too_large` / `unsupported_type` before any byte moves |
| `attachments.chunk` | `{upload_id, offset, data_b64}` | `{received}` (total bytes so far). Chunks arrive in order; a repeated `offset` is idempotent. |
| `attachments.commit` | `{upload_id, sha256}` | `{attachment: {ref, name, mime, size, preview_ref?}}`. A digest mismatch is `bad_request`, and nothing is kept. |
| `attachments.cancel` | `{upload_id}` | `{disposition: "cancelled"}` |

`submission.send` gains `attachments: [{ref, add_to_knowledge}]`, and its `text` may be empty when attachments are
present (as on Discord). Ingesting into knowledge happens only when the user chose it for that attachment; it is never
automatic. The committed user message lists them as
`attachments: [{ref, name, mime, size}]`.

### Results: artifacts and reports

Messages gain `artifacts: [{ref, name, mime, size, kind, available}]`, where `kind` is `image`, `file` or `report`.

| Method | Params | Result |
|---|---|---|
| `artifacts.read` | `{ref, offset, length (max chunk_bytes)}` | `{data_b64, size, eof}`, or `not_found` once deleted or expired |
| `reports.page` | `{report_id, page}` | `{page, pages, text}`. Paging reads the stored result and never re-runs the check. Re-running is the separate command `schedules.run`. |

The app never executes artifact content (no HTML or SVG rendering); it shows images and offers files to open or save.

### Tool details

| Method | Params | Result |
|---|---|---|
| `tool.detail` | `{request_id, invocation_id}` | `{tool, target?, arguments, previews: [{label, text, truncated}], output: {cursor?, expires_at?}}`. Arguments are scrubbed; previews are labeled as previews. |
| `tool.output` | `{cursor, limit}` | `{text, next_cursor?, eof, expires_at}`. Retained output, fetched without re-running anything (Odin's `get_tool_output` contract). `limit` is in characters, at most 65,536. Once the output is no longer kept, the error is `expired`. |

### Running work and resume

| Method | Params | Result |
|---|---|---|
| `work.list` | `{kind?, conversation_id?}` | `{items: [{kind, id, title, state, conversation_id?, request_id?, started_at?, detail, actions}]}`. `kind` is `agent`, `task`, `loop`, `process`, `schedule` or `workflow`. `actions` lists the controls Odin offers for that item now, so the app never guesses them. |
| `work.control` | `{control_command_id, kind, id, action}` | `{disposition}`. `action` is one of the item's `actions`: `stop`, `cancel`, `restart`, `pause`, `resume` or `run_now`. `disposition` is `requested` (settled later as `work.updated`), `done`, or `not_available` when the item no longer offers that action. |
| `control.resume` | `{control_command_id, conversation_id, request_id, generation}` | `{disposition: "admitted" or "rejected", reason?}`. Guarded resume binds the exact preserved request: one whose latest outcome is `interrupted` or `suspended`. Unknown effects reject it, and so does other work running in the conversation. Admitted work starts again as that request with a new `generation`. |

### Status, usage and reload

| Method | Params | Result |
|---|---|---|
| `status.get` | `{}` | Minor 1's fields plus `model: {main, effort, provider}`, `providers: [{name, health}]`, `limits: {chunk_bytes, attachment_bytes, attachments_per_turn}` and `summary`, the text Odin's `/status` shows |
| `usage.get` | `{period}` (`session`, `day` or `week`) | `{period, tokens, context: {used, budget}, quota: [{account, window, used_percent, resets_at}], summary}`. Every number is `{value, kind}`: `kind` is `measured`, `estimated` or `unknown`, and `value` is null when unknown, never an invented number. `quota` lists the account in use first. `summary` is the text Odin's `/usage` shows. |
| `runtime.reload` | `{scope}` (`skills`, `config` or `context`) | `{disposition, summary}`. With `context`, it is Odin's `/reload`: reload the context files and show what is in context. |

### Notifications

The core emits `notification.intent` events; the app decides how to show them from its own settings (previews on by
default, D13; mute; quiet hours). `notifications.ack` `{dedupe_key, outcome}` (`shown`, `suppressed` or `failed`)
records what happened. An outcome of `shown` means the OS accepted it, not that anyone saw it.

### Settings and secrets

| Method | Params | Result |
|---|---|---|
| `settings.schema` | `{}` | `{rev, sections: [{id, title, leaves: [{path, type, title, description, default, value, enum?, min?, max?, apply, sensitive}]}]}`. `apply` is `live` or `restart` (Odin's apply registry). A sensitive leaf's `value` is `{set}`. |
| `settings.set` | `{expected_rev, changes: [{path, value} or {path, delete: true}]}` | `{rev, restart_required, applied}`. Partial: only the submitted leaves change. Validation errors name the leaf, and nothing is applied. |
| `secrets.set` | `{path, value}` | `{set: true}`. The value is stored in the profile's keyring and never echoed. |
| `secrets.clear` | `{path}` | `{set: false}` |

### Management domains

Each method has the Odin shape of the listed route.

| Domain | Methods | Odin shape |
|---|---|---|
| Codex accounts | `codex.accounts.list`, `codex.accounts.activate`, `codex.accounts.remove`, `codex.accounts.label`, `codex.login.begin`, `codex.login.poll` | `GET /api/codex/status`, `POST /api/codex/account/{index}/activate`, `DELETE /api/codex/account/{index}`, `PUT /api/codex/account/{index}/label`, `POST /api/codex/device-code`, `POST /api/codex/device-poll` |
| Models | `models.main.set`, `models.agents.get`, `models.agents.set` | `PUT /api/llm/main-model`, `GET` / `PUT /api/agents/model` |
| Personality | `personality.get`, `personality.set`, `personality.presets.save`, `personality.presets.delete` | `/api/personality`, `/api/personality/presets` |
| Tools | `tools.list`, `tools.set_enabled`, `tools.timeouts.get`, `tools.timeouts.set` | `GET /api/tools/builtins`, `POST /api/tools/builtins/{name}/enabled`, `/api/tools/timeouts` |
| Skills | `skills.list`, `skills.get`, `skills.save`, `skills.validate`, `skills.test`, `skills.set_enabled`, `skills.delete`, `skills.config.get`, `skills.config.set` | `/api/skills` and its sub-routes |
| MCP servers | `mcp.list`, `mcp.status`, `mcp.save`, `mcp.set_enabled`, `mcp.delete`, `mcp.reconnect`, `mcp.refresh_tools`, `mcp.tools` | `/api/mcp/*` |
| Hosts and trust | `hosts.list`, `hosts.prepare`, `hosts.test`, `hosts.commit`, `hosts.set_enabled`, `hosts.references`, `hosts.delete`, `hosts.public_key` | `/api/hosts`, `/api/hosts/candidates`, `/candidates/{token}/test` and `/commit`, `/{alias}/references` and the rest |
| Schedules | `schedules.list`, `schedules.save`, `schedules.delete`, `schedules.run`, `schedules.reset_failures`, `schedules.history`, `schedules.validate_cron` | `/api/schedules/*` |
| Memory | `memory.list`, `memory.get`, `memory.set`, `memory.delete`, `memory.bulk_delete` | `/api/memory/*` |
| Named lists | `lists.list` `{}` → `{items: [{name, count, updated_at}]}`; `lists.get` `{name}` → `{name, items}`; `lists.delete` `{name}` | No Odin route: the core reads and writes the same store as Odin's `manage_list` tool |
| Knowledge | `knowledge.list`, `knowledge.search`, `knowledge.ingest`, `knowledge.reingest`, `knowledge.delete`, `knowledge.versions`, `knowledge.restore` | `/api/knowledge/*` |
| Records | `audit.query`, `audit.verify`, `usage.get`, `health.get`, `logs.search`, `turn_state.list`, `computer.status`, `computer.reconcile` | `/api/audit*`, `/api/usage*`, `/api/health/components`, `/api/logs/search`, `/api/turn-state/*`, `/api/computer/*` |

### New events and errors

| Event | Payload |
|---|---|
| `conversation.deleted` | `{conversation_id}` |
| `conversation.context_reset` | `{conversation_id, message_id}` (the recording notice) |
| `artifact.unavailable` | `{conversation_id, message_id, ref, reason}` |
| `work.updated` | `{kind, id, state, conversation_id?}` |
| `notification.intent` | `{conversation_id, message_id, category, preview, dedupe_key}`. `preview` is scrubbed. |
| `settings.changed` | `{rev, paths, restart_required}` |

| Error | Meaning |
|---|---|
| `too_large` | Over a size limit. The limit is in `status.get` `limits`. |
| `unsupported_type` | The core does not accept this type for this use |
| `expired` | An upload, cursor or login code passed its expiry |

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
