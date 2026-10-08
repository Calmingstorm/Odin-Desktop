# Round F: Desktop SSH socket paths

Python-only implementation handoff on `campaign/v1.0-ui`, based on `af5d46f`.
No commit, push, pull, live service, live configuration or desktop operation was
performed by this worker. The parent owns UI changes, upstream import integration
and final combined gates. This report is not the common Round F report.

## Implementation

- Fresh provisioning, schema defaults and explicit Core defaults use a short
  private runtime namespace, not the profile's potentially long cache path.
- Prefer a verified owner-UID, exactly-0700 `XDG_RUNTIME_DIR` with no symlink
  components. Otherwise use `/tmp/odin-desktop-<uid>/<profile>/ssh`.
- A valid long profile identifier gets a stable 12-hex hashed profile component
  when needed; an overly long runtime root falls back to `/tmp`.
- Correct only an exact, too-long former provisioned default
  `<selected-profile-cache>/ssh-sockets`. The correction is runtime-only,
  including SettingsService initialization, settings preparation, reload and
  ensure_profile. Existing YAML is not rewritten by this correction.
- Explicit custom path spelling, relative paths and existing custom directory
  modes remain intact. Overlong custom paths fail clearly, never silently move.
- The Desktop pool adapter reserves the registry filename, separator and
  OpenSSH's 17-byte temporary suffix before directory creation. Every actual
  socket pathname gets another byte guard, including legacy host/user names.
  Relative paths reserve against their effective absolute spelling as well.
- The shared `src/tools/ssh_pool.py` is unchanged. The executor selects the
  Desktop adapter through a delayed import to avoid the tools package's import
  cycle. Pool lifecycle, master containment and reuse behavior are inherited.

## Security and scope

Managed directories are created with 0700 beneath checked, held no-follow
directory descriptors. Existing managed components must belong to the invoking
UID and already be 0700; symlinks, foreign/root ownership and unsafe modes are
rejected, not repaired. Ancestors require root/current-UID ownership and no
group/other write permission, with a root-owned sticky `/tmp` exception only.
Configured paths outside the managed namespace keep the existing pool policy.
No existing user directory is chmodded by this feature.

This does not claim protection against a malicious process running as the same
UID replacing directories after descriptors close and before OpenSSH opens its
socket. Selection is read-only; use-time validation rechecks the runtime root.
The namespace is UID/profile scoped, as requested, not keyed by alternate data
roots having the same profile ID. Supported Desktop scope is Linux; the guard
uses its 107 pathname bytes plus the separate NUL byte. This is not macOS
qualification or remote-host SSH connection proof.

## Tests and commands

All Python tests ran as UID 1003 (`odin`) through the repository's restricted
isolation helper, with its separate mount/PID namespaces and private `/tmp`.
No remote host or active desktop runtime was used.

Working command:

```sh
sudo -n -u odin .venv/bin/python scripts/run-phase1-tests.py tests/test_desktop_ssh_sockets.py tests/test_desktop_core_paths.py tests/test_desktop_request_core.py tests/test_desktop_provisioning.py
```

Working outcomes, in order: collection failed on an import cycle; after fixing
the delayed adapter import, 95 passed / 1 failed because a fixture wrote config
before establishing profile identity; after fixing that fixture and adding
security coverage, **116 passed in 6.66s**.

Final focused command:

```sh
sudo -n -u odin .venv/bin/python scripts/run-phase1-tests.py tests/test_desktop_ssh_sockets.py tests/test_desktop_core_paths.py tests/test_desktop_request_core.py tests/test_desktop_provisioning.py tests/test_desktop_settings.py tests/test_desktop_executor_profile.py
```

Result: **145 passed in 7.89s**. The new socket suite contributes 33 cases,
including actual AF_UNIX bind with the complete temporary suffix, long HOME,
long profile, Aaron's exact legacy spelling, unchanged saved YAML, custom path
preservation, byte-versus-character limits, exact boundary/overflow, relative
path guard, unusable XDG fallbacks, planted managed components, ownership,
use-time root recheck and UID fallback symlink refusal.

Additional commands:

```sh
.venv/bin/python scripts/maintenance/inventory.py report
git diff --check
.venv/bin/ruff check src/desktop/ssh_pool.py src/desktop/ssh_sockets.py tests/test_desktop_ssh_sockets.py
```

Results: inventory `errors: []`, gate `byte-drift-clean-review-pending`;
diff whitespace clean; Ruff all checks passed. The other four maintenance
gates, overall UI gates and combined smoke are the parent's responsibility.

## Exact records and files

`maintenance/desktop-deltas.json` was regenerated through the existing
`scripts.maintenance.inventory.record` generator for precisely these ten paths,
retaining prior path rationales and named evidence and appending the Round F
contract. Records remain pending independent review, not self-approved:
For the seven changed pre-existing source/test entries, the entire pre-Round-F
record is retained verbatim as `previous_review_lineage`, including nested
executor review records. This explicitly preserves historic approvals without
applying those approvals to the new Round F delta. No existing path entry was
removed. The generic recorder initially dropped executor lineage; the parent
caught this and the full lineage was restored before handoff.

- `src/config/schema.py`
- `src/desktop/core.py`
- `src/desktop/provisioning.py`
- `src/desktop/settings.py`
- `src/desktop/ssh_pool.py` (new)
- `src/desktop/ssh_sockets.py` (new)
- `src/tools/executor.py`
- `tests/test_desktop_core_paths.py`
- `tests/test_desktop_request_core.py`
- `tests/test_desktop_ssh_sockets.py` (new)

Named-test fingerprints referencing the two updated existing Desktop test files
were refreshed, without recapturing any unchanged source patches or changing
their review provenance. `maintenance/ledger.json` remains untouched: no
post-baseline upstream port is performed here. The Python-specific report and
Desktop ledger are the only additional maintenance files changed by this worker.
