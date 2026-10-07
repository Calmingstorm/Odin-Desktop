# Step 8 package status and lifecycle handoff, req04650fd0

Scope: `src/desktop/package_status.py`, its real-profile behaviour tests, and
`src/desktop/core.py` integration only. No updater, installer, apply, release
publication, native launch, replacement execution or new protocol method.

## Existing owners reused

| Owner | Existing behaviour / new projection |
|---|---|
| `package_state.inspect_profile`, `PackageUpgrade.prepare/commit` | Compatibility before writable attachment; profile identity/schema checks; durable backup/pending/commit barriers. Status retains the actual startup observation and marks committed only after the existing commit returns. This is not a live distribution validator or a reinspection/boot sweep on every read. |
| `version.get_version`, `package_state.compatibility` | Actual engine package version and independent protocol/storage/turn/checkpoint/computer versions. Core transport version remains separate. No directory/PID-derived installation identity or inferred package-format qualification. |
| `OwnerAuthority` | Stable profile/installation identity and current inode-bound runtime lock. Status retains the original incarnation ID even when release rotates authority seals. Lost/replaced identity or runtime fencing never becomes admission/readiness. |
| `CoreLifetime`, existing `runtime.shutdown` command journal | First stop edge, parent EOF and durable idempotent shutdown acceptance. Accepted does not mean settled, cleaned or stopped. Replaying an old shutdown receipt cannot stop a successor. No alternate stop RPC. |
| `CoreService.close`, engine `producers_quiesced`, `ResourceCleanupJournal` | Existing producer and retained-owner barriers, durable current/previous uncertainty. `_close_complete` is distinct from the `_closed` idempotency guard, set only after the entire close returns successfully, outside `finally`. Earlier cleanup uncertainty survives successful later close/restart. |
| `package_ownership.acquire_core_lease`, `src/__main__.py` finalization; shipped P4.2 ownership/preflight | Independent package/app/core leases and entry-point finalization/containment remain external authority. The status reader does not acquire/release them, probe package-manager locks, invoke cleanup, or substitute PID exit for release evidence. |

## Named surface and status contract

Existing authenticated `status.get` and `runtime.status` events gain `package`:

- `identity`: product, actual package version, installation/profile, original
  core incarnation. Credentials, token paths and backup paths are not returned.
- `compatibility`: existing independent compatibility versions.
- `profile_state`: startup migration state/version, explicitly labeled as
  startup-barrier evidence, not proof a release exists or packaging qualifies.
- `update`: `notice_only`, `not_checked`, `app_release_notice` owner, explicit
  reason that the core did not check release metadata, `apply_available: false`.
- `handoff`: current admission/fencing, stop reason, producer/close barriers,
  existing cleanup receipt, and explicit blockers. `core_quiesced` requires
  successful close, stopped admission, settled producers, complete cleanup with
  no inherited uncertainty, and no known fencing loss. Observed fencing loss
  stays latched after runtime release rather than becoming a clean handoff. It describes only this
  incarnation. It neither proves no successor exists nor attests app exit.
- `replacement_safe` is always **false**. Even after clean core close and profile
  release, `external_package_ownership_barrier_required` remains. Package-manager
  preflight/user-managed replacement must consult their actual owners. No effect
  rollback, quarantine reconciliation, or replay is implied.

The shutdown event projects pending quiescence before the committed stop edge,
never cleanup success. The existing shutdown response stays `{disposition:
accepted}`. No capability or protocol/schema version is added. Existing minor-2
client behavioural tests receive the additive field. App IPC's status handler
(`app/src/main/ipc.ts:138–146`) preserves additive fields and validates only the
existing `first_run` projection; app typing/presentation remains app-owned.

## P4.3 accurately pending

At inspection, PR39 is **OPEN**, head
`99782d2e3adb8ce7505501199b1dd2d7ffc9b21a`. Its
`app/src/main/release-notice.ts` and `app/src/shared/api.ts` were inspected
read-only. They are not present in this main-based checkout and are not copied.

That pending owner has `checkReleases` / `openRelease` main/preload methods, not
core update methods. Its `ReleaseNotice` contains `currentVersion`, optional
`latestVersion` / `releaseUrl`, and states `cannot-check-private`, `offline`,
`rate-limited`, `unavailable`, `malformed`, `no-release`,
`invalid-current-version`, `equal`, `older`, `newer`. It anonymously queries the
fixed repository, validates published stable versions and exact release URLs,
never follows redirects or reads credentials, and opens only its validated
latest result. Decision C/D and work order P4.3 explicitly leave this outside
core shutdown/apply. This lane therefore does not duplicate HTTP/version/link
logic or pretend a pending notice is available, up to date, or unable to check
for a particular network reason. Core status truthfully says **not checked**.

## Behaviour pins in `tests/test_desktop_package_status.py`

- `test_package_identity_is_profile_bound_and_incarnation_fenced`
- `test_package_reads_are_notice_only_without_receipts_or_cleanup_effects`
- `test_shutdown_acceptance_is_not_quiescence_and_event_never_claims_ready`
- `test_package_handoff_waits_for_producers_close_and_external_ownership`
- `test_parent_loss_uses_same_package_handoff`
- `test_unknown_cleanup_survives_successful_close_and_restart`
- `test_cleanup_storage_failure_does_not_turn_closed_guard_into_success`
- `test_replaced_runtime_lock_is_not_valid_package_fencing`
- `test_listener_close_failure_does_not_attest_successful_core_close`
- `test_failed_package_commit_keeps_pending_startup_status`

Real temporary profiles, authenticated Unix IPC, actual migration/journal/lock
owners and engine close barriers; only network/keyring and bounded failure/close
pause primitives are fixtures. No native/live operations or bare pytest.

## Actual targeted validation

Initial package-only run: 8 passed, 1 failed because retained-cleanup fixture
was created before profile identity. Fixed fixture by first starting/closing a
real profile, without weakening identity checks. Subsequent selection passed.

Final targeted command:

```text
.venv/bin/python scripts/run-phase1-tests.py tests/test_desktop_package_status.py tests/test_desktop_core_lifecycle.py tests/test_desktop_management_core.py tests/test_desktop_package_state.py tests/test_desktop_package_ownership_entry.py tests/test_desktop_resource_cleanup.py -ra
```

Restricted isolation helper, invoking UID 1003: **98 passed, 1 skipped**, 94.81s
on final rerun after pinning retained fencing loss (earlier run: 108.56s).
Skip: `tests/test_desktop_package_state.py:308`, exact previous candidate
resources required for candidate upgrade proof. No full qualification run.

Gaps remain separate: PR39 notice merge/app tests, exact previous-candidate
package upgrade, native distribution/platform qualification, shipped ownership
and process-containment finalization proof, actual external replacement and
publication. This status does not waive any of them. Parent owns integration,
ledger, CI/app validation and final qualification.
