# Slice 1 capability disposition inventory

This is review data, not a UI implementation or a second config schema.

- `ui-v1-core-inventory.tsv`: every one of the 290 `schema_facts()` identifiers,
  including object maps, record containers and their recursively exposed members.
  Entry keys are deliberately absent, matching the registry's own identifiers.
- `ui-v1-write-owners.json`: explicit single editor/workflow owners, exceptional
  transactions and the 61-field Advanced allowlist (29 logical editor groups),
  with required search and category headings for the later Advanced UI.
- `ui-v1-management-inventory.json`: separate runtime management actions, app
  bridge actions and app-owned preferences, with source evidence and status.

The disposition names are `primary`, `more-options`, `advanced`,
`internal-or-legacy`, and `unsupported-on-desktop`. There is no default disposition,
prefix expansion, unclaimed Other bucket, or implicit Advanced membership.
The focused inventory tests consume these data directly and reject schema drift.

## Ownership and capability boundaries

The `editor` is a unique workflow identifier, not permission to render every
member as an independent scalar row. A record container and its visible members
share the same editor. Arbitrary map keys and record entry identifiers remain
runtime user data. Structured custom model profiles are Advanced; refreshed
OpenRouter catalogue profiles are internal and must never overwrite authored
profiles. The automatic agent allowlist includes its actual mixed string/record
shape and per-entry reasoning policy; `schema_facts()` exposes only that array,
so no invented `agents.auto_model_allowlist.model` schema path is listed.

Core metadata remains authoritative for values, enums, limits, revisions,
sensitivity and apply modes. Owners are verified against Desktop `_handler`,
not upstream web routes. Host enrollment and image follow-default intent use
their existing specialized transactions. Native computer configuration other
than `computer.enabled` is rejected by Desktop; availability, consent and
cleanup remain separate management capabilities.

The three global outbound webhook fields are unsupported on Desktop: although
`_handler` names `webhooks.outbound.save`, its actual contract edits targets only
and does not accept generic configuration changes. Naming a method is not proof
of a working write owner. Per-target enablement and scrubbing remain supported;
there is no advertised global switch or rate-limit control in this slice.

`primary` means a discoverable workflow, not always-expanded controls. Disabled
providers, browser and email retain Configure while disabled. More options holds
user-recognizable feature, model, privacy, cost, compatibility and safety choices.
Advanced holds numeric capacity and tuning, including history budgets, iteration
and queue limits, attachment bytes/preview characters, browser viewport/waits,
reflection pacing and retention. The explicit reviewer exceptions remain in More
options: Ollama context size, tool deadlines, MCP limits and session archive caps.
Transport retry/pooling, legacy aliases, owner-derived identities, paths and pure
diagnostic framing are internal for the field-specific reasons in the TSV.

## Review A corrections: A2 and A3

All **290 paths** remain explicit: **76 primary, 42 More options, 61 Advanced,
81 internal/legacy and 30 unsupported**. Relative to review A, 43 numeric tuning
paths moved from More options to Advanced, seven pure diagnostic paths moved from
More options to internal, and `browser.cdp_url` moved from primary to More options.
No runtime/UI behavior is changed by these data.

The review's explicit More options examples are retained: auxiliary enable/model;
image enable, host-model and image-model intent; all seven OpenRouter routing
fields (order, fallbacks, quantizations, sort, data collection, reasoning default
and model pins); `ollama.num_ctx`; `tools.tool_timeouts` and
`tools.command_timeout_seconds`; MCP publication/request limits; governor switches;
`tools.allow_host_tofu`; `email.tls_verify`; `browser.allow_private_targets`;
`observability.trajectory_user_content`; `turn_state.auto_resume`;
`agents.model_selection_hints` and `agents.thinking_mode`;
`tools.skill_allowed_urls`; and both session archive disk-use caps.

`observability.context_trace.*`, `observability.prompt_budget_accounting`,
`observability.max_user_content_chars`, `observability.max_tool_result_chars` and
`observability.loop_trace` are internal diagnostics, not ordinary user settings.
The trajectory user-content switch remains a real privacy choice. Browser's
More options contains `browser.cdp_url`: empty launches Desktop's own browser;
an existing CDP endpoint is optional compatibility setup, not a prerequisite.

The approximately eight-per-page target counts visible choices honestly, not just
collapsed sections. Logical groups are editor/workflows, not individual rows:

| Destination | More options paths | Logical groups | Disposition rationale |
|---|---:|---:|---|
| General | 0 | 0 | Advanced is a secondary destination, not another normal section. |
| Models and providers | 17 | 8 | Explicit multi-field exception; see below. |
| Personality | 0 | 0 | No secondary core settings. |
| Tools | 8 | 6 | Two deadlines, two streaming choices, mail TLS/directory policy and Browser CDP/private-target policy. |
| Skills | 1 | 1 | Allowed endpoint policy. |
| MCP servers | 5 | 2 | Two publication caps and per-server directory, allowlist and request deadline. |
| Hosts and access | 4 | 2 | Three governor switches and trust-on-first-use policy. |
| Work | 4 | 3 | Loop reflection, auto-resume and two outgoing privacy/verification choices. |
| Data and privacy | 3 | 2 | Two archive disk-use caps and trajectory user-content privacy. |

Models genuinely exceeds eight scalar paths. OpenRouter routing alone has seven
independent choices; auxiliary has two; image enable/intent has three; agent
thinking/hints has two; Ollama context, reasoning-history feedback and adaptive
compaction have one each. Their eight workflow groups are auxiliary, Ollama,
compatible policy, OpenRouter routing, conversation compaction, image enable,
image intent and agent policy. Present routing in its own provider-specific
Configure/More options group, not as seven always-expanded global settings.
Grouping does not claim 17 controls are eight fields, nor justify moving the
reviewer's explicit choices to Advanced or internal merely to meet a quota.

Advanced now exceeds 30 fields. Its future UI **requires search and category
headings**: Models and context, Tool execution, Hosts and access, Work and recovery,
and Data and retention. The requirement is explicit in the owner inventory and
tested; it is not a claim that search or any UI was implemented in this correction.
Each path still has a supported write owner and user-change reason, and Advanced
is an explicit allowlist, never a dump of schema leftovers. Normal pages must not
duplicate Advanced editors or render a mixed-disposition workflow's tuning leaves
merely because its policy editor also appears in More options.

## Secrets

Ordinary credential leaves use explicit `secrets.set` / `secrets.clear`.
Incoming webhook records use per-entry secret calls, never plaintext container
writes. MCP environment/header containers and credential-bearing endpoint URLs
use `mcp.save`'s keep/replace/remove transaction. Outbound target signing keys and
private endpoint URLs use `webhooks.outbound.save`'s transaction. These are not
generic `secrets.set` container-JSON APIs. Credentials have no readback editor.
Internal credentials such as account paths and audit signing identity have no
visible route. Open settings folder remains an expert support escape hatch only:
Exit, edit, relaunch; credentials stay in app-controlled secret transactions.

App preferences and planned geometry/setup dismissal are separate from core
fields. Planned preferences are explicitly not claims of implemented capability.
Management actions preserve destructive scope, confirmation, steering/cancellation
distinctions, native qualification and unknown-effect/quarantine boundaries.

## Management versus bridge reachability

Inventorying an existing core method is not proof that the current preload
publishes it. The two exhaustive action arrays deliberately remain separate.
For example, `webhooks.outbound.*` and `integrations.email.get` are composed core
management methods but have no named bridge entry today. Their supported core
capability is retained in the inventory, not fabricated as an existing app call.
Converting those workflows later requires a reviewed named IPC/schema/preload
addition. Similarly, a visible field describes its intended single workflow;
this slice does not claim that every such workflow is already implemented.

The tests compare the actual composed `METHODS` plus direct `CAPABILITIES` with
management entries, the actual preload keys and generated tables with app
entries, and real write/read owners. They mutate inventory copies to prove that
new fields, invalid paths, duplicate editor ownership, unsupported methods,
wrong owner routes, generic secret-container routes and new/unclassified bridge
methods fail. Native unsupported writes are exercised against a disposable
SettingsService; the outbound global limitation is exercised against its real
target-only owner contract. App preferences are checked from the TypeScript
compiler AST of the actual persisted state/defaults, not prose assertions.
