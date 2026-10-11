"""The real core on Windows, end to end (phase 2 plan B4).

A fresh profile, the engine started as the app starts it, the sealed session,
the startup trace's committed method list, the refusals, and a clean exit when
the parent closes stdin.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.desktop.platform.windows import windows_profile_paths
from src.desktop.platform.windows_ipc import WindowsIpc, pipe_name

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "windows-core-methods.json")
                     .read_text(encoding="utf-8"))
# The installed app's interpreter flags (its own test pins them to the same file).
LAUNCH = json.loads((ROOT / "tests" / "fixtures" / "windows-core-launch.json")
                    .read_text(encoding="utf-8"))["interpreter_flags"]
STARTUP_SECONDS = 120


@dataclass
class Core:
    process: subprocess.Popen
    pipe: str
    token_file: Path
    token: str
    profile: str
    log: Path
    paths: object

    def stderr(self) -> str:
        return self.log.read_text(encoding="utf-8", errors="replace")


def launch(tmp_path, prepare=None, flags=LAUNCH) -> Core:
    """The engine started as the app starts it, in a fresh profile. ``prepare`` gets the
    profile's paths before the first start."""
    profile = f"e2e{uuid.uuid4().hex[:8]}"
    local = tmp_path / "local"
    paths = windows_profile_paths(profile, environ={"LOCALAPPDATA": str(local)})
    # The app's part: the private profile folders and the token, before the first start.
    paths.create_private()
    token = secrets.token_hex(32)
    token_file = paths.config_dir / "ipc.token"
    token_file.write_text(token, encoding="ascii")
    if prepare is not None:
        prepare(paths)
    (tmp_path / "home").mkdir()
    return start(tmp_path, profile, paths, token_file, token, flags)


def start(tmp_path, profile, paths, token_file, token, flags=LAUNCH, log_name="core.log") -> Core:
    """The engine started as the app starts it, on a profile ``launch`` made."""
    environ = {**os.environ, "LOCALAPPDATA": str(tmp_path / "local"),
               "APPDATA": str(tmp_path / "roaming"), "USERPROFILE": str(tmp_path / "home")}
    log = tmp_path / log_name
    pipe = pipe_name(profile)
    with open(log, "wb") as stderr:
        process = subprocess.Popen(
            [sys.executable, *flags, "-m", "src", "--socket", pipe,
             "--token-file", str(token_file), "--profile", profile,
             "--data-dir", str(paths.data_dir)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=stderr, cwd=ROOT,
            env=environ)
    return Core(process, pipe, token_file, token, profile, log, paths)


def end(core: Core) -> None:
    if core.process.poll() is None:
        core.process.kill()
    core.process.wait(30)
    if core.process.stdin:
        core.process.stdin.close()


@pytest.fixture
def core(tmp_path):
    running = launch(tmp_path)
    try:
        yield running
    finally:
        end(running)


async def connect(core: Core, token_file: Path | None = None):
    from src.desktop.local_client import LocalClient

    deadline = time.monotonic() + STARTUP_SECONDS
    while True:
        if core.process.poll() is not None:
            pytest.fail(f"core exited {core.process.returncode}:\n{core.stderr()[-3000:]}")
        try:
            return await LocalClient.connect(core.pipe, token_file or core.token_file,
                                             core.profile)
        except (FileNotFoundError, TimeoutError):  # no pipe yet, or every instance busy
            if time.monotonic() > deadline:
                pytest.fail(f"no pipe after {STARTUP_SECONDS}s:\n{core.stderr()[-3000:]}")
            await asyncio.sleep(0.25)


async def call(client, method: str, params: dict | None = None) -> dict:
    request = await client.request(method, params)
    while True:
        frame = await asyncio.wait_for(client.read(), 60)
        if frame.get("t") == "res" and frame.get("id") == request:
            return frame


def outcome(reply: dict) -> str:
    return "ok" if reply.get("ok") else "error " + str(reply.get("error", {}).get("code"))


class Recording:
    """Records every byte one connection writes and reads."""

    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.sent, self.received = bytearray(), bytearray()

    async def readexactly(self, n):
        data = await self.reader.readexactly(n)
        self.received += data
        return data

    def write(self, data):
        self.sent += data
        self.writer.write(data)

    def __getattr__(self, name):
        return getattr(self.writer, name)


async def test_the_real_core_serves_the_trace_and_exits_clean(core):
    client = await connect(core)
    try:
        capabilities = client.welcome["capabilities"]
        read_only = sorted(m for m in capabilities
                           if m.rsplit(".", 1)[-1] in {"get", "list", "schema"})
        assert read_only == sorted(FIXTURE["read_only"]), "update the committed method list"
        outcomes = {method: outcome(await call(client, method, FIXTURE["params"].get(method)))
                    for method in read_only}
        assert outcomes == FIXTURE["read_only"]

        created = (await call(client, "conversations.create", {"title": "e2e"}))["result"]
        conversation = created["conversation"]
        updated = await call(client, "conversations.update", {
            "id": conversation["id"], "expected_rev": conversation["rev"], "title": "e2e 2"})
        assert outcome(updated) == "ok"
        revision = updated["result"]["conversation"]["rev"]
        snapshot = await call(client, "conversation.snapshot",
                              {"conversation_id": conversation["id"]})
        assert outcome(snapshot) == "ok"
        reset = await call(client, "conversations.reset_context",
                           {"id": conversation["id"], "expected_rev": revision})
        assert outcome(reset) == "ok"
        deleted = await call(client, "conversations.delete", {
            "id": conversation["id"], "expected_rev": reset["result"]["conversation"]["rev"]})
        assert outcome(deleted) == "ok"

        schema = (await call(client, "settings.schema"))["result"]
        saved = await call(client, "settings.set", {
            "expected_revision": schema["revision"],
            "changes": [{"path": "timezone", "value": "America/New_York"}]})
        assert outcome(saved) == "ok", saved
        memory = {"scope": "global", "key": "e2e"}
        assert outcome(await call(client, "memory.set", {**memory, "value": "kept"})) == "ok"
        assert (await call(client, "memory.get", memory))["result"]["value"] == "kept"
        assert outcome(await call(client, "memory.delete", memory)) == "ok"
    finally:
        await client.close()

    await refusals(core)

    core.process.stdin.close()  # the parent's end of the link
    assert core.process.wait(60) == 0, core.stderr()[-3000:]
    assert "Teardown unproven" not in core.stderr()


# None of these is in Windows-1252, an English Windows's ANSI code page.
NON_LATIN = "Odin → ✓ 日本"


async def test_text_outside_the_ansi_code_page_survives_another_save_and_a_restart(tmp_path):
    """Started as the app starts it (-X utf8), the engine keeps a setting the ANSI code page can't
    hold through a later save of another setting and a restart, like Linux. Without UTF-8 mode
    that later save reads config.yml back as the ANSI code page and writes the name back
    garbled; the installed app lost a turn's trajectory to the same default, over a "→"."""
    import ctypes

    names, configs = {}, {}
    # Short folder names: a restart writes a profile backup deep enough to meet MAX_PATH here.
    for arm, folder, flags in (
            ("shipped", "utf8", LAUNCH),
            ("without UTF-8 mode", "ansi", [f for f in LAUNCH if f not in ("-X", "utf8")])):
        home = tmp_path / folder
        home.mkdir()
        first = launch(home, flags=flags)
        try:
            client = await connect(first)
            try:
                saved = await call(client, "personality.set",
                                   {"preset": "odin", "custom_name": NON_LATIN})
                assert outcome(saved) == "ok", saved
                schema = (await call(client, "settings.schema"))["result"]
                other = await call(client, "settings.set", {
                    "expected_revision": schema["revision"],
                    "changes": [{"path": "timezone", "value": "Pacific/Auckland"}]})
                assert outcome(other) == "ok", other
            finally:
                await client.close()
            first.process.stdin.close()
            assert first.process.wait(60) == 0, first.stderr()[-3000:]
        finally:
            end(first)
        again = start(home, first.profile, first.paths, first.token_file, first.token, flags,
                      "core-2.log")
        try:
            client = await connect(again)
            try:
                names[arm] = (await call(client, "personality.get"))["result"]["custom_name"]
            finally:
                await client.close()
        finally:
            end(again)
        configs[arm] = first.paths.config_file.read_bytes()

    assert names["shipped"] == NON_LATIN
    assert NON_LATIN in configs["shipped"].decode("utf-8")
    if ctypes.windll.kernel32.GetACP() == 65001:
        pytest.skip("this Windows's ANSI code page is UTF-8: the failing arm can't fail here")
    assert names["without UTF-8 mode"] != NON_LATIN, names
    assert NON_LATIN.encode("utf-8") not in configs["without UTF-8 mode"]


async def refusals(core: Core) -> None:
    from src.desktop.ipc_auth import client_session
    from src.desktop.protocol import encode_frame, read_frame

    wrong = core.token_file.with_name("wrong.token")
    wrong.write_text(secrets.token_hex(32), encoding="ascii")
    with pytest.raises(PermissionError, match="engine proof refused"):
        await connect(core, wrong)

    reader, writer = await WindowsIpc().connect(core.pipe)
    writer.write(encode_frame({"t": "hello", "protocol": {"major": 0, "minor": 2},
                               "client": {"name": "e2e", "version": "0"},
                               "profile_id": core.profile, "token": core.token, "features": []}))
    await writer.drain()
    assert await read_frame(reader) == {"t": "bye", "reason": "unauthorized"}
    writer.close()

    reader, writer = await WindowsIpc().connect(core.pipe)
    wire = Recording(reader, writer)
    sealed_reader, sealed_writer = await client_session(
        wire, wire, token=core.token, profile_id=core.profile, endpoint=core.pipe,
        client={"name": "e2e", "version": "0"}, offered={"major": 0, "minor": 2}, features=[])
    welcome = await read_frame(sealed_reader)
    assert welcome["t"] == "welcome" and welcome["profile_id"] == core.profile
    sealed_writer.write(encode_frame({"t": "req", "id": str(uuid.uuid4()),
                                      "method": "status.get", "params": {}}))
    await sealed_writer.drain()
    while (frame := await read_frame(sealed_reader))["t"] != "res":
        pass
    assert frame["ok"]
    writer.close()
    for secret in (core.token.encode(), bytes.fromhex(core.token)):
        assert secret not in wire.sent and secret not in wire.received
    assert b"status.get" not in wire.sent  # sealed, not just token-free
