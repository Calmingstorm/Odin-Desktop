# Step 8 fresh-profile D17 proof

Schema 1 `fresh-profile-parity.json` is data, not a claimed-success flag.
`scripts.maintenance.fresh_profile_parity.check(root)` is stdlib-only and returns
`valid`, `errors`, `status`, `delta_count`. It verifies archive/source/citation/test
hashes, complete observation digests, exact granular delta rows and finite approval
classifications. Compact delta rows are `[path, old, new, citation]`; citations map
to precise D-decision rows or prompt-changes part C in the generator. No wildcard
approval applies to newly introduced fields. Unknown approval blocks closure.

Dynamic tests re-extract all settings and access observations from pinned v4.13.0
`load_config(config.yml)` in an extracted disposable source tree, and real Desktop
`ensure_profile` plus `SettingsService` in an independent disposable XDG profile.
Only random profile roots are normalized. Canonical complete observation hashes
include 287 baseline and 267 Desktop setting/access/runtime leaves. Every delta
is recomputed, so omissions cannot hide behind a parity boolean.

Both actual executors dispatch explicit-host and omitted-host `run_command`, and
`http_probe` without host. Only `_exec_command` is stubbed. Both select
127.0.0.1/root; no shell, SSH or HTTP operation executes. Desktop uses a genuine
OS-authenticated owner context. Readiness is fixture-provided, not a bundled-native
qualification claim. Configured default is localhost, preference is empty and owner
inventory is localhost on both sides. Real persisted fresh configuration is tested.

Three initially unapproved template mismatches were restored under the parent's D17
direction in fresh provisioning only: browser enabled, the two shipped localhost:3000
private browser targets, and shipped localhost:8188 skill URL. Schema defaults and
existing profiles remain unchanged. No mismatches were labeled approved to hide them.

Remaining finite delta rows cite D1/D6/D17 removed transport/tier surfaces, independent
fresh-state D5 path relocation, D17 admin-to-owner override naming, or prompt-changes
part C channel-ID removal. These classifications require independent review.

Hashes cover relevant config/permissions/host/handler modules plus fresh provisioning,
settings, owner identity, runtime paths, executor, HTTP command builder and governor.
Unrelated package-status/request/UI lanes are excluded. Relevant dependency changes
require recollection, not blind hash refresh. Full qualification is parent-owned.
Pinned executor import required discord.py 2.7.1 in the shared test venv only.
No live install, config, service, graphical session, commit, push or ledger changed.

Isolation is enforced by the required test launcher, not invented in this module:
`collect()` rejects root but its non-root check alone does not prove PID isolation.
The internal `_baseline` worker is not a public collection/qualification command.
Run dynamic extraction only through the mandated isolated tests. Static report is
safe outside that boundary and imports no engine modules.

Focused final verification: 49 passed across `test_desktop_fresh_profile_parity.py`,
`test_desktop_provisioning.py`, and `test_desktop_settings.py`, using the mandated
non-root PID-namespace launcher. Static report returned valid/pass, zero errors,
38 deltas. Ruff and `git diff --check` passed for this lane. No full qualification
or native runtime result is claimed here.
