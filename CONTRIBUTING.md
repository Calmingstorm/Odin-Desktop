# Contributing to Odin Desktop

The project is implementing the approved plan, authorized by Aaron on 2026-10-04 (brief, "GO"). These rules bind
everyone working here, Claude and Odin alike.

## Where work happens

- **This repository only.** No commits, branches, PRs or issues in `Calmingstorm/Odin`. Odin's code is copied *from* a
  pinned upstream Git object, never edited upstream as part of this project.
- **Never touch a live install.** No changes to `/opt/odin`, its data or config, or any running service, and no
  restarts. Never copy from `/opt/odin`'s working tree.
- **The repository stays private** (D16).

## Layout

| Path | Contents | Owner |
|---|---|---|
| `src/`, `tests/` | The engine, kept at Odin's module paths so upstream fixes port as the same diff | Odin |
| `maintenance/` | Baseline record, source manifest, port ledger, safety manifest | Odin |
| `scripts/maintenance/` | Drift-report and manifest tooling | Odin |
| `app/` | The Electron app: main process, preload bridge, renderer | Claude |
| `docs/design/` | The approved design | per-file owner |

## Changes

- **Code goes through a branch and a PR.**
  - Pull `main` first, then branch.
  - Odin's PRs are reviewed by Claude, and Claude's by Odin. Nothing merges without that review.
  - Delete the branch once it's merged.
- **Design docs** may still be edited directly on `main`, by their owner only.
- **Commits** carry no attribution trailers (`Co-Authored-By`, session footers).
- **Tests ship with the change** that needs them. Run the touched tests while working, and the full suite at each gate.
- **Tests exercise real code behaviour.** Never write a test that reads a human-written document (`.md`, `.sh`) to assert
  its wording, or one that only checks that a file exists. Documents used as data by real code, generated output
  checked against its generator, and machine-readable plans the tooling consumes are fine.

## Running tests safely

Odin's suite includes process-group tests. Run bare, these can signal every process the user owns, including a live
Odin or the desktop session. **Always run the suite in an isolated PID namespace:**

```bash
sudo unshare --mount --pid --fork --mount-proc --kill-child \
  sudo -u "$USER" env -u DBUS_SESSION_BUS_ADDRESS -u XDG_RUNTIME_DIR .venv/bin/pytest -q
```

- Never point a test at `/opt/odin`, live config or data, or a real workspace.
- Never use destructive or attack commands as test input. Test failure paths with harmless failures or stubbed
  primitives.
- Computer-use and native-lifecycle proofs run only in hard-isolated graphical environments, never on an active desktop.
- Installing dependencies into this repo's own `.venv` (and `node_modules` for `app/`) is fine. System package installs
  need Aaron's OK first.

## Upstream maintenance

The baseline, port ledger, cadence and drift gates are defined in
[`docs/design/maintenance.md`](docs/design/maintenance.md). CI fails on any unexplained divergence in guard, classifier,
governor or containment code.
