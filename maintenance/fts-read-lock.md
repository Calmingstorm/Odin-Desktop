# Desktop PR 2: FTS shared-connection read/write race

Status: implemented and locally verified, **review pending**. Parent owns delta-ledger
registration and the PR. This task made no commit and no upstream change.

## Origin and unchanged evidence

- Worktree: `/home/odin/odin-desktop` only.
- Read `CONTRIBUTING.md` and `docs/work/phase-1-bring-over.md` before editing.
- Source origin: pinned Git object `refs/baselines/odin-v4.13.0`, upstream release
  `v4.13.0`, commit `cd7530906e9cfa10a0fa900247d7ce2a8bb33e25`. Not a live-install copy.
- Before this adaptation, `src/search/fts.py` matched that object's SHA256:
  `91869849dffc5527778a1df70215c47970f76830e7055fa14aad1925c01e68b4`.
- Adapted source SHA256:
  `684992cfa3d3148cc0e3861b2ae1e119a75e9b74c7734e0df5a0d6664a797220`.
- `tests/test_search_write_atomicity.py` remains byte-identical to the pinned
  object and to its pre-task state, SHA256:
  `fb965a88b7237a6d95d7cbd9e6ec631a68cc4a9f3d3ddb71975f73ed7cf430ee`.
- Only owned edits: `src/search/fts.py`, new
  `tests/test_desktop_fts_read_lock.py`, and this document. Other concurrent
  worktree changes were neither edited nor staged by this task.

## Actual CI failure and diagnosis

Read the failed log of Desktop CI run `37245152626`. The stack is:

`test_search_write_atomicity.py:210` -> `asyncio.gather` ->
`SessionVectorStore.backfill` -> `asyncio.to_thread(_backfill_fts_sync)` ->
`FullTextIndex.has_session` -> `fts.py:187`, `self._conn.execute` ->
`sqlite3.InterfaceError: bad parameter or other API misuse`.

This is a read/write race on the FTS instance's single connection, not the
test's row-count queries. Those counts run after all three backfills have
completed. Backfills can call `has_session` while another pool thread is in
`index_session`'s delete/insert/commit transaction. Writes held `_write_lock`,
but `has_session` and several other reads did not. WAL isolation applies to
separate connections; it does not isolate callers sharing this connection's
transaction and statement state. No sqlite-vec or vector-store source change
is required for this observed FTS stack.

## Narrow adaptation and connection audit

- Retain `_write_lock`'s name, changing it from `threading.Lock` to `RLock`.
  Reads can be nested under the same lock in the same thread without deadlock.
- Add the existing lock around `execute` **and** `fetchone`/`fetchall` in:
  `search_sessions` (both filter branches), `has_session`, `search_knowledge`,
  `count_knowledge_source`, `has_knowledge_source`, and `has_knowledge_chunk`.
- Already-locked readers stay unchanged: `knowledge_chunk_sources`,
  `get_knowledge_source_rows`, `channel_cursor`,
  `channel_needs_reconciliation`, and `search_channel_logs`.
- Private `_channel_needs_reconciliation` is called under the lock from its
  public wrapper or channel transaction. `_search_channel_logs` is called by
  the locked public wrapper. `_rollback_after_failure` runs under mutation
  locks. Initialization uses its local unpublished connection before readers
  or writers can share it; it requires no new concurrent-access mechanism.
- All existing mutation transaction scopes are retained, including knowledge
  replacement/deletion, channel clear, batch insertion/reconciliation,
  identity removal, commit, rollback, and progress-handler installation/reset.
- SQL, schema, query validation, result shape/ranking, busy timeout, write
  acknowledgements and rollback/error semantics are unchanged. No new error
  suppression, retry, fabricated empty results or weakened shared assertions.
- Public operations are serialized per method, not across arbitrary callers'
  multi-method sequences. RLock does not make separate connections globally
  atomic, or turn a same-thread query into a committed-state snapshot while
  that thread itself owns an open transaction.

## Deterministic regression and sensitivity

The new 59-case suite uses real temporary SQLite FTS files and connection
proxies, with bounded Events and thread joins, no endpoints or native helpers.

- Pause a writer after a real DELETE in its open session transaction. Each
  public reader must reach the lock attempt, but must not enter the connection
  until the writer commits; then it must return actual rows/state.
- The same proxy injects `InterfaceError` if a reader enters that open writer
  transaction. An explicit reader-lock bypass retains writer locking and
  deterministically observes the injected error for every newly locked read
  path, including both session-search branches.
- Before source editing, the `has_session` exclusion test failed against the
  original implementation with `reader bypassed the transaction lock`.
- Pause `has_session`'s `fetchone` and session search's `fetchall`; a writer
  cannot acquire the lock before fetch completes. This rejects an execute-only
  lock that releases while a cursor is still being fetched.
- All public readers are exercised under same-thread nested lock ownership.
- Injected `InterfaceError` still propagates from session existence/search,
  knowledge search and channel search.
- Audit every mutation's execute/commit/rollback/progress-handler operation
  under lock ownership, including injected insert failures and rollback.

## Actual isolated results

Every pytest invocation used the repository Python 3.12 and
`scripts/run-phase1-tests.py`: PID/mount namespace, scrubbed `env -i`, private
HOME/XDG roots, plugin allowlist, and 90-second per-test signal timeout.

- Final new regression suite repeated independently 3 times: **59 passed**
  each (8.89s, 6.52s, 6.55s).
- Original unedited atomicity suite repeated independently 5 times:
  **14 passed** each (3.81s, 3.86s, 3.93s, 4.57s, 5.59s).
- Final combined regression + original atomicity + `test_fts_search.py` +
  `test_fts_channel_and_errors.py` + `test_fts_inventory_boundaries.py`:
  **148 passed**, 14.84s.
- Related `test_hybrid_search.py`, `test_search_identity.py`,
  `test_knowledge_publication_atomicity.py`,
  `test_knowledge_reconciliation_boundaries.py`, and
  `test_desktop_core_search.py`: **62 passed**, 5.26s.
- `test_session_search.py -k 'not TestSessionSearchAPI'`:
  **44 passed, 10 deselected**, 3.23s. This is the retained non-API subset,
  not a claim that the whole inherited file passed.
- Ruff on the two owned Python files and `git diff --check`: passed.

Broader inherited integration attempts were also made and must not be hidden:
the initial 9-file related run produced **107 passed, 42 failed**. A narrower
run still including the knowledge snapshot route tests produced **62 passed,
5 failed**. Session API and knowledge snapshot route tests encounter the
explicit Phase-2 management-route gate. The inherited B7/B10 channel tests
expect Discord `ChannelLogger.index_to_fts` to index messages, whereas Desktop's
retired adapter returns zero; its fixture expects nonzero indexed counts.
A direct rerun of B10's legacy-schema case confirmed that fixture boundary
(`0 == 12`), not a SQLite read-lock exception. No such fixture, route, adapter
or shared assertion was changed. These failed integration runs are not included
in the passing retained results above and do not establish full CI success.

## Safety and review limitations

No live data/config/service, system install, real endpoint, upstream repository
mutation, native lifecycle, desktop input, commit, staging, or spawned agent.
Tests use temporary databases and harmless injected SQLite faults. No full
suite, new CI run, reviewer approval or coverage percentage is claimed.
Parent must ledger this source adaptation and obtain the required review.
