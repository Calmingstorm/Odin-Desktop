# Phase 2 step 2: conversations, transcript and search

The core serves minor-3 conversation navigation and mutations over the real
owner-authenticated local transport. Domain records, command receipts and events
share the FULL-synchronous SQLite journal. Existing transport-only profiles can
upgrade; only explicitly registered domain schemas are adopted on reopening.

Implemented: revisioned create/update/delete/reset/mark-read, immutable labeled
child context through a recorded cutoff, committed transcript paging, coherent
snapshot watermarks, activity/control/tool/unresolved state-provider projection,
literal app search and jump, and native current-request history readers using
the existing FTS and reciprocal-rank helpers. Transcript state is independent
of compactable model sessions. Search snippets scrub whole strings first.

The request-state provider and transactional deletion hooks are small seams for
step 3. Step 2 does not admit execution, claim runner parity, or fabricate request
activity. Native history ownership is supplied by step 3's trusted request
binding, never a model-provided foreign conversation ID.

Fixture difference: context reset is refused while work is running or queued,
so context cannot be changed under an admitted runner. The fixture currently
permits that reset. Delete follows the protocol: terminal unknown effects are
not a new busy rule; later request storage retains their tombstones. Missing
paging anchors return `not_found`, rather than silently using the latest page.

Targeted isolated verification before the gate: 73 conversation/search/core
tests and 126 transport/core/command regressions passed. Full gates run once
from a fresh group-writable worktree with a throwaway HOME and the required PID
namespace launcher. Gate logs and counts are recorded in the PR after execution.

No app or design-contract edits, live-service operations, active-desktop input,
or deployment are part of this step. New drift records remain review-pending.
