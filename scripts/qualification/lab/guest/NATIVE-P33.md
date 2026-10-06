# P3.3 source-app native guest helper

Parent/operator owns all VM lifecycle and package tests. These helpers do not
start/stop VMs, install packages, change production code, claim D-Bus service
names, or install fake notification services. They operate only a marked VM
as nonroot `odq` against the existing guest graphical session.

## Preconditions

### Reproducible guest source archive

Build the source bundle from the checkout being qualified; do not reuse a
manually assembled or cached tar:

```
python3 scripts/qualification/lab/guest_archive.py --output /path/to/evidence/native-p33-guest.tar.gz
```

The builder's reviewed manifest includes the guest session/smoke/probe scripts,
both desktop-shell provisioning helpers, the Node guest runner and its display
helper, the notification fixture and private receiver, and
`app/fixture-core/fixture_core.py`. It refuses missing/symlinked inputs and
never overwrites an existing output. Validate changes with
`pytest -q tests/test_native_p33_guest_archive.py`; this uses tiny synthetic
files and does not archive dependency trees.

The archive is not a complete application image. Provision the same checkout's
`app/out` and `app/node_modules` (including Electron and Playwright) separately,
plus the explicit guest engine Python/runtime selected by
`ODIN_DESKTOP_ENGINE_PYTHON`. Verify these correspond to the source revision;
never bundle all of `node_modules` into this helper archive or silently fall
back to stale files. Guest OS Python modules and desktop packages are installed
through the guest provisioning recipe below.

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

Tray Open/Exit opens the actual native popup, then searches only the app-owned
accessible tree, bounded in time/depth/count, for showing menu items in a showing
menu. Activation uses native AT-SPI actions, never Electron callbacks. Without
a native menu action, X11 may right-click one viewable app-owned XEmbed icon:
`xwininfo` provides its actual rectangle, `_XEMBED_INFO` identifies embedding,
and XRes validates the X-server client PID (guest `libxres1` required). If GTK
does not export accessible items, a newly appeared, viewable, app-owned
override-redirect `_NET_WM_WINDOW_TYPE_POPUP_MENU` window is required. Only after
native focus is verified on that exact popup does genuine keyboard Home/End,
Return select Open/Exit; guest `xdotool` is required for this route. The runner
must still prove real visible state or clean process/socket/receipt shutdown.
No guessed
coordinates or Wayland coordinate fallback. The runner passes exact inner PID,
UID, start ticks, executable and namespace; collector maps through kernel NSpid
and validates accessibility-bus GetConnectionUnixProcessID, never treating an
inner accessible PID as an outer /proc PID. Missing/ambiguous ownership or popup
targets fail explicitly. An absent notification daemon does not block tray or
no-tray lifecycle; only the notification row fails explicitly. Clean Exit also
requires journal accepted shutdown and removal of the owned core socket.

For failed-row-only runs, `--cases=tray-open,tray-exit` hides the initial window
as setup without rerunning autostart/close rows. `--cases=notification,tray-exit`
with `--core=notification-fixture` skips duplicate Open. Allowed cases are
`autostart,close,tray-open,notification,tray-exit`; invalid/duplicate selections
are rejected. Omission retains full qualification; omitted Exit is ordinary
fallback cleanup, never a native Exit pass.

GNOME no-tray checks close-keeps-running and genuine second launch reopening;
Exit uses renderer input Ctrl+Q, explicitly not an OS keyboard proof. Autostart
uses the production renderer API and validates enable/disable entry in the
throwaway config; it does not claim a new login happened. AppImage and installed
package acceptance are separate parent-owned cases.

All raw evidence stays outside Git. Commit only these compact helpers and
small summaries/manifests if reviewed. Host syntax checks and mocked guard tests
are not a native qualification result.
