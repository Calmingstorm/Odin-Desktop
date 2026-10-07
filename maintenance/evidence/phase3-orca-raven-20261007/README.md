# Orca task matrix on the Raven UI

A re-run of the P3.4 Orca matrix after the Raven UI (#84, #85, #86) and the notification jump fix (#87), on main
`dae1e369`. Same seven task groups, same lab VMs and runner (`scripts/qualification/lab/orca.py`), one invocation per
desktop and one attempt per group, with no retries, skips or waivers.

| Task group | Cinnamon/X11 | GNOME/Wayland | KDE/Wayland |
|---|---|---|---|
| Bridge, named Message and native button role | PASS | PASS | PASS |
| Chat/results, Attach/cancel, Save/copy/report | PASS | PASS | FAIL |
| Conversation, child/modal/search | PASS | PASS | PASS |
| Busy, Steer, consumed/queued, Stop/Resume, unknown/no-flood | PASS | PASS | PASS |
| All eleven settings, names/roles/states/errors/secret | PASS | PASS | PASS |
| Delayed history/search retains focused message | PASS | PASS | PASS |
| Explicitly provisioned real-core services | PASS | PASS | PASS |
| Total | 7/7 | 7/7 | 6/7 |

This matches the 2026-10-06 result in `../phase3-orca-final-20261006/`. KDE fails the same way: "Owned active native
dialog required: Attach files". The KDE portal file chooser is not visible to AT-SPI, which is the existing blocker,
not a Raven regression. The KDE row is not acceptance.

## The first Cinnamon attempt

The first Cinnamon run failed all seven groups at launch: the test app's core stopped repeatedly ("Core stopped
unexpectedly. Cleanup unknown; replacement must acquire the real profile lock"), and the new UI reported that
correctly. The cause was lab state, not the app under test. P3.3's native tests on 2026-10-06 (#59) had installed
the packaged `.deb` in `odq-cinnamon` and enabled Start at login for `odq`, so a hidden packaged Odin started with
the session. Inside that VM only, the packaged Odin was exited through its own `--exit` launcher action, and
`~odq/.config/autostart/odin-desktop.desktop` was moved to `~odq/.config/autostart-disabled-orca-rerun-20261007/`.
The package stays installed. After a VM restart, the Cinnamon row was run once more: 7/7. The failed attempt is kept
with the external evidence and in `summary.json`.

## Artifact and evidence

- Staging from main `dae1e369`: `app/` and `src/` (as `engine/src`) by `git archive`, `npm ci` with Electron's
  install step, the host's Node v22.23.3 as `bin/node`, and the engine's locked runtime dependencies
  (`uv export --frozen --no-dev --no-emit-project`, then `uv pip install --target engine/site-packages
  --require-hashes --no-deps`). The packer refused two staged dependency files, which were removed from the staging
  copy only: `app/.npmrc` (a `legacy-peer-deps` setting) and `app/node_modules/siginfo/.travis.yml` (an upstream
  deploy configuration with an encrypted key).
- Artifact SHA-256: `478abb490721a72ecae3ca12b73c98b2ab8abdb45f4d7f87e0c4dd37c32e5d7f`. Manifest SHA-256:
  `42afc55dfe3f85f31838a9aa03ca4d9decaafa2fb679fae98a86934d4b638d13`. Orca 46.1 in every guest.
- In Git: each desktop's guest proof, `summary.json` (every task's status and first error line), and
  `external-SHA256SUMS`.
- Outside Git, on the host: `/home/calmingstorm/odin-desktop-evidence/orca-raven-20261007/`, with the complete task
  reports, traces, guest screenshots, Orca and speech logs, the lifecycle logs and the pack log.
  `external-SHA256SUMS` covers every file there.
- Every guest proof reports its owned children and descendants exited and its cgroup removed. One VM ran at a time,
  and each was stopped after its run.

This qualifies the source-build Orca tasks on Cinnamon and GNOME. It is not packaged-app, audible-output or
braille qualification, and KDE's native chooser remains a blocker.
