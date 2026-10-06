# P3.1 slice 4: real step-6A management integration

This is the original round-0 evidence at `667e6a47`, not the current feature
contract. PR38 review found the missing D2 skill-Test port. The subsequent fix
publishes and executes `skills.test`; its new smoke and qualification evidence
are recorded in `pr38-review1-validation.md`. Historical refusal observations
below are preserved, not claimed as the corrected behavior.

## Source and scope

- Base: `phase-2/services-part-a@964482858ba7b9f11fa0a6ee34d0f1ee01d1abce`.
  Main was merged, not rebased, and pushed before this branch was created.
- Qualified runtime/app source: `667e6a47543070d3030221129d6827337047dea7`.
- Fresh detached worktree: `/home/odin/desktop-p31-slice4-fresh`.
- Raw evidence: `/home/odin/desktop-p31-slice4-evidence/`.
- This evidence commit changes only documentation and maintenance associations;
  no runtime/app source changed after the qualified SHA.

Existing named bridge methods now work with actual Skills/MCP ownership, browser
health observations and the real computer management envelope. MCP writes bind
the displayed profile settings revision and never replay automatically on stale
binding. Per-server keyring refusals do not hide unrelated servers. Saved MCP
schema fields refresh after management writes so the same screen does not show
contradictory old values. Failed skill modules remain visible and removable.

Real `computer.reconcile` sends exact session ID and generation, no acknowledgment
or additional confirmation. It does not assert input release from success or a
closed state. Browser `retry_available` observes the existing wired next-use seam,
separately from actual qualified readiness; no new RPC or launch is introduced.

## Fresh-checkout gates

Locked setup: `uv sync --frozen --extra dev`, `npm ci --ignore-scripts`, explicit
`node node_modules/electron/install.js`. Python 3.12.3, Node 22.23.3. No system
packages installed. Gates ran as unprivileged `odin`, with scrubbed HOME/XDG,
separate PID namespaces, and Electron only on Xvfb/private session buses.

| Gate | Actual result |
| --- | --- |
| `npm run check` | Typecheck/build pass; 66 files, **639 tests passed** |
| `npm run smoke` | Fixture regression passes, screenshot retained |
| `npm run test:real-core` | 3 files, **26 tests passed** |
| `npm run smoke:real-core` | Pass, ready real core, 19 rendered checkpoints |
| `npm run test:a11y` | **16 passed**, 0 skipped, 0 unexpected, 0 flaky |
| Browser owner engine regression | **33 passed**, isolated namespace |
| Drift / lint / plan | 0 drift errors; 0 new lint findings (7 inherited); plan pass |

The check and fixture smoke commands were launched through `launchIsolated` from
`app/scripts/real-core-isolation.mjs`. The other app gates use their existing
isolation runners. Browser tests used `unshare --mount --pid --fork --mount-proc
--kill-child`, dropped to `odin`, private HOME/XDG and explicit pytest plugins.
Namespace gate exit and post-gate checks found no remaining checkout-owned
Electron/core/MCP child; fresh tracked files remained unchanged. Screenshot and
JSON evidence files exist. No active desktop, live service or `/opt/odin` changes.

## What the real smoke observed

- Validated, saved and read `slice4_constant`, rendered Loaded with **0 runs**.
- Requested `skills.test` through the named bridge and received genuine
  `capability_unavailable`; the UI says Test is unavailable and disables it.
  **The skill was not executed.** 6A intentionally withholds request-test admission.
- Saved `slice4_local` using the real MCP manager and harmless local stdio fixture,
  enabled it, completed initialize/tools discovery and refresh, and rendered
  `mcp_slice4_local_constant` in the expanded tools list. No tool call or remote
  MCP endpoint was needed. The fixture was disabled/deleted before normal exit.
- Browser: disabled, ready=false, retry_available=false for this fresh profile.
  Real-core contract and browser-owner cases additionally cover enabled/missing
  bundle with ready=false/retry_available=true and qualification failure/retry.
- Computer: session=null, management_available=true, foreground_available=false,
  input_supported=false, native_qualified=false, dispatch=none.
- Account keyring absence stayed a distinct `keyring_unavailable`, never invented
  account rows. Default provider credentials were not configured or contacted.

Contract tests also exercise skill CRUD/toggle/config redaction, failed-module
deletion, MCP limits/global and per-server enable/reconnect, stale receipt identity,
server-local relocked-keyring reasons and secret non-readback. Renderer tests cover
exact-generation reconciliation, late receipts without replay and unknown-release
outcomes; a disposable real core refuses unknown recovery identity honestly.

## Evidence hashes

| Artifact | SHA-256 |
| --- | --- |
| `check.log` | `1449e8ed003e664831d59a5285890e2bfc5ecb8a37668c37120112d54c332a4d` |
| `fixture-smoke.log` | `e386be254ec7577f8d0cf453ee96aa2ae0a5da2095f947480a37143e02e2b01a` |
| `real-core-tests.log` | `d4b56249590ff31c883fd7166d400c7d1ab75caf6196bb8353240eaf46e75ef6` |
| `real-smoke.log` | `f27d4e2a94fd846a4a2d16aa26ab24739a54853ea105d007251e3aa5d5b3050f` |
| `a11y.log` | `c839cfd5d31863aca09bf6935cf6a857c732b46b2e4a1460f70495b5df79ca74` |
| `browser.log` | `480c126ce22293a595a0aaccd963f37115eaaf5156ff10bfed935572f74dc336` |
| `real-evidence.json` | `5a80c3fe0322a8962ece5ec730484b5db4115a7ebb53e9e1afe00061670d483c` |
| `accessibility.json` | `7efd96336cae989d717b69d779112ce866fa1675772088279dee8ad8a2791ae6` |
| `real-settings-5.png` (Skills) | `704d0244b1ea2dfd053e95f408c7226a63ffe5bb8a7229edf862e2cf56e71056` |
| `real-settings-6.png` (MCP tools) | `0f2720ded5348aea5f7c7e525b61507f4b1ea2394ed17b246b82faa9e3810fee` |

## Limits and review

This is not full P3.1 closure, native input/Orca/Wayland/package qualification or a
successful provider generation claim. A11y retains axe incomplete findings and
Chromium AX evidence; passing automated audits does not prove spoken screen-reader
behavior. Isolated desktop portal/FUSE/PipeWire diagnostics remain in the a11y log;
they did not skip or fail gate cases. No accounts, remote MCP servers or native
sessions were used. Browser next-use retry is not advertised qualification.

An independent read-only review questioned pending-before-start retry state. No
change was needed: management capabilities/listener publish only after startup
settles, and catalog dispatch cannot use the retry seam before it is wired. The
status Boolean deliberately describes that wired seam, not hypothetical direct
internal calls before service startup. Independent maintenance review remains
pending (320 entries); no approval was manufactured.
