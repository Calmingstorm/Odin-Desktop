# C12: full Advanced with the real core

Run only after the parent declares the UI/engine tree stable. This is source-build
visual evidence, not installed/native-platform qualification. No commits or services
are changed by the runner.

As the nonprivileged `odin` account, from `app/`:

```sh
ODIN_APP_E2E_OUT=/mnt/storage/odin-desktop-evidence/ui-v1-slices5-7-20261008 \
  node scripts/real-core-advanced-capture.mjs
```

The output name does not change scope: this C12 lane belongs in the **first E/C
corrective commit before slices 5 to 7**. Each rerun gets a new external directory
and preserves previous evidence. It builds/typechecks, then invokes the existing
`launchIsolated` gate unchanged: numeric nonroot identity, isolated PID/private
`/proc`, disposable HOME/XDG, private D-Bus, private Xvfb, Chromium/renderer
sandboxing. There is no fixture or unisolated fallback. No live desktop, installer,
service or VM is used.

The engine is the exact repository production entry (`python -B -P -m src`). The
fresh disposable profile is synthetic; its schema/defaults are real. Running core
argv, cwd, PID namespace and handshake instance are recorded. No account or provider
is configured. No renderer schema injection or fixed-clock engine override is used.

Assertions cover the complete reviewed Advanced allowlist, all five categories,
exactly one owner per schema field or container, no extra rows/secrets, saved scalar
values, enum choices, numeric bounds, labels/help, no horizontal overflow, no engine
revision change, and orderly Exit. Nested schema facts retain their container owner.
The assertion imports the single pure presentation manifest, not a duplicate test
table. Node's composite TypeScript project includes that one metadata-only file.

Full-window 1180x780 dark screenshots overlap vertically from the top to the bottom
of the Advanced scroller. The receipt verifies that every owner appeared in at least
one captured viewport, with no coverage gaps or changing page height. Public
Advanced schema metadata, per-frame hashes, source/build/engine hashes, Git head and
dirty-diff provenance, receipt and manifest are stored outside Git. A source change
during capture makes the run fail, not quietly become evidence of two builds.

Harmless tests, without an engine/display:

```sh
npx vitest run test/advanced-capture-contract.test.ts \
  test/advanced-real-capture-runner.test.ts test/coverage-main-smoke-contract-b3.test.ts
```

The existing three-phase real-core smoke now also checks the full Advanced inventory
and category order instead of only `logging.level`. Its existing entry/isolation
and provider/work behavior are unchanged.
