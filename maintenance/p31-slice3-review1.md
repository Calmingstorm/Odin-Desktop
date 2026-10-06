# P3.1 slice 3, PR #31 review round 1

Review: `/home/odin/reviews/desktop-pr31-review.md`, reviewed original source `43c4fff`.

## Integration and scope

- Merge `main` into the existing branch, not a rebase or force-push. The deleted `phase-2/controls-resume` branch
  is no longer the base. PR #31 targets `main`; no review PR merge or deployment is authorized.
- Keep both sides of all app conflicts: chat/tools/artifacts/controls plus settings/management, onboarding,
  accessibility and source-build lifecycle. Both real-core Vitest suites and the real renderer contract stay
  in the separate isolation gate; none leaks into the ordinary unit gate.
- No engine production edits, live configuration, real account, active-desktop input, service restart or
  `/opt/odin` changes. Dependency setup is confined to this checkout's `.venv` and `app/node_modules`.

## Review corrections

1. **Typed resume:** `continue` and `resume` are documented in the banner as resume triggers. Accepted late
   receipts clear optimistic bubbles even when the result references the original request/message IDs.
   Committed user/notice events and recovery snapshots also settle their matching submission IDs.
   Generation is taken from core `request.started`, not guessed from admission. Genuine failure notices stay
   visible, and unrelated notices never clear another submission.
2. **Committed failure notices:** provider failure must produce a durable request-bound notice and the rendered
   smoke must show that exact notice, not only a terminal outcome or a locally invented assistant message.
3. **Real provider configuration:** canned loopback generation uses revision-bound provider settings, write-only
   credential methods, and model adoption through the actual Broker/core. Only the external keyring is ephemeral.
   The obsolete test-only provider-config entry is removed; no replacement runner/client/settings owner is used.

## Gate boundaries

The smoke preserves the fresh, missing-vault management lane separately from the unlocked ephemeral-vault
provider-chat lane. The typed path's checkpoint is created by real request execution followed by interruption
of a harness-owned isolated core before Electron starts. No synthetic checkpoint rows or automatic-restart
bypass is used. All provider peers are canned loopback HTTP/SSE, not a live account.

File/save chooser selections are injected only in isolated main-process smoke; actual attachment/artifact
adapters execute. Native chooser UI/default-app launch/folder reveal, real vault unlock/durability, production
OAuth, packaged runtime and Orca/Wayland acceptance remain outside this integration gate.

## Qualification record

Final qualification must run `npm run check`, `npm run smoke`, `npm run test:real-core`, `npm run smoke:real-core`
and `npm run test:a11y` from a fresh checkout. Exact tested source, merge parent, counts, logs, JSON evidence,
screenshots, cleanup checks and any intervening failures are recorded below after execution.

Incremental checks are not fresh qualification: renderer-focused tests passed 93 cases; combined `check` passed
716 cases in 77 files; accessibility passed 15 cases including the updated Resume banner AX/axe checkpoint.
An early in-progress typecheck failed because a smoke helper accepted `unknown` params instead of the Broker's
`Record<string, unknown>` shape. It was fixed, not counted as a passing gate.

Additional development failures remain recorded, not silently replaced with passing reruns:

- Initial genuine provider configuration exposed real model-catalogue/profile validation requirements. The
  canned peer now serves catalogue and qualification HTTP requests; the real settings owner is unchanged.
- The first combined real gate passed 21/22 request contracts but failed the attachment publication wait and
  then hit the old 120-second wrapper limit before the settings/renderer suites could finish. The unchanged
  attachment case passed a targeted rerun. The merged gate now has a bounded 600-second budget.
- Smoke failed on inherited selector/text drift from main: accessible Attach/Close-search controls, the renamed
  message scroll container, retained aria-disabled EOF controls and the actual filename-specific save receipt.
  It also failed by comparing raw error Markdown with rendered text. Exact committed message IDs and
  request-bound publication waits now verify rendered error content rather than mislabeling guarded replies.
- HTTP 400 is the runner's committed guarded error reply, not a `notice`. That scenario remains. Separate real
  missing-provider execution explicitly verifies the committed `notice` in both fresh management and chat.
- A dedicated hold token separates the interrupted checkpoint from later Stop, so releasing resume cannot
  accidentally unhold the Stop scenario. No runtime behavior or control restriction was weakened.
- Intermediate attempts at expired/busy checkpoint failure had incorrect expected dispositions and were
  replaced by an existing real checkpoint's offline integrity corruption, exercising actual unreadable-state
  refusal. The corrected contract verifies one notice and no user message or new generation.

The final incremental smoke passed both lanes: 39 management checkpoints and 11 provider-chat checkpoints,
including typed generation-2 resume, ordinary continue, retained output, attachments/artifacts, real failure
notice, exact-request Stop/Steer, queue/search/reset and conversation lifecycle. Fresh gates still follow.
