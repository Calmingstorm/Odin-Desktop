# Phase 2 step 5 validation

## Artifact and base

Runtime, provisioning, settings, keyring credentials and named management services are implemented in one
step-5 branch. It started at step 1 `d1098b3025643bb6ecb0b6686fc0a181df447672`, then rebased onto
`main@8ae8ebcc` after PR #14 merged. Steps 2–4 and step 6 are not implemented or claimed by this branch.

The final executable source and accounting gate target is `2f7286aa8b3f6b948f0d0fbc6bd3ad9058baa392`.
This validation document is added afterward without changing executable source, dependencies or tests.

## Final fresh-checkout gates

- Checkout: `/home/odin/desktop-phase2-step5/qualification-corrected-parent/final`.
- `umask 002` was set before `git worktree add`; the parent and checkout were both verified mode `0775`.
- A new copied-interpreter Python 3.12 venv was created there and populated with locked dev extras.
- All suites ran through the isolated PID/mount namespace launcher, with throwaway HOME/XDG roots and no
  active desktop/session environment. Credential tests use temporary keyring adapters. Composed management
  tests explicitly forbid unstubbed HTTP session creation.
- Exact byte-drift report: **zero errors**, review pending. No source archive, original corpus or safety
  manifest was changed to manufacture acceptance.
- Lint gate: **zero new findings**, seven inherited findings.
- Phase-2 ownership checker: passed. Its behavior suite: **30 passed** separately.
- Qualification: **30/30 groups passed**, **13,679 passing executions**, **2 skipped**, **0 failures/errors**.
- Step-5 management group: **256 passed**. Core transport group: **227 passed**.
- Existing mock-coroutine warnings remain in inherited agent-lifecycle/tool-timeout cases; they are not new
  acceptance exclusions. The approved original-corpus selections and existing skip boundaries remain intact.

Raw artifacts:

- `/home/odin/desktop-phase2-step5/corrected-final-gates.log`
- `/home/odin/desktop-phase2-step5/corrected-environment.log`
- `qualification-corrected-parent/final/.test-state/qualification-result.json`
- `qualification-corrected-parent/final/.test-state/qualification-0.xml` through `qualification-29.xml`

## Earlier failure and correction

The first fresh-checkout full run against `ac2a3bb7` completed every group: **29/30 groups passed**, with
**13,675 passes**, **2 skips**, **3 failures**, no errors. Three transport-retention cases exposed step-1
raw-JSON identities being compared as new keyed identities. This was an actual compatibility bug, not a
reason to drop those assertions.

The correction adds a stored `hmac-v1` scheme tag and compares legacy identities with their original raw
semantics. A request-shaped digest envelope cannot impersonate the keyed scheme. Existing refusals, pending
outcomes and expired tombstones remain replayable without effects. Targeted confirmation was **47 passed**.
Exact accounting was refreshed, then all gates were rerun from a second fresh group-writable checkout.

The failed run remains preserved at `/home/odin/desktop-phase2-step5/final-gates.log` and its original XML
directory. The final green result does not relabel the earlier run.

## Behavior exercised

- Authenticated protocol dispatch, real persisted settings/schema/image intent, stale revision refusals,
  saved/effective distinctions, dedicated prepared-owner apply/rollback and configuration reload.
- Profile-namespaced Secret Service adapter with locked/read/write/clear failures and no credential-file
  fallback. Stable private keyed command identities, exact replay across real core restart and no secret
  values in config, responses, events or receipt bindings.
- Fresh independent local/default-host state, shallow app roots, harmless real local command execution,
  explicit/omitted targets, missing-remote refusal and HTTP probe's local fallback. Registry enrollment,
  trust, candidate testing, leased-generation draining and revocation retain Odin's controls.
- Retained provider clients/pools and generation handling with stubbed qualification/network boundaries;
  successful device login adopts a Codex client, and last-account removal retires it. Polling is bounded
  per request and respects interval/expiry. No real account login was performed.
- Shared executor memory/lists, real knowledge SQLite/FTS/version behavior, read-only relocated signed and
  plain audit readers, real health observations, unknown usage labels and context reload.
- Retained outbound validation/dispatcher behavior and temporary-keyring signing/credential-bearing URLs.
  One narrow retained persistence fix attaches an absent outbound target list before mutating it.

## Contract differences and boundaries

- Pinned Odin's fresh knowledge-ingest success is `{source, chunks}`, not the fixture's extra
  `status`/`outcome` fields. Other duplicate/conflict outcomes retain the upstream response helper.
- Memory values are stringified as the pinned route does, rather than preserved as arbitrary fixture JSON.
- Outbound deletion returns `{status: "deleted", webhook_id}`, not `id`.
- Existing list storage does not persist every later modification timestamp. List `updated_at` is the
  recorded metadata when present, otherwise the latest item `added_at`, never invented wall time.
- `knowledge.import` and read-only `integrations.email.get` are named upstream-derived extensions, not a
  generic passthrough. Inbound webhooks remain step 7.
- Computer activation, skills/MCP/schedules and browser startup are step 6. Their absent owners are not
  falsely advertised as ready. Skills reload reports unavailable until that owner is composed.
- Provider constructors do not unlock keyrings or probe endpoints. New-request admission must call the
  shared owner's explicit readiness seam; this branch does not claim a running turn engine.
- Usage/context figures without an actual measurement source stay unknown. Provider/native SSH/real
  Secret Service qualification was not performed; credential and network behavior was tested through
  controlled adapters. Native packaging/active-desktop qualification remains a later phase.
- No changes or deployment to `/opt/odin`, live configuration/data, services or the active desktop.
  No merge or independent approval is claimed. Claude's review remains required.
