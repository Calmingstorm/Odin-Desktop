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

## Final fresh qualification, 2026-10-06

Tested source: `46da834e915aae477f05186b3c8c3c0d9fa9ee53`. This is a true merge commit with original PR head
`43c4fff4f831bccc55350734758483b614973331` and main `0b7d596f7e870d06699722f151c4d9837c5433f1` as parents.
Main was rechecked after qualification and had not advanced. No rebase, force-push or review-PR merge.

Fresh clone: `/home/odin/desktop-pr31-review1-fresh`, created with `git clone --no-hardlinks`; clean before and
after all gates. Provisioned with `uv sync --frozen`, `npm ci --ignore-scripts` and explicit pinned Electron
installation, Node 22.23.3 and Python 3.12.3. No dependency/lockfile changes. The pinned npm tree reports
11 audit findings (10 high, 1 critical); this is not a dependency-security qualification or an audit-fix scope.

| Gate | Final result |
|---|---|
| `npm run check` | PASS: typecheck, 716 tests in 77 files, build |
| `npm run smoke` | PASS: isolated fixture Electron |
| `npm run test:real-core` | PASS: 38 tests in 3 files, then 6 onboarding tests; no skips |
| `npm run smoke:real-core` | PASS: 39 management + 11 provider-chat checkpoints; 4 retained-output pages |
| `npm run test:a11y` | PASS: 15 tests; zero unexpected, flaky or skipped cases |

All five commands ran sequentially, once, from the same fresh source from 04:41:14Z through 04:46:42Z.
The final gate sequence had no failures. Earlier development failures above remain recorded separately.

Real smoke evidence confirms:

- Typed `continue` completes generation 2 on request `r_1dec405c5a744337afb052abfe5e5246` with one original
  user message. With nothing resumable left, a second `continue` commits an ordinary new user message/request.
- Guarded reply, real tool details and 119,698 characters over four output pages; actual 700,000-byte multi-chunk
  attachment, posted-file download and decoded image.
- A committed `notice`, bound to the failed request, reads `No LLM provider available. Please try again later.`
  The HTTP-400 scenario separately retains the actual guarded error reply, not mislabeled as a notice.
- Exact-request Stop; Steer safe-boundary consumed receipt; queued follow-up; search/highlighted jump;
  context reset retaining transcript; rename/child/archive/unarchive/delete.
- Main's real settings/management, missing-keyring error/Retry, readiness and unavailable later-service views
  remain covered in the independent management lane. No fixture rows or falsely successful empty reads.

Evidence root: `/home/odin/desktop-pr31-review1-evidence/`. It contains the exact gate script, `gates.tsv`, source
and clean-status records, all five logs, `real-evidence.json`, `real-management-evidence.json`, `accessibility.json`,
fixture/chat/settings screenshots, and `artifact-sha256.txt`. Selected hashes are in the adjacent machine result.

Post-gate validation passed 3/3: fresh checkout clean, all five exit codes zero, no test executable/script from
the checkout retained. The initial broad process-scan predicate matched Odin's own command-supervision worker
because its argv contained the scan text. The corrected predicate checks executable/script positions and passed;
no process was killed to manufacture cleanup. Namespace/profile cleanup is also recorded by the gates.

The final evidence-only commit changes this document and the adjacent result JSON, not tested app/engine source.
No deploy, live-service or active-desktop change.
