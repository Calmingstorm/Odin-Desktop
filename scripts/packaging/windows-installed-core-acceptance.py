#!/usr/bin/env python3
"""The installed app's real core over its sealed pipe (phase 4c, plan R4 item 1).

For a disposable Windows account only. Run as the test user after a default install, with the
installed runtime's own interpreter (python.exe -I -B). It starts a loopback scripted model,
starts Odin.exe hidden, authenticates to the core with the engine's own client and points the
compat provider at the scripted model through the ordinary settings methods. Then it runs a
tool turn whose tool writes a marker. A skill with a dependency then installs it through the
bundled pip from a loopback package index (the test user's own pip.ini points there, and is
restored), into the profile, leaving the install tree unchanged. Then it exits the app, starts
it again and reads the turn back and runs the skill again, and checks that a client offering
another protocol major is refused. Nothing from the install is left running. The report is
JSON and is written however the run ends.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import http.server
import json
import os
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from pathlib import Path

MODEL = "canned-contract"
PROMPT = "[tool] Run the scripted local tool."
REPLY = "Scripted reply: the installed tool ran."
MARK = "installed core tool ran"
SKILL = "skill_package_probe"
PACKAGE, MODULE, VERSION = "odin-skill-probe", "odin_skill_probe", "1.0"
PACKAGE_MARK = "odin skill probe 1.0"


def scripted_model(marker: Path) -> http.server.ThreadingHTTPServer:
    """The compat provider's chat API, answering as app/scripts/windows-real-core-smoke.mjs does."""
    quoted = str(marker).replace("'", "''")
    command = f"Set-Content -LiteralPath '{quoted}' -Value '{MARK}'"

    def text(message) -> str:
        content = message.get("content")
        if isinstance(content, str):
            return content
        return "\n".join(part.get("text", "") for part in content or [])

    class Model(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):  # noqa: N802 - http.server's name
            if self.path != "/v1/models":
                self.send_error(404)
                return
            body = json.dumps({"data": [{"id": MODEL, "object": "model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # noqa: N802
            size = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(size) or b"{}")
            if self.path != "/v1/chat/completions":
                self.send_error(404)
                return
            messages = body.get("messages") or []
            last = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
            prompt = text(messages[last]) if last >= 0 else ""
            answered = any(m.get("role") == "tool" for m in messages[last + 1:])
            delta = {"content": "COMPLETE"}  # asked without tools: the completion judge
            if body.get("tools"):
                delta = {"content": "Scripted reply: installed core."}
                if "[tool]" in prompt:
                    delta = {"content": REPLY} if answered else {"tool_calls": [{
                        "index": 0, "id": f"call_{uuid.uuid4().hex[:8]}", "type": "function",
                        "function": {"name": "run_command", "arguments": json.dumps(
                            {"host": "localhost", "command": command})}}]}
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for frame in ({"id": "scripted", "object": "chat.completion.chunk", "model": MODEL,
                           "choices": [{"index": 0, "delta": {"role": "assistant", **delta},
                                        "finish_reason": None}]},
                          {"choices": [{"index": 0, "delta": {}, "finish_reason":
                                        "tool_calls" if "tool_calls" in delta else "stop"}]},
                          {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                                                    "total_tokens": 120}}):
                self.wfile.write(f"data: {json.dumps(frame)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def probe_wheel(folder: Path) -> Path:
    """A minimal pure-Python wheel of the probe package, written without build tools."""
    wheel = folder / f"{MODULE}-{VERSION}-py3-none-any.whl"
    info = f"{MODULE}-{VERSION}.dist-info"
    files = {f"{MODULE}/__init__.py": f'MARK = "{PACKAGE_MARK}"\n',
             f"{info}/METADATA": f"Metadata-Version: 2.1\nName: {PACKAGE}\nVersion: {VERSION}\n",
             f"{info}/WHEEL": ("Wheel-Version: 1.0\nGenerator: odin-acceptance\n"
                               "Root-Is-Purelib: true\nTag: py3-none-any\n")}
    record = []
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, text in files.items():
            data = text.encode()
            archive.writestr(name, data)
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
            record.append(f"{name},sha256={digest.decode()},{len(data)}")
        archive.writestr(f"{info}/RECORD", "\n".join([*record, f"{info}/RECORD,,"]) + "\n")
    return wheel


def package_index(wheel: Path) -> http.server.ThreadingHTTPServer:
    """A PEP 503 simple index on 127.0.0.1 holding only the probe wheel (pip treats loopback as
    a secure origin)."""
    data = wheel.read_bytes()
    link = f"/files/{wheel.name}#sha256={hashlib.sha256(data).hexdigest()}"

    class Index(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):  # noqa: N802 - http.server's name
            if self.path.rstrip("/") == f"/simple/{PACKAGE}":
                body, kind = f'<a href="{link}">{wheel.name}</a>'.encode(), "text/html"
            elif self.path == f"/files/{wheel.name}":
                body, kind = data, "application/octet-stream"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Index)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def skill_code() -> str:
    definition = {"name": SKILL, "description": "Installed-core acceptance probe",
                  "input_schema": {"type": "object", "properties": {}},
                  "dependencies": [f"{PACKAGE}=={VERSION}"]}
    return (f"SKILL_DEFINITION = {definition!r}\nasync def execute(inp, context):\n"
            f"    import {MODULE}\n    return {MODULE}.MARK\n")


def tree_state(root: Path) -> dict[str, tuple[int, int]]:
    """Every file under root by relative path: size and modification time."""
    return {str(path.relative_to(root)): (path.stat().st_size, path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


class Run:
    def __init__(self, report: Path):
        self.report = report
        self.checks: list[dict] = []
        local = Path(os.environ["LOCALAPPDATA"])
        self.install = local / "Programs" / "Odin"
        self.exe = self.install / "Odin.exe"
        self.token = local / "odin-desktop" / "default" / "config" / "ipc.token"
        self.profile = local / "odin-desktop" / "default"

    def check(self, name: str, ok: bool, detail="") -> bool:
        self.checks.append({"check": name, "ok": bool(ok), "detail": str(detail)[:2000]})
        return bool(ok)

    def processes(self) -> list[dict]:
        """Every process whose image is in the install, with its command line (CIM). This script
        runs on the installed interpreter itself, so its own process is left out."""
        script = ("$f = $env:ODIN_INSTALL_FOLDER; @(Get-CimInstance Win32_Process | Where-Object {"
                  " $_.ExecutablePath -and $_.ExecutablePath.StartsWith($f, "
                  "[StringComparison]::OrdinalIgnoreCase) } | Select-Object ProcessId, Name,"
                  " CommandLine) | ConvertTo-Json -Compress")
        env = {**os.environ, "ODIN_INSTALL_FOLDER": str(self.install) + "\\"}
        shell = Path(os.environ.get("SystemRoot") or r"C:\Windows") / (
            r"System32\WindowsPowerShell\v1.0\powershell.exe")
        out = subprocess.run([str(shell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                              script], capture_output=True, text=True, env=env, timeout=120)
        if out.returncode:
            raise RuntimeError(f"process listing failed: {out.stderr.strip()[:300]}")
        rows = json.loads(out.stdout or "[]")
        rows = rows if isinstance(rows, list) else [rows]
        return [row for row in rows if row.get("ProcessId") != os.getpid()]

    async def connect(self, deadline: float):
        from src.desktop.local_client import LocalClient
        from src.desktop.platform.windows_ipc import pipe_name

        last = None
        while time.monotonic() < deadline:
            try:
                return await LocalClient.connect(pipe_name("default"), self.token, "default")
            except (OSError, ValueError) as exc:  # not listening yet, or no token yet
                last = exc
                await asyncio.sleep(2)
        raise TimeoutError(f"the installed core never answered: {type(last).__name__}: {last}")

    async def start(self):
        subprocess.Popen([str(self.exe), "--hidden"], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.DETACHED_PROCESS)
        return await self.connect(time.monotonic() + 180)

    def exit_app(self) -> list[dict]:
        subprocess.run([str(self.exe), "--exit"], timeout=120, check=False)
        deadline, left = time.monotonic() + 120, []
        while time.monotonic() < deadline:
            left = self.processes()
            if not left:
                break
            time.sleep(2)
        return left


def argv_of(command_line: str) -> list[str]:
    """A command line as the process itself parsed it (CommandLineToArgvW)."""
    import ctypes
    from ctypes import wintypes

    shell32, kernel32 = ctypes.WinDLL("shell32"), ctypes.WinDLL("kernel32")
    shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    count = ctypes.c_int()
    argv = shell32.CommandLineToArgvW(command_line, ctypes.byref(count))
    if not argv:
        return []
    try:
        return [argv[index] for index in range(count.value)]
    finally:
        kernel32.LocalFree(ctypes.cast(argv, ctypes.c_void_p))


async def call(client, method: str, params: dict | None = None) -> dict:
    identity = await client.request(method, params)
    while True:
        message = await asyncio.wait_for(client.read(), 60)
        if message.get("t") == "bye":
            raise RuntimeError(f"the core closed the connection: {message.get('reason')}")
        if message.get("t") == "res" and message.get("id") == identity:
            if message.get("ok") is not True:
                raise RuntimeError(f"{method} refused: {json.dumps(message.get('error'))[:300]}")
            return message["result"]


async def use_scripted_model(client, base_url: str) -> dict:
    """The compat provider at the scripted model, as app/src/main/real-core-smoke.ts sets it."""
    async def save(method, changes):
        schema = await call(client, "settings.schema")
        await call(client, method, {"expected_revision": schema["revision"], "changes": changes})

    await save("providers.compat.set", [{"path": "openai_compatible.enabled", "value": False}])
    await save("providers.codex.set", [{"path": "openai_codex.enabled", "value": False}])
    await save("providers.auxiliary.set",
               [{"path": "openai_codex.auxiliary.enabled", "value": False}])
    await save("providers.compat.set", [
        {"path": "openai_compatible.base_url", "value": base_url},
        {"path": "openai_compatible.model", "value": MODEL},
        {"path": "openai_compatible.preset", "value": "custom"},
        {"path": "openai_compatible.reasoning_dialect", "value": "none"},
        {"path": "openai_compatible.reasoning_effort", "value": "none"},
        {"path": "openai_compatible.max_tokens", "value": 4096}])
    await call(client, "secrets.set",
               {"path": "openai_compatible.api_key", "value": "canned-local-test-only"})
    await save("providers.compat.set", [{"path": "openai_compatible.enabled", "value": True}])
    schema = await call(client, "settings.schema")
    await call(client, "models.main.set",
               {"model": f"compat:{MODEL}", "expected_revision": schema["revision"]})
    return (await call(client, "status.get"))["model"]


async def turn(client) -> dict:
    """A tool turn, read back from committed messages as the engine's own prompt client does."""
    cid = (await call(client, "conversations.create", {}))["conversation"]["id"]
    admitted = await call(client, "submission.send", {
        "client_submission_id": uuid.uuid4().hex, "conversation_id": cid, "text": PROMPT})
    rid, generation = admitted["request_id"], admitted.get("generation", 1)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        snapshot = await call(client, "conversation.snapshot",
                              {"conversation_id": cid, "limit": 100})
        terminal = next((item for item in snapshot["recent"] if item["request_id"] == rid
                         and item["generation"] == generation), None)
        replies = [item.get("text") for item in snapshot["messages"]["items"]
                   if item.get("request_id") == rid and item.get("role") == "assistant"]
        if terminal is not None and (replies or terminal["outcome"] != "completed"):
            return {"conversation_id": cid, "request_id": rid, "disposition":
                    admitted.get("disposition"), "outcome": terminal["outcome"],
                    "replies": replies}
        await asyncio.sleep(0.5)
    raise TimeoutError("the tool turn did not end within 180 s")


async def skill_test(client) -> dict:
    return await call(client, "skills.test", {"name": SKILL})


async def refused_major(run: Run) -> dict:
    """A client offering protocol major 1: proofs pass, then the core's own version check."""
    from src.desktop import platform
    from src.desktop.ipc_auth import client_session
    from src.desktop.platform.windows_ipc import endpoint_text, pipe_name
    from src.desktop.protocol import read_frame

    ipc = platform.current_platform().ipc
    pipe = pipe_name("default")
    reader, writer = await ipc.connect(pipe)
    try:
        sealed_reader, _ = await client_session(
            reader, writer, token=ipc.load_token(run.token), profile_id="default",
            endpoint=endpoint_text(pipe), client={"name": "odin-acceptance", "version": "0"},
            offered={"major": 1, "minor": 0}, features=[])
        return await asyncio.wait_for(read_frame(sealed_reader), 10)
    finally:
        writer.close()


async def acceptance(run: Run, work: Path) -> None:
    marker = work / "installed-core-marker.txt"
    marker.unlink(missing_ok=True)
    executable = Path(sys.executable).resolve()
    run.check("the installed interpreter, isolated", executable.is_relative_to(run.install)
              and sys.flags.isolated and sys.flags.dont_write_bytecode, executable)
    model = scripted_model(marker)
    index = package_index(probe_wheel(work))
    config = Path(os.environ["APPDATA"]) / "pip" / "pip.ini"
    kept = config.read_bytes() if config.exists() else None
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(f"[global]\nindex-url = http://127.0.0.1:{index.server_address[1]}"
                      "/simple/\n", encoding="utf-8")
    try:
        base_url = f"http://127.0.0.1:{model.server_address[1]}/v1"
        client = await run.start()
        # The installed tree before the core does any work: it must end exactly the same.
        before = tree_state(run.install)
        try:
            welcome = client.welcome
            run.check("the installed core authenticates and welcomes over its sealed pipe",
                      welcome.get("t") == "welcome" and welcome.get("profile_id") == "default",
                      json.dumps({"core": welcome.get("core"), "protocol": welcome.get("protocol"),
                                  "capabilities": len(welcome.get("capabilities") or [])}))
            cores = [row for row in run.processes() if "ownership.py" not in (
                row.get("CommandLine") or "") and row.get("Name", "").lower() == "python.exe"]
            bundled = str(run.install / "resources" / "runtime" / "python" / "python.exe").lower()
            argvs = [argv_of(row.get("CommandLine") or "") for row in cores]
            run.check("the core is the bundled interpreter, isolated, running the bundled engine",
                      argvs and all(argv and argv[0].lower() == bundled
                                    and argv[1:5] == ["-I", "-B", "-m", "src"] for argv in argvs),
                      [row.get("CommandLine") for row in cores])
            health = await call(client, "health.get")
            run.check("health.get answers", isinstance(health, dict), json.dumps(health)[:300])
            served = await use_scripted_model(client, base_url)
            run.check("the compat provider serves the scripted model", served == {
                "main": MODEL, "effort": None, "provider": "compat"}, served)
            result = await turn(client)
            written = marker.read_text(encoding="utf-8-sig").strip() if marker.exists() else ""
            run.check("a tool turn completes, its tool's effect on disk", result["outcome"] ==
                      "completed" and result["replies"][-1:] == [REPLY] and written == MARK,
                      json.dumps({**result, "marker": written}))
            saved = await call(client, "skills.save",
                               {"name": SKILL, "code": skill_code(), "create": True})
            tested = await skill_test(client)
            placed = [str(path) for path in run.profile.rglob(f"{MODULE}/__init__.py")]
            run.check("a skill's dependency installs through the bundled pip into the profile",
                      tested.get("is_error") is False and PACKAGE_MARK in str(tested.get("result"))
                      and placed and not any(Path(path).is_relative_to(run.install)
                                             for path in placed),
                      json.dumps({"saved": saved, "tested": tested, "placed": placed})[:1500])
        finally:
            await client.close()
        left = run.exit_app()
        run.check("Exit ends every process from the install", not left,
                  [row.get("Name") for row in left])

        client = await run.start()
        try:
            snapshot = await call(client, "conversation.snapshot",
                                  {"conversation_id": result["conversation_id"], "limit": 100})
            texts = [(item.get("role"), item.get("text")) for item in snapshot["messages"]["items"]]
            run.check("after a relaunch the turn is still there", ("user", PROMPT) in texts and (
                "assistant", REPLY) in texts, texts)
            served = (await call(client, "status.get"))["model"]
            run.check("and so are the settings", served.get("main") == MODEL, served)
            tested = await skill_test(client)
            run.check("and the skill still imports its package", tested.get("is_error") is False
                      and PACKAGE_MARK in str(tested.get("result")), json.dumps(tested)[:500])
            changed = sorted(set(before.items()) ^ set(tree_state(run.install).items()))
            run.check("the install tree is unchanged by all of it (a tool turn, a skill install, "
                      "a restart)", not changed, changed[:20])
        finally:
            await client.close()
        answer = await refused_major(run)
        run.check("a client offering protocol major 1 is refused", answer.get("t") == "bye"
                  and answer.get("reason") == "incompatible", answer)
        left = run.exit_app()
        run.check("Exit again ends every process from the install", not left,
                  [row.get("Name") for row in left])
    finally:
        model.shutdown()
        index.shutdown()
        if kept is None:
            config.unlink(missing_ok=True)
        else:
            config.write_bytes(kept)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    run = Run(args.report)
    outcome = ""
    try:
        if sys.platform != "win32":
            raise RuntimeError("native Windows required")
        work = Path(os.environ.get("TEMP") or args.report.parent)
        asyncio.run(acceptance(run, work))
    except Exception as exc:  # any failure is a failed check, never a lost report
        outcome = f"{type(exc).__name__}: {exc}"
        try:
            left = run.exit_app() if run.exe.exists() and run.processes() else []
            if left:
                outcome += f" (still running after Exit: {[row.get('Name') for row in left]})"
        except Exception as cleanup:  # recorded, never raised over the original failure
            outcome += f" (cleanup: {type(cleanup).__name__}: {cleanup})"
    finally:
        if outcome:
            run.check("the run reached its end", False, outcome)
        failed = [item for item in run.checks if not item["ok"]]
        args.report.write_text(json.dumps({"failed": len(failed), "checks": run.checks},
                                          indent=2) + "\n", encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
