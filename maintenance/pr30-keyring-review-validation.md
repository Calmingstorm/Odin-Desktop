# PR #30 P2: prompt-free background keyring access and explicit Retry

Validated 2026-10-05 after the PR #27/main merges, on `app/p32-first-run`
based on `3bdf4579515f8d662e2673cb58b80295b00405af`. No rebase, merge to
main, deployment, live service change, active desktop interaction or production
credential was performed. Commits carry no attribution trailers.

## Contract and implementation

- The production secret adapter uses SecretStorage directly against the existing
  default collection. It checks collection/item lock state and never enters
  Keyring's automatic unlock path. Missing collections are not created. A relock
  raises the existing sanitized `keyring_unavailable` failure, never a prompt.
- Create/delete wire operations refuse returned prompt objects rather than
  executing them. Profile namespace, legacy keyring attribute names and labels
  remain compatible; there is still no credential-file fallback.
- Every live credential boundary runs off the event loop: startup hydration,
  readiness/status, schema, secret set/clear/rollback, provider preparation,
  Codex accounts and OAuth refresh persistence, model discovery and integrations.
  Transactional workers settle before cancellation releases their domain gate.
- Only explicit owner Retry sends the named strict-empty `secrets.unlock` command
  through `secretsUnlock()` in the sandboxed preload. Native unlock has a
  **10-second caller deadline**. Its independent daemon receiver remains pending
  until completion, suppressing duplicate prompts in this core process.
- Durable command admission precedes the prompt. Only its wait releases core
  serialization. Hydration, refresh of an already-initialized Codex pool and final
  receipt publication reacquire serialization. Timeout retains an unknown
  outcome; the same command ID never prompts again.
- Only this named prompt request is dispatched concurrently on an authenticated
  IPC connection. Ping and ordinary methods remain responsive on the app's
  **same socket**; ordinary requests retain their ordered dispatch path.
- Success rehydrates without replaying credential writes or falsely claiming
  provider-client adoption. Hydration preserves composed nested config/email/tool
  references. Late native completion does not itself publish configuration.
- Startup status is committed before exposing the listener, preserving the
  welcome/catch-up high watermark after status became asynchronous.

## Behavioral regression coverage

The fake Secret Service collection records unlock calls and rejects event-loop
access. Tests prove locked startup/schema/status produce no unlock; explicit
Retry performs one unlock and hydrates; command replay does not unlock again;
never-answer prompts time out without blocking same-socket ping/status/hosts;
core close and an actual `asyncio.run` subprocess exit do not wait for a pending
unlock receiver. Additional coverage includes relock races, refused write/delete
prompts, nested-reference preservation, late completion without worker
publication, repeated cancellation during serial reacquisition and generation-
fenced Codex pool refresh.

Domain tests exercise actual provider/account/integration/model owners, record
off-loop vault access, and hold writes across cancellation to prove durable
save/adoption/rollback ordering. App tests prove strict named IPC authority,
no prompt on mount/background refresh, one unlock for held Retry, failure retry
and core-incarnation fencing. The actual Electron locked-keyring scenario now
recovers through the rendered Retry itself, with exactly one recorded unlock,
rather than making the fake keyring healthy before clicking.

## Final gates

All five requested app gates were repeated on the final lint-clean source.
`test:real-core` includes the separately built actual Electron onboarding E2E.

| Gate | Result |
| --- | --- |
| `npm run check` | Typecheck/build passed; 636 tests in 67 files passed |
| `npm run smoke` | Isolated fixture Electron smoke passed |
| `npm run test:real-core` | 19 real-core contracts and 5 onboarding E2E passed |
| `npm run smoke:real-core` | 23 checkpoints, all eleven Settings sections passed |
| `npm run test:a11y` | 15 passed; no failures, skips or flaky tests |
| Focused Python backend/domain/transport suite | 329 passed on final lint-clean bytes |
| Complete Desktop Python regression files | 3753 passed, 1 skipped, 4 existing cleanup warnings |
| Exact inventory report | `errors: []`, `byte-drift-clean-review-pending` |
| Lint gate | 7 inherited findings, zero new findings |
| `git diff --check` | Passed |

Tests ran as unprivileged `odin` with repository Python 3.12 and Node 22. Engine
tests used isolated PID namespaces and disposable HOME/XDG; graphical gates used
isolated Xvfb, with a private D-Bus only for the accessibility harness. No active
workstation display, session bus, keyring or live install was inherited.

### Failures found before the final gates

An early real-core pass found stale expected capability enumeration after adding
`secrets.unlock`, followed by a real startup race: async readiness allowed a
welcome before the initial status event committed. The capability expectation
and production startup ordering were fixed without weakening either assertion.

Broad-test runner mistakes also exposed retained process-identity assumptions:
pytest at namespace PID 2 collided with forged-PID cases; shell tail-exec then
made pytest PID 1, rejected by trust fixtures. Final broad runner keeps a real
PID-1 shell and consumes PID 2 with a harmless short sleep before starting
pytest. Retained Hyprland tests and runtime identity checks were not changed.
Final lint cleanup only organized imports and wrapped long lines, followed by
new focused backend and complete app gates. The complete final Desktop rerun
passed 3753 tests with one inherited skip and four subprocess/coroutine cleanup
warnings in 243.43 seconds. This is the Desktop regression corpus, not the full
30-group engine qualification.

## Evidence and limitations

Final evidence is outside Git under `/home/odin/pr30-keyring-final-*`.
Exact adaptation records remain pending independent review, not self-approved.

```text
257e31cdaa48134a1bb9ce6069467cfa2b48998fda49599bafcf22e5383b69aa  pr30-keyring-final-check.log
e5ab74e9a4b286f05c2427946f87394eb6fffb931e2802853954e9a87921c09b  pr30-keyring-final-fixture-smoke.log
f477f60c906095335ac3ffe1dc057a0b1a7c5cfe51d6adb525745c5e4621f56c  pr30-keyring-final-real-tests.log
bebd56d02707e9e58d4b5d3e473cfd1148a90d2f823782a940222d4a9f65e7bd  pr30-keyring-final-real-smoke.log
87567c88bbf71604afc5fd4a25cfd8053c3263b53fb8b4d4ca9902a407122d1a  pr30-keyring-final-a11y.log
2c3c4d806f66a91a2759b8ca5b847bddca8bf2c15dbbcb73cce11fcec1ad605e  pr30-keyring-final-a11y-report.json
622a5fb6b1091e04c053a66d1b7438189d7335a9f3677981fa92fb2ef0b837de  pr30-keyring-final-python-focused.log
8e4efa729d674315620f670fad7e2278084e76f8d1e799c634f23d0abe13d865  pr30-keyring-final-python-all-corrected.log
d3f73444641cd6a193ff710e5f9ea3e8ed259d94a128cc314f61744138e771c9  pr30-keyring-final-drift.json
9d34ab5bc2efad4fadb7e30a2f0674d4426c54769eed8fb7fe58b6cfe61c4584  pr30-keyring-final-lint.json
```

- **Native Secret Service prompt acceptance/lifecycle remains #20's isolated VM
  work.** Synthetic collection behavior is not native acceptance or durability.
- The caller deadline bounds explicit unlock, not all ordinary D-Bus I/O. A hung
  nonprompting daemon call can retain cancellation-settled transactional work.
  This is not an unconditional keyring-hang/shutdown guarantee.
- Duplicate-prompt suppression is process-local. Prompt cleanup across core
  restart is unproven. A timed-out native prompt is not automatically dismissed.
- Late native completion itself never rehydrates or publishes. A subsequent
  independent schema read can observe the unlocked collection and hydrate.
- Retained OAuth code logs refresh success before durable vault save, although
  public token/account acknowledgement remains gated on persistence.
- No successful production OAuth/generation, Orca/AT-SPI, Wayland, packaging,
  full engine qualification or full Phase 3 exit is claimed by these gates.
