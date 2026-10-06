# Orca host runner

`orca.py` source-builds an operator-prepared artifact, then pushes/runs/pulls it
in **one already-running** `odq-cinnamon`, `odq-gnome` or `odq-kde` VM. It does not
create, start, stop, provision, repair storage or touch the host display/session.
The caller owns lifecycle and must stop each VM before moving to the next.

## Prepared staging

Use an external private staging tree, not the repository itself. Copy only:

- `app/`: source build configuration and `src`, `resources`, `fixture-core`,
  `package.json`, exact `package-lock.json`, `test/e2e` suite/support/configuration
  and installed pinned `node_modules`. Electron must have completed its package
  install script: both `node_modules/electron/path.txt` and `dist/electron` exist.
- `bin/node`: the explicit prepared Node runtime. Its version is recorded.
- Optional `engine/src` and `engine/site-packages`: source plus dependencies for
  the isolated real-core lane. Never copy existing config, data, credentials or
  user profiles. Engine source must match this working repository's `src` bytes.

The runner copies current `guest/orca_run.py`, `guest/smoke.py`,
`guest/real_core.py`, `guest/owned_processes.py` and
`guest/native_dialog_events.py` into the stage. The focused probe scripts
are also copied and source-bound when used. Archive construction materializes
ordinary npm hardlinks as independent files; hardlink extraction is refused.
It invokes the staged Electron Vite CLI with the staged Node and a clean
environment, bounded at 300 seconds. No dependency installation or downloading
occurs in this tool. Ordinary app build flags are unchanged; no sandbox bypass.

```sh
python3 scripts/qualification/lab/orca.py pack \
  --staging /private/external/stage --output /private/artifact-new.tar.gz
python3 scripts/qualification/lab/orca.py run odq-cinnamon \
  --artifact /private/artifact-new.tar.gz --evidence /private/evidence-new
```

For a launch defect, use the bounded one-launch lane **before** repeating the
task suite:

```sh
python3 scripts/qualification/lab/orca.py run odq-kde \
  --artifact /private/artifact-new.tar.gz --evidence /private/kde-probe-new \
  --probe electron
python3 scripts/qualification/lab/orca.py run odq-gnome \
  --artifact /private/artifact-new.tar.gz --evidence /private/gnome-probe-new \
  --probe gtk-electron
```

The GNOME probe must first hear the plain GTK entry and button; only then does
it launch Electron once with full stderr logging. Probe proofs are explicitly
`focused-probes-not-qualification`, never passing seven-task reports.
`--probe native-attach` observes an actual native chooser and cancels it with
grounded keyboard input, without running the unrelated task groups.

Both destinations must be new. Archives contain an explicit base Git SHA,
dirty-tree flag, actual working-source digests, runtime version and every file
digest. Dirty trees are not represented as clean commit builds. Device files,
hardlinks, absolute/traversing paths, credentials, escaping/chained symlinks and
symlink-parent extraction pivots are rejected. Upload operates on a private
frozen copy to avoid validation/upload races.

## Guest contract

Only the fixed archived Python bootstrap is invoked:
`python3 WORKDIR/scripts/qualification/lab/guest/orca_run.py DESKTOP WORKDIR`.
The actual VM's ownership, device/cap isolation, pinned base image, running state,
storage/headroom and one-at-a-time policy pass the existing `lab.py` checks under
its shared mutation lock. Root preparation dependencies are handled by the main
operator's fixed guest preparation, not caller-supplied shell commands.

The bootstrap uses the guest's actual odq session and a fresh non-audible speech
sink, invokes `app/test/e2e/orca.spec.ts`, and writes `WORKDIR/evidence`:
`guest-proof.json`, `tasks.json`, `orca-debug.log`, `tasks.log`,
`orca-console.log`, `speech-dispatcher.log`, `native-dialog-events.jsonl` and
`native-dialog-collector.log`. The proof includes `passed`,
`source_sha256` (SHA256 of exact `artifact-manifest.json` bytes), `session.Type`,
`orca_version`, `cleanup.owned_children_exited`, and `cleanup.uinput_restored`.
`cleanup.descendants_exited` is also mandatory. Each root-owned child joins a
fresh non-delegated cgroup before exec and before its UID/GID drop, without PAM
relocating it. Cleanup records PID/starttime/UID evidence, uses pidfd-bound TERM,
then bounded atomic `cgroup.kill` if needed. Success requires `cgroup.events`
reporting no population and removal of that exact run's group. A dead launcher
does not exempt detached or double-fork descendants. No cgroup/pidfd support
means failure, not a weaker process-name or PID-replay fallback.
Host also records installed
package versions and guest SHA256 comparisons of uploaded source/build bytes.

The exact archive-verified Electron runtime is installed root-owned below
`/usr/local/lib/odq/<run nonce>-sandbox`, with the normal Chromium SUID sandbox
helper. The guest's `/run` may be `noexec,nosuid` and cannot host that runtime.
No caller-writable ancestor, `--no-sandbox` or kernel-policy relaxation is used.
The installed runtime is retired after its cgroup is empty, and its removal is
part of the proof.

A stable guest-only AT-SPI collector registers for native activation events
before Electron starts. Native chooser lookup binds the actual event sender
and object path, then revalidates the live process incarnation, UID, executable,
title, role and ACTIVE/SHOWING states. Orca's debug text is **never input
authority**. The event writer's ready header, bus/process identity and open
descriptor are checked; stale, foreign or unavailable references fail closed.
GNOME's exact `/usr/libexec/xdg-desktop-portal-gnome` backend is supported only
in the GNOME guest, for the same two requested chooser titles. Executable and
all ancestors must be canonical, root-owned and not writable by the guest.
GTK4 4.14's dialog reports MODAL/SHOWING but omits ACTIVE from `GetState` despite
emitting a real `object:state-changed:active(1)` event. For that backend only,
the latest collector event supplies the active state while MODAL/SHOWING,
title, dialog role, UID, PID and start time are rechecked before every chord.
A newer inactive event or any other observed activation revokes that binding;
foreign activations are recorded as revocations, never input targets. No
portal request-token association is claimed. This VM-only fixture lane trusts
the exact installed portal plus actual current native modal activation.
Confirmed input release is required; partial native input errors are not
replayed by the suite's readiness polling.

Default host timeout is 2100 seconds, longer than the guest's 1800-second task
deadline and bounded cleanup. Failed output is retained, never replayed. The
remote directory is removed only after confirmed guest-owned child cleanup. An
unknown cleanup outcome leaves it intact for explicit operator recovery. No
global process kills, host session fallback or implicit forced VM shutdown.

If bundled engine source is present, the bootstrap sets the fixed real-core
wrapper command. It must run as the unprivileged guest user with a fresh task
HOME/XDG tree; the wrapper removes ambient app/source import paths and imports
only the bundled engine/dependencies plus the guest Python standard library.
The host requires the real-core Playwright test to pass, not skip. Missing engine
dependencies are failure, never permission to substitute the fixture.

## Rootless tests

```sh
sudo -n unshare --mount --pid --fork --mount-proc --kill-child \
  sudo -u "$USER" env -u DBUS_SESSION_BUS_ADDRESS -u XDG_RUNTIME_DIR \
  .venv/bin/python -m pytest -q tests/test_lab_orca*.py \
    tests/test_native_dialog_events.py tests/test_orca_guest_tasks.py \
    tests/test_lab_focused_probe.py
```

These test archives, provenance, fail-closed targets/preflight, private output,
failed/timeout evidence and guest identity/cleanup contracts using fake Incus and
fake session discovery. They never claim native Orca runtime qualification.
