# Step 8 part 2, batch B

Independent `phase-2/step8p2-batch-b`, base `b74056c4`. Assignment: all21 sorted
step5 paths indexed `[1::4]`. Prior audit `91c37f3b`; per-suite decisions and
test/product references are in `step8-part2-batch-b.json`. Parent owns final
map/dispositions/ledger/integration. No shared plans or product code changed.

## Complete-suite result

**One direct-original restoration:** `tests/test_native_knowledge.py`, 26 cases,
33 assertion nodes, zero edits/setup/import transformations. Real retained
`src/discord/native_tools/knowledge.py:KnowledgeTools` satisfies all original
handlers' assertions with their unchanged narrow dependency fakes.
This is retained native-handler coverage, **not** Desktop management publication:
`ManagementService.compose` uses `KnowledgeService`, not `KnowledgeTools`.

**20 complete-suite deferrals**, each explicitly recorded in JSON. No partial
exports, synthetic API routes, fake status codes or product changes. No viable
full-suite runtime adapter. New `test_desktop_phase2_runtime_b.py` contains10
focused boundary/provenance probes, not inherited case restorations.

## High-value re-audit with real owners

Audit signing's six REST cases (`test_audit_signing.py:898-1054`) assert200/409.
Six new probes exercise actual authenticated Unix IPC and composed RecordsService
using temporary real audit files: valid, tampered active, tampered rotated,
signing disabled, unsigned prefix, empty signed. Invalid integrity yields
**ok=True plus valid=False**, not a conflicting-integrity error envelope.
The report identifies the bad segment, does not repair history and does not add
a read receipt. `RecordsService._handle` returns verifier report and
`ManagementService.invoke` wraps it as success. Deriving a fake409 from
valid=False would conceal a real transport distinction and is not qualification.

Webhook campaign's three CRUD tests (`188-312`) pin absent503/200 statuses.
More importantly, `test_crud_keeps_unregistered_configured_target:252-254` pins
preservation of an externally saved desired URL when boot rejected a different
URL. The new test uses actual IntegrationsService/SettingsService, temporary
profile and injected keyring. Desktop rewrites that row from rejected in-memory
boot state: `_mutate` selects settings.config targets, `_desired_rows` copies the
rejected row. This is a real semantic gap, not a status-spelling issue. A real
persist failure separately returns MethodError internal_error, not503, with no
runtime/config change or vault residue. No product fix was attempted.
Retained YAML comments/environment-placeholder cases at315-351 still exercise
config.persistence.patch_config_paths; they are not retired merely because
runtime secrets use keyring, and not counted as a restored file subset.

## Targeted validation and protections

Inspected originals before execution. Only sanctioned USER=odin runner, sanitized
env-i, private HOME/XDG roots and isolated mount/PID namespace with kill-child.
No full qualification, native display, live install, external HTTP or services.
New probes refuse aiohttp.ClientSession and close actual disposable core/owners.

```text
USER=odin .venv/bin/python scripts/run-phase1-tests.py tests/test_native_knowledge.py tests/test_desktop_phase2_runtime_b.py
36 passed in 7.39s
```

Earlier direct-original26 passed in3.31s. Final36 =26 original plus10 new probes;
zero skips. All21 retained hashes match frozen archive/map. Archive SHA256:
`845d783bd4ee46cd44e63d56532512fd9cef10d08b1432e45047d155c6b348d0`.
Automated provenance probe calls frozen_source for every owned path, enforcing
archive identity, unique regular member, no symlink ancestry and byte equality.
Zero adaptation hunks means assertion/signature/decorator and reverse-hunk
protection reduces to exact original bytes. Parent must add direct-original
selection and reviewed deferrals to its own integration records.
