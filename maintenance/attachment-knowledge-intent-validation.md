# Attachment knowledge intent fix

Validated 2026-10-06 on `fix/attachment-knowledge-intent`, branched from accepted
main. Main advanced during setup, so the uncommitted branch was fast-forwarded to
`288ce7b4bec4774885dde6c0d76aa38fff4f7744` before final tests. No PR28 code or
dependency is included. Executable candidate:
`fb2c506cac6469234196126161a6c64aedab5797`.

## Behavior

- Remove the nonexistent `engine.ingest_attachment` lookup and eager invocation.
- Process each admitted stream in adoption order. A checked `add_to_knowledge`
  flag selects the existing `AttachmentIntent.INGEST_KNOWLEDGE`; unchecked streams
  use the existing inference from the original message content.
- The unchanged Odin attachment processor supplies its existing model-facing
  note byte for byte. No new prompt text or automatic knowledge write is added.
  Actual ingestion still belongs to the model's `ingest_document` tool.
- Preserve text separators, image-block order, and the single retained-source
  manifest. Rebase each retained full-content index across per-stream results,
  so two retained files cannot both claim source index zero.
- Fresh-request-only processing remains behind the existing resume guard.
  Original request identity, reset fencing, guarded delivery, failure notices,
  cancellation and shutdown logic are unchanged.

## Final gates

| Gate | Result |
| --- | --- |
| Request and attachment suites | 158 passed, no skips or failures |
| New real IPC intent cases | 5 passed, included in the 158 and full qualification |
| `npm run check` | Typecheck/build passed; 737 tests in 76 files |
| `npm run test:real-core` | 22 contracts plus 6 actual Electron onboarding E2E passed |
| Exact drift | `errors: []`, byte-drift-clean-review-pending |
| Lint | 7 inherited findings, zero new findings |
| Phase 2 ownership/suite-map gates | Passed; static accounting, not feature qualification |
| Fresh full classified qualification | 30/30 groups, 14,436 passed, 2 inherited skips, zero failures/errors |
| Diff/checkout checks | Clean |

The requested full qualification ran once, at the end, from a fresh detached
checkout of the candidate under the `2775` group-writable
`/home/odin/desktop-attachment-knowledge-20261006/qualification-parent/` folder.
Each group used the accepted restricted PID/mount isolation launcher, unprivileged
UID 1003, and sanitized throwaway HOME/XDG without live display/session sockets.
Locked dependencies were installed into this repository's `.venv` and
`app/node_modules`, not the live installation. The real-core app gates used their
accepted namespace runner; graphical onboarding used isolated Xvfb.

The two inherited skips are the opt-in Hyprland native wire-timing test, which
requires `ODIN_HYPRLAND_INPUT_TEST_BINARY`, and the missing-Playwright import path,
which cannot execute when the locked Playwright dependency is installed.
Three inherited warnings appeared: an unawaited mock in agent lifecycle, an
unawaited slow-handler fixture in tool timeouts, and subprocess-transport cleanup
after a closed event loop in containment. They were not hidden or waived into
new claims. npm reported inherited locked audit findings: 10 high, 1 critical.

## Evidence and limitations

The Python tests drive real uploads, submission admission, retained runner,
captured model input and guarded durable reply. They cover mixed checked/unchecked
text files, all-unchecked current-task behavior, all-unchecked explicit textual
ingestion, attachment-only submissions, and retained full-source ordering.

The app contract drives the actual Broker and AttachmentManager through a real
uploaded file. A loopback deterministic Ollama-protocol service is only the model
boundary. It observes the exact ingestion note and proves a committed assistant
reply, `request.completed`, completed snapshot and absence of `request.failed`.
It does not claim actual knowledge ingestion or a production model connection.
Existing non-text handlers' intent wording remains unchanged; this patch does
not invent ingestion notes for images, PDFs or archives.

A separate read-only technical inspection found no blocker in the production
intent/aggregation/lifecycle change. Claude's independent PR review remains
required; ledger entries are pending, not self-approved.

Initial development failures are retained outside Git: the new Python helper
first used the wrong upload receipt shape; the app synthetic compatible endpoint
did not satisfy provider qualification. The final app contract uses the simpler
real Ollama client and harmless loopback protocol. Its first assertion assumed one
tool-capable model call, although actual runtime setup can also issue such a call;
the final assertion checks exact attachment content in the captured inputs, while
durable request/reply assertions remain strict. No production gate was disabled.

External evidence directory:
`/home/odin/desktop-attachment-knowledge-20261006/`.

```text
f0594d864600d805f17bdee1a42a14a7542dbf4b7353646a211fd46e8719a217  request-attachments.log
7b040a41bcb5db267327b52620a5d3ec77cd82b9d972b38a91f72437d9de584d  app-final.log
6d3c743cd3009d9c2d8f1cef26c3953b28fd61b5c9054b8e9fae00a101de4a0d  full-qualification.log
29db1670e9a7a15757dfc8be1dcb31c3ab96ebadc5fd50a40a5d5988c033bd1e  qualification-parent/fresh/.test-state/qualification-result.json
```

No upstream Odin change, PR merge, deployment, service restart, production
credential/account or active-desktop interaction. No attribution trailers.
