# Slice 1 capability disposition inventory

This is review data, not a UI implementation or a second config schema.

- `ui-v1-core-inventory.tsv`: every one of the 290 `schema_facts()` identifiers,
  including object maps, record containers and their recursively exposed members.
  Entry keys are deliberately absent, matching the registry's own identifiers.
- `ui-v1-write-owners.json`: explicit single editor/workflow owners, exceptional
  transactions and the 18-field Advanced allowlist (10 logical editor groups).
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
supported capacity, attachment, learning, safety and privacy policies rather than
silently declaring rare capabilities internal. Advanced is a small explicit list:
custom protocol/profile/context corrections, host safety overrides, queue ceilings,
shell, log detail and the hard agent iteration ceiling. Transport retry/pooling,
legacy aliases, owner-derived identities, paths and diagnostic implementation
details are internal for the field-specific reasons in the TSV.

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
