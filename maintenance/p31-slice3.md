# P3.1 slice 3: chat on the real core

Stacked on `phase-2/controls-resume` at
`b8d7191024701d0af41b03ec7bbd9a7a7d6762d8`. No rebase or force push; PR target is that branch.
The engine is unchanged by this slice. No deployment, active-desktop input, live-service change, real account,
credential import or new approval was performed.

## Concrete integration corrections

- Derive queued message identity from the real committed user message, including event reordering.
- Retain tool cards for terminal requests without an assistant reply and expose available cards in search jumps.
- Keep settled Stop/Steer receipts visible after the running card disappears.
- Deduplicate binary references repeated across retained-output pages; do not fetch past EOF.
- Fence stale older-history and collapsed/reopened tool-detail reads.
- Describe Resume as an attempt against preserved progress, not a guarantee that a checkpoint exists.
- Match the core's positive-generation control contract.
- Best-effort cancel a begun attachment when chunk transport throws, preserving the original error.

All reply text remains committed guarded text (D9). No owner execution restriction, added confirmation,
prompt-behavior change, generic renderer RPC or replacement engine runner was introduced (D17/D19).

## Gate model and boundaries

The canned loopback provider serves real OpenAI-compatible SSE and scripted tool calls, hold/release and HTTP
failure. Actual `OpenAICompatibleClient`, guarded execution, tools, journals, attachment processing, results and
generation-bound controls execute. The test-only provider entry uses the existing `config_provider` composition
seam because the steps 2–4 CLI does not load provider settings. It does not replace the provider client or runner.

The existing real-core runner verifies its separate PID namespace, unprivileged UID, disposable HOME/XDG and
exact source import. Electron runs only on isolated Xvfb. Native chooser selections are injected under that
boundary, then the actual attachment/artifact adapters execute. No native chooser/default-app/Orca/portal,
packaged-runtime, notification acceptance or active-workstation qualification is claimed.

The contract gate proves a genuine interrupted checkpoint resumes the **same request**, generation 2, with
one original user message. Its SIGKILL targets only the harness-owned isolated core. It also proves Stop/Steer,
safe-boundary consumption, queued follow-up, D9 before publication, immutable receipts, CRUD/child inheritance,
reset preserving transcript but clearing model context, search/jump, watermark catch-up, actual retained-output
paging, posted text/PNG bytes and attachment commit/adoption/cancel.

## Honest outstanding handoffs

- At the inspected #23 base, typed `continue` is ordinary chat, not a control. The Resume banner says so.
- #22's latest failure-notice fixes are not yet in #23. Provider failure is genuinely terminal failed; missing
  committed failure notices are identified in smoke evidence, not invented or called qualified.
- Work/management/settings/report methods not served by this stack remain unavailable. This slice does not
  claim Phase 2 exit, full P3.1, packaging or native acceptance.

Merge updated `phase-2/controls-resume` into this branch when it advances and rerun all four gates. No rebase,
force push or merge of the review PR is authorized.

## Qualification

Final qualification uses a fresh clone with Node 22, Python 3.12 from `uv sync --frozen`,
`npm ci --ignore-scripts` and explicitly acquired pinned Electron. Required commands are `npm run check`,
`npm run smoke`, `npm run test:real-core`, and `npm run smoke:real-core`.
Exact SHA, commands, results, logs, screenshot/evidence and artifact hashes are recorded with the final gate
evidence outside the disposable test profiles and summarized in the PR.

Development corrections before the fresh gate: an in-progress smoke file replacement caused a temporary missing
module typecheck failure; a real renderer contract initially matched the ordinary Vitest include and was moved
behind the isolation-only gate; a retained-output test initially used a small/specialized result without a cursor
and was replaced with actual generic retained evidence. None is counted as a successful gate.
