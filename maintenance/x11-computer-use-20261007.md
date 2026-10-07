# Desktop 1.0.0 X11 computer publication

Base: `4d32dc0e0d79e961d95370c7b4ff52bb2911d98e`, fetched from main before branching.
Branch: `app/x11-computer-use`. CI intentionally not requested; engine workflow is disabled.

## Runtime change

Computer use remains opt-in. Native Wayland sessions, including XWayland with a
local DISPLAY, remain unpublished and receive the 1.1 guidance reason. Otherwise
the same explicit local `:NNNNN` display boundary as Odin is required.

The session supplies display, authority and monitor topology. A bounded disposable
read-only worker discovers monitor names, then the unchanged X11 attached backend
starts and probes metadata, scope availability and XTest capability. It does not
capture pixels, inject input, change focus or create devices. Publication requires
successful startup and acknowledged settled cleanup. An unresolved probe is
retained, not forgotten or retried as a new backend. Lack of an eligible current
application does not permanently hide the tools; each admitted task starts its
own backend and retains the existing observation, target and consent checks.

Runtime attachment fields are not persisted. Settings exposes and accepts only
`computer.enabled`. Foreground startup uses the rebound facade's runtime settings,
including after live activation; activation invalidates the actual model catalog.
Core and renderer status now reflect real availability, without claiming a native
qualification campaign passed. `native_qualified` remains false.

Existing foreground admission, background exclusion, vision transport, consent,
ownership/freshness and guardian-loss quarantine code is unchanged. The existing
X11 shared-input release limitations remain unchanged too.

## Observed final local results

- Focused isolated Python selection: **129 passed**, 30.92 seconds.
- Private authenticated Xvfb: enabled tools published; admitted foreground start,
  delivered observation and verified click reach a harmless receiver with exactly
  one press/release pair. Disabled tools are absent.
- Real CoreService, authenticated local management and retained model runner:
  the provider receives no computer tools while disabled, receives all three
  after live activation, and the cached catalog withdraws them after revocation.
- App check: typecheck, **1,102 tests** and production build passed.
- Sharded real-core: **66 tests**, four isolated shards, **172.370 seconds** within
  the unchanged 600-second aggregate bound; onboarding **6 passed**.
- Five short gates: inventory, lint, phase2 plan, D19 and closure passed.
- Touched Python lint and diff whitespace checks passed.

No real desktop capture or input, VM/lab work, deployment, restart, sub-agent,
custom skill creation or CI run. All native tests used private Xvfb inside the
unchanged isolated PID/mount runner. This is source-tree regression evidence,
not a claim of Aaron's real-session acceptance or full native qualification.

## Disclosed intermediate failures

The first catalog unit test used the management-only policy rather than the
actual foreground policy and hid computer definitions. Switching that fixture
to the production foreground catalog exposed the intended behavior. A real-core
activation regression then found stale cached tool publication; activation now
invalidates that catalog, and the full model-offer regression passes.

The initial real-core launcher preflight rejected a shared venv because its
editable install imported another checkout. No tests ran in that attempt. A
fresh lane-owned `uv sync --locked --extra dev` fixed provenance; final real-core
and focused tests used this lane's own environment. Old disabled-status/UI
assertions were updated to the new truthful state. No timeout or safety gate was
relaxed. Initial stale ledger test digests were re-recorded with prior reason,
contract and invariant preserved and new history appended.

## Retained evidence manifest

All paths are under `/mnt/storage/odin-desktop-evidence/x11-computer-use-20261007/`.
Large raw evidence remains outside Git.

| Artifact | SHA-256 |
| --- | --- |
| `app-final.log` | `43ff2e34c54cf83d4248e63fc685cd0938e914e0f41a080be74c20d59929b765` |
| `focused-final.log` | `61e4af2eed301e4705f7a38b78dbbc777ec8ce966eba0aaf91a771005eb68606` |
| `real-core-final.log` | `e588d9d7de6502f6a7e990ae67541f99bcd64d4d2a414da735f3250367d5e3ac` |
| `inventory.log` | `8fbde7be273c409e7b0d98172d422fa7acc4fb74ff49bfc0838fb9f904c0402a` |
| `lint_gate.log` | `9d34ab5bc2efad4fadb7e30a2f0674d4426c54769eed8fb7fe58b6cfe61c4584` |
| `phase2_plan.log` | `ee20850a561b355e8240ab57ec1ff604439ca4f5322807e31a00dbd9139f2a48` |
| `d19.log` | `99fbe39a2df60200f49c3a6fe3687bd84a772cd584157ff47bd9863cb3395ac6` |
| `phase2_closure.log` | `7cb542353d8541b70241389de8aacb89b68f62560be26ca5edd614239624616e` |
