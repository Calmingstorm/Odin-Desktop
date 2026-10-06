#!/usr/bin/env python3
"""Dedicated Docker lane for offline lab fixtures that need container-local sudo.

Never invoke the restricted PID helper here. It correctly denies escalation.
No native qualification, host paths, display, credentials or sockets are exposed.
Only Dockerfile enters the build context; a fixed regular-file allowlist enters
the stopped container through docker cp. Tests run as UID 1000, never root.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI = "scripts/qualification/lab/ci"
TESTS = (
    "tests/test_lab_common.py",
    "tests/test_lab_cinnamon.py",
    "tests/test_lab_gnome.py",
    "tests/test_lab_guest_smoke.py",
    "tests/test_lab_hyprland.py",
    "tests/test_lab_kde.py",
)
FILES = (*TESTS, f"{CI}/run.py", f"{CI}/pytest.ini",
         "scripts/qualification/lab/lab.py",
         *(f"scripts/qualification/lab/guest/{name}" for name in (
             "common.sh", "cinnamon.sh", "gnome.sh", "hyprland.sh", "kde.sh", "smoke.py")),
         *(f"scripts/qualification/lab/images/{name}.json" for name in (
             "cinnamon", "gnome", "hyprland", "kde")))
CAPS = ("CHOWN", "DAC_OVERRIDE", "FOWNER", "SETUID", "SETGID")
LABEL = "org.odin.desktop.lab-fixture"


def clean_environment():
    # Do not pass DOCKER_HOST, proxy, display, session or credential variables.
    return {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/nonexistent",
            "DOCKER_CONFIG": "/nonexistent", "LANG": "C.UTF-8"}


def docker(*arguments, **kwargs):
    # Buildx needs a writable config directory. It contains no host credentials
    # and is removed after each command, not copied from the user's ~/.docker.
    with tempfile.TemporaryDirectory(prefix="odin-lab-docker-config-") as config:
        environment = clean_environment()
        environment.update(HOME=config, DOCKER_CONFIG=config)
        return subprocess.run(["docker", *arguments], env=environment, check=True, **kwargs)


def create_arguments(name, image):
    return ["create", "--name", name, "--label", f"{LABEL}={name}",
            "--network", "none", "--cap-drop", "ALL",
            *(part for cap in CAPS for part in ("--cap-add", cap)),
            "--pids-limit", "256", "--memory", "1g", "--cpus", "2",
            "--user", "0:0", image]


def archive_sources(root, archive):
    with tarfile.open(archive, "w") as bundle:
        for relative in FILES:
            source = root / relative
            # Reject symlinks at every level, not just the leaf. Never copy secrets.
            if (not source.is_file() or any(path.is_symlink() for path in
                    (source, *source.parents)) or root not in source.parents):
                raise ValueError(f"Unsafe or missing fixture source: {relative}")
            bundle.add(source, arcname=relative, recursive=False)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if os.geteuid() == 0:
        raise SystemExit("Refusing root host launcher; Docker access must be non-root")
    if args not in ([], ["--collect-only"]):
        raise SystemExit("Only --collect-only is supported; test selection is fixed")
    name = f"odin-lab-fixture-{uuid.uuid4().hex}"
    image = f"odin-desktop-lab-fixture:{uuid.uuid4().hex}"
    previous = {}
    exit_code = 1
    container_created = image_created = False
    cleanup_failed = False

    def cancelled(signum, _frame):
        raise SystemExit(128 + signum)

    for signum in (signal.SIGTERM, signal.SIGINT):
        previous[signum] = signal.signal(signum, cancelled)
    try:
        with tempfile.TemporaryDirectory(prefix="odin-lab-fixture-") as temporary:
            context = Path(temporary) / "context"
            context.mkdir()
            source = ROOT / CI / "Dockerfile"
            if not source.is_file() or source.is_symlink():
                raise ValueError("Dockerfile must be a regular file")
            (context / "Dockerfile").write_bytes(source.read_bytes())
            archive = Path(temporary) / "fixtures.tar"
            archive_sources(ROOT, archive)
            docker("build", "--tag", image, str(context), timeout=600)
            image_created = True
            docker(*create_arguments(name, image), *args, timeout=60)
            container_created = True
            # cp accepts a tar stream into a stopped container. No mounts, ever.
            with archive.open("rb") as stream:
                docker("cp", "-", f"{name}:/fixture", stdin=stream, timeout=60)
            print(f"Running disposable offline lab fixture container {name}", flush=True)
            docker("start", "--attach", name, timeout=300)
            result = docker("inspect", "--format", "{{.State.ExitCode}}", name,
                            capture_output=True, text=True, timeout=60)
            exit_code = int(result.stdout.strip())
    except subprocess.CalledProcessError as error:
        exit_code = error.returncode or 1
    except subprocess.TimeoutExpired as error:
        print(f"Docker operation exceeded its {error.timeout}s deadline", file=sys.stderr)
        exit_code = 124
    finally:
        # A second cancellation must not interrupt release of this invocation's
        # resources. SIGKILL cannot be caught; no universal cleanup claim there.
        for signum in previous:
            signal.signal(signum, signal.SIG_IGN)
        # Cleanup only this generated name/image, even if create/start failed or
        # cancellation raced the Docker client. Never prune or select by prefix.
        for operation in (("rm", "--force", name), ("image", "rm", image)):
            try:
                docker(*operation, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=30)
            except (subprocess.SubprocessError, OSError):
                print(f"Cleanup incomplete for owned artifact {operation[-1]}", file=sys.stderr)
                # A failure before create may legitimately have no artifact.
                # Once creation succeeded, deletion is part of the hard gate.
                if (operation[0] == "rm" and container_created
                        or operation[0] == "image" and image_created):
                    cleanup_failed = True
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    return 1 if cleanup_failed and exit_code == 0 else exit_code


if __name__ == "__main__":
    raise SystemExit(main())
