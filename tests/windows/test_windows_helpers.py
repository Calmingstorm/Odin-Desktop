"""The local helpers on this computer: branch freshness and http_probe (phase 3 plan C12)."""
from __future__ import annotations

import functools
import http.server
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from src.desktop.platform import windows_helpers as helpers
from src.desktop.platform.windows_tools import exec_command, handle_http_probe
from src.tools.branch_freshness import check_branch_freshness
from src.tools.bulkhead import BulkheadFullError
from tests.windows.test_windows_exec import alive

PYTHON = getattr(sys, "_base_executable", "") or sys.executable


def executor(**extra):
    return SimpleNamespace(
        bulkheads={}, ssh_pool=None, _ensure_local_workspace=lambda: None,
        _command_shell_mode=lambda: "auto", _acquire_host=lambda alias: None,
        config=SimpleNamespace(command_timeout_seconds=60), **extra)


def git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=Odin Test", "-c", "user.email=test@example.invalid",
                    *args], cwd=cwd, check=True, capture_output=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)


async def test_branch_freshness_asks_this_computers_git(tmp_path, monkeypatch):
    origin, work, other = tmp_path / "origin.git", tmp_path / "work", tmp_path / "other"
    git("init", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    git("clone", str(origin), str(work), cwd=tmp_path)
    git("commit", "--allow-empty", "-m", "first", cwd=work)
    git("push", "origin", "main", cwd=work)
    git("clone", str(origin), str(other), cwd=tmp_path)
    for message in ("second", "third"):
        git("commit", "--allow-empty", "-m", message, cwd=other)
    git("push", "origin", "main", cwd=other)
    monkeypatch.chdir(work)  # where the engine runs local git, as on Linux
    status = await check_branch_freshness(functools.partial(exec_command, executor()),
                                          "127.0.0.1", "owner")
    assert (status.local_branch, status.commits_behind, status.fetch_failed) == ("main", 2, False)
    assert status.is_stale and status.remote_ref == "origin/main"


async def test_branch_freshness_keeps_odins_commands_for_other_hosts():
    sent = []

    async def remote(address, command, ssh_user):
        sent.append(command)
        return 0, "main\n" if "rev-parse" in command else "0\n"

    status = await check_branch_freshness(remote, "192.0.2.5", "owner")
    assert not status.is_stale and sent == [
        "git rev-parse --abbrev-ref HEAD 2>/dev/null", "git fetch origin --quiet 2>&1",
        "git rev-list --count HEAD..origin/main 2>/dev/null || echo 0"]


def test_only_the_freshness_questions_have_powershell_forms():
    behind = "git rev-list --count HEAD..origin/o'brien 2>/dev/null || echo 0"
    assert helpers.powershell_git(behind) == (
        "git rev-list --count 'HEAD..origin/o''brien' 2>$null; "
        "if ($LASTEXITCODE -ne 0) { '0' }; exit 0")
    with pytest.raises(ValueError, match="no PowerShell form"):
        helpers.powershell_git("git status")


@pytest.fixture
def echo_server():
    received = []

    class Echo(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            # Header values arrive as Latin-1 text (HTTP's own rule): compare their bytes.
            header = self.headers.get("X-Odin", "").encode("latin-1")
            received.append((self.rfile.read(length), header))
            self.send_response(201)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Echo)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1], received
    server.shutdown()
    server.server_close()


async def test_http_probe_sends_a_json_body_byte_for_byte(echo_server):
    port, received = echo_server
    body = '{"name": "Odin \\"Desktop\\"", "path": "C:\\\\x y", "mark": "h\u00e9 \u2713"}'
    text, code = await handle_http_probe(executor(), {
        "url": f"http://127.0.0.1:{port}/", "method": "POST", "body": body,
        "headers": [{"name": "X-Odin", "value": 'quote " and \u00e9'}]})
    assert code == 0 and "status_code: 201" in text, text
    assert received == [(body.encode("utf-8"), 'quote " and \u00e9'.encode("utf-8"))]


async def test_http_probe_reports_curls_own_failure(tmp_path):
    handler = http.server.BaseHTTPRequestHandler
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as idle:
        port = idle.server_address[1]  # bound, then closed: nothing answers there
    text, code = await handle_http_probe(executor(), {"url": f"http://127.0.0.1:{port}/",
                                                      "timeout": 5})
    assert code == 7, text


async def test_other_hosts_keep_odins_curl_command():
    sent = []

    async def remote(address, command, ssh_user, *, target=None):
        sent.append((address, command, target))
        return 0, "remote"

    fake = executor(_exec_command=remote)
    assert await helpers.probe(fake, "192.0.2.5", "curl -sS 'http://x/'", "owner") == (0, "remote")
    assert sent == [("192.0.2.5", "curl -sS 'http://x/'", None)]


async def test_the_transport_refuses_plainly(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="http_probe runs curl"):
        await helpers.probe(executor(), "127.0.0.1", "wget http://x/", "owner")

    class Full:
        def acquire(self):
            raise BulkheadFullError("subprocess", 1, 0)

    busy = executor()
    busy.bulkheads["subprocess"] = Full()
    code, text = await helpers.probe(busy, "127.0.0.1", "curl -sS http://127.0.0.1:9/", "owner")
    assert code == 1 and "bulkhead full" in text
    monkeypatch.setenv("SystemRoot", str(tmp_path))  # a Windows without curl.exe
    code, text = await helpers.probe(executor(), "127.0.0.1", "curl -sS http://x/", "owner")
    assert code == 1 and "curl.exe isn't on this computer" in text


async def test_run_argv_ends_the_job_on_timeout_and_reports_errors(tmp_path):
    marker = tmp_path / "child.pid"
    program = ("import subprocess, sys, time; "
               "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], "
               "creationflags=subprocess.CREATE_NO_WINDOW); "
               f"open(r'{marker}', 'w').write(str(child.pid)); time.sleep(60)")
    code, text = await helpers.run_argv([PYTHON, "-I", "-S", "-c", program], timeout=3)
    assert (code, text) == (1, "Command timed out after 3 seconds")
    assert not alive(int(marker.read_text()))
    (tmp_path / "bad.exe").write_bytes(b"not a program")
    code, text = await helpers.run_argv([str(tmp_path / "bad.exe")], timeout=5)
    assert code == 1 and text.startswith("Local exec error: ")
    utf8 = "import sys; sys.stdout.buffer.write('h\u00e9'.encode()); raise SystemExit(4)"
    code, text = await helpers.run_argv([PYTHON, "-c", utf8], timeout=30)
    assert (code, text.strip()) == (4, "h\u00e9")


@pytest.mark.parametrize("inp, result", [
    ({"url": "http://127.0.0.1/", "headers": [{"name": 1, "value": "x"}]},
     ("http_probe error: Header entry 0 name and value must be strings", 1)),
    ({"url": "http://127.0.0.1/", "method": "TRACE"},
     ("http_probe error: Invalid HTTP method: TRACE. Allowed: DELETE, GET, HEAD, OPTIONS, PATCH, "
      "POST, PUT", 1)),
    ({"url": "http://127.0.0.1/", "host": "ghost"}, "Unknown or disallowed host: ghost"),
])
async def test_http_probe_refuses_before_anything_runs(inp, result):
    assert await handle_http_probe(executor(), inp) == result


class Lease:
    def __init__(self, address):
        self.target = SimpleNamespace(address=address, ssh_user="u")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    async def run(self, factory):
        return await factory()


async def test_http_probe_through_a_lease_on_this_computer(echo_server):
    port, received = echo_server
    fake = executor()
    fake._acquire_host = lambda alias: Lease("127.0.0.1")
    text, code = await handle_http_probe(fake, {"url": f"http://127.0.0.1:{port}/",
                                                "host": "localhost", "method": "POST",
                                                "body": "x"})
    assert code == 0 and "status_code: 201" in text and received == [(b"x", b"")]


@pytest.mark.parametrize("answer, result", [
    ((7, ""), ("http_probe failed (exit 7): curl returned no output", 7)),
    ((0, "  "), ("http_probe: no response received", 1)),
])
async def test_http_probe_reports_curls_empty_answers(monkeypatch, answer, result):
    from src.desktop.platform import windows_tools

    async def canned(*args, **kwargs):
        return answer

    monkeypatch.setattr(windows_tools, "probe", canned)
    assert await handle_http_probe(executor(), {"url": "http://127.0.0.1/"}) == result


def test_the_executor_resolves_http_probe_to_the_windows_handler():
    from src.desktop.platform import windows_tools
    from src.tools.executor import ToolExecutor

    class Owner:  # browser_web.py stays upstream's: the route sits in the executor
        async def _handle_http_probe(self, inp):
            return "upstream"

        async def _handle_browser_click(self, inp):
            return "click"

    owner = Owner()
    executor = ToolExecutor.__new__(ToolExecutor)
    executor._handler_owners = {"browser_web": owner}
    handler = executor._resolve_handler("http_probe")
    assert handler.func is windows_tools.handle_http_probe and handler.args == (owner,)
    assert executor._resolve_handler("browser_click") == owner._handle_browser_click

    async def override(inp):
        return "a test's own handler"

    setattr(executor, "_handle_http_probe", override)  # the historical patch seam still wins
    assert executor._resolve_handler("http_probe") is override
