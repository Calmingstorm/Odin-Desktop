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
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from src.desktop.platform.darwin import user_temp_root
from tests.macos.test_core_end_to_end import hello
from tests.macos.test_core_tools_end_to_end import (
    ROOT,
    Client,
    ScriptedModel,
    call,
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


def tiny_pdf(text: str) -> bytes:
    """A one-page PDF that says ``text``, built by hand (no PDF library in the test)."""
    stream = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode()
    bodies = [b"<< /Type /Catalog /Pages 2 0 R >>",
              b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
              b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
              b"/Resources << /Font << /F1 5 0 R >> >> >>",
              b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
              b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(bodies, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    start = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(bodies) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(bodies) + 1, start)
    return bytes(out)


SKILL = '''
SKILL_DEFINITION = {
    "name": "acceptance_dependency",
    "description": "Says something through a package installed into the profile",
    "input_schema": {"type": "object", "properties": {}},
    "dependencies": ["text-unidecode==1.3"],
}


async def execute(inp, context):
    from text_unidecode import unidecode

    return "the skill says " + unidecode("Ça marche sur le Mac")
'''


def serve_page() -> ThreadingHTTPServer:
    """A page on 127.0.0.1:3000, which a fresh profile lets the bundled browser open."""
    class Page(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = b"<html><body><h1>The Mac acceptance page</h1></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 3000), Page)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def processes(pattern: str) -> list[int]:
    found = subprocess.run(["/usr/bin/pgrep", "-f", pattern], capture_output=True, text=True)
    return [int(pid) for pid in found.stdout.split()]


async def test_the_installed_app_runs_odin_and_exits_clean(packaged):
    checks: dict[str, object] = {}
    model = ScriptedModel()
    work = packaged.home / "work"
    work.mkdir()
    notes = work / "notes.txt"
    pdf = work / "note.pdf"
    pdf.write_bytes(tiny_pdf("Hello from the Mac PDF"))
    add = "*** Begin Patch\n*** Add File: notes.txt\n+first line\n+second line\n*** End Patch"
    update = ("*** Begin Patch\n*** Update File: notes.txt\n@@\n first line\n-second line\n"
              "+second line, patched\n*** End Patch")
    model.scripts.update({
        "command": sequence(("run_command", {"host": "localhost",
                                             "command": 'echo "app $((40 + 2))"; uname -s; '
                                                        'echo "PATH=$PATH"'})),
        "failure": sequence(("run_command", {"host": "localhost", "command": "exit 7"})),
        "file": sequence(
            ("apply_patch", {"host": "localhost", "root": str(work), "patch_text": add}),
            ("apply_patch", {"host": "localhost", "root": str(work), "patch_text": update}),
            ("read_file", {"host": "localhost", "path": str(notes), "raw": True})),
        "job": job,
        # The beacon note shares no word with the question: only the bundled embedding model,
        # offline, can find it (full text alone finds nothing).
        "search": sequence(
            ("ingest_document", {"source": "acceptance-note",
                                 "content": "A beacon on the coast guides ships at night."}),
            ("search_knowledge", {"query": "lighthouse by the sea"})),
        "pdf": sequence(("analyze_pdf", {"host": "localhost", "path": str(pdf)})),
        "browser": sequence(("browser_read_page", {"url": "http://127.0.0.1:3000/"})),
        "skill": sequence(("create_skill", {"name": "acceptance_dependency", "code": SKILL}),
                          ("acceptance_dependency", {})),
        "mcp": sequence(("mcp_acceptance_echo", {"text": "hello from the app"}),
                        ("mcp_acceptance_child_pid", {})),
    })
    page = serve_page()
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
            # Started as Finder starts it (launchd's minimal PATH): Homebrew's folders first, then
            # the system's path files, each folder once.
            folders = re.search(r"PATH=(\S+)", said).group(1).split(":")
            listed = [line.strip() for line in Path("/etc/paths").read_text().splitlines()
                      if line.strip()]
            assert folders[:2] == ["/opt/homebrew/bin", "/opt/homebrew/sbin"], folders
            expected = [folder for folder in listed if folder not in folders[:2]]
            assert folders[2:2 + len(expected)] == expected, folders
            assert len(folders) == len(set(folders)), folders
            checks["a command, with the Mac's PATH"] = folders

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

            done, tools = await run(client, conversation, "search")
            assert calls(tools) == [("ingest_document", "success"), ("search_knowledge", "success")]
            assert "beacon on the coast" in model.results["search"][1], model.results
            checks["search by meaning, offline, with the bundled model"] = True

            done, tools = await run(client, conversation, "pdf")
            assert calls(tools) == [("analyze_pdf", "success")], model.results
            assert "Hello from the Mac PDF" in model.results["pdf"][0], model.results
            installed = list((packaged.data).rglob("fitz")) + list(packaged.data.rglob("pymupdf"))
            assert installed, "the first-use PDF reader was not installed into the profile"
            assert not list(Path(APP).rglob("pymupdf*")), "the PDF reader is in the app"
            checks["the PDF reader installed on first use, into the profile"] = True

            done, tools = await run(client, conversation, "browser")
            assert calls(tools) == [("browser_read_page", "success")], model.results
            assert "The Mac acceptance page" in model.results["browser"][0], model.results
            browser = processes(f"{APP}/Contents/Resources/runtime/browser")
            assert browser, "the bundled browser is not the one that ran"
            checks["the bundled browser read a page"] = {"browser": browser}

            done, tools = await run(client, conversation, "skill")
            assert calls(tools) == [("create_skill", "success"),
                                    ("acceptance_dependency", "success")], model.results
            assert "the skill says Ca marche sur le Mac" in model.results["skill"][1], model.results
            checks["a skill's dependency installed into the profile"] = True

            revision = (await call(client, "settings.schema"))["revision"]
            await call(client, "mcp.set_global_enabled",
                       {"enabled": True, "expected_revision": revision})
            revision = (await call(client, "settings.schema"))["revision"]
            await call(client, "mcp.save", {
                "name": "acceptance", "expected_revision": revision, "enabled": True,
                "transport": "stdio", "command": sys.executable,
                "args": [str(ROOT / "tests" / "fakes" / "mcp_stdio_server.py"), "grandchild"],
                "cwd": str(work)})
            deadline = time.monotonic() + 60
            while "echo" not in json.dumps(await call(client, "mcp.tools", {"name": "acceptance"})):
                assert time.monotonic() < deadline, await call(client, "mcp.status")
                await asyncio.sleep(0.5)
            done, tools = await run(client, conversation, "mcp")
            assert calls(tools) == [("mcp_acceptance_echo", "success"),
                                    ("mcp_acceptance_child_pid", "success")], model.results
            assert "hello from the app" in model.results["mcp"][0], model.results
            child = int(re.search(r"\d+", model.results["mcp"][1]).group())
            revision = (await call(client, "settings.schema"))["revision"]
            await call(client, "mcp.set_enabled",
                       {"name": "acceptance", "enabled": False, "expected_revision": revision})
            assert await gone(child), "the MCP server's tree outlived its stop"
            checks["an MCP server child, stopped with its tree"] = True
        finally:
            await client.close()

        assert packaged.exit() == 0
        packaged.process.wait(90)
        checks["the app exited"] = packaged.process.returncode
        for pid in [*guardian, *engine, *browser]:
            assert await gone(pid, 30), f"{pid} outlived Exit: {packaged.stderr()}"
        checks["the guardian, the engine and the browser are gone"] = True

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

        # The start check ran on this app before READY, and nothing has written into the app
        # since: the metadata it recorded then is still every entry's now.
        shipped = importlib.util.spec_from_file_location(
            "shipped_ownership", Path(APP) / "Contents/Resources/ownership.py")
        ownership = importlib.util.module_from_spec(shipped)
        sys.modules[shipped.name] = ownership  # its dataclass looks its module up there
        shipped.loader.exec_module(ownership)
        resources = Path(APP) / "Contents/Resources"
        record = json.loads((packaged.home / "Library/odin-desktop/.install-ownership/macos"
                             / "bundle.json").read_text())
        manifest = hashlib.sha256((resources / "bundle-manifest.json").read_bytes()).hexdigest()
        assert record["manifest"] == manifest, record
        assert record["files"] == ownership._bundle_metadata(resources), "the app was written to"
        checks["the start check passed, and nothing wrote into the app"] = manifest
    finally:
        model.close()
        page.shutdown()
        page.server_close()
        if REPORT:
            # The evidence names the candidate it came from: its revision and disk image.
            report = {"app": APP, "python": sys.version,
                      "revision": os.environ.get("ODIN_MACOS_PACKAGED_REVISION", ""),
                      "disk_image_sha256": os.environ.get("ODIN_MACOS_PACKAGED_DMG_SHA256", ""),
                      "checks": checks}
            Path(REPORT).write_text(json.dumps(report, indent=2, default=str) + "\n")
