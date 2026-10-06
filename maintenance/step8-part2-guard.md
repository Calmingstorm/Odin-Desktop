# Step 8 part 2: complete subsystem guard restoration

Owned artifact: **the entire `tests/test_subsystem_guard.py` suite**, restored through
`tests/desktop_adapters/step8_runtime_guard.py` and
`tests/test_desktop_phase2_runtime_guard.py`. Source bytes remain unchanged, pinned SHA-256
`5c4f14908ca2b46527800bc7304633e2833509048ee474d9192c8c68de24c1d7`.
Disposition is restored, owner step 5, frozen adapter, no excluded classes or cases.
There are 115 original test functions, 116 inherited parameterized cases, and 206 inherited assertions.

## Production omission and minimal correction

Read the PR26 review, CONTRIBUTING, inherited suite and pinned archive composition before changes.
Pinned `src/discord/wiring.py:471-489` constructs the retained guard unconditionally with the configured
degraded/unavailable thresholds and registers its real subsystem names. Desktop's
`ManagementService.compose` previously constructed no guard; `ProviderOwner` already passed the
executor's guard into the retained gateway, but received `None` in production.

`ManagementService.compose` now constructs exactly one retained `SubsystemGuard` from actual profile
configuration, registers the upstream subsystem set with `llm_compat` replacing upstream's retired
`llm_kimi` spelling, and attaches it to the executor before provider construction. The manager and
runtime expose that same object. ProviderOwner's existing handoff remains untouched. There are no
changes to guard policy, gateway outcome classification, admission thresholds, clamping, transient
capacity handling or recovery. No fake guard is supplied by the tests.

## Exact fixture adaptation

Only the four obsolete setup statements in
`TestGracefulDegradationConfig.test_real_bot_guard_is_always_constructed_with_supported_thresholds`
are replaced: the Config and OdinBot imports, Config construction, and OdinBot construction.
They occupy inherited lines 767, 768, 770 and 779. Their newline-joined AST dump hash is
`9086afe8b438724161cd25d175c34ec72b2968497b1fbf5d5ce1ce223bd03d90`.
The replacement is `cfg, bot = desktop_guard_graph(legacy_enabled)`.

The fixture bootstraps real OwnerAuthority identity before writing its trusted temporary profile,
starts actual CoreService and ManagementService composition, authenticates the real local token
handshake, and makes `status.get` through IPC. Keyring storage is in-memory; aiohttp sessions are
refused. No executor, runtime, provider, authority or guard substitution occurs.
The inherited synchronous method receives the actual composed config and manager. Both False and
True stored legacy flag values run with actual 7/19 constructor thresholds and disabled Codex.

The adapter pins archive/source bytes, the exact entire setup AST, the complete assertion/signature/
decorator/parameter corpus, and reverse-restores the setup before comparing the complete module AST.
It exports every original test class. `CORPUS_SELECTIONS` declares the entire suite and exclusions
are empty. Negative tests reject setup threshold drift, assertion drift and unrelated nonassert
changes. No shared fixture manifest, suite map, ledger, checker or qualification plan is modified.

## Concrete test evidence

Executed only using the sanitized PID namespace runner as `USER=odin`:

```text
USER=odin .venv/bin/python scripts/run-phase1-tests.py tests/test_desktop_phase2_runtime_guard.py tests/test_desktop_management_core.py tests/test_desktop_providers.py tests/test_desktop_runtime.py
178 passed in 7.22s
```

Log: `maintenance/step8-part2-guard-test.log`. This is targeted evidence, not full qualification.

Behavioral tests observe and delegate the real constructor, prove it runs once with 7/19, and prove
exact shared identity across all four owners. Real gateway `call_with_tools` for codex, ollama and
compat consumes a fake network
transport, not a fake gateway: six failures stay available, seven become degraded, nineteen become
unavailable, and the next call is blocked before transport dispatch. Runtime status reads the same
degraded/unavailable state. A successful real gateway outcome resets degraded state and counters.
Registration is exact and remains present with Codex disabled; independent subsystem state and 3/10
default threshold behavior with profile values omitted are also checked.

Development corrections before the successful run: setup was switched from manually transcribed
source to its exact whole-node hash pin; temporary identity now precedes config persistence; the
behavioral test uses the actual gateway entry point `call_with_tools`. Earlier runs are not claimed
as passes. No deployment, native desktop interaction, live configuration access, or push occurred.

Independent read-only review `11a6da6d` approved production composition and whole-suite fidelity,
including `register_module(namespace, module)` full export. No concrete defects were identified.
That review did not run tests or rely on the test log; the execution evidence above is separate.
