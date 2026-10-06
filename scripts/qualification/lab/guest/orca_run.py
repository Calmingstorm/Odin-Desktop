#!/usr/bin/env python3
"""Run the Orca tasks only in a named qualification VM's real user session."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import shlex
import stat
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from owned_processes import OwnedProcesses  # noqa: E402
from smoke import session_environment, session_info  # noqa: E402


def guest_context(desktop):
    if desktop not in ("cinnamon", "gnome", "kde"):
        raise RuntimeError("Unsupported Orca qualification desktop")
    if os.geteuid() != 0:
        raise RuntimeError("Guest bootstrap requires guest root")
    if subprocess.check_output(["systemd-detect-virt"], text=True).strip() not in ("kvm", "qemu"):
        raise RuntimeError("Orca runner requires an actual VM")
    if subprocess.check_output(["hostname"], text=True).strip() != f"odq-{desktop}":
        raise RuntimeError("Wrong qualification guest")
    account = pwd.getpwnam("odq")
    info = session_info()
    expected = "x11" if desktop == "cinnamon" else "wayland"
    if info.get("Type") != expected:
        raise RuntimeError("Wrong graphical session type")
    env = session_environment(account.pw_uid, expected)
    sessions = subprocess.check_output(
        ["loginctl", "list-sessions", "--no-legend", "--no-pager"], text=True
    )
    for line in sessions.splitlines():
        columns = line.split()
        if len(columns) >= 3 and columns[1:3] == [str(account.pw_uid), "odq"]:
            state = subprocess.check_output(
                ["loginctl", "show-session", columns[0], "-p", "Active", "-p", "Type"], text=True
            )
            if f"Type={expected}" in state and "Active=yes" in state:
                env["XDG_SESSION_ID"] = columns[0]
                break
    if "XDG_SESSION_ID" not in env:
        raise RuntimeError("No explicit active graphical guest session ID")
    identities = {"cinnamon": ("cinnamon",), "gnome": ("gnome",), "kde": ("kde", "plasma")}
    if not any(name in env.get("XDG_CURRENT_DESKTOP", "").lower() for name in identities[desktop]):
        raise RuntimeError("Wrong live desktop identity")
    return account, info, env


def user_command(env, argv):
    return ["env", "-i", *(f"{key}={value}" for key, value in env.items()), *argv]


def prepare_kde_portal(session, account, collector_ready):
    """Restart only the fixed guest backend after Orca has enabled its live bus.

    The systemd user manager does not inherit the session shell's Qt flags.
    Temporarily import only those flags; restore their prior manager values in
    all exits. Never admit plasmashell or derive an input target from this setup.
    """
    service = "plasma-xdg-desktop-portal-kde.service"
    executable = Path("/usr/lib/x86_64-linux-gnu/libexec/xdg-desktop-portal-kde")
    if not collector_ready.get("address"):
        raise RuntimeError("KDE portal preparation requires the ready accessibility collector")
    for path in (executable, *executable.parents):
        metadata = path.lstat()
        if path.is_symlink() or metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise RuntimeError("KDE portal executable ancestry is not canonical root-owned")
    flags = {"QT_ACCESSIBILITY": "1", "QT_LINUX_ACCESSIBILITY_ALWAYS_ON": "1"}

    def command(argv):
        return subprocess.check_output(
            user_command(session, argv), text=True, user=account.pw_uid,
            group=account.pw_gid, timeout=20,
        ).strip()

    prior = {}
    for line in command(["systemctl", "--user", "show-environment"]).splitlines():
        key, separator, value = line.partition("=")
        if separator and key in flags:
            if value not in ("0", "1"):
                raise RuntimeError("Unsupported prior Qt accessibility manager value")
            prior[key] = value
    for name in ("IsEnabled", "ScreenReaderEnabled"):
        if command([
            "busctl", "--user", "get-property", "org.a11y.Bus", "/org/a11y/bus",
            "org.a11y.Status", name,
        ]) != "b true":
            raise RuntimeError("KDE portal requires enabled live accessibility status")
    try:
        command(["systemctl", "--user", "set-environment", *(f"{k}={v}" for k, v in flags.items())])
        command(["systemctl", "--user", "restart", service])
    finally:
        missing = [key for key in flags if key not in prior]
        if missing:
            command(["systemctl", "--user", "unset-environment", *missing])
        if prior:
            command([
                "systemctl", "--user", "set-environment",
                *(f"{k}={v}" for k, v in prior.items()),
            ])
    pid = int(command(["systemctl", "--user", "show", service, "-p", "MainPID", "--value"]))
    if pid <= 0:
        raise RuntimeError("KDE portal service has no live process")
    proc = Path("/proc") / str(pid)
    if proc.stat().st_uid != account.pw_uid or (proc / "exe").resolve() != executable:
        raise RuntimeError("KDE portal service process identity mismatch")
    actual_env = dict(
        entry.split("=", 1) for entry in (proc / "environ").read_text().split("\0") if "=" in entry
    )
    if any(actual_env.get(key) != value for key, value in flags.items()):
        raise RuntimeError("KDE portal did not inherit the accessibility flags")
    address_reply = shlex.split(command([
        "busctl", "--user", "call", "org.a11y.Bus", "/org/a11y/bus",
        "org.a11y.Bus", "GetAddress",
    ]))
    if address_reply != ["s", collector_ready["address"]]:
        raise RuntimeError("KDE portal preparation changed the collector accessibility bus")
    session_keys = ("DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR", "WAYLAND_DISPLAY")
    if any(actual_env.get(key) != session.get(key) for key in session_keys):
        raise RuntimeError("KDE portal inherited a different graphical session")
    return {"service": service, "pid": pid, "exe": str(executable), "qt_environment": flags,
            "collector_address": collector_ready["address"], "manager_environment_restored": True,
            "session_environment": {key: actual_env[key] for key in session_keys}}


def orca_pid(uid, log):
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            args = (proc / "cmdline").read_bytes().split(b"\0")
            if proc.stat().st_uid == uid and any(
                Path(arg.decode()).name == "orca" for arg in args if arg
            ):
                # Orca sets its process title, erasing its argument vector.
                # Bind the actual writer's open descriptor, not erased argv.
                for descriptor in (proc / "fd").iterdir():
                    if descriptor.resolve() == log.resolve():
                        return int(proc.name)
        except (OSError, UnicodeError):
            continue
    raise RuntimeError("No owned Orca process bound to the fresh debug log")


def artifact_provenance(root):
    return hashlib.sha256((root / "artifact-manifest.json").read_bytes()).hexdigest()


def prepare_native_sandbox(root):
    """Install only the exact manifest-verified Chromium SUID helper in this VM."""
    relative = "app/node_modules/electron/dist/chrome-sandbox"
    helper = root / relative
    manifest = json.loads((root / "artifact-manifest.json").read_text())
    if helper.is_symlink() or not helper.is_file():
        raise RuntimeError("Native sandbox helper must be a regular archived file")
    expected = manifest["files"][relative]["sha256"]
    actual = hashlib.sha256(helper.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError("Native sandbox helper source digest mismatch")
    for item in helper.parent.rglob("*"):
        if item.is_symlink():
            raise RuntimeError("Native runtime symlinks are not installable")
        if item.is_file():
            relative_item = str(item.relative_to(root))
            if (
                hashlib.sha256(item.read_bytes()).hexdigest()
                != manifest["files"][relative_item]["sha256"]
            ):
                raise RuntimeError("Native runtime source digest mismatch")
    # Never place a privileged executable beneath user-writable ancestors.
    # /run is nosuid,noexec in the pinned KDE VM. Use the guest's installed
    # runtime directory, not a user-writable artifact ancestor or host path.
    directory = Path("/usr/local/lib/odq") / f"{root.name}-sandbox"
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)
    import shutil

    installed_runtime = directory / "electron"
    shutil.copytree(helper.parent, installed_runtime, symlinks=False)
    for item in installed_runtime.rglob("*"):
        os.chown(item, 0, 0)
        if item.is_dir():
            os.chmod(item, 0o755)
        else:
            os.chmod(item, 0o755 if item.stat().st_mode & 0o111 else 0o644)
    os.chown(installed_runtime, 0, 0)
    os.chmod(installed_runtime, 0o755)
    installed = installed_runtime / "chrome-sandbox"
    os.chmod(installed, 0o4755)
    return {
        "path": str(installed),
        "sha256": actual,
        "uid": installed.stat().st_uid,
        "mode": oct(installed.stat().st_mode & 0o7777),
    }


def real_core_environment(root):
    if not (root / "engine").exists():
        return {}
    if (
        not (root / "engine/src/__main__.py").is_file()
        or not (root / "engine/site-packages").is_dir()
    ):
        raise RuntimeError("Incomplete bundled real engine; no fixture-only fallback")
    wrapper = root / "scripts/qualification/lab/guest/real_core.py"
    if not wrapper.is_file():
        raise RuntimeError("Bundled real-core wrapper is missing")
    return {
        "ODIN_ORCA_REAL_CORE_CMD": json.dumps(["/usr/bin/python3", "-B", "-P", str(wrapper)]),
        "ODIN_ORCA_REAL_CORE_REQUIRED": "1",
    }


def debug_buffering_customization():
    return (
        "from orca import debug\n"
        "if debug.debugFile is not None:\n"
        "    debug.debugFile.reconfigure(line_buffering=True, write_through=True)\n"
    )


def wait_native_collector(collector, events, console, uid, *, timeout=20):
    """Require a live owned child and its flushed private bus-registration receipt."""
    deadline = time.monotonic() + timeout
    while True:
        if collector.poll() is not None:
            raise RuntimeError("Native dialog collector exited before readiness")
        if events.exists():
            info = events.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != uid
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise RuntimeError("Native dialog collector evidence must be private and owned")
            with events.open() as source:
                first = source.readline(16385)
            if len(first) > 16384:
                raise RuntimeError("Oversized native dialog collector readiness")
            if first.endswith("\n"):
                ready = json.loads(first)
                identity = ready.get("collector", {})
                if (
                    ready.get("type") != "ready"
                    or identity.get("pid") != collector.pid
                    or identity.get("uid") != uid
                    or not ready.get("address")
                    or not ready.get("collector_peer")
                    or not ready.get("run")
                    or not isinstance(ready.get("started_ns"), int)
                ):
                    raise RuntimeError("Native dialog collector readiness binding mismatch")
                messages = console.read_text(errors="replace").splitlines()
                acknowledged = any(
                    line == json.dumps({"native_event_collector": "ready", "path": str(events)})
                    for line in messages
                )
                if acknowledged and collector.poll() is None:
                    return ready
        if time.monotonic() >= deadline:
            raise RuntimeError("Native dialog collector readiness timed out; no app launch")
        time.sleep(0.1)


def start_native_collector(containment, processes, env, account, root, console_output):
    events = root / "evidence/native-dialog-events.jsonl"
    console = root / "evidence/native-dialog-collector.log"
    if events.exists() or events.is_symlink():
        raise RuntimeError("Native dialog event evidence already exists; no reuse")
    env["ODIN_ORCA_DIALOG_EVENTS"] = str(events)
    collector = containment.spawn(
        user_command(
            env,
            [
                "/usr/bin/python3",
                "-B",
                str(root / "scripts/qualification/lab/guest/native_dialog_events.py"),
            ],
        ),
        stdout=console_output,
        stderr=subprocess.STDOUT,
        uid=account.pw_uid,
        gid=account.pw_gid,
    )
    processes.append(collector)
    ready = wait_native_collector(collector, events, console, account.pw_uid)
    return collector, ready


def run(desktop, root, probe=None):
    if probe not in (None, "electron", "gtk-electron", "native-attach", "native-files"):
        raise RuntimeError("Unsupported focused probe")
    account, info, session = guest_context(desktop)
    root = Path(root)
    if (
        not root.is_absolute()
        or root.parent != Path("/var/tmp")
        or not root.name.startswith("odq-orca-")
        or root.is_symlink()
    ):
        raise RuntimeError("Use an explicit private /var/tmp/odq-orca-* artifact directory")
    root = root.resolve(strict=True)
    source_sha256 = artifact_provenance(root)
    evidence = root / "evidence"
    evidence.mkdir(mode=0o700)
    for dirname in ("speech", "prefs", "profile", "config", "data", "cache"):
        (root / dirname).mkdir(mode=0o700)
    speech = root / "speech"
    prefs = root / "prefs"
    log = evidence / "orca-debug.log"
    (speech / "speechd.conf").write_text(
        'LogLevel 3\nDefaultModule dummy\nAddModule "dummy" "sd_dummy" ""\n'
        'AudioOutputMethod "alsa"\nAudioALSADevice "null"\nDisableAutoSpawn\n',
        encoding="utf-8",
    )
    # Ordinary Orca verbosity and live-region settings. Disable typing echo so
    # fixture secret entry tests measure the widget, not an explicit key echo.
    settings = json.loads(Path("/home/odq/.local/share/orca/user-settings.conf").read_text())
    settings["general"].update(
        {
            "enableKeyEcho": False,
            "enableEchoByCharacter": False,
            "enableEchoByWord": False,
            "enableEchoBySentence": False,
            "enableSound": False,
            "speechServerFactory": "speechdispatcherfactory",
            "speechServerInfo": None,
            "enableSpeech": True,
        }
    )
    (prefs / "user-settings.conf").write_text(json.dumps(settings), encoding="utf-8")
    # Orca's own debug file defaults to block buffering. Native emissions at the
    # end of an idle task otherwise remain invisible until the next task begins.
    # Customize only I/O buffering; never generate or rewrite speech evidence.
    (prefs / "orca-customizations.py").write_text(
        debug_buffering_customization(),
        encoding="utf-8",
    )
    # The app gets disposable storage but the actual guest session's bus/runtime.
    env = {
        **session,
        "HOME": str(root / "profile"),
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_DATA_HOME": str(root / "data"),
        "XDG_CACHE_HOME": str(root / "cache"),
        "PATH": f"{root / 'bin'}:/usr/local/bin:/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "SPEECHD_ADDRESS": f"unix_socket:{speech / 'speechd.sock'}",
        "ODIN_ORCA_LOG": str(log),
        "ODIN_ORCA_DESKTOP": desktop,
        "ODIN_ORCA_EVIDENCE": str(evidence),
        "ODIN_ORCA_ROOT": str(root),
        "ODIN_APP_A11Y_REPORT": str(evidence / "tasks.json"),
        "NO_AT_BRIDGE": "0",
        "GTK_MODULES": "gail:atk-bridge",
        "GTK_A11Y": "always",
        "ACCESSIBILITY_ENABLED": "1",
        "ELECTRON_ENABLE_LOGGING": "1",
    }
    env.update(real_core_environment(root))
    subprocess.run(["chown", "-R", f"{account.pw_uid}:{account.pw_gid}", str(root)], check=True)
    sandbox = None
    processes = []
    containment = OwnedProcesses(root.name)
    uinput = Path("/dev/uinput")
    input_stat = uinput.stat()
    proof = {
        "probe": probe,
        "desktop": desktop,
        "session": info,
        "session_environment": session,
        "source_sha256": source_sha256,
        "real_core_required": "ODIN_ORCA_REAL_CORE_CMD" in env,
        "orca_version": subprocess.check_output(["orca", "--version"], text=True).strip(),
        "speech_sink": "private speech-dispatcher Unix socket, sd_dummy only",
        "passed": False,
        "cleanup": {},
    }
    try:
        sandbox = prepare_native_sandbox(root)
        proof["native_sandbox"] = sandbox
        proof["native_runtime_mount"] = subprocess.check_output(
            ["findmnt", "-T", sandbox["path"], "-n", "-o", "TARGET,OPTIONS"], text=True
        ).strip()
        options = proof["native_runtime_mount"].split()[-1].split(",")
        if "noexec" in options or "nosuid" in options:
            raise RuntimeError("Verified native runtime requires executable SUID mount")
        env["CHROME_DEVEL_SANDBOX"] = sandbox["path"]
        env["ODIN_ORCA_ELECTRON"] = str(Path(sandbox["path"]).parent / "electron")
        if desktop == "gnome":
            subprocess.run(
                user_command(
                    env,
                    [
                        "gsettings",
                        "set",
                        "org.gnome.desktop.interface",
                        "toolkit-accessibility",
                        "true",
                    ],
                ),
                check=True,
                user=account.pw_uid,
                group=account.pw_gid,
            )
            proof["toolkit_accessibility"] = subprocess.check_output(
                user_command(
                    env,
                    ["gsettings", "get", "org.gnome.desktop.interface", "toolkit-accessibility"],
                ),
                text=True,
                user=account.pw_uid,
                group=account.pw_gid,
            ).strip()
        with (
            (evidence / "speech-dispatcher.log").open("w") as speech_log,
            (evidence / "orca-console.log").open("w") as orca_log,
            (evidence / "native-dialog-collector.log").open("w") as collector_log,
        ):
            speechd = containment.spawn(
                user_command(
                    env,
                    [
                        "speech-dispatcher",
                        "-s",
                        "-C",
                        str(speech),
                        "-S",
                        str(speech / "speechd.sock"),
                        "-P",
                        str(speech / "speechd.pid"),
                        "-L",
                        str(speech),
                        "-t",
                        "0",
                    ],
                ),
                stdout=speech_log,
                stderr=subprocess.STDOUT,
                uid=account.pw_uid,
                gid=account.pw_gid,
            )
            processes.append(speechd)
            deadline = time.monotonic() + 20
            while not (speech / "speechd.sock").exists():
                if speechd.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("Private dummy speech-dispatcher did not start")
                time.sleep(0.1)
            orca = containment.spawn(
                user_command(
                    env, ["orca", "--replace", "--user-prefs", str(prefs), "--debug-file", str(log)]
                ),
                stdout=orca_log,
                stderr=subprocess.STDOUT,
                uid=account.pw_uid,
                gid=account.pw_gid,
            )
            processes.append(orca)
            deadline = time.monotonic() + 30
            while not log.exists() or "SPEECH OUTPUT:" not in log.read_text(errors="replace"):
                if orca.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("Orca did not produce initial speech output")
                time.sleep(0.2)
            env["ODIN_ORCA_PID"] = str(orca_pid(account.pw_uid, log))
            collector, ready = start_native_collector(
                containment, processes, env, account, root, collector_log
            )
            proof["native_dialog_collector"] = ready
            if desktop == "kde":
                proof["kde_portal_preparation"] = prepare_kde_portal(session, account, ready)
            # This is the isolated guest's synthetic keyboard device, never a
            # shared host device. Restore its exact owner/mode in every exit.
            os.chown(uinput, input_stat.st_uid, account.pw_gid)
            os.chmod(uinput, 0o660)
            if desktop == "gnome":
                # One ordinary native Escape in the guarded disposable session
                # dismisses GNOME's startup overview, as measured by focused probes.
                dismiss = containment.spawn(
                    user_command(
                        env,
                        [
                            "/usr/bin/python3",
                            "-B",
                            str(root / "scripts/qualification/lab/guest/focused_probe.py"),
                            "key",
                            "Escape",
                        ],
                    ),
                    stdout=collector_log,
                    stderr=subprocess.STDOUT,
                    uid=account.pw_uid,
                    gid=account.pw_gid,
                )
                processes.append(dismiss)
                if dismiss.wait(timeout=15) != 0:
                    raise RuntimeError("Guest GNOME startup overview dismissal failed")
                proof["gnome_startup_escape"] = True
            command = [
                str(root / "bin/node"),
                str(root / "app/node_modules/@playwright/test/cli.js"),
                "test",
                "--config=test/e2e/orca.config.ts",
                "--workers=1",
            ]
            if probe:
                command = [
                    "/usr/bin/python3",
                    "-B",
                    str(root / "scripts/qualification/lab/guest/focused_probe.py"),
                    probe,
                ]
            with (evidence / "tasks.log").open("w") as task_log:
                tasks = containment.spawn(
                    user_command(env, command),
                    cwd=root / "app",
                    stdout=task_log,
                    stderr=subprocess.STDOUT,
                    uid=account.pw_uid,
                    gid=account.pw_gid,
                )
                processes.append(tasks)
                tasks.wait(timeout=1800)
            proof["task_exit_code"] = tasks.returncode
            proof["passed"] = tasks.returncode == 0
            proof["orca_running_during_tasks"] = orca.poll() is None
            proof["speechd_running_during_tasks"] = speechd.poll() is None
            proof["collector_running_during_tasks"] = collector.poll() is None
            proof["passed"] = bool(
                proof["passed"]
                and proof["orca_running_during_tasks"]
                and proof["speechd_running_during_tasks"]
                and proof["collector_running_during_tasks"]
            )
    except Exception as exc:
        proof["error"] = str(exc)
    finally:
        proof["cleanup"] = containment.cleanup(processes)
        if sandbox and proof["cleanup"].get("descendants_exited"):
            import shutil

            shutil.rmtree(Path(sandbox["path"]).parent.parent)
            proof["cleanup"]["native_sandbox_removed"] = True
        try:
            os.chown(uinput, input_stat.st_uid, input_stat.st_gid)
            os.chmod(uinput, input_stat.st_mode & 0o7777)
            proof["cleanup"]["uinput_restored"] = (
                uinput.stat().st_uid,
                uinput.stat().st_gid,
                uinput.stat().st_mode & 0o7777,
            ) == (input_stat.st_uid, input_stat.st_gid, input_stat.st_mode & 0o7777)
        except OSError as exc:
            proof["cleanup"].update({"uinput_restored": False, "uinput_error": str(exc)})
        proof["passed"] = bool(
            proof["passed"]
            and proof["cleanup"]["descendants_exited"]
            and proof["cleanup"].get("uinput_restored")
        )
        proof["evidence_sha256"] = {
            str(path.relative_to(evidence)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in evidence.rglob("*")
            if path.is_file()
        }
        (evidence / "guest-proof.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(proof, indent=2))
    return 0 if proof["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("desktop", choices=("cinnamon", "gnome", "kde"))
    parser.add_argument("root")
    parser.add_argument(
        "--probe", choices=("electron", "gtk-electron", "native-attach", "native-files")
    )
    args = parser.parse_args()
    sys.exit(run(args.desktop, args.root, args.probe))
