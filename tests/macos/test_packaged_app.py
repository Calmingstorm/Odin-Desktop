"""The installed Mac app, started as a user starts it (phase 4): Odin.app from the .dmg build.

Runs on a disposable Mac only: CI sets ODIN_MACOS_PACKAGED_APP to the built Odin.app. The app gets
an isolated home with its own disposable login keychain (made by path, which leaves it unlocked;
the user's keychain search list is restored exactly), starts hidden, and its engine is driven
over the app's own socket and token with a scripted model, as the app's window would: a reply, a
command, a failing command, patches and a raw read, and a background job stopped from Work (best
effort on macOS). Exit is the user's own (a second start with --exit). Afterwards the app, the
guardian and the engine are gone, and the app's, the engine's and the install lease's records say
the Exit was clean.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.desktop.platform.darwin import user_temp_root
from tests.macos.test_core_end_to_end import hello
from tests.macos.test_core_tools_end_to_end import (
    Client,
    ScriptedModel,
    calls,
    chat,
    gone,
    job,
    run,
    sequence,
    use,
)

APP = os.environ.get("ODIN_MACOS_PACKAGED_APP", "")
REPORT = os.environ.get("ODIN_MACOS_PACKAGED_REPORT", "")
STARTUP_SECONDS = 240
pytestmark = pytest.mark.skipif(not APP, reason="needs a built Odin.app (CI's macOS app job)")


def security(*args: str, secret: str = "") -> str:
    """The security tool's output; a failure says why, never the keychain's password."""
    result = subprocess.run(["/usr/bin/security", *args], capture_output=True, text=True)
    if result.returncode != 0:
        shown = " ".join("<password>" if secret and arg == secret else arg for arg in args)
        raise AssertionError(f"security {shown} exited {result.returncode}: "
                             f"{result.stderr.strip()} {result.stdout.strip()}")
    return result.stdout


def search_list() -> list[str]:
    listed = security("list-keychains", "-d", "user").splitlines()
    return [line.strip().strip('"') for line in listed if line.strip()]


class PackagedApp:
    """The running Odin.app, seen as the engine tests see a core (hello needs these names)."""

    profile = "default"

    def __init__(self, home: Path):
        self.home = home
        self.executable = Path(APP) / "Contents" / "MacOS" / "Odin"
        root = home / "Library" / "odin-desktop" / self.profile
        self.config, self.data = root / "config", root / "data"
        self.token_file = self.config / "ipc.token"
        self.socket = user_temp_root() / "odin-desktop" / self.profile / "core.sock"
        self.log = home / "app.log"
        self.environment = {"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                            "LANG": "en_US.UTF-8", "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
                            "USER": os.environ.get("USER", ""),
                            "LOGNAME": os.environ.get("USER", "")}
        self.process: subprocess.Popen | None = None
        self.token = ""
        self.keychain: Path | None = None

    def start(self) -> None:
        with open(self.log, "ab") as output:
            self.process = subprocess.Popen([str(self.executable), "--hidden"],
                                            env=self.environment, stdin=subprocess.DEVNULL,
                                            stdout=output, stderr=output)

    def exit(self) -> int:
        """Exit as a user does from Terminal: a second start with --exit."""
        return subprocess.run([str(self.executable), "--exit"], env=self.environment,
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=120).returncode

    def stderr(self) -> str:
        core = self.data / "logs" / "core.log"
        logs = [self.log.read_text(errors="replace")[-3000:]]
        if core.exists():
            logs.append(core.read_text(errors="replace")[-5000:])
        return "\n--- core.log ---\n".join(logs)

    async def connect(self) -> Client:
        deadline = time.monotonic() + STARTUP_SECONDS
        while not (self.token_file.exists() and self.socket.exists()):
            if self.process.poll() is not None:
                pytest.fail(f"Odin exited {self.process.returncode}: {self.stderr()}")
            if time.monotonic() > deadline:
                pytest.fail(f"no engine socket within {STARTUP_SECONDS} s: {self.stderr()}")
            await asyncio.sleep(0.25)
        self.token = self.token_file.read_text().strip()
        reader, writer, welcome = await hello(self)
        assert welcome["t"] == "welcome", welcome
        return Client(reader, writer)


@pytest.fixture
def packaged(tmp_path):
    home = Path(os.path.realpath(tmp_path)) / "home"
    keychains = home / "Library" / "Keychains"
    keychains.mkdir(parents=True)
    keychain = keychains / "login.keychain-db"
    password = secrets.token_hex(16)
    before = search_list()
    security("create-keychain", "-p", password, str(keychain), secret=password)
    try:
        security("list-keychains", "-d", "user", "-s", *before)  # the user's list, exactly
        assert search_list() == before
        # create-keychain leaves it unlocked (unlock-keychain refuses a keychain named "login"
        # outside the real home); only its five-minute lock is turned off.
        security("set-keychain-settings", str(keychain))
        app = PackagedApp(home)
        app.keychain = keychain
        yield app
        if app.process is not None and app.process.poll() is None:
            app.process.kill()
            app.process.wait(30)
    finally:
        subprocess.run(["/usr/bin/security", "delete-keychain", str(keychain)], check=False)
        security("list-keychains", "-d", "user", "-s", *before)
        shutil.rmtree(user_temp_root() / "odin-desktop" / "default", ignore_errors=True)


def processes(pattern: str) -> list[int]:
    found = subprocess.run(["/usr/bin/pgrep", "-f", pattern], capture_output=True, text=True)
    return [int(pid) for pid in found.stdout.split()]


async def test_the_installed_app_runs_odin_and_exits_clean(packaged):
    checks: dict[str, object] = {}
    model = ScriptedModel()
    work = packaged.home / "work"
    work.mkdir()
    notes = work / "notes.txt"
    add = "*** Begin Patch\n*** Add File: notes.txt\n+first line\n+second line\n*** End Patch"
    update = ("*** Begin Patch\n*** Update File: notes.txt\n@@\n first line\n-second line\n"
              "+second line, patched\n*** End Patch")
    model.scripts.update({
        "command": sequence(("run_command", {"host": "localhost",
                                             "command": 'echo "app $((40 + 2))"; uname -s'})),
        "failure": sequence(("run_command", {"host": "localhost", "command": "exit 7"})),
        "file": sequence(
            ("apply_patch", {"host": "localhost", "root": str(work), "patch_text": add}),
            ("apply_patch", {"host": "localhost", "root": str(work), "patch_text": update}),
            ("read_file", {"host": "localhost", "path": str(notes), "raw": True})),
        "job": job,
    })
    packaged.start()
    try:
        client = await packaged.connect()
        try:
            guardian = processes(f"{APP}/Contents/Resources/runtime/odin-guardian")
            engine = processes(f"{APP}/Contents/Resources/runtime/python/bin/python3")
            assert guardian and engine, (guardian, engine, packaged.stderr())
            checks["engine under the guardian"] = {"guardian": guardian, "engine": engine}
            await use(client, model)
            # The key is in this home's login keychain, not the account's own.
            own = security("default-keychain", "-d", "user").strip().strip('"')
            assert "odin-desktop:default:" in security("dump-keychain", str(packaged.keychain))
            assert "odin-desktop:default:" not in security("dump-keychain", own)
            checks["a provider and its key in the login keychain"] = True
            conversation = await chat(client)

            done, tools = await run(client, conversation, "command")
            assert done["outcome"] == "completed" and calls(tools) == [("run_command", "success")]
            said = model.results["command"][0]
            assert "app 42" in said and "Darwin" in said, model.results
            checks["a command"] = True

            done, tools = await run(client, conversation, "failure")
            assert calls(tools) == [("run_command", "failure")], model.results
            checks["a failing command"] = True

            done, tools = await run(client, conversation, "file")
            assert calls(tools) == [("apply_patch", "success")] * 2 + [("read_file", "success")]
            assert notes.read_bytes() == b"first line\nsecond line, patched\n"
            assert ("<<<ODIN_READ_FILE_RAW_CONTENT_V1>>>\nfirst line\nsecond line, patched\n"
                    in model.results["file"][2]), model.results
            checks["patches and a raw read"] = True

            done, tools = await run(client, conversation, "job")
            results = model.results["job"]
            pid = int(re.search(r"PID (\d+)", results[0]).group(1))
            stopped = json.loads(results[-1])["result"]
            assert stopped["settlement"]["resource_release"] == "best_effort", results
            assert await gone(pid), "the job outlived its stop"
            checks["a background job stopped from Work"] = stopped["settlement"]
        finally:
            await client.close()

        assert packaged.exit() == 0
        packaged.process.wait(90)
        checks["the app exited"] = packaged.process.returncode
        for pid in [*guardian, *engine]:
            assert await gone(pid, 30), f"{pid} outlived Exit: {packaged.stderr()}"
        checks["the guardian and the engine are gone"] = True

        root = packaged.config.parent
        app_record = json.loads((root / "default-cleanup-state.json").read_text())
        current = app_record.get("current", app_record)
        assert current["state"] == "process-exited" and current["shutdownAccepted"] is True
        assert current["processOutcome"] in {"exited", "not-running"} and not current["unsaved"]
        core_record = json.loads((packaged.data / "resource-cleanup.json").read_text())
        assert core_record["version"] == 1 and core_record["state"] == "complete", core_record
        assert all(row.get("state") in {"released", "not_started"}
                   for row in core_record["resources"].values()), core_record
        receipts = sorted((packaged.home / "Library/odin-desktop/.install-ownership/macos/receipts")
                          .glob("*.json"))
        roles = sorted(json.loads(path.read_text())["role"] for path in receipts)
        states = {json.loads(path.read_text())["state"] for path in receipts}
        assert roles == ["app", "core"] and states == {"clean"}, (roles, states)
        checks["clean Exit records (app, engine, lease)"] = True
    finally:
        model.close()
        if REPORT:
            Path(REPORT).write_text(json.dumps({"app": APP, "python": sys.version,
                                                "checks": checks}, indent=2, default=str) + "\n")
