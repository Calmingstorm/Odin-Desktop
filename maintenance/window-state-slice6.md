# Slice 6: window state evidence

Implemented against corrective base `db994421cfc06f42d43c7c7431f1a649c6bc5720`.
No commit, push, service operation, live install, VM, system installation or active
desktop interaction was performed by this slice.

## Ownership and behavior

- `app/src/main/window-state.ts` owns validated/versioned normal DIP geometry,
  reachable-titlebar repair, backend classification and debounced capture/flush.
- `app/src/main/index.ts` remains the single app-state writer. Each save reads
  latest geometry, notifications, appearance, no-tray notice and per-profile
  `setupReminderHidden`. Existing unrelated fields are retained. The dismissal
  IPC callbacks are `getSetupReminderHidden` and `setSetupReminderHidden`; API,
  preload and renderer changes belong to the parallel onboarding slice.
- Invalid/null/array JSON cannot break startup. Negative monitor coordinates are
  permitted, work areas are already DIP, effective minimums fit tiny displays.
- Move/resize writes debounce for 250 ms. Close-to-tray and orderly Exit/session
  logout flush. Minimized/fullscreen/maximized native bounds do not replace
  retained normal geometry. Display removal and relevant metric changes repair
  reachability, deferring native application until restored when necessary.
- Geometry/UI state persistence and native capture races are best effort and do
  not make cleanup unknown. Explicit preference/dismissal writes still return a
  save failure instead of claiming durable adoption. Draft flush failure remains
  an unknown-cleanup condition.
- The existing guarded, main-only isolated E2E hooks were extended, not exposed
  through preload or IPC. No guard predicate was weakened.

## Backend evidence and limits

The preparatory source inspection used Electron 44.5.1 / Chromium
152.0.7977.130: `shell/app/electron_main_delegate.cc` resolves Ozone through
Chromium `ui/linux/display_server_utils.cc` before platform startup;
`ui/ozone/platform_selection.cc` selects the native command-line value;
Electron `shell/common/api/electron_api_command_line.cc` reads that command line.
The implementation reads `app.commandLine.getSwitchValue('ozone-platform')`
**after ready**, without writing it. `x11` identifies the X11 backend even when
`WAYLAND_DISPLAY` is set. `wayland` restores size/maximize without x/y. Unknown
selection conservatively omits position. Environment variables, native-handle
sizes and GPU EGL displayType are not used as backend evidence.

The isolated runtime proof observed resolved `x11`, including an explicitly
misleading `WAYLAND_DISPLAY`. It does **not** qualify native Wayland, XWayland
against a real Wayland compositor, physical multi-monitor hotplug, hardware DPI,
GNOME/KDE placement policies or packaged installation. Their deterministic
geometry/backend cases have pure tests; native behavior has only Xvfb/Openbox
qualification here.

One initial maximized-restart acceptance failed: on hidden X11 startup maximize,
Electron's `getNormalBounds()` temporarily reported the maximized rectangle.
The controller now retains the known normal rectangle through maximize and
applies it on real unmaximize. The corrected isolated acceptance proves the
native unmaximized rectangle, rather than trusting the transient query or
weakening the geometry assertion.

## Verified gates (2026-10-08)

Executed as nonprivileged `odin`, never on display `:0`:

```sh
cd app
npx vitest run test/window-state.test.ts test/coverage-main-b3.test.ts test/shutdown.test.ts
npm run typecheck
npm run build
ODIN_APP_E2E_OUT=/home/odin/reviews/desktop-ui-v1/window-state-evidence \
  node scripts/lifecycle-e2e.mjs window-state.spec.ts
npx vitest run test/window-state.test.ts --coverage \
  --coverage.include=src/main/window-state.ts \
  --coverage.reportsDirectory=/home/odin/reviews/desktop-ui-v1/window-state-coverage
```

- Focused suites: **78 passed** (30 window, 32 main orchestration, 16 shutdown).
- TypeScript/Vue typecheck and Electron build: passed.
- Isolated real Electron acceptance: **4 passed**. The existing runner established
  nonroot separate PID namespace/private proc, disposable HOME/XDG, private D-Bus,
  Xvfb and Chromium sandbox. The fixture owned and terminated its own Openbox WM.
- Acceptance covers normal restart and close-to-tray; latest notifications,
  appearance and dismissal preservation; real maximize restart/unmaximize;
  minimized/fullscreen retention; corrupted/null/absurd state startup; failed
  app-state writes with orderly `process-exited`, `unsaved:false` cleanup.
- `window-state.ts` focused V8 coverage: statements **97.41%**, branches **94.89%**,
  functions **92%**, lines **97.72%**.
- `git diff --check`: passed.

External evidence: `/home/odin/reviews/desktop-ui-v1/window-state-evidence/playwright.json`
contains structured test receipts/attachments; focused HTML/JSON/LCOV coverage is
under `/home/odin/reviews/desktop-ui-v1/window-state-coverage/`.

App-state remains a best-effort single-process JSON write using the existing
writer, not a crash-atomic transactional database. No concurrent/selectable
profile capability is advertised. The final integrated full suite/release gate
belongs to the parent campaign, not this focused acceptance.
