# P3.3 source-app native guest helper

Parent/operator owns all VM lifecycle and package tests. These helpers do not
start/stop VMs, install packages, change production code, claim D-Bus service
names, or install fake notification services. They operate only a marked VM
as nonroot `odq` against the existing guest graphical session.

## Preconditions

- Hostname `odq-cinnamon`, `odq-gnome`, `odq-kde`, or `odq-hyprland` and detected VM.
- Root-owned non-writable `/etc/odin-desktop-qualification`, exactly
  `odin-desktop-qualification-v1` followed by newline.
- Actual odq session environment, local `/run/user/<uid>/bus`, runtime ownership,
  local X11 socket, plus native Wayland socket for Wayland sessions.
- Guest Python packages `python3-pyatspi`, `python3-dbus`, GI/GLib; working guest
  accessibility bus and actual desktop notification daemon. No daemon fallback.
- Built checkout `app/out`, matching `app/node_modules` including Electron and
  Playwright. Engine Python supplied as `ODIN_DESKTOP_ENGINE_PYTHON`; real engine
  environment for `--core=real`, `dbus-next` for existing notification fixture.
- Fresh mode-0700 odq-owned `/tmp/odrc-<run>` HOME. The existing notification
  fixture independently requires this prefix.

## Run, inside guest only

Run collector **outside** the app's PID namespace with the real session env,
as odq, using `/usr/bin/python3 native-p33-probe.py
--socket=/tmp/odrc-<run>/native.sock`. It emits a ready JSON line. Keep stdout/
stderr in the external evidence directory. Use the parent's root guest-session
launcher to discover/scrub session environment; never reuse host display/bus.

Run Node in a **real new guest PID namespace with mounted /proc**, dropping to
odq. Preserve actual original guest namespace in
`ODIN_REAL_CORE_OUTER_PID_NS`; set `HOME=ODIN_REAL_CORE_ROOT=/tmp/odrc-<run>`.
Do not fabricate namespace values to enable the existing source-only seam.
The helper calls the same VM guard before launching:

```
node app/scripts/native-p33-guest.mjs --core=real --socket=/tmp/odrc-<run>/native.sock --out=/tmp/odrc-<run>/result.json
```

Repeat with a new root and `--core=notification-fixture` for exact notification
DOM routing. No test authority is added to production. The helpers require
the existing source `ODIN_APP_E2E` seam. Wayland launches explicit native
`--ozone-platform=wayland`; Xwayland DISPLAY remains required by the seam but
is not used to silently downgrade Electron. Missing seam means failure.

The collector accepts a JSON line `{"operation":"stop"}` over its owned
Unix socket, responds, closes and unlinks only its own socket. Otherwise it
expires after 15 minutes. It never kills the desktop or other processes.

## Evidence and limits

`result.json` separates real-core lifecycle from fixture conversation/ack
delivery. Native notification acceptance alone is not appearance. Appearance
requires an accessible marker owned by the real daemon; click requires native
AT-SPI action, real daemon `ActionInvoked`, and exact older message DOM
highlight/viewport/jump-banner witnesses. No simulated notification signals.

Tray Open/Exit first locates a real native tray menu and acts on its accessible
items, not Electron callbacks. X11-only observed rectangle right-click is
allowed when no menu action exists; no coordinate fallback on Wayland. Missing
AT-SPI targets/actions report failure, never a synthetic pass. Native process
witnesses use UID, PID, start ticks, executable and namespace. Clean Exit also
requires journal accepted shutdown and removal of the owned core socket.

GNOME no-tray checks close-keeps-running and genuine second launch reopening;
Exit uses renderer input Ctrl+Q, explicitly not an OS keyboard proof. Autostart
uses the production renderer API and validates enable/disable entry in the
throwaway config; it does not claim a new login happened. AppImage and installed
package acceptance are separate parent-owned cases.

All raw evidence stays outside Git. Commit only these compact helpers and
small summaries/manifests if reviewed. Host syntax checks and mocked guard tests
are not a native qualification result.
