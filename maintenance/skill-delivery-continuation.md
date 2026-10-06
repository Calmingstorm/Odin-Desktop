# Complete foreground and independent background skill delivery

Continuation of `req-ff273868`, PR #62. This supersedes the earlier
foreground-only/draft status in `skill-delivery-validation.md` and
`skill-delivery-result.json`, which remain historical failed/incomplete evidence.

## Prerequisite and implementation

True-merged current main `541d29e7ad53ec4cd231a371774aa8fbb8f5500c`, then integrated
PR #37's authentic durable background work prerequisite at
`4ede9e75fb079a0a305c7b24f89700d7fb7c4416`. PR #37 was not merged on GitHub by this
lane. Its commit ancestry is preserved in this feature branch. No rebase or
force-push. The broader prerequisite is disclosed, not presented as a tiny
callback-only patch.

Main's sole computer/controller/store, actual browser/MCP qualification and
producer-first teardown remain authoritative. Both sides of the computer and
retention test conflicts are retained. Cleanup fixtures now assert premature
management close refuses without closing the shared webhook transport, then
follow actual scheduler, requests, engine, management cleanup order. Computer
background-lineage rejection precedes publication validation without removing
either fence or changing existing rejection assertions.

Skill message and immediate-file callbacks use the existing durable conversation
publication path, original skill producer name and actual accessed-host capture.
Background managers issue separate sealed requests and independent task/run
identities. A stored conversation ID or captured foreground child context does
not grant background delivery. Scheduled workflows use real scheduler admission,
AgentManager workers use registered independent requests, and each LoopManager
iteration has its own admitted identity. Execution after the foreground origin
has settled is covered by actual composition tests.

Staged files are consumed atomically on the final scheduled workflow notice or
stored report. Agent and loop completion publishes an artifact-only final notice:
it does not bypass response guards with raw model text. Failure and cancellation
also preserve and publish already-produced explicit files before settlement.
Finalization fences late producer callbacks before draining delivery, and retires
its latch after terminal settlement. Conversion/commit failures retain stages and
mark failure; automatic recovery of uncommitted stage publications is not claimed.
Tool execution is never replayed to repair delivery.

## Behavioral proof

`tests/test_desktop_background_skill_delivery.py` adds eight real-composition
cases: successful scheduled workflow send/stage, scheduled post-stage failure,
independent agent send/stage, independent loop send/stage, and authenticated real
loop cancellation after staging. They prove scrubbed durable text, exact opaque
bytes and MIME, skill/host provenance, owning-conversation isolation, foreign and
late refusal, final-stage ordering, no later-foreground attachment leak, and no
effect replay through delivery recovery or duplicate command receipts.

The cancellation case uses actual IPC `work.control`, not a replaced manager. It
verifies an interrupted iteration and stopped loop, exactly one artifact-only
notice, no fabricated success text, empty staging, original producer/host bytes,
and refusal to replay the interrupted generation.

`app/test/real-core-skills.test.ts` retains the foreground posted-file/decoded-image
contracts and adds send/stage scheduled workflows through actual `skills.save`,
`schedules.save`, `schedules.run`, Broker/core transport and artifact retrieval.
It proves final workflow attachment, opaque bytes, producer/host provenance,
separate destination, persistence after restart and duplicate-command no-replay.
The only fixture mode override selects the existing dispatcher's explicit
file-delivery policy. No renderer RPC or authorization alternative was added.

No step 8 dispositions or inherited test bodies were edited. Lane 8 still owns
restoration of the callback/export cases listed in the earlier validation file.

## Final fresh-checkout gate source

`229b3142ae053c2ffb9307d7d563a4e505dd28ad`, detached ordinary-odin checkout
`/home/odin/desktop-skill-delivery-final-req-ff273868`.

- Exact byte lineage, no-new-findings lint, ownership-plan and suite-map passed.
- Touched namespace selection: **204 passed**, zero failed/skipped.
- App check: **758 tests**, typecheck and build passed.
- Real-core: **26 contracts plus six onboarding tests passed**, zero skips.
- Private-Xvfb/private-D-Bus real-core smoke: **40 screen checkpoints passed**.
- Final classified qualification is recorded in the companion final result.

The first complete continuation qualification on `d0fa623` finished all 31
groups with three failures. Two standalone teardown fixtures lacked the optional
composed outbound owner field; cleanup now retains the established injected
runtime owner fallback without closing a duplicate producer. The third was a
step-6A test asserting `schedules.list` remained unavailable even after actual
step-6B composition. It now verifies the authenticated real empty schedule read,
while retaining the skill-test and native-input refusal assertions. Post-fix
focused suites passed 41 and 35 cases. Failed full XML/logs remain retained and
are not overwritten as a passing claim. The corrected fresh source receives one
full invocation after these fixes; the earlier failed full gate stays explicit.

The new correctness fixtures explicitly use a 30-second outer setup/workflow RPC
budget. Failed runs showed the shared three-second fixture bound expiring during
full host-reading workflow execution, then during setup before cancellation.
The inherited defaults, actual product deadlines, assertions and no-retry rules
remain unchanged. The first fresh continuation focused run is retained as
203 passed/one setup-timeout failure; the final selection is a complete pass.

Raw evidence remains under
`/mnt/storage/odin-desktop-evidence/skill-delivery-req-ff273868/continuation/`.
The initial full run's lost supervisor and the first foreground-only incomplete
qualification remain disclosed. The final continuation uses a bounded transient
systemd supervisor running as UID/GID 1003, with the unchanged per-group PID
namespace launcher. Loss of the tool's outer command supervisor does not kill or
replay this run. The unit owns only this checkout, has a 55-minute payload bound,
and writes progress plus an exit receipt. It is not a deployed Desktop service.

No upstream Odin change, self-deployment, live-service restart, active desktop
session input, native workstation qualification, webcam capture or PR merge.
