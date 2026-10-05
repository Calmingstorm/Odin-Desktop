# P3.1 slice 2: real settings and management

Code candidate `105f9e0e83fc904c351e6a6fa7443fd37513ae67`, rebased onto merged
Phase 2 step five at `main@566b7954`. This evidence-only record adds no source changes.
Final gate used fresh detached checkout `/home/odin/desktop-p31-slice2-final`.

## Commands and isolation

As unprivileged `odin`, Node 22 from `/usr/bin`, repository Python 3.12:

```text
uv sync --frozen
npm ci --ignore-scripts
node node_modules/electron/install.js
npm run check
npm run smoke
npm run test:real-core
ODIN_SMOKE_OUT=/home/odin/p31-final-real-core.png npm run smoke:real-core
```

Electron used isolated Xvfb with disposable HOME/XDG, no inherited desktop display or bus.
Real engine tests/smoke additionally used the reviewed unprivileged PID-namespace runner.
No production credentials/accounts, live service, active desktop or deployment was used.
Normal exits used the app Exit/runtime.shutdown and parent-EOF path. Runner teardown
removed private profiles and terminated namespace children; no unisolated fallback.

## Results

- Typecheck, production build and fixture/unit/renderer suite: **554/554**, 56 files.
- Fixture Electron smoke: **passed**.
- Actual Broker/real-core contracts: **19/19**, two files, 38.23 seconds.
- Actual Electron/real-core smoke: **passed**, 22 named checkpoints, every Settings section.
- Additional narrow Python regressions: **78 passed** in isolated profiles.
- Exact maintenance drift: zero errors, pending independent review. No source/safety
  corpus or admission-policy exception was manufactured for qualification.

## Fresh real-core observations

| Section | Observed result |
| --- | --- |
| General | Local preferences available; start-at-login off; notification previews on. |
| Models and providers | Real schema and configured default model; Codex runtime unavailable without credentials; Ollama/compatible disabled. Missing keyring returns distinct account failure with Retry, not a successful empty list. |
| Personality | Actual Odin preset and retained built-in presets. |
| Tools | Real built-in inventory, enabled/disabled/backend-unavailable states and real timeout settings. Enabled does not imply an available backend. |
| Skills | Explicitly unavailable until step six. |
| MCP servers | Explicitly unavailable until step six. |
| Hosts and trust | One local `localhost` at `127.0.0.1`, local trust, configured/effective default `localhost`, actual provisioned Ed25519 public key and fingerprint. |
| Scheduled and running work | Explicitly unavailable; no invented schedules or running rows. |
| State | Empty global and authenticated personal scopes, empty named lists and knowledge sources; actual on-demand context reload. No fixture memory. |
| Records | Empty audit/logs; signing disabled is unverified, not intact; usage unknown with history unavailable; turn-state store not enabled; actual health reports missing owners and one configured host; computer use unavailable. |
| Other | Real schema-derived miscellaneous profile settings, if present. |

Read/write behavior covers settings revisions/receipt replay, provider saves versus adoption,
main-model stale rollback, agent models, personality, tools/timeouts, authorized memory,
list corpus read/delete, knowledge versions/restore, local host/trust management and records.
Deterministic Codex authentication uses a localhost auth service and ephemeral keyring boundary.
Secrets are excluded from responses/events/diagnostics and disposable profile files.

## Evidence hashes

Files remain under `/home/odin` outside Git; screenshots/JSON include disposable paths only.

```text
d65e96c729d586d09dc353caa39c5de87bb25f7d559a303a94e39b2968680cc9  p31-final-check.log
d529d62d89a4ebb0a760bab10b32870402c23236b68a9eb7a5350f38616445c3  p31-final-fixture-smoke.log
fdc1e41c65e437dec501f2e20777079ccd0143abc605742093664c2ede675abf  p31-final-real-tests.log
41adf4ed108a7d86327212d610bee4e5466303812b8019128f50cef30658a692  p31-final-real-smoke.log
0587a1a0c654ba1ad1f999fa092ab441868d6722250bd146f470f02d62cdbb9b  p31-final-real-core-evidence.json
7e574da9550b3a1d2e4c90f09bbe61d397248387ba3fd95ba3dcbd0f0fcb96e9  p31-final-real-core.png
```

## Limits

This is a settings/runtime slice, not Phase 2 exit or full P3.1 completion. Model adoption
is not successful generation/endpoint health. Temporary keyring tests are not native Secret
Service unlock qualification. Existing legacy remote-host enrollment remains unchanged;
no import of another installation is supported. Xvfb does not qualify native lifecycle,
portal consent, keyboard accessibility/Orca or package ownership.
