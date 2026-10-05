# P3.2: first-run onboarding within Settings

Code candidate `fe38ee85`, stacked on P3.1 slice-two PR #27 at
`2ffa2fa9e64a62ddbe837929b08a6b51d332e118`. Final gates used fresh detached
checkout `/home/odin/desktop-p32-final`. This evidence-only record changes no code.

## Commands/environment

Unprivileged `odin`, Node 22 from `/usr/bin`, Python 3.12 in the fresh checkout:

```text
uv sync --frozen --extra dev
npm ci --ignore-scripts
node node_modules/electron/install.js
npm run check
npm run smoke
npm run test:real-core
ODIN_SMOKE_OUT=/home/odin/p32-final-real-core.png npm run smoke:real-core
```

`test:real-core` includes `test:onboarding`. Actual Electron launches ran only
under isolated Xvfb; real core launches additionally used the reviewed separate
PID namespace, private disposable HOME/XDG and scrubbed environment. No active
workstation desktop, bus, accounts, keyring, live install or service was used.
Dependencies were installed only into repository `.venv` and `app/node_modules`.

## Results

- Typecheck/build/unit/renderer/fixture suite: **575/575**, 58 files.
- Fixture smoke: **passed**.
- Actual Broker/real-core contracts: **19/19**.
- Actual Electron onboarding E2E: **5/5**, six launches, 25.62 seconds.
- Actual fresh real-core smoke: **passed**, 22 checkpoints including every Settings section.
- Isolated narrow Python suite on the fresh candidate: **227 passed**, 10.27 seconds.
  First-run/settings/runtime/providers/management/Codex/models/provisioning/hosts/state.
- Exact source/evidence drift: **zero errors**, pending independent review.
- Fresh candidate checkout remained clean after qualification.

## Behavior and interpretation

`status.get.first_run` owns fresh/incomplete/saved/effective-ready/degraded. No
second wizard, renderer completion flag, new RPC route or system-prompt change.
The banner opens the existing Models and providers form; section re-entry retains
the section without duplicate forms. Set up later hides only the current chat
reminder, not core state or navigation. Defaults remain start-at-login **off** and
notification previews **on**, with direct General controls and preference persistence.

Effective-ready means required configuration committed and the actual owner
adopted the matching provider/model/client/settings. It is not network/generation/
quota qualification. The initial implementation incorrectly required a positive
guard/success-count gate even though the real composition has no guard. Integration
review removed that extra gate under D17 before final qualification. Actual
ProviderOwner-without-guard behavior is asserted in real-core tests; explicit
guard/breaker failures still report degraded. No probe or governor was added.

E2E drives real rendered controls and socket transport through:

- Fresh/second launch, setup later, section routing and re-entry.
- Incomplete configuration, failed provider qualification/rollback and retry.
- Stale settings revision and actual socket disconnection at save admission,
  then reconnection and retry without false commit/readiness.
- Canceled/expired device login, successful deterministic authentication,
  saved-but-not-effective second launch, explicit model adoption and degradation recovery.
- Locked and missing keyring failures, rendered Retry, recovered schema/accounts/status.
- Immediately cleared submitted secret fields and absent stored-secret readback
  in renderer HTML/fields/storage, preload results, logs, config, drafts and transcript.

The test-only auth adapter blocks outbound HTTP and supplies synthetic external
auth/keyring outcomes. Actual core ownership, journals, settings, provider graph,
rollback and adoption remain production implementations. A boolean reconstructs
known synthetic credentials on the second test launch; this is not native vault
durability evidence. No production account or token was copied or contacted.

Main retains raw device authorization material and projects only a random local
`login_id`, intended verification code and recognized URL. Both direct IPC answers
and late Broker receipts use that projection. The named verification opener accepts
no renderer URL and opens only the recognized core URL. Trusted core transport
receipts retain their existing raw device-code response for idempotency; this is
not renderer/log readback or a plaintext credential fallback. OAuth tokens and
user-entered secrets have no file-scanning exception.

## Fresh real-core screen observations

The ordinary fresh smoke has no Secret Service. Core readiness is therefore
`degraded / keyring_unavailable`; the banner visibly shows failure and Retry.
With the deterministic healthy empty vault, first/second launch remains fresh.

All Settings sections retain PR #27's actual data: local/default host and SSH
public key; real provider/model schema, Odin personality, tools/timeouts; empty
authorized memory scopes/lists/knowledge/audit/logs; unknown usage and disabled
turn-state store. Health reports actual missing runtime owners, not universal
health. Step-six Skills/MCP/background work/computer use stay unavailable.
General remains usable independently of keyring/provider readiness.

## Evidence hashes

Logs and screenshots remain outside Git under `/home/odin`:

```text
bf5b89ae23c96744ce38e00b5fcb53156b35ffa8105ec142ace8a37ad3ee542e  p32-final-check.log
6fee43f5de34d5ecd6c7052765b377a55f1adcb56c1dd0d0e9e053edbb61ea13  p32-final-fixture-smoke.log
5936562c556ae2bfa6a4c28a01c7352fda84449c9c77f3b11cf8b43e09a6e213  p32-final-real-tests.log
4b8804d0b131c1e6fe290ff75a46b21d7ec1c216607d978fecf38627ff4f7fbe  p32-final-real-smoke.log
3bdba7dd371cc6e4b5db2664dbcc0b0b9581daa322a5d9e799c7c864b4084586  p32-final-python-tests.log
3064dc47e3855997fb9c571ef8f09cbb8c9443cebe18b78bc1ec17a2c9c7fcc2  p32-final-real-core-evidence.json
cabcdbbd2c5ae6dc0260889b077ae278cbbd12e8abf348486338a9ad57cead15  p32-final-real-core.png
ee9b665871c76e0e5da4b08c96c4dfe5eb726fd4d69abecfe4e8121c724e0029  p32-final-drift.json
```

## Cleanup and limits

App exits used normal runtime shutdown/parent EOF. The isolation runner tears down
namespace children and removes disposable HOME/XDG; E2E removes its control/result
files. No live service restart/deploy/desktop interaction occurred. These are
source-build behavioral proofs, not native Secret Service unlock/durability,
production OAuth, generation, Orca/keyboard, portals, packaging or full Phase 3 exit.
