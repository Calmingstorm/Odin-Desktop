# P3.3 part 2: native VM continuation, gate OPEN

Source candidates: freshly fetched main `cd52a8e2b055a9c4abc051a49566b9daf3e1bd79`.
Branch `app/p33-native-part2` does not adopt unmerged PR54. D17 and production
authority are unchanged. Native helpers are source-development scripts only.

Raw evidence and current-main candidates remain outside Git under
`/mnt/storage/odin-desktop-evidence/lane7-p33-native-20261006/`.
The draft is opened after Cinnamon, before GNOME/KDE. Those rows are pending
and will be appended, not assumed passed.

## Cinnamon/X11 initial row

- Actual installed current-main `.deb` starts a sandbox-enabled renderer and
  bundled real core under odq. Native AT-SPI reads the rendered core-ready UI.
- Native Ctrl+W hides; app/core survive. Native XEmbed child is 24x24 and
  right-click produces an actual native popup. **Open/Exit acceptance remains
  unqualified**: source helper's two native AT-SPI cases fail bounded target
  discovery. No callback is substituted and neither case is retried.
- Source real-core helper: two cases pass (autostart API enable/disable and
  close retains exact process identities); two native tray cases fail.
- Notification-fixture attempt fails before readiness: the guest source archive
  omitted `app/fixture-core/fixture_core.py`. No OS acceptance, appearance or
  click-through is claimed, and the failed attempt is retained.
- Actual packaged native Start at login checkbox is accepted. It writes
  `/opt/Odin/odin-desktop --hidden`. A real guest display-manager restart creates
  a new active login and launches one bundled core, hidden, with linger off.
  Launcher reopen exposes the native window. No host session was touched.
- Busy actual dpkg reinstall refuses. After normal launcher Exit, the same
  current-main candidate reinstalls successfully and preserves autostart and
  clean app/core receipts. This is guarded same-version replacement, not a
  previous-version migration claim.
- VM-only `rtcwake -m mem -s 12` loses the guest agent and does not regain it.
  **Sleep/wake and D12 remain unqualified**. Emergency force-stop of only
  `odq-cinnamon` is verified STOPPED; no host suspend or input occurred.

Keyring is degraded/locked in the real native UI. No credentials were supplied.
Missing schedule/Work integration is not replaced with a fake service.
PNG captures are retained; image inspection is unavailable in this agent,
so screenshots alone are not described as proof of human appearance.

## Candidate identity

| Artifact | SHA-256 |
|---|---|
| current-main `.deb` | `b43517d5b224501ca275f7bfa963673743a4e568c23fdfe38d22e0b8675b44d2` |
| current-main AppImage | `3205d674fd7f3b0aabdb038e9df5331ef7138d0738c1e1da929eac1c1217ecbc` |

Both candidates built successfully but **failed package qualification**:
extracted `.deb` manifest reports `apparmor-profile` mismatch; AppImage reports
`app.asar` mismatch. Separate package qualifier aborts on its missing Python
preinstall tool. These are not accepted release/native candidates. Observed
guest execution is partial evidence, not a waiver of their failed gates.

Fresh source/build and package gates are recorded separately as they finish.
P3.3 is not closed by partial native rows or source fixture results.
