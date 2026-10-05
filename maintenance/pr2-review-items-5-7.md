# PR 2 review items 5, 6 and 7

Implemented on `review/phase1-maintenance`, isolated checkout
`/home/odin/odin-desktop-maintenance-review`. Only these review items are owned by
this change. Independent review remains pending.

## Item 5: exact safety-policy restoration

`src/tools/risk_classifier.py` and `src/tools/recovery.py` are byte-identical to
the immutable `maintenance/odin-v4.13.0.tar.gz`, pinned to v4.13.0 commit
`cd7530906e9cfa10a0fa900247d7ce2a8bb33e25`. Archive SHA256:
`845d783bd4ee46cd44e63d56532512fd9cef10d08b1432e45047d155c6b348d0`.
No live-install copy was used.

- Classifier restored SHA256:
  `60ba605878d4c4d6493c38a743c9d0f234ff272778e9fe2f3bb7125a2a3700dc`.
- Recovery restored SHA256:
  `3d9af1d6bbf4354e35fbbdf14e93be7cdf497f66254377e757b4f81397b57c11`.
- `add_reaction` retains MEDIUM classification. `purge_messages`,
  `add_reaction`, `create_poll` and `set_permission` retain `UNSAFE_TO_RETRY`.
- New regression tests hash-verify the complete archive, compare complete source
  bytes, load harmless same-named skills only into temporary directories, and
  verify classification, transient recovery skip, no retry budget, and safe
  authentication hints. The other three names retain baseline LOW static
  classification; this change does not invent higher policy.
- The two obsolete delta entries are removed, not re-recorded. Their adaptation
  plan entries are removed too. `report` identifies both as shared-byte-identical.

## Item 6: Linux v1 host check

The local branch of `HostEnrollmentManager.test` again requests exactly
`["sh", "-c", "printf 'odin-host-test linux\\n'"]`, as upstream. The remote
branch is unchanged. The only remaining source delta is the approved reference
scan strip adaptation to explicit engine stores rather than a transport/token
inventory. This is not expanded local macOS support.

Mocked-command regressions verify the exact argv, successful selected Linux
test, selected macOS mismatch, and existing local consent. No real shell, SSH
target or native platform probe is exercised by those tests.

## Item 7: deliberate retained differences

### FTS

Retain `src/search/fts.py` and `tests/test_desktop_fts_read_lock.py` unchanged.
This is an intentional **upstream-candidate** correctness fix. Proposed ledger
metadata:

- Reason: CI `37245152626` exposed `has_session` sharing a SQLite connection
  with concurrent backfill writes. RLock serializes execute **and fetch** with
  retained transaction scopes.
- Contract: same-thread nested reads remain supported; cross-thread readers
  wait for commit. SQL, result shapes, rollback and error propagation unchanged.
- Invariant: no automatic retry or swallowed `InterfaceError`. Per-method
  serialization is not multi-method or cross-connection atomicity. No native,
  platform or full-runtime parity claim.
- Backport: `upstream-candidate; applicability/independent review pending`.
- Evidence: `tests/test_desktop_fts_read_lock.py` and original unmodified
  `tests/test_search_write_atomicity.py`; diagnosis, sensitivity and limitations
  in `maintenance/fts-read-lock.md`.

### Computer built-in reservations

Keep `src/tools/builtin_policy.py` unchanged. Its `COMPUTER_TOOL_NAMES` union is
baseline policy, deliberately retained even when the Phase 1 catalog does not
publish `computer_session`, `computer_observe` or `computer_act`.

- Reason: intentional Desktop readiness divergence adds live availability while
  preserving computer name reservation independently of publication.
- Contract: literal True readiness admits only Phase 1 executor names; computer
  names stay reserved and unavailable even with fabricated readiness.
- Invariant: reservation never grants publication or native authority. New
  reservation tests do not prove every skill/MCP collision consumer uses this
  shared set.
- Evidence: `tests/test_desktop_capabilities_publication.py` plus
  `tests/test_desktop_maintenance_review.py`.
- Limitation found during testing: `SkillManager` separately derives names from
  `TOOLS`, so its creation path currently permits these three names. Initial
  tests demanding rejection failed (9 passed, 3 failed). This task did not
  expand item 7 into a skill-manager source rewrite. The final assertions cover
  the actual shared reservation and Phase 1 nonpublication contract, not an
  unproven universal collision guarantee. Parent was notified.

## Validation and exact ledger refresh

The final touched/relevant test run used:

`sudo -n unshare --mount --pid --fork --mount-proc --kill-child sudo -n -u odin env -u DBUS_SESSION_BUS_ADDRESS -u XDG_RUNTIME_DIR PYTHONPATH=/home/odin/odin-desktop-maintenance-review /home/odin/odin-desktop/.venv/bin/python -m pytest -q`

Files: `tests/test_desktop_maintenance_review.py`,
`tests/test_desktop_capabilities_skills_hosts.py`,
`tests/test_desktop_fts_read_lock.py`, `tests/test_search_write_atomicity.py`.
Result: **102 passed in 9.05s**. The preceding combined run found one stale
Desktop local-uname test (101 passed, 1 failed); that expectation was updated
to Linux v1. No inherited test bytes were changed. Ruff on the two edited test
files and `git diff --check` passed. No full suite or coverage percentage claimed.

Local maintenance rehearsal, using the parent's explicitly authorized reuse-map
pin `54572e8cd5bd7515ddbca7db04f532a9a776fd072c6c7e39ad957c12b8686cf5`:

1. Removed delta entries for restored `src/tools/risk_classifier.py` and
   `src/tools/recovery.py` with a context-checked patch.
2. Ran `inventory.py record` individually for `src/tools/hosts/control.py`,
   `src/tools/builtin_policy.py`, `src/search/fts.py`, the new
   `tests/test_desktop_maintenance_review.py`, and modified
   `tests/test_desktop_capabilities_skills_hosts.py`, using the concrete
   contracts above. All remain pending independent review.
3. Re-recorded `src/tools/hosts/registry.py`, `src/tools/skill_context.py` and
   `src/tools/skill_manager.py` solely because their named evidence includes
   the modified local-enrollment test. Their source bytes were not changed;
   reasons explicitly state evidence-digest refresh, not approval.
4. `inventory.py refresh`: **1762 upstream paths, 1358 safety paths**.
5. `inventory.py report`: archive verified, **no errors**,
   `byte-drift-clean-review-pending`, **198 pending records**, both restored
   source paths shared-byte-identical. This is static drift evidence only.

Per parent integration instructions, generated `desktop-deltas.json`,
`manifest.json`, `safety-manifest.json`, and the local checker pin adjustment
are deliberately **not included in this commit**. Parent must apply the exact
records/removals above after all source/test cherry-picks, mark FTS backport
disposition explicitly, and refresh/report the combined branch. No unrelated
drift was captured; no executor/host-access/permission-manager records touched.
