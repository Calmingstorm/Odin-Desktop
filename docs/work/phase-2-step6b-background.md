# Phase 2 step 6, part B: work, reports and recovery

Stack: `phase-2/controls-resume`, merged without rebasing or rewriting history.
Part A and runtime management remain separate lanes. This implements no webhook
ingress, native desktop qualification, packaging, or Phase 2 closure claim.

## Composition and authority

- The existing profile graph owns the actual agent, background-task, loop,
  process and schedule managers. `WorkService` persists opaque immutable public
  IDs plus manager generation, execution generation, owner and conversation.
  A recycled PID or edited schedule destination cannot inherit the old ID.
- Background admission comes from the active sealed request, or the scheduler's
  issued execution nonce and persisted run binding. It is never a fabricated
  message, browser session, token, or privileged test shim. The existing request
  store supplies independent durable execution destinations after foreground
  settlement. Interrupted work never starts again on reopen.
- Work mutations use step 4's durable controls. Pending receipts stay unknown;
  retrying the same control returns its stored result, not a successor action.
  Requested cancellation and actual manager/resource settlement remain distinct.
  Agent nesting, budgets, completion and queued-not-consumed corrections use the
  retained manager, not another implementation.
- Process controls preserve current tool, host, generation and request scope
  authorization. They never claim containment because a signal was requested.
- Report pages are stored once with immutable owner/conversation/request/run/
  generation/producer provenance. Reading pages or repairing delivery never
  reruns the check. Stored pages are receipts, not live retained-evidence cursors.

## D12 and computer admission

Overdue reminders produce one bounded notice with due time, lateness and omitted
slot count. Slot counting is bounded. Missed action recovery is manual; workflow
automatic catch-up is bounded at zero. Interrupted or uncertain external effects
never replay automatically. Existing timezone, paused-one-time and known retry
rules remain. The scheduler task uses sealed installation authority and can post
to durable conversations without a connected app window. Exit runs nothing.

`ComputerForegroundBinding` composes the existing controller and private store
with admitted owner/conversation/foreground-turn/task lineage. Background requests
cannot acquire this binding. Generation, consent, scope, quarantine, observation
freshness, cleanup uncertainty and no-replay stay in the retained controller.
Inherited child contexts retire with the root, including automatic resume.
The standalone facade publishes **no native usability capability**. Part A later
shares its management controller via `bind_foreground`; no second controller is
created in that composition. All computer tests here use stub backends.

## Evidence and limits

Named tests: `test_desktop_work.py`, `test_desktop_work_native.py`,
`test_desktop_reports.py`, `test_desktop_schedule_recovery.py`,
`test_desktop_computer_binding.py`, `test_desktop_background_requests.py`, and
`test_desktop_background_core.py`. The last exercises actual IPC composition,
retained task/agent/loop execution, harmless disposable process registration,
stored report paging, schedule controls, disconnected reminders, destination
generation retirement and separate failure-notice settlement.

Every engine suite uses the required PID namespace and throwaway HOME. The final
full qualification is from a fresh checkout under a group-writable parent.
Exact source and test digests are pending independent review in
`maintenance/phase2-step6b-adaptation-plan.json`; passing tests are not approval.

An initial qualification attempt was stopped after discovering a scheduler
control response-shape gap during integration review. It is not counted as final
qualification. The replacement run must finish on the final committed source.
No live service, `/opt/odin`, active desktop or destructive test command was used.
