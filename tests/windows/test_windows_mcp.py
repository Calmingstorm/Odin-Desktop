"""MCP stdio servers on Windows, each in a kill-on-close job of its own (phase 3 plan C9)."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

import pytest

from src.desktop.platform import windows_mcp
from src.tools.mcp.errors import MCPConnectError
from src.tools.mcp.transport_stdio import StdioTransport, build_child_env
from tests.windows.test_windows_exec import alive, written

PYTHON = getattr(sys, "_base_executable", "") or sys.executable

# A line server: it answers each request with its params, and starts a grandchild that
# sleeps (pid in child.pid). With "stay" it keeps running after its stdin ends.
SERVER = r'''
import json, subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                         creationflags=subprocess.CREATE_NO_WINDOW)
with open("child.pid", "w") as handle:
    handle.write(str(child.pid))
for line in sys.stdin:
    message = json.loads(line)
    reply = {"jsonrpc": "2.0", "id": message["id"], "result": message["params"]}
    sys.stdout.write(json.dumps(reply) + "\n")
    sys.stdout.flush()
if "stay" in sys.argv:
    time.sleep(120)
'''


def transport(tmp_path, command, *args, env=None):
    received, closed = [], []
    server = StdioTransport("test", command, list(args), env=env, cwd=str(tmp_path),
                            on_message=received.append, on_closed=closed.append,
                            negotiated_version=lambda: None)
    return server, received, closed


async def round_trip(server, received, value):
    await server.send({"jsonrpc": "2.0", "id": value, "method": "echo", "params": {"v": value}})
    deadline = time.monotonic() + 30
    while not received and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    assert received == [{"jsonrpc": "2.0", "id": value, "result": {"v": value}}]


async def grandchild(tmp_path) -> int:
    marker = tmp_path / "child.pid"
    deadline = time.monotonic() + 30
    while not written(marker):
        assert time.monotonic() < deadline
        await asyncio.sleep(0.05)
    return int(written(marker))


@pytest.mark.parametrize("stay", [True, False])
async def test_a_server_answers_and_its_whole_tree_ends_at_stop(tmp_path, stay):
    (tmp_path / "server.py").write_text(SERVER)
    server, received, closed = transport(tmp_path, PYTHON, "server.py", *(["stay"] if stay else []))
    await server.start()
    await round_trip(server, received, 1)
    child = await grandchild(tmp_path)
    assert alive(child)
    await server.shutdown()
    assert closed == ["transport shut down"]
    assert server.returncode is not None and not alive(child)


async def test_an_npx_style_cmd_launcher_runs_through_cmd(tmp_path):
    (tmp_path / "server.py").write_text(SERVER)
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "server.cmd").write_text(f'@"{PYTHON}" "%~dp0..\\server.py" %*\n')
    path = f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}"
    server, received, closed = transport(tmp_path, "server", "stay", env={"Path": path})
    await server.start()
    await round_trip(server, received, 2)
    child = await grandchild(tmp_path)
    await server.shutdown()
    assert closed == ["transport shut down"] and not alive(child)


def test_a_command_is_found_as_linux_exec_finds_it(tmp_path, monkeypatch):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "tool.cmd").write_text("@exit 0\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "local.exe").write_bytes(b"MZ")
    env = {"Path": f"C:\\odin-missing;\"{tmp_path / 'bin'}\"", "PATHEXT": ".EXE;.CMD"}

    def found(command, env, cwd):
        where = windows_mcp.find_program(command, env, cwd)
        return where and os.path.normcase(where)  # PATHEXT's case may name the file

    tool = os.path.normcase(tmp_path / "bin" / "tool.cmd")
    local = os.path.normcase(tmp_path / "sub" / "local.exe")
    assert found("tool", env, "C:\\") == tool
    assert found("tool.cmd", env, "C:\\") == tool
    assert found("sub\\local", env, str(tmp_path)) == local
    assert found(str(tmp_path / "sub" / "local.exe"), env, "C:\\") == local
    assert found("local", env, str(tmp_path / "sub")) is None  # never the working folder
    monkeypatch.chdir(tmp_path / "sub")
    assert found("local", env, "C:\\") is None  # nor this process's
    assert found("tool", {}, "C:\\") is None  # no PATH, nothing found


async def test_start_refuses_plainly(tmp_path):
    for command, cwd, message in (("odin-no-such-program", tmp_path, "command not found"),
                                  ("", tmp_path, "stdio requires 'command'"),
                                  (PYTHON, tmp_path / "missing", "cwd does not exist")):
        server, _, _ = transport(cwd, command)
        with pytest.raises(MCPConnectError, match=message):
            await server.start()
    (tmp_path / "bad.exe").write_bytes(b"not a program")
    server, _, closed = transport(tmp_path, ".\\bad.exe")
    with pytest.raises(MCPConnectError, match="failed to start"):
        await server.start()
    await server.shutdown()  # never started: closes at once
    assert closed == ["transport shut down"]


async def test_a_started_transport_refuses_a_second_start(tmp_path):
    (tmp_path / "server.py").write_text(SERVER)
    server, _, _ = transport(tmp_path, PYTHON, "server.py")
    await server.start()
    try:
        with pytest.raises(MCPConnectError, match="already started"):
            await server.start()
    finally:
        await server.shutdown()


def test_the_child_env_keeps_windows_variables_and_no_secrets(monkeypatch):
    monkeypatch.setenv("ODIN_TEST_TOKEN", "do-not-pass")
    env = build_child_env({"path": "C:\\only", "EXTRA": "1"})
    names = [name.upper() for name in env]
    assert "ODIN_TEST_TOKEN" not in names
    assert env["SystemRoot"] == os.environ["SystemRoot"] and "WINDIR" in names
    assert names.count("PATH") == 1 and env["path"] == "C:\\only"
    assert env["EXTRA"] == "1"


@pytest.mark.parametrize("failure", ["grace", "error"])
async def test_closing_the_job_ends_what_termination_left(tmp_path, monkeypatch, failure):
    async def survived(running, timeout):
        return False

    async def failed(running, timeout):
        raise OSError("terminate failed")

    (tmp_path / "server.py").write_text(SERVER)
    server, _, closed = transport(tmp_path, PYTHON, "server.py", "stay")
    await server.start()
    child = await grandchild(tmp_path)
    monkeypatch.setattr(windows_mcp, "terminate", survived if failure == "grace" else failed)
    monkeypatch.setattr("src.tools.mcp.transport_stdio._STDIN_CLOSE_GRACE", 0.5)
    await server.shutdown()
    expected = "process survived termination grace" if failure == "grace" else "transport shut down"
    assert closed == [expected]
    deadline = time.monotonic() + 10  # the job's handle closed: kill-on-close ends the tree
    while alive(child) and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    assert not alive(child)


def test_a_working_folder_is_a_windows_absolute_path():
    from src.tools.mcp.errors import MCPConfigError
    from src.tools.mcp.manager import validate_server_config

    def check(cwd, **config):
        validate_server_config("box", {"transport": "stdio", "command": "python", "cwd": cwd,
                                       **config})

    for cwd in ("C:\\servers\\one", "c:/servers/one", "\\\\host\\share\\one",
                "\\\\?\\C:\\servers", ""):
        check(cwd)
    for cwd in ("servers\\one", "C:servers", "\\servers", "/home/one", "C:\\a\0b"):
        with pytest.raises(MCPConfigError, match="cwd must be an absolute path"):
            check(cwd)
    with pytest.raises(MCPConfigError, match="requires 'command'"):  # Linux's rules still apply
        check("C:\\servers", command="")


# Writes what it was given, then serves until its stdin ends.
ARGUMENTS = r'''
import json, sys
with open("args.json", "w") as handle:
    json.dump(sys.argv[1:], handle)
for line in sys.stdin:
    pass
'''


async def test_a_batch_launcher_receives_its_arguments_unchanged(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "args.py").write_text(ARGUMENTS)
    (tmp_path / "bin" / "server.cmd").write_text(f'@"{PYTHON}" "%~dp0..\\args.py" %*\n')
    # cmd.exe would act on these outside quotes: a second command, a pipe, redirections.
    args = ["plain", "two words", "a&type nul>marker.txt", "x|y", "<z>", "c^d", "(e)", ""]
    server, _, _ = transport(tmp_path, str(tmp_path / "bin" / "server.cmd"), *args)
    await server.start()
    deadline = time.monotonic() + 30
    while not written(tmp_path / "args.json"):
        assert time.monotonic() < deadline
        await asyncio.sleep(0.05)
    await server.shutdown()
    assert json.loads(written(tmp_path / "args.json")) == args
    assert not (tmp_path / "marker.txt").exists()  # no second command ran


@pytest.mark.parametrize("argument", ["%PATH%", 'say "hi"', "bang!", "line\nbreak", "cr\rhere"])
async def test_a_batch_launcher_refuses_what_cmd_would_change(tmp_path, argument):
    (tmp_path / "server.cmd").write_text("@exit 0\n")
    server, _, _ = transport(tmp_path, str(tmp_path / "server.cmd"), argument)
    with pytest.raises(MCPConnectError, match="can't receive an argument"):
        await server.start()
    assert server._process is None
