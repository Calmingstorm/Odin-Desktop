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

Reset while work is active is a known production-core gap: the reset fence and
admitted-context behavior intentionally land with step 3, where running/queued
work exists. The fixture already permits reset during work; a behavioral test
locks that parity. Delete follows the protocol: terminal unknown effects are
not a new busy rule; later request storage retains their tombstones. Missing
fixture paging anchors now return `not_found`, rather than silently using the
latest page.

Search scaling: `search.query` currently linearly scans all visible messages
and artifact names and scrubs them per query. That is acceptable at current
history sizes. A persistent index is deferred as a maintenance improvement;
preserve literal, case-insensitive substring semantics (do not substitute FTS
unless it can prove exact parity) and keep indexed data non-authoritative.

Targeted isolated verification before the gate: 73 conversation/search/core
tests and 126 transport/core/command regressions passed. Full gates run once
from a fresh group-writable worktree with a throwaway HOME and the required PID
namespace launcher. Gate logs and counts are recorded in the PR after execution.

No design-contract edits, live-service operations, active-desktop input, or
deployment are part of this step. App fixture corrections and regression tests
are included. New drift records remain review-pending.
