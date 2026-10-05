# Phase 2 step 6A: qualified local service owners

This branch started on step 5 PR #21 at `982477643adaa7652a74199198110981fe2fdfa0`,
then rebased bottom-up onto its review-1 fixes at
`b3f533e1ce26b41f3b7176478e34dda78154cfb1` before final qualification.
It implements only the services in `/home/odin/reviews/desktop-step6a.md`. No request
delivery, background work, schedules, reports, native packaging or foreground computer
admission is claimed. D17 behavior is restored through retained managers, not a new
executor or privileged identity. D19 model-facing text is not rewritten here.

## Composition

`ManagementService.compose` attaches one profile-owned skills, MCP, computer management
and browser lifetime, plus workspace diagnostics and the retained catalog merge.
`CoreService.start` watches its parent before asynchronous qualification and publishes
named management methods only after startup settles. Parent loss cancels and settles
startup without opening a listener. Shutdown attempts every owner's cleanup even when
one fails, then reports cleanup uncertainty instead of fabricated success.

The existing authenticated IPC connection installs the genuine `OwnerContext`. Skills
and MCP text/configuration never generate one. Computer management uses a separate
owner/host-only `ManagementContext` bound to the current request task. It has no turn,
conversation, pixels, input or foreground grant. Controller-owned recovery checkpoints
retain bounded management authority; arbitrary child tasks do not inherit it.

## Services and part-B seams

- **Skills:** real retained-manager create/edit/delete, enable/disable, validate,
  schema publication, reload and profile-keyring configuration. The engine interpreter
  installs validated index dependencies through its declared, locked pip dependency.
  `get_tool_definitions` and `list_skills` expose qualified state; `skill_manager` is
  the later request-dispatch seam. `skills.test` is deliberately unadvertised until
  genuine request admission/delivery exists. Skills remain trusted in-process Python,
  not a sandbox, including owner-authored import-time effects.
- **MCP:** configured supervised startup, desired-state management, current-generation
  qualified tools, bounded publication and reconnect. Header/environment containers
  and credential-bearing endpoints live in the existing profile keyring. Public
  configuration contains no credential values. The retained `MCPToolOutcome` dispatch
  seam requires genuine current owner context; non-owner/background admission and
  delivery remain part B. Reconnect, reload and rollback never replay a tool call.
- **Browser:** packaging-owned `assets/browser` Chromium layouts only, never PATH,
  system browser, personal profile or configured operator CDP. Disabled startup launches
  nothing. Enabled startup qualifies headless disposable context/page creation and
  copied HTTP/WebSocket guards before assigning the executor owner. Its boot policy
  snapshot remains separate from saved restart-only settings. Packaging must provide
  the binary; stubbed lifecycle tests are not packaged Chromium qualification.
- **Computer:** status, exact-generation pause/stop/cancel/close, explicit recovery,
  release-only cleanup and activation/revocation over the retained controller/store.
  No foreground start/resume/observation/export/input. Readiness explicitly says
  `dispatch: none`, `input_supported: false`, `native_qualified: false`.
  Worker-only GI discovery never changes core search paths/environment or qualifies
  a native backend. The immutable original GI cases execute through a worker-placement
  adapter, with unchanged assertions and parameter identities.
- **Diagnostics:** existing `health.get` includes bounded local workspace collection
  from the actual executor resolver. Fixed argv, no shell/fetch/network, bounded output,
  entry/depth/time caps and single-flight timeout workers. Local refs do not prove
  remote freshness. No force-push governor or arbitrary caller path/command exists.
  Filesystem deadlines are cooperative between syscalls; Python cannot interrupt a
  stalled filesystem call. External Git worktree metadata is explicitly unsupported.
- **Catalog:** the existing merge order/collision rules are retained. Built-in readiness
  is rechecked even after a cached merge. MCP/skill definitions cannot shadow unavailable
  built-ins. Publishing schema never supplies execution authority.

## Settings and qualification boundaries

Computer activation uses the existing revisioned settings transaction via its named
owner. Revocation does not regain consent or resume work on rollback. Composite reload
stages MCP state and finishes reconciliation before provider/shared-config publication;
failure restores prepared owners without tool replay. Skill runtime timeout/URL state
follows the effective executor config, not saved pending-restart values. Browser and
native runtime configuration remain boot snapshots or explicit qualification refusals.

Temporary keyring adapters, inert pip/connection/Playwright/native primitives and benign
disposable Git fixtures are the test boundaries. Engine suites use only the isolated
PID namespace with throwaway HOME. Final gate evidence is recorded separately in
`maintenance/phase2-step6a-validation.md`. Exact maintenance records remain pending
Claude's independent review. No `/opt/odin`, live service, operator browser or active
desktop changes are authorized or performed.
