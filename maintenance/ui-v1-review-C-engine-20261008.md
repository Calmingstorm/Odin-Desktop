# Review C E1/E2 engine corrections

Scope: `/home/odin/odin-desktop-ui-v1`, `campaign/v1.0-ui`. E1/E2 only;
parent combines the other C corrections before committing. No commit/push,
renderer edits, slices 5–7, live installs/services/displays or VMs.
Historical C evidence and reports are unchanged.

## Changed behavior

- **E1:** `fresh_config_document()` is also the defaults base for existing
  settings/runtime merges. It now leaves timezone to the schema's **UTC**.
  Only the absent-config creation branches in `ensure_profile()` and
  `provision_fresh_profile()` resolve and persist the system timezone.
  Existing documents without timezone remain UTC; explicit saved zones remain
  intact. Real temporary-profile/settings regressions cover load, save, reload,
  deletion/default restoration and byte preservation. Both new-file entrypoints
  still resolve the system zone exactly once.
- **E2:** Outbound Test validates an optional reviewed revision under the
  settings/file locks, releases them, and calls public `send_test_event(id)`.
  Public `get_status()` qualifies the profile owner instead of service-side
  optional private `_sync` access. Delivery, keyring qualification, statistics,
  closed-owner refusal and cancellation remain the public owner's responsibility.
  The old private snapshot/delivery/statistics/shutdown-copy path is removed.

**Intentional limitation accepted by review C:** a concurrent edit after the
revision check can be adopted before the public owner selects the target ID.
There is no longer an immutable reviewed-target delivery guarantee. The revised
race regression explicitly exercises this window and proves settings/file locks
are not held across external I/O. Unrelated mutation/adoption private-state
seams are outside E2; this is not a claim that the entire integration service has
been refactored to a public-only API.

## Files

- `src/desktop/provisioning.py`
- `src/desktop/integrations.py`
- `tests/test_desktop_provisioning.py`
- `tests/test_desktop_settings.py`
- `tests/test_desktop_shared_outbound.py`
- `maintenance/desktop-deltas.json`: exact pending-review source/test records
  plus 11 named touched-test digest references refreshed in existing records.
- `maintenance/fresh-profile-parity.json`: changed provisioning source hash;
  observations/deltas are unchanged and dynamically revalidated.
- `maintenance/ui-v1-review-C-engine-plan.json`: five explicit record plans.
- This correction report. No historical report rewrites.

## Observed validation

All Python tests used the existing `scripts/run-phase1-tests.py` restricted
isolation helper as nonprivileged **UID 1003**, with private PID/mount namespace,
sanitized HOME/XDG and no live display/session sockets. No plain pytest.

- Initial four-file focused run: **110 passed** in 12.68s.
- Final eight-file run: **350 passed** in 18.38s, no skips/failures:
  provisioning, settings, shared outbound, integrations, first run,
  phase2 review integrations, browser runtime, fresh profile parity.
- Public-only dispatcher regression rejects unexpected private attribute access,
  verifies reviewed and ID-only calls, and proves stale revision rejection before
  public sending. Retained-owner regressions cover missing/invalid revision,
  missing target, close after revision admission, in-flight shutdown cancellation
  and reviewed/ID-only locked-credential refusal without HTTP.
- Static inventory: `errors: []`, `byte-drift-clean-review-pending`.
  Five owned records independently validate as `ledgered-exact-delta`;
  implementation approval remains pending, not fabricated by the recorder.
- Static fresh-profile parity: `valid: true`, 42 deltas, no errors.
  Dynamic parity extraction/comparison also passed in the final isolated run.
- Scoped `git diff --check` passes for all owned source/test/ledger/parity files.

Receipts retained outside Git at `/home/odin/reviews/desktop-ui-v1/`:
`C-engine-final-tests.log`, `C-engine-final-tests.xml`,
`C-engine-inventory-report.json`, `C-engine-parity-report.json` and intermediate
test logs. Final test log SHA-256:
`bdee9ef4d64aff27f7eff8f44675ddbaf6b44b682c5db8da6cea4ae13d0263da`.
Final JUnit SHA-256:
`90537cf5a6b426a27b8642418a8428fb878a8f7fd43e1d973146d912ae6ddcb4`.

## Intermediate failures and unclaimed boundaries

- An extra compatibility invocation named nonexistent
  `tests/test_desktop_settings_schema.py`; isolated collection exited 4 with no
  tests run. Corrected the selector, not the test runner.
- A broad raw upstream compatibility selection returned **383 passed / 5 failed**.
  Two unchanged `TestOutboundWebhooksConfig` cases still supply the stripped
  Discord config field; their reviewed Desktop replacements are accounted in
  `tests/test_desktop_shared_config.py`. Three unchanged `test_webhook_campaign`
  cases call stripped HTTP management routes, now explicitly Phase2Unavailable;
  their Desktop owner adaptation is recorded in the existing phase2 suite map.
  None was changed/skipped to obtain the final focused result. Full classified
  qualification belongs to the parent combined-C gate.
- Whole-tree diff checking during concurrent renderer work found another worker's
  trailing blank line in `OutboundWebhooks.vue`; no renderer file was edited here.
- No new full-suite, coverage-ratchet, app/UI/native, real-provider or release
  qualification claim. Parent must run the combined-C gates on its final tree.
