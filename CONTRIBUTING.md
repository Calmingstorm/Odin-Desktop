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
.venv/bin/python scripts/run-phase1-tests.py tests/test_desktop_isolated_runner.py
# Reviewed pass-now selection, then the full classified qualification:
.venv/bin/python scripts/run-phase1-tests.py
.venv/bin/python scripts/run-qualified-tests.py
```

- Never point a test at `/opt/odin`, live config or data, or a real workspace.
- The launchers first check permission for the restricted, root-owned
  `/usr/local/sbin/odin-desktop-isolate` helper with `sudo -n -l`, then probe it.
  It creates private mount/PID namespaces and drops straight back to the invoking
  numeric UID/GID with no supplementary groups, capabilities or privilege escalation.
  A generic non-interactive `sudo -n unshare` launcher is tried last for full-sudo users.
  Both paths verify the separate `/proc`, PID namespace and non-root identity before
  starting tests. If neither works, no tests run. Each invocation has a throwaway HOME/XDG tree and
  a clean environment without credentials or live display/session sockets.
- CI short gates run on `odin-desktop-ci-light` (server-2 or desktop); tests and
  qualification run only on `odin-desktop-ci` (desktop). Server-2's util-linux 2.37.2
  cannot preserve the UID in an unprivileged namespace. Both jobs require a cached
  Python 3.12 before setup-python, and newer pushes cancel the old PR run.
- A current-user-only user namespace reports
  host root-owned files as overflow UID 65534. The unchanged profile, environment
  and native trust guards then correctly reject ancestors such as `/home` and
  `/tmp`. Passing the PID/identity probe does not prove filesystem qualification.
  Do not accept overflow ownership, run tests as root, or hide failing groups.
  The launchers therefore do not offer that path. The restricted helper preserves
  actual host ownership without weakening guards or permitting privileged test code.
  Cancellation kills the launcher's owned process group as the user with SIGKILL,
  which kills namespace PID 1 and its descendants. No privileged kill permission is needed.
- Never use destructive or attack commands as test input. Test failure paths with harmless failures or stubbed
  primitives.
- Computer-use and native-lifecycle proofs run only in hard-isolated graphical environments, never on an active desktop.
- Offline qualification-lab tests that deliberately create root-owned fixture
  configuration run with `scripts/run-lab-fixture-tests.py`, a fixed offline
  corpus wrapper around the unchanged PID launcher and repository `.venv`.
  Fresh fixture commands probe a single-map user namespace; ownership-retry
  cases instead require two distinct UID/GID mappings. Namespace root is never host
  root. Unsupported mappings under the restricted helper's no-new-privileges
  setting produce explicit capability skips, printed with `-rs`; never weaken
  the helper or its guards to make a fixture pass. This lane requires no Docker
  and is not native desktop or VM qualification.
- Offline Cinnamon/GNOME capture fixtures execute the test interpreter, including
  the emitted PNG validators, so Pillow comes from the locked environment rather
  than system Python. The real GNOME keyfile-compilation test skips with an explicit
  reason when `dconf` is absent; it is not a host runner requirement. Real
  compilation runs only where that capability is available.
- Installing dependencies into this repo's own `.venv` (and `node_modules` for `app/`) is fine. System package installs
  need Aaron's OK first.

## Upstream maintenance

The baseline, port ledger, cadence and drift gates are defined in
[`docs/design/maintenance.md`](docs/design/maintenance.md). CI fails on any unexplained divergence in guard, classifier,
governor or containment code.
