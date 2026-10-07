# Orderly logout Exit

Implementation scope: Cinnamon/X11, GNOME/Wayland and Plasma/KDE Wayland.
No lab guest, live desktop, service or live installation was used during development.
Native guest verification remains Claudia's next gate, not a claim made by this PR.

## Mechanisms and cancellation

| Desktop | Mechanism |
| --- | --- |
| Cinnamon | An app-owned Python sibling registers with `org.gnome.SessionManager`. `QueryEndSession` replies positively within the 500 ms call bound without quiescing. `CancelEndSession` therefore leaves Odin running. Only `EndSession` or `Stop` writes a live pipe notification to the app's existing bounded Exit. |
| GNOME | The same SessionManager client API. The sibling keeps its client registration alive while the core shuts down. App Exit fsyncs its receipt, then closes the sibling's parent pipe. The sibling acknowledges actual end after that barrier, or after an eight-second deadline if the app hangs. |
| KDE/Plasma | The app registers a mode-0700, owner-marked hook under `$XDG_CONFIG_HOME/plasma-workspace/shutdown/odin-desktop.sh`. Plasma invokes this after both ksmserver and KWin's cancellable close stages succeed, before stopping the session target or KWin. The hook invokes the existing `--exit` route and waits for the original PID/start-time identity to disappear, within `timeout -k 1s 8s`. A cancelled logout never invokes this stage. |

The monitor is a sibling rather than a core worker because a core worker's bus
connection would disappear before Electron's own shutdown receipt is persisted.
It uses the already-selected bundled Python runtime (including `-I -B`) and the
existing `dbus-next` dependency. No new dependency. Plasma uses the existing
Linux coreutils `timeout` command; if it is unavailable the hook returns without
blocking logout, rather than introducing an unbounded fallback.

Missing bus/manager, refused registration, unwritable hook location, foreign
hook contents or non-file hook paths fail open. There are no inhibitors and no
new admission restrictions (D17). The monitor never activates a missing manager.
The hook is removed after normal Exit; stale crash hooks reject reused/dead
owner identities before invoking a launcher. User-edited hooks are not replaced
or removed. No session-end IPC capability, durable replay event or renderer hook
is introduced.

## Source references

- [GNOME ClientPrivate API](https://github.com/GNOME/gnome-session/blob/main/gnome-session/org.gnome.SessionManager.ClientPrivate.xml): query/cancel versus actual end, one-second query response, ten-second end response.
- [cinnamon-session client](https://github.com/linuxmint/cinnamon-session/blob/master/cinnamon-session/csm-dbus-client.c): exports the same `org.gnome.SessionManager.ClientPrivate` interface and routes `EndSessionResponse`.
- [Plasma 6.4 shutdown](https://github.com/KDE/plasma-workspace/blob/Plasma/6.4/startkde/plasma-shutdown/shutdown.cpp): both cancellation branches precede `logoutComplete`; `runShutdownScripts` precedes session target stop or KWin quit.
- [Plasma current shutdown](https://github.com/KDE/plasma-workspace/blob/master/startkde/plasma-shutdown/shutdown.cpp): same ordering, now `graphical-session.target`.
- [KDE portal 6.4](https://github.com/KDE/xdg-desktop-portal-kde/blob/Plasma/6.4/src/inhibit.cpp) has no `CreateMonitor`/session-state implementation. [Current KDE portal](https://github.com/KDE/xdg-desktop-portal-kde/blob/master/src/inhibit.cpp) does. Depending solely on a current-master portal monitor would not cover deployed older Plasma releases, so this implementation does not use it.

## Behaviour proofs

`tests/test_desktop_session_end.py` uses a real private session bus and fake
SessionManager/ClientPrivate service. It verifies query/cancel, actual-end
deduplication, sender/path identity, delayed cleanup response, absent bus/manager
fail-open and parent timeout. `app/test/session-logout.test.ts` covers runtime
selection, hook ownership, fail-open, quoting, stale PID identity and symlink
refusal. `app/test/e2e/session-logout.spec.ts` goes through Electron, the real
engine, native fake D-Bus service or real generated Plasma shell hook, and
asserts clean app and core receipts. No synthetic main-process Exit is used to
trigger the successful end paths.

Raw logs/traces and final gate results are retained outside Git under
`/mnt/storage/odin-desktop-evidence/logout-exit-20261007/`; the result summary
and hash manifest are committed beside this document after gates finish.
