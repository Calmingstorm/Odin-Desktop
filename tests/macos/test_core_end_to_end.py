"""The real core on macOS, end to end.

A fresh profile under a temporary home's Library, the socket in the verified per-user temporary
folder, the token handshake and its refusals, the committed read-only method list, ordinary writes
that stay in the profile, and a clean exit on parent EOF, on runtime.shutdown and on SIGTERM.
The temporary home has no login keychain, so the engine's keychain is unavailable here, exactly as
Linux CI has no Secret Service: no keychain is read or written by these tests.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

from src.desktop.platform.macos import macos_profile_paths, macos_socket_path
from src.desktop.platform.macos_ipc import MacOSIpc

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "windows-core-methods.json").read_text())
STARTUP_SECONDS = 120


class Core:
    def __init__(self, home: Path):
        self.home = home
        self.profile = f"e2e{uuid.uuid4().hex[:8]}"
        self.paths = macos_profile_paths(self.profile, home=home)
        self.paths.create_private()
        self.token = secrets.token_hex(32)
        self.token_file = self.paths.config_dir / "ipc.token"
        self.token_file.write_text(self.token, encoding="ascii")
        self.token_file.chmod(0o600)
        self.socket = macos_socket_path(self.profile)
        self.log = home / f"core-{uuid.uuid4().hex[:6]}.log"
        self.process = None

    def start(self):
        environment = {"PATH": os.environ["PATH"], "HOME": str(self.home), "LANG": "en_US.UTF-8",
                       "TMPDIR": os.environ.get("TMPDIR", "/tmp"), "PYTHONDONTWRITEBYTECODE": "1"}
        with open(self.log, "wb") as stderr:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "src", "--socket", str(self.socket),
                 "--token-file", str(self.token_file), "--profile", self.profile,
                 "--data-dir", str(self.paths.data_dir)],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=stderr, cwd=ROOT,
                env=environment)
        return self

    def stderr(self) -> str:
        return self.log.read_text(encoding="utf-8", errors="replace")

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            self.process.wait(30)
        shutil.rmtree(self.socket.parent, ignore_errors=True)
        # The SSH pool's per-profile control-socket folder (macos_desktop's /private/tmp root).
        ssh = f"/private/tmp/odin-desktop-{os.geteuid()}/{self.profile}"
        shutil.rmtree(ssh, ignore_errors=True)


@pytest.fixture
def home():
    folder = Path(os.path.realpath(tempfile.mkdtemp(prefix="odin-e2e-")))
    yield folder
    shutil.rmtree(folder, ignore_errors=True)


async def send(writer, message):
    encoded = json.dumps(message).encode()
    writer.write(struct.pack(">I", len(encoded)) + encoded)
    await writer.drain()


async def receive(reader, timeout=60):
    async with asyncio.timeout(timeout):
        header = await reader.readexactly(4)
        return json.loads(await reader.readexactly(struct.unpack(">I", header)[0]))


async def hello(core: Core, *, token=None, profile=None):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + STARTUP_SECONDS
    while True:
        if core.process.poll() is not None:
            pytest.fail(f"core exited {core.process.returncode}: {core.stderr()[-3000:]}")
        try:
            reader, writer = await MacOSIpc.connect(core.socket)
            break
        except (FileNotFoundError, ConnectionRefusedError):
            if loop.time() > deadline:
                pytest.fail(f"no listener within {STARTUP_SECONDS} s: {core.stderr()[-3000:]}")
            await asyncio.sleep(0.05)
    await send(writer, {"t": "hello", "protocol": {"major": 0, "minor": 2},
                        "client": {"name": "macos-e2e", "version": "1"},
                        "profile_id": profile or core.profile, "token": token or core.token,
                        "features": []})
    return reader, writer, await receive(reader)


async def call(reader, writer, method, params=None):
    request_id = str(uuid.uuid4())
    await send(writer, {"t": "req", "id": request_id, "method": method, "params": params or {}})
    while True:
        message = await receive(reader)
        if message.get("t") == "res" and message.get("id") == request_id:
            return message


def outcome(reply: dict) -> str:
    return "ok" if reply.get("ok") else "error " + str(reply.get("error", {}).get("code"))


async def close(writer):
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass


async def test_the_core_boots_answers_and_exits_on_parent_eof(home):
    core = Core(home).start()
    try:
        reader, writer, welcome = await hello(core)
        assert welcome["t"] == "welcome" and welcome["profile_id"] == core.profile
        try:
            status = await call(reader, writer, "status.get")
            assert status["result"]["phase"] == "ready", status
            capabilities = welcome["capabilities"]
            read_only = sorted(m for m in capabilities
                               if m.rsplit(".", 1)[-1] in {"get", "list", "schema"})
            assert read_only == sorted(FIXTURE["read_only"]), "update the committed method list"
            outcomes = {m: outcome(await call(reader, writer, m, FIXTURE["params"].get(m)))
                        for m in read_only}
            # Windows always has DPAPI; this home has no login keychain, as Linux CI has no
            # Secret Service, so the one keychain-backed listing reports it unavailable.
            expected = {**FIXTURE["read_only"], "codex.accounts.list": "error keyring_unavailable"}
            assert outcomes == expected

            created = (await call(reader, writer, "conversations.create",
                                  {"title": "e2e"}))["result"]["conversation"]
            deleted = await call(reader, writer, "conversations.delete",
                                 {"id": created["id"], "expected_rev": created["rev"]})
            assert outcome(deleted) == "ok"
            schema = (await call(reader, writer, "settings.schema"))["result"]
            saved = await call(reader, writer, "settings.set", {
                "expected_revision": schema["revision"],
                "changes": [{"path": "timezone", "value": "America/New_York"}]})
            assert outcome(saved) == "ok", saved
            memory = {"scope": "global", "key": "e2e"}
            assert outcome(await call(reader, writer, "memory.set",
                                      {**memory, "value": "kept"})) == "ok"
            assert (await call(reader, writer, "memory.get", memory))["result"]["value"] == "kept"
        finally:
            await close(writer)

        # Refusals: a wrong token and a wrong profile are told goodbye, the core keeps serving.
        reader, writer, bye = await hello(core, token=secrets.token_hex(32))
        assert bye == {"t": "bye", "reason": "unauthorized"}
        await close(writer)
        reader, writer, bye = await hello(core, profile="someoneelse")
        assert bye == {"t": "bye", "reason": "wrong_profile"}
        await close(writer)

        core.process.stdin.close()  # the app's end of the parent link
        assert core.process.wait(60) == 0, core.stderr()[-3000:]
        assert not core.socket.exists()
        log = core.stderr()
        assert "Traceback" not in log and "Teardown unproven" not in log, log[-3000:]
        assert "macOS process containment: session-scoped, best effort" in log
        # Everything the profile wrote is under the temporary home's Library.
        library = home / "Library"
        assert (library / "Application Support" / "odin-desktop" / core.profile / "data").is_dir()
        assert (library / "Caches" / "odin-desktop" / core.profile).is_dir()
    finally:
        core.stop()


@pytest.mark.parametrize("stop", ["runtime.shutdown", "SIGTERM"])
async def test_the_core_stops_cleanly_on_request_and_signal(home, stop):
    core = Core(home).start()
    try:
        reader, writer, welcome = await hello(core)
        assert welcome["t"] == "welcome"
        if stop == "runtime.shutdown":
            reply = await call(reader, writer, "runtime.shutdown", {"reason": "e2e"})
            assert outcome(reply) == "ok"
        else:
            core.process.send_signal(signal.SIGTERM)
        await close(writer)
        assert core.process.wait(60) == 0, core.stderr()[-3000:]
        assert not core.socket.exists()
        assert "Traceback" not in core.stderr()
    finally:
        core.stop()
