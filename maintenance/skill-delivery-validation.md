# Request-owned skill message and file delivery

Request: `req-ff273868`, `/home/odin/reviews/desktop-skill-delivery.md`.
Repository: `Calmingstorm/Odin-Desktop`. No upstream Odin work or deployment.

## Scope and qualification boundary

The foreground delivery gap is implemented. A skill's `post_message` callback
scrubs secrets and commits a durable notice to its admitted conversation.
`post_file` in send mode uses the same `ArtifactPost` construction/publication
seam as Desktop media tools. The producer is the actual skill name, including
`invoke_skill` calls; accessed-host provenance is copied from the real execution
capture rather than supplied by a renderer. Export retains `export_skill`
producer identity and always stages.

Stage mode stores exact producer bytes and metadata in the profile journal,
scoped by owner, conversation, request and generation. Notices do not consume
staged files. The guarded final reply publishes artifacts and deletes its staged
rows in one transaction. A suspended reply preserves staging for the same
request's later generation. Failed publication retains staging; final-reply
identity deduplication prevents duplicate artifact publication. Conversation
deletion removes staging. No generic renderer RPC or replacement tool loop was
introduced.

Callbacks require the original sealed, currently executing request. Unbound,
foreign and late callbacks are refused. A final read-only review found that a
still-running skill child could previously publish during the parent's final
delivery drain. Commit `c077388` adds an executing-state fence and a decisive
real-composition test for message, send-file and stage-file callbacks during
that exact window.

**The requested feature is not complete.** Independent scheduled, agent and
loop skill publication remains fail-closed. Main contains step 6A, but not
PR #37's durable background invocation/work admission. A captured foreground
request or a conversation ID is not background authority. The unwired prototype
was removed, not shipped. An awaited child task created by a foreground skill is
tested, but is not claimed as independently admitted background work. This PR
must remain draft until genuine background admission and owning-conversation
delivery are integrated and tested.

## Tests and interpretation

`tests/test_desktop_skill_delivery.py` executes the real composed request
service, runner, dispatcher, SkillManager, SkillContext, delivery and artifact
store. It covers direct and `invoke_skill` calls, scrubbed durable messages,
opaque bytes, staged final replies, rejected envelopes, settled child callbacks,
export, authorization refusal, atomic failure, deletion and idempotent reply
publication. The durable-domain reopen/generation test uses explicit contexts:
it proves staging mechanics, not end-to-end resumed checkpoint execution.

`app/test/real-core-skills.test.ts` runs the actual Broker and core in the
verified ordinary-user PID namespace. Only the external model/secret boundary
and delivery-mode selection are controlled. The temporary skill performs a real
owned-host read and posts PNG and binary artifacts. Contracts inspect exact
bytes, MIME, hashes, decoded pixels, skill and host provenance, conversation
isolation, command deduplication and restart persistence. Stage mode has no
artifact publication before the guarded final reply.

The implementation was branched from main `ed006967`, then true-merged main's
step 6A, CI timeout and user documentation. Tested final source is
`c077388c74893730550892cf2d38a04851adc7a8`. No rebase or force-push.

## Inherited cases for lane 8

No step 8 dispositions or inherited test bodies were changed. The behavior gaps
behind these cases are now wired:

- `TestInvokeSkill.test_complete_input_executes_with_callbacks`
- `TestFileDelivery.test_export_skill_always_stages`
- `TestFileDelivery.test_file_cb_stage_mode_appends_pending`
- `TestFileDelivery.test_file_cb_send_mode_posts_to_channel`

The original fixture assertions name `pending_files` and a mocked channel send.
Desktop instead requires real admitted authority and durable staging/artifacts.
These are candidates for lane 8's reviewed transport adaptation, not a claim
that the untouched inherited fixtures already pass or permission to weaken
their semantic assertions.

## Evidence and development failures

Raw logs, screenshots, XML results and the SHA-256 artifact manifest live under
`/mnt/storage/odin-desktop-evidence/skill-delivery-req-ff273868/`. Large evidence
is not added to Git. The companion result file records final gate outcomes.

Failed development attempts remain retained: an invalid dependency extra;
premature temporary-profile fixture creation; initial schema/fixture failures;
missing actual skill readiness; an injected Delivery fixture incompatible with
a new keyword; and the post-main-merge readiness removal experiment. The
corrected implementation preserves real readiness and ordinary-user isolation.
The first fresh pre-qualification gate chain was cancelled before full
qualification to fix the settled-child publication issue. It is not a passing
final gate. The final classified qualification was invoked once on fixed source.

## Final fresh-checkout results

- Exact lineage/safety drift, lint, ownership plan and suite-map gates passed.
- Touched Python selection: **99 passed**, ordinary UID 1003 in the restricted
  mount/PID namespace. No skipped or failed cases.
- `npm run check`: typecheck, **747 passed**, build passed.
- `npm run test:real-core`: **24 contracts plus six onboarding tests passed**.
  Both new skill contracts passed, with no skips.
- `npm run smoke:real-core`: passed **40 screen checkpoints** on private Xvfb
  and private D-Bus. The actual workstation session was not used.
- Classified full qualification: **incomplete infrastructure failure**. Five
  of 31 groups completed, **9,235 passed, zero failures/errors, one skip**. The
  supervising tool reported `Local command supervisor ownership lost` at
  900,011 ms while group six was starting. No final qualification-result JSON
  exists. This is not a clean full gate. No second full invocation was run;
  the attempted process launch was refused before starting because the shared
  process registry was at its 20-job limit. Original log and five XML files are
  retained. No remaining group, parity, background or release acceptance is
  inferred from the partial results.

Final delivery remains draft for both independent background admission and the
unfinished full qualification. The raw artifact manifest records SHA-256 and
absolute path for every retained artifact. Final commits after `c077388` add
only documentation/evidence, not tested engine or app source.

The inherited npm dependency graph reported 11 audit findings (10 high, one
critical). No dependency lock was changed or blind audit fix applied by this
feature lane.

No live service restart, deployment, active graphical-session action, webcam
capture, upstream change or PR merge was performed.
