"""Odin's tools through the real core on macOS, end to end (phase 3).

The engine starts as the app starts it, in a fresh profile, with a scripted model: an
OpenAI-compatible peer on this computer that asks for real tool calls (never a real model).
The engine's own tool loop and executor run each call, and what a model would read back reaches
the peer, where it is checked: commands, a script, a background job, reading and patching a file,
validation, an HTTP probe and an MCP server whose process tree must end when it is stopped.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import os
import re
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tests.macos.test_core_end_to_end import Core, hello, receive, send

ROOT = Path(__file__).resolve().parents[2]
MODEL = "scripted-macos"
TURN_SECONDS = 180
PYTHON = sys.executable


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Client:
    """One authenticated connection: requests, frames and pongs, as the app sends them."""

    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer

    async def send(self, frame: dict) -> None:
        await send(self.writer, frame)

    async def read(self) -> dict:
        return await receive(self.reader, timeout=150)

    async def request(self, method: str, params: dict | None = None) -> str:
        request_id = str(uuid.uuid4())
        await self.send({"t": "req", "id": request_id, "method": method, "params": params or {}})
        return request_id

    async def close(self) -> None:
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except OSError:
            pass


async def connect(core: Core) -> Client:
    reader, writer, welcome = await hello(core)
    assert welcome["t"] == "welcome", welcome
    return Client(reader, writer)


# The real CLI with only the OS secret storage replaced by an in-memory double (as the app's
# real-core tests do): settings and provider changes need a keyring, and a test home has no
# login keychain. Nothing here reads or writes a keychain.
MEMORY_KEYRING_ENTRY = """
import runpy
from src.desktop.management import ManagementService


class MemoryKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, namespace, name):
        return self.values.get((namespace, name))

    def set_password(self, namespace, name, value):
        self.values[(namespace, name)] = value

    def delete_password(self, namespace, name):
        self.values.pop((namespace, name), None)


original = ManagementService.compose.__func__
backend = MemoryKeyring()
ManagementService.compose = classmethod(
    lambda cls, core, **kw: original(cls, core, secret_backend=backend))
runpy.run_module("src", run_name="__main__")
"""


def launch(tmp_path) -> Core:
    import subprocess

    home = Path(os.path.realpath(tmp_path)) / "home"
    home.mkdir()
    core = Core(home)
    entry = home / "memory-keyring-core.py"
    entry.write_text(MEMORY_KEYRING_ENTRY)
    # Inherited (coverage measures the engine through its environment), with this home.
    environment = {**os.environ, "HOME": str(home), "LANG": "en_US.UTF-8",
                   "TMPDIR": os.environ.get("TMPDIR", "/tmp"), "PYTHONDONTWRITEBYTECODE": "1",
                   "PYTHONPATH": str(ROOT)}
    with open(core.log, "wb") as stderr:
        core.process = subprocess.Popen(
            [PYTHON, "-B", str(entry), "--socket", str(core.socket),
             "--token-file", str(core.token_file), "--profile", core.profile,
             "--data-dir", str(core.paths.data_dir)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=stderr, cwd=ROOT,
            env=environment)
    return core


def end(core: Core) -> None:
    if core.process is not None and core.process.poll() is None:
        core.process.stdin.close()
        try:
            core.process.wait(60)
        except Exception:
            pass
    core.stop()


def _text(message: dict) -> str:
    content = message.get("content") or ""
    if isinstance(content, str):
        return content
    return "\n".join(part.get("text", "") for part in content if isinstance(part, dict))


class ScriptedModel:
    """The model's side of the chat API. A prompt names its script with ``[script:<name>]``;
    each generation after it gets the script's next call, chosen from the tool results so
    far (the text a model reads), then a final reply. Asks without tools (the completion
    judge) are answered COMPLETE."""

    def __init__(self):
        self.scripts: dict = {}
        self.results: dict[str, list[str]] = {}
        self.errors: list[str] = []
        self.tools: dict[str, str] = {}  # the latest description of each tool the model was given
        self._ids = itertools.count(1)
        model = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path != "/v1/models":
                    self.send_error(404)
                    return
                body = json.dumps({"data": [{"id": MODEL, "object": "model"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                request = json.loads(self.rfile.read(length) or b"{}")
                if self.path != "/v1/chat/completions":
                    self.send_error(404)
                    return
                delta = model.answer(request)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                finish = "tool_calls" if "tool_calls" in delta else "stop"
                for frame in (
                    {"id": "scripted", "object": "chat.completion.chunk", "model": MODEL,
                     "choices": [{"index": 0, "delta": {"role": "assistant", **delta},
                                  "finish_reason": None}]},
                    {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
                    {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                                              "total_tokens": 120}},
                ):
                    self.wfile.write(f"data: {json.dumps(frame)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_port
        self.base_url = f"http://127.0.0.1:{self.port}/v1"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def answer(self, request: dict) -> dict:
        if not request.get("tools"):
            return {"content": "COMPLETE"}
        for tool in request["tools"]:
            function = tool.get("function") or tool
            self.tools[function.get("name")] = function.get("description") or ""
        messages = request.get("messages") or []
        prompts = [index for index, message in enumerate(messages)
                   if message.get("role") == "user" and "[script:" in _text(message)]
        if not prompts:
            return {"content": "Scripted reply: no script."}
        name = re.search(r"\[script:([a-z_]+)\]", _text(messages[prompts[-1]])).group(1)
        results = [_text(message) for message in messages[prompts[-1] + 1:]
                   if message.get("role") == "tool"]
        self.results[name] = results
        try:
            step = self.scripts[name](results)
        except Exception:
            self.errors.append(traceback.format_exc())
            step = None
        if step is None:
            return {"content": f"Scripted reply: {name} finished."}
        tool, arguments = step
        return {"tool_calls": [{"index": 0, "id": f"call_{next(self._ids)}", "type": "function",
                                "function": {"name": tool, "arguments": json.dumps(arguments)}}]}

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def sequence(*calls):
    """A script of fixed calls, one per generation, then the reply."""
    return lambda results: calls[len(results)] if len(results) < len(calls) else None


async def ask(client, method: str, params: dict | None = None) -> dict:
    request = await client.request(method, params)
    while True:
        frame = await asyncio.wait_for(client.read(), 120)
        if frame.get("t") == "ping":
            await client.send({"t": "pong", "n": frame.get("n", 0)})
        elif frame.get("t") == "res" and frame.get("id") == request:
            return frame


async def call(client, method: str, params: dict | None = None):
    frame = await ask(client, method, params)
    assert frame.get("ok"), f"{method}: {frame.get('error')}"
    return frame["result"]


async def use(client, model: ScriptedModel) -> None:
    """The scripted model as the main model, set as the app sets a provider."""
    async def save(method, changes):
        revision = (await call(client, "settings.schema"))["revision"]
        await call(client, method, {"expected_revision": revision, "changes": changes})

    await save("providers.compat.set", [{"path": "openai_compatible.enabled", "value": False}])
    await save("providers.codex.set", [{"path": "openai_codex.enabled", "value": False}])
    await save("providers.auxiliary.set",
               [{"path": "openai_codex.auxiliary.enabled", "value": False}])
    await save("providers.compat.set", [
        {"path": "openai_compatible.base_url", "value": model.base_url},
        {"path": "openai_compatible.model", "value": MODEL},
        {"path": "openai_compatible.preset", "value": "custom"},
        {"path": "openai_compatible.reasoning_dialect", "value": "none"},
        {"path": "openai_compatible.reasoning_effort", "value": "none"},
        {"path": "openai_compatible.max_tokens", "value": 4096}])
    await call(client, "secrets.set",
               {"path": "openai_compatible.api_key", "value": "scripted-local-test-only"})
    await save("providers.compat.set", [{"path": "openai_compatible.enabled", "value": True}])
    revision = (await call(client, "settings.schema"))["revision"]
    await call(client, "models.main.set",
               {"model": f"compat:{MODEL}", "expected_revision": revision})
    status = await call(client, "status.get")
    assert status["model"] == {"main": MODEL, "effort": None, "provider": "compat"}


async def chat(client) -> str:
    return (await call(client, "conversations.create", {"title": "tools"}))["conversation"]["id"]


async def run(client, conversation: str, script: str) -> tuple[dict, list[dict]]:
    """Sends a prompt naming ``script`` and waits for its request to end: (its outcome, its
    tool calls as the app lists them). See ``settled`` for one that must complete."""
    admitted = await call(client, "submission.send", {
        "client_submission_id": uuid.uuid4().hex, "conversation_id": conversation,
        "text": f"Run [script:{script}]"})
    assert admitted["disposition"] == "accepted", admitted
    request, generation = admitted["request_id"], admitted.get("generation", 1)
    deadline = time.monotonic() + TURN_SECONDS
    while time.monotonic() < deadline:
        snapshot = await call(client, "conversation.snapshot",
                              {"conversation_id": conversation, "limit": 30})
        done = next((item for item in snapshot["recent"] if item["request_id"] == request
                     and item["generation"] == generation), None)
        if done:
            return done, snapshot["tools"].get(request, [])
        await asyncio.sleep(0.5)
    pytest.fail(f"[script:{script}] still running after {TURN_SECONDS}s")


def calls(tools: list[dict]) -> list[tuple]:
    return [(tool["tool"], tool.get("outcome")) for tool in tools]


def settled(done: dict, core, model: ScriptedModel, script: str) -> None:
    """The request completed with no unknown effects; otherwise what the model read and the
    engine's log say why."""
    assert done["outcome"] == "completed" and not done["unknown_effects"], (
        f"{done}\nthe model read: {model.results.get(script)}\nscript errors: {model.errors}\n"
        f"engine log:\n{core.stderr()[-4000:]}")


async def gone(pid: int, seconds: float = 30) -> bool:
    deadline = time.monotonic() + seconds
    while alive(pid):
        if time.monotonic() > deadline:
            return False
        await asyncio.sleep(0.2)
    return True


def job(results: list[str]):
    """Start a job that answers one line, write it the line, poll until it answers, then stop
    it once."""
    if not results:
        return "manage_process", {"action": "start", "host": "localhost",
                                  "command": 'read line; echo "got $line"; sleep 120'}
    found = re.search(r"PID (\d+)", results[0])
    if found is None:
        return None
    pid = int(found.group(1))
    if len(results) == 1:
        return "manage_process", {"action": "write", "host": "localhost", "pid": pid,
                                  "input_text": "ping\n"}
    polls = results[2:]
    answered = next((index for index, result in enumerate(polls) if "got ping" in result), None)
    if answered is None:
        return ("manage_process", {"action": "poll", "host": "localhost", "pid": pid,
                                   "wait_seconds": 2}) if len(polls) < 6 else None
    if len(polls) == answered + 1:
        return "manage_process", {"action": "kill", "host": "localhost", "pid": pid}
    return None


async def test_local_tools_run_through_the_engine(tmp_path):
    model = ScriptedModel()
    work = tmp_path / "work"
    work.mkdir()
    notes = work / "notes.txt"
    add = "*** Begin Patch\n*** Add File: notes.txt\n+first line\n+second line\n*** End Patch"
    update = ("*** Begin Patch\n*** Update File: notes.txt\n@@\n first line\n-second line\n"
              "+second line, patched\n*** End Patch")
    large_text = "large \u03bb payload " * 2800  # over Odin's plain command limit: compressed
    large = f"*** Begin Patch\n*** Add File: large.txt\n+{large_text}\n*** End Patch"
    # Odin 4.15 (#657): a move that only changes the name's case, on this case-insensitive APFS.
    case_only = ("*** Begin Patch\n*** Update File: notes.txt\n*** Move to: Notes.txt\n@@\n"
                 " first line\n-second line, patched\n+second line, renamed\n*** End Patch")
    model.scripts.update({
        "command": sequence(("run_command", {
            "host": "localhost", "command": 'echo "e2e $((40 + 2))"'})),
        "failure": sequence(("run_command", {"host": "localhost", "command": "exit 7"})),
        "script": sequence(("run_script", {
            "host": "localhost", "interpreter": "bash",
            "script": 'total=$((6 * 7))\necho "script $total"\necho "path ${PATH%%:*}"'})),
        "job": job,
        "file": sequence(
            ("apply_patch", {"host": "localhost", "root": str(work), "patch_text": add}),
            ("read_file", {"host": "localhost", "path": str(notes)}),
            ("apply_patch", {"host": "localhost", "root": str(work), "patch_text": update}),
            ("read_file", {"host": "localhost", "path": str(notes)}),
            ("read_file", {"host": "localhost", "path": str(notes), "raw": True}),
            ("apply_patch", {"host": "localhost", "root": str(work), "patch_text": large})),
        "case": sequence(
            ("apply_patch", {"host": "localhost", "root": str(work), "patch_text": case_only})),
        "validate": sequence(("validate_action", {"bundle_name": "e2e", "checks": [
            {"type": "http", "target": f"{model.base_url}/models", "expected": [200],
             "host": "localhost"},
            {"type": "port", "target": f"127.0.0.1:{model.port}", "host": "localhost"},
            {"type": "process", "target": "--token-file", "host": "localhost"},
            {"type": "command", "target": "echo ready", "host": "localhost"},
            # Odin 4.15's macOS probes, chosen because this Mac's local host says os: macos.
            {"type": "service", "target": "com.apple.logd", "host": "localhost"},
            {"type": "log_absent", "target": "unit=odin-desktop-e2e-absent:never logged here",
             "window_seconds": 60, "host": "localhost"}]})),
        "probe": sequence(("http_probe", {"host": "localhost", "url": f"{model.base_url}/models"})),
    })
    core = launch(tmp_path)
    try:
        client = await connect(core)
        try:
            await use(client, model)
            conversation = await chat(client)

            done, tools = await run(client, conversation, "command")
            settled(done, core, model, "command")
            assert calls(tools) == [("run_command", "success")], model.results
            assert "e2e 42" in model.results["command"][0]
            # The model is told which bash runs commands here and that the Mac's tools differ.
            told = re.search(r" Local commands run under (Apple's bash 3\.2 \(/bin/bash\)|"
                             r"bash \(/\S+\)) on this Mac, where the system's own tools are the "
                             r"BSD versions, not GNU", model.tools["run_command"])
            assert told, model.tools["run_command"]

            done, tools = await run(client, conversation, "failure")
            settled(done, core, model, "failure")
            assert calls(tools) == [("run_command", "failure")], model.results
            assert model.results["failure"][0].startswith("Command failed (exit 7)")

            done, tools = await run(client, conversation, "script")
            settled(done, core, model, "script")
            assert calls(tools) == [("run_script", "success")], model.results
            assert "script 42" in model.results["script"][0]
            # The model's script runs with the user's PATH, never the engine's private python3.
            assert "odin-desktop-bin-" not in model.results["script"][0], model.results

            done, tools = await run(client, conversation, "job")
            settled(done, core, model, "job")
            results = model.results["job"]
            pid = int(re.search(r"PID (\d+)", results[0]).group(1))
            assert results[0].startswith(f"Process started (PID {pid})"), results
            assert results[1] == f"Wrote 5 bytes to PID {pid}.", results
            assert "got ping" in results[-2], results
            stopped = json.loads(results[-1])["result"]  # the app's Work control stops it
            assert stopped["disposition"] == "done", results
            # macOS: the stop converged on the job's session; it is labelled best effort.
            assert stopped["settlement"]["resource_release"] == "best_effort", results
            assert stopped["settlement"]["scope"] == "session_best_effort", results
            assert {outcome for _, outcome in calls(tools)} == {"success"}
            assert await gone(pid), "the job outlived its stop"

            done, tools = await run(client, conversation, "file")
            settled(done, core, model, "file")
            expected = [("apply_patch", "success"), ("read_file", "success")] * 2 + [
                ("read_file", "success"), ("apply_patch", "success")]
            assert calls(tools) == expected, model.results
            results = model.results["file"]
            assert "second line" in results[1] and "patched" not in results[1], results
            assert "second line, patched" in results[3], results
            assert ("<<<ODIN_READ_FILE_RAW_CONTENT_V1>>>\nfirst line\nsecond line, patched\n"
                    "<<<ODIN_READ_FILE_RAW_END_V1>>>") in results[4], results
            assert (work / "large.txt").read_text(encoding="utf-8") == large_text + "\n"
            assert sorted(path.name for path in work.iterdir()) == ["large.txt", "notes.txt"]
            assert notes.read_bytes() == b"first line\nsecond line, patched\n"

            done, tools = await run(client, conversation, "case")
            settled(done, core, model, "case")
            assert calls(tools) == [("apply_patch", "success")], model.results
            assert sorted(path.name for path in work.iterdir()) == ["Notes.txt", "large.txt"]
            assert (work / "Notes.txt").read_bytes() == b"first line\nsecond line, renamed\n"

            done, tools = await run(client, conversation, "validate")
            settled(done, core, model, "validate")
            assert calls(tools) == [("validate_action", "success")], model.results
            report = model.results["validate"][0]
            assert report.startswith("[PASS] bundle='e2e' passed=6/6"), report

            done, tools = await run(client, conversation, "probe")
            settled(done, core, model, "probe")
            assert calls(tools) == [("http_probe", "success")], model.results
            assert "200" in model.results["probe"][0] and MODEL in model.results["probe"][0]
            assert model.errors == []
        finally:
            await client.close()
    finally:
        end(core)
        model.close()


async def test_an_mcp_server_serves_the_model_and_its_tree_ends_at_stop(tmp_path):
    model = ScriptedModel()
    model.scripts["mcp"] = sequence(
        ("mcp_e2e_echo", {"text": "hello from macos"}),
        ("mcp_e2e_child_pid", {}))
    core = launch(tmp_path)
    try:
        client = await connect(core)
        try:
            await use(client, model)
            revision = (await call(client, "settings.schema"))["revision"]
            await call(client, "mcp.set_global_enabled",
                       {"enabled": True, "expected_revision": revision})
            revision = (await call(client, "settings.schema"))["revision"]
            await call(client, "mcp.save", {
                "name": "e2e", "expected_revision": revision, "enabled": True,
                "transport": "stdio", "command": PYTHON,
                "args": [str(ROOT / "tests" / "fakes" / "mcp_stdio_server.py"), "grandchild"],
                "cwd": str(tmp_path)})
            deadline = time.monotonic() + 60
            while "echo" not in json.dumps(await call(client, "mcp.tools", {"name": "e2e"})):
                assert time.monotonic() < deadline, await call(client, "mcp.status")
                await asyncio.sleep(0.5)

            done, tools = await run(client, await chat(client), "mcp")
            settled(done, core, model, "mcp")
            expected = [("mcp_e2e_echo", "success"), ("mcp_e2e_child_pid", "success")]
            assert calls(tools) == expected, model.results
            results = model.results["mcp"]
            assert "hello from macos" in results[0], results
            child = int(re.search(r"\d+", results[1]).group())
            assert child and alive(child)

            revision = (await call(client, "settings.schema"))["revision"]
            await call(client, "mcp.set_enabled",
                       {"name": "e2e", "enabled": False, "expected_revision": revision})
            assert await gone(child), "the server's tree outlived its stop"
            assert model.errors == []
        finally:
            await client.close()
    finally:
        end(core)
        model.close()


# The SSH path needs a host that is not this computer by address (127.0.0.1 runs locally), so the
# test serves one itself: an unprivileged sshd on this machine's own network address, with its own
# host key and only this profile's key authorized. CI's disposable runner sets the variable; it
# never runs by default, so no listener opens on a person's network.
ssh_target = pytest.mark.skipif(os.environ.get("ODIN_MACOS_SSH_TEST") != "1",
                                reason="opens an sshd on this machine's network address (CI only)")


def _own_address() -> str:
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # no packet is sent; it picks the outbound address
        return probe.getsockname()[0]
    finally:
        probe.close()


@ssh_target
async def test_a_remote_host_serves_the_model_over_ssh(tmp_path):
    import shutil
    import socket
    import subprocess

    from src.tools.hosts.trust import fingerprint_public_key

    address = _own_address()
    assert not address.startswith("127.")
    serve = Path(os.path.realpath(tmp_path)) / "sshd"
    serve.mkdir(mode=0o700)
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(serve / "host_key")],
                   check=True)
    with socket.socket() as free:
        free.bind((address, 0))
        port = free.getsockname()[1]
    remote = Path(os.path.realpath(tmp_path)) / "remote"
    remote.mkdir()
    add = "*** Begin Patch\n*** Add File: notes.txt\n+first line\n+second line\n*** End Patch"
    update = ("*** Begin Patch\n*** Update File: notes.txt\n@@\n first line\n-second line\n"
              "+second line, patched\n*** End Patch")
    model = ScriptedModel()
    model.scripts["ssh"] = sequence(
        ("run_command", {"host": "box", "command": "uname -s; echo e2e-$((6 * 7))"}),
        ("run_command", {"host": "box", "command": "exit 7"}),
        ("read_file", {"host": "box", "path": "/etc/hosts"}),
        # Odin's own GNU-written commands on a remote Mac, made portable by Desktop; the host's
        # own python3 runs the patch runner.
        ("apply_patch", {"host": "box", "root": str(remote), "patch_text": add}),
        ("apply_patch", {"host": "box", "root": str(remote), "patch_text": update}),
        ("read_file", {"host": "box", "path": str(remote / "notes.txt"), "raw": True}))
    core = launch(tmp_path)
    sshd = None
    try:
        client = await connect(core)
        try:
            await use(client, model)
            public = await call(client, "hosts.public_key")
            (serve / "authorized_keys").write_text(public["public_key"].strip() + "\n")
            (serve / "authorized_keys").chmod(0o600)
            (serve / "sshd_config").write_text(
                f"Port {port}\nListenAddress {address}\nHostKey {serve / 'host_key'}\n"
                f"AuthorizedKeysFile {serve / 'authorized_keys'}\nPasswordAuthentication no\n"
                "KbdInteractiveAuthentication no\nUsePAM no\nStrictModes no\n"
                f"PidFile {serve / 'sshd.pid'}\n")
            sshd = subprocess.Popen(["/usr/sbin/sshd", "-D", "-f", str(serve / "sshd_config"),
                                     "-E", str(serve / "sshd.log")])
            fingerprint = fingerprint_public_key(
                " ".join((serve / "host_key.pub").read_text().split()[:2]))
            candidate = await call(client, "hosts.prepare", {
                "alias": "box", "address": address, "port": port, "os": "macos",
                "ssh_user": os.environ.get("USER") or os.getlogin(), "trust_mode": "pinned",
                "expected_fingerprints": [fingerprint]})
            tested = await call(client, "hosts.test", {"token": candidate["candidate_token"]})
            assert tested["tested"], (tested, (serve / "sshd.log").read_text()[-2000:])
            await call(client, "hosts.commit", {"token": candidate["candidate_token"]})

            done, tools = await run(client, await chat(client), "ssh")
            settled(done, core, model, "ssh")
            expected = [("run_command", "success"), ("run_command", "failure"),
                        ("read_file", "success"), ("apply_patch", "success"),
                        ("apply_patch", "success"), ("read_file", "success")]
            assert calls(tools) == expected, model.results
            results = model.results["ssh"]
            assert "Darwin" in results[0] and "e2e-42" in results[0], results
            assert results[1].startswith("Command failed (exit 7)"), results
            assert "localhost" in results[2], results
            assert (remote / "notes.txt").read_bytes() == b"first line\nsecond line, patched\n"
            assert ("<<<ODIN_READ_FILE_RAW_CONTENT_V1>>>\nfirst line\nsecond line, patched\n"
                    "<<<ODIN_READ_FILE_RAW_END_V1>>>") in results[5], results
            assert model.errors == []
        finally:
            await client.close()
    finally:
        end(core)
        model.close()
        if sshd is not None:
            sshd.terminate()
            sshd.wait(10)
        shutil.rmtree(serve, ignore_errors=True)
