# P4.1 Chromium resource

`app/packaging/python/chromium.py` exports
`stage_chromium(bundle_root: Path, cache_dir: Path) -> dict`. The root is
`resources/runtime`. Metadata paths are relative to that root. Repeated staging
validates the complete existing tree against the pinned archive, including bytes,
modes and closure. Corrupt trees fail rather than being silently overwritten.

## Pinned inputs and licenses

`app/packaging/python/chromium.lock.json` records exact download URLs, SHA-256,
version, revision and license input hashes. Staging verifies the Playwright wheel
against `uv.lock`, then verifies its `browsers.json` matches the resource.
Cached inputs are hashed on every use and corrupt caches fail closed. Downloads
are build-only. There is no runtime installation/download path.

Playwright 1.63.0 selects Chromium Headless Shell revision 1243, version
153.0.8010.12 for Linux x86_64. This is the actual Playwright-provided headless
Chromium, not a workstation executable. The staged archive carries 287 files,
272,533,063 uncompressed bytes, including `LICENSE.headless_shell` with Chromium's
BSD-3-Clause license and complete bundled third-party notices.

The alternative full Chrome for Testing archive includes proprietary Widevine
whose included license forbids distribution without a separate agreement. This
bundle deliberately uses the matching headless-shell archive, which does not
contain Widevine. Firefox/WebKit, media recording/FFmpeg and interactive full
Chrome are not bundled or claimed here. Playwright itself remains an Apache-2.0
locked runtime dependency.

## Runtime and sandbox

`BrowserManager` derives the absolute executable from
`ODIN_DESKTOP_BUNDLE_ROOT/browser/chromium/chrome-headless-shell-linux64/chrome-headless-shell`.
Explicit `bundled_executable` remains supported. Missing resources fail before
Playwright starts, rather than falling back to PATH or user browser caches.
The production launch sets `chromium_sandbox=True` and contains neither
`--no-sandbox` nor `--disable-setuid-sandbox`. Sandbox initialization failure is
reported as a launch failure, never retried with weaker flags.

## Observed evidence, 2026-10-05

- `tests/packaging/test_chromium_staging.py` and `test_chromium_runtime.py`:
  13 tests passed inside an isolated PID/mount namespace. These exercise hash
  rejection, cache-only staging, archive traversal/symlink/special-file rejection,
  mode normalization, lock drift, metadata, repeat staging/corruption and the
  actual runtime launch arguments.
- Including the existing browser automation tests, 65 passed and one skipped
  (the missing-Playwright import test skips when Playwright is installed).
  The broader browser wait-timeout module still has an unrelated removed-engine
  test importing `src.discord.client`; that module is absent from Desktop's core.
- A repeated stage over the real 287-file resource completed with URL opening
  explicitly disabled, returning identical metadata after full byte/mode/closure
  verification.
- `tests/packaging/chromium_offline.py` ran using the staged Python 3.12.11 with
  `-I -B` and installed `src.tools.browser.BrowserManager`. A separate unprivileged
  `hyprlab` user, empty HOME, absent browser cache, `PATH=/nonexistent`, unset
  DISPLAY/DBus/XDG runtime, read-only runtime bind mounted at a path with spaces,
  and a network namespace with no external interface proved first use. The page
  title was `Python D14 offline`; a real 12,701-byte PNG was rendered. The renderer
  had `Seccomp: 2` and `NoNewPrivs: 1`. No no-sandbox flags appeared.
- `tests/packaging/chromium_offline.cjs` independently exercised the staged
  Playwright driver's Node runtime against the same Chromium resource under
  equivalent isolation: version 153.0.8010.12, expected DOM/title, 8,385-byte PNG,
  renderer seccomp and NoNewPrivs verified.
- Chromium main executable's ELF symbol requirement is GLIBC_2.25; this is not
  the whole-app glibc floor. Host `ldd` found no missing shared libraries, but
  distribution native-library qualification remains the parent candidate gate.

Metadata: `/home/odin/desktop-p41-stage/chromium-metadata.json`. Evidence logs:
`chromium-python-offline-proof.log` and `chromium-offline-proof.log` alongside it.
No live service, `/opt/odin`, active workstation desktop, package install or
native desktop backend was used or qualified by these proofs.
