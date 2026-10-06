# P3.3 part 2: native VM continuation, gate OPEN

Source candidates: freshly fetched main `cd52a8e2b055a9c4abc051a49566b9daf3e1bd79`.
Branch `app/p33-native-part2` does not adopt unmerged PR54. D17 and production
authority are unchanged. Native helpers are source-development scripts only.

Raw evidence and current-main candidates remain outside Git under
`/mnt/storage/odin-desktop-evidence/lane7-p33-native-20261006/`.
Draft PR59 opened after Cinnamon at `6deb7ac04acc3d7b1f85a717f5eb4629e3317fa4`,
before GNOME/KDE. All three rows were attempted once without manufacturing a
native pass. Their limitations remain below.

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
Parent inspected both PNGs: the Chat UI is rendered with core ready and the
provider/keyring degradation notice; the tray icon and native popup visibly
contain Open Odin, disabled Odin is running, and Exit Odin. Painting is proved,
not activation. The native Open/Exit failures are unchanged.

## GNOME/no-tray mandatory row

- Actual active GNOME Wayland logind session, extensions disabled (`true`),
  StatusNotifierWatcher owner absent (`false`), sysctl userns restriction `1`,
  AppArmor module active. Linger remains off.
- Native collector fails with `org.freedesktop.DBus.Error.NameHasNoOwner` for
  `org.freedesktop.Notifications`. It does not autoactivate a substitute daemon.
  No notification acceptance, appearance or click-through is claimed.
- Source runner never reaches app launch: missing Node was supplied as a guest
  project binary, then absent collector socket prevents entry. Native no-tray
  hide/relaunch/Exit are **unqualified**, not silently substituted with X11.
- Actual current-main `.deb` replacement is refused by existing Task1 unresolved
  app/core cleanup. That state is not erased. No candidate reinstall retry,
  live app adoption of PR54, or manufactured clean receipt was attempted.
- Guest stopped gracefully and verified before KDE started.

## KDE actual Wayland row

- Active KDE Wayland logind session and actual `kwin_wayland` process verified;
  sysctl restriction `1`, linger off. Current-main `.deb` installs normally.
- Actual package launch aborts before renderer/core: Chromium reports its SUID
  sandbox helper is not configured correctly. Observed helper mode is `0755`
  root-owned. No chmod/setuid repair, disabled sandbox or retry is used.
- Real desktop notification collector starts, records its actual process and
  daemon ownership. Source seam refuses the session because reviewed session
  discovery supplies Wayland but no DISPLAY. No DISPLAY is invented and no
  source/production guard is weakened. Native tray/notification routes remain
  unqualified.
- FUSE-mounted current-main AppImage also aborts with the same SUID sandbox
  diagnostic. Unlike unmerged PR54, current main has no safe-refusal patch;
  this is a failure, not plain-message acceptance or successful relocation.
- Guest stopped gracefully; all odq guests are verified STOPPED afterward.

## Task matrix disposition

| Required task family | Cinnamon | GNOME/no-tray | KDE/Wayland |
|---|---|---|---|
| actual native tray/no-tray hide/relaunch/Open/Exit | partial, Open/Exit fail | blocked/unqualified | package launch fails |
| OS notification acceptance/appearance/exact click | fixture provisioning fail | real daemon absent | package/seam unavailable |
| isolated actual login hidden single core | observed pass | unqualified | unqualified |
| VM sleep/wake D12 | failed wake, unqualified | unqualified | unqualified |
| package relocation/upgrade native | guarded same-version deb partial | unresolved cleanup refusal | deb and AppImage sandbox abort |

**15 required desktop/task cells: 1 observed pass, 2 partial, 4 failed,
8 blocked/unqualified.** This accounting is task-family disposition, not a
test-case pass count. Source native helper separately measured 2 passing and
2 failing Cinnamon steps, plus one fixture runner failure. Full P3.3 remains
OPEN; unavailable background work and notifications are not stubbed acceptance.

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
