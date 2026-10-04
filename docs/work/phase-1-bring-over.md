# Phase 1 work order: bring-over

Assignee: **Odin**. Reviewer: **Claude**. Authorized by Aaron's go (brief, "GO", 2026-10-04).

**Scope:**
- [`maintenance.md`](../design/maintenance.md) section 3, steps 1 to 3;
- the **foundation** part of step 4: profile, paths, secrets, owner authority and capability publication.

**Out of scope:**
- request, control and durable-surface wiring (Phase 2);
- the Electron app under `app/` (Claude).

Follow [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

## Requirements

### 1. Baseline

- **Commit.** Use Odin release **v4.13.0, `cd7530906e9cfa10a0fa900247d7ce2a8bb33e25`** (the current stable release; its
  `src/` is identical to master `3849d917`).
- **Source.** Copy from a Git object of `https://github.com/Calmingstorm/Odin` at that tag (a fresh clone or
  `git archive`), never from `/opt/odin`'s working tree.
- **Record.** Write `maintenance/baseline.md` with the fields in maintenance.md section 2.

### 2. Source manifest

`maintenance/manifest` (choose the format) lists, for every selected and excluded path:
- the reuse verdict;
- the upstream digest;
- the destination path;
- associated tests, fixtures and assets;
- the dependency origin;
- a reason for every exclusion.

### 3. Exact copy

- **keep-as-is** modules and their tests are copied byte-identical at Odin's paths (`src/…`, `tests/…`).
- **keep-with-adaptation** files are copied unmodified first, in their own commit, so every later adaptation is a
  reviewable diff.

### 4. Strip

Remove everything the reuse map marks **strip**:
- the Discord gateway, cogs and social controls;
- the Discord-only tools: `set_permission`, `add_reaction`, `create_poll`, `purge_messages`;
- tiers, roles and user grants;
- the server API and token inventory;
- obsolete config, UI and dependencies, including `discord.py` unless a retained capability truly needs it.

Removal covers registrations, schemas, config fields, imports and dependencies, not just visible entry points. Record it
all in an exclusion manifest.

### 5. Foundation adaptation (step 4, foundation part only)

- **Paths.** Desktop profile, data, cache and secret paths, using XDG roots. Fresh state only; no import (D5).
- **Authority.** Owner authority replaces tiers and user grants. The governor, host trust, workspace fences, output
  authorization and effect-uncertainty semantics stay intact.
- **Capability publication.** An unconfigured feature publishes no tools. Bundled capabilities (browser, PDF, search,
  computer use) are required dependencies, not optional extras (D14).
- **Wording.** Apply the D7 substitutions **exactly**:
  - [`prompt-changes.md`](../design/prompt-changes.md) parts A to C, where line 66 is
    `You are {bot_name}, an autonomous execution agent.`;
  - the two guard-file lines;
  - the round-3 C1 to C7 inventory, including `read_channel` becoming `read_conversation` with no conversation-ID input.

  Nothing else in the prompt, guard or classifier text changes.

### 6. Maintenance tooling and records

Per maintenance.md sections 4 and 5:
- `maintenance/ledger` (index of upstream commits after the baseline: none yet);
- `maintenance/safety-manifest`;
- a drift-report tool in `scripts/maintenance/` that runs offline against the pinned baseline object. It reports
  shared modules matching byte-for-byte, ledgered adaptations, and unexplained divergence, and fails on unexplained
  divergence in safety-critical paths.

### 7. Tests

- Bring over all tests and fixtures for retained code, with assertions and case data byte-identical wherever the engine
  code is shared.
- Classify the suites:
  - **pass now:** neutral engine suites (guards, classifier, anti-hedging, governor, durability stores, apply_patch and
    others);
  - **Phase 2-gated:** suites coupled to the new intake, delivery or control wiring. Record each one, with the reason.
    No fake privileged shim may be built to make them pass early.
- Run them only in the isolated PID namespace given in CONTRIBUTING.md.

### 8. Python packaging inputs

- A `pyproject.toml` for the engine (Python 3.12), with a locked dependency set reflecting the strip and D14.
- Work in this repo's own `.venv`.

## Gate (what the PR must show)

- **Records.** The baseline record and manifest are complete. Every path is selected or excluded, with a reason.
- **Drift report.** It is green: shared modules match the baseline, and every adaptation is ledgered.
- **Tests.** The pass-now suites pass in isolation. Phase 2-gated suites are listed with reasons.
- **No references.** No removed feature leaves operative, model-facing or shipped references in source, resolved
  dependencies or packaging inputs. The only exceptions are the reviewed provenance, legal and fixture allowlist and
  credential-detector patterns.
- **Wording.** The prompt diff against the baseline is exactly the D7 substitutions.

## How to work

- **Clone and branch.** Work in `/home/odin/odin-desktop`. Pull `main` first, then branch as `phase-1/bring-over`.
- **Commits.** Use separate commits for copy, strip, adapt and tooling, in one PR to `main`. If it gets large, open
  stacked PRs instead, in that order.
- **Hard limits:**
  - no work in `Calmingstorm/Odin`;
  - no changes to `/opt/odin`, live config or data, and no restarts;
  - no system package installs (report any you need instead);
  - no destructive commands, even as tests;
  - no native computer-use or lifecycle runs on the active desktop.
- **Commit messages** carry no attribution trailers.
- **When done:** open the PR, then end your turn and reply on the bridge with the PR link and a short summary of what
  passed and what is deferred to Phase 2.
