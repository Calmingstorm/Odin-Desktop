# D17 host parity review delta

Review item 3 removes Desktop's owner allowlist, not host authentication or trust.
This worktree deliberately does not contain the parent's executor/governor or
permission-manager changes. It does not edit frozen upstream tests.

## Runtime contract

- `src/permissions/host_access.py` no longer contains `HostAccessEntry`,
  `default_policy`, `set_policy`, or web-token request-host/default scope contexts.
- `get_allowed_hosts(owner_id)` checks the actual `PermissionManager.is_owner`
  context and returns the current available provider result on every call.
  The provider must be `HostRegistry.active_aliases`, not configured aliases.
- The default runtime store is `host-preferences.json`, containing only
  `default_host`. `set_default_host` requires an authenticated owner and a live
  available alias (or the empty string). Private atomic publication and degraded
  durability reporting remain real. Reloading a new manager preserves the default.
- Missing, malformed, duplicate-key, nonprivate, nonregular or linked preference
  files suppress only default selection. Corrupt preference mutation is refused
  with the existing corruption backup behavior. Legacy `host-policy.json` is not
  read, migrated, overwritten or backed up.
- Trust, host identity, registry publication and lease primitives are unchanged.
  Retirement and forced revocation still remove targetability. Disabling,
  untrusted pinned keys and UUID collisions still fence host acquisition.
- Startup's diagnostic reads `default_host`, not the removed policy serializer.

## Desktop fixture/test adaptations

| Path | Exact semantic adaptation | Evidence |
| --- | --- | --- |
| `tests/desktop_adapters/tools_cases.py` | Delete artificial grant-store writes; authentic manager plus live `registry.active_aliases`. | shared tools, shared owner contracts, host parity |
| `tests/desktop_adapters/foundation_cases.py` | Delete skill grant-store write; authentic manager with available `srv`; explicitly unselect obsolete `test_host_access` serializer suite; fully empty selections execute no removed import/setup. | shared foundation, host parity |
| `tests/test_desktop_foundation.py` | Owner full inventory independent of preference; availability removes only absent hosts/default; preference corruption does not revoke owner. | foundation, host parity |
| `tests/test_desktop_final_config.py` | Legacy enrolled inventory usable to owner without policy; legacy non-owner still denied and YAML unchanged. | final config, host parity |
| `tests/test_desktop_capabilities_skills_hosts.py` | Owner skill discovery returns full live inventory; default selection never narrows it. | skills hosts, host parity |
| `tests/test_desktop_shared_foundation.py` | Invalid preference leaves inventory usable; corrupt mutation preserves bytes and backup; default-only preference and non-owner write denial. | shared foundation, host parity |
| `tests/test_desktop_shared_tools.py` | Registry retirement replaces policy-grant revocation; parent's requested no-governor regression asserts upstream open fallback. | shared tools, host parity |
| `tests/test_desktop_shared_owner_contracts.py` | Registry retirement replaces empty policy grant as pre-query output fence; test is async so authentic transport retirement callback has a running loop. | shared owner contracts, host parity |
| `tests/test_desktop_host_parity.py` | New D17 proof: six legacy-file conditions; default-only persistence and bad defaults; provider publication/retirement/force revoke; trust and identity unchanged; genuine concurrent contexts, foreign identity/seal denial and runtime revocation; durability and startup diagnostics. | host parity |

Evidence shorthand above names the corresponding `tests/test_desktop_*.py` files.
Source `host_access.py` evidence is host parity, foundation and shared foundation.
Source `startup.py` evidence is host parity.

The formerly selected frozen `tests/test_host_access.py::TestEntrySemantics::
test_to_dict_roundtrip` only serializes the upstream per-user allowlist DTO now
removed by D17. It is explicitly unselected, not assertion-rewritten. All frozen
source bytes and adapter AST verification remain intact. Foundation triage now
names the D17 replacements and explicitly records the retired upstream ACL/DTO
contract, without claiming equivalent behavior. Parent integration must refresh
case accounting from qualification collection; this worktree does not silently
claim the removed case still ran.

## Ledger and integration handoff

Eleven exact paths above (two runtime source paths plus nine test/adapter paths)
were individually recorded through `inventory.py record`, with specific D17
reason/contract/invariant and named evidence. Records are pending independent
review, not approval. `inventory.py refresh` regenerated 1762 upstream and 1358
safety paths without capturing or approving drift. Archive verification passed.

`inventory.py report` failed on 17 pre-existing records whose named evidence
digest changed because these Desktop tests changed. Parent owns reconciliation
after cherry-picking all concurrent changes. Generated ledgers/manifests and the
temporary reuse-map pin synchronization are intentionally not committed here,
per parent direction. Exact proposed metadata and evidence digests remain in
this worktree's uncommitted `maintenance/desktop-deltas.json`; re-record each path
in the integration branch, then re-pin other affected evidence individually.

No executor, permission manager, `test_desktop_capabilities_owner.py`, upstream
repository, live installation/configuration/service, graphical session, runtime
skill or system installation was modified. No push is authorized.

## Observed focused verification

The seven touched Desktop test modules completed with **1472 passed, 1 skipped,
1 deselected** in 74.31 seconds, after final source/test edits, under the mandated
non-root isolated PID namespace with `DBUS_SESSION_BUS_ADDRESS` and
`XDG_RUNTIME_DIR` unset and the main repository venv. The single deselected case
is `test_missing_governor_matches_upstream_open_default`, requested by the parent
and dependent on its concurrent executor fix, not included in this worktree.
An earlier inclusive run confirmed that was the only failure. No broad gate or
parent integration pass is claimed here. Ruff passed for all touched Python
paths, and `git diff --check` passed.
