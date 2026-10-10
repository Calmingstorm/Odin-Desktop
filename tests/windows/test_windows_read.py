"""read_file on the local Windows host goes through the shared handler (phase 3 plan C3)."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.desktop.platform import windows_read
from src.desktop.platform.windows_tools import handle_read_file

VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "read-file-vectors.json"


class Lease:
    def __init__(self, address):
        self.target = SimpleNamespace(address=address, ssh_user="u")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    async def run(self, factory):
        return await factory()


def tool(address="127.0.0.1", allowed=True):
    calls = []

    async def exec_command(address, command, ssh_user, target=None):
        calls.append(command)
        return 0, "remote text"

    fake = SimpleNamespace(
        config=SimpleNamespace(),
        _acquire_host=lambda alias: Lease(address) if allowed else None,
        _exec_command=exec_command)
    return fake, calls


@pytest.fixture(autouse=True)
def budget(monkeypatch):
    import src.tools.output_delivery as delivery

    monkeypatch.setattr(delivery, "get_delivery_budget", lambda config: 11_500)


async def test_a_local_windows_path_reads_numbered_lines(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_bytes(b"alpha\r\nbeta\r\n")
    fake, calls = tool()
    result = await handle_read_file(fake, {"path": str(path), "host": "localhost"})
    assert result == ("1: alpha\r\n2: beta\r\n\n[returned 1-2]", 0)
    assert calls == []  # no shell for a local read


async def test_raw_mode_frames_the_exact_utf8_content(tmp_path):
    path = tmp_path / "data.json"
    path.write_bytes('{"k": "v\u2713"}\n'.encode())  # write_text would add a CR
    fake, _ = tool()
    text, code = await handle_read_file(fake, {"path": str(path), "host": "localhost",
                                               "raw": True})
    assert code == 0
    header = json.loads(text.split("\n", 1)[0].removeprefix("<<<ODIN_READ_FILE_RAW_V1 ")
                        .removesuffix(">>>"))
    assert header["returned_start_line"] == 1 and header["content_bytes"] == len(
        '{"k": "v\u2713"}\n'.encode())
    assert '{"k": "v\u2713"}\n<<<ODIN_READ_FILE_RAW_END_V1>>>' in text


async def test_errors_and_refusals_keep_the_handler_contract(tmp_path):
    fake, _ = tool()
    text, code = await handle_read_file(fake, {"path": str(tmp_path / "missing.txt"),
                                               "host": "localhost"})
    assert code == 2 and "cannot open" in text
    assert "absolute path" in await handle_read_file(fake, {"path": "relative.txt",
                                                            "host": "localhost"})
    blocked, _ = tool(allowed=False)
    assert "disallowed host" in await handle_read_file(blocked, {"path": "C:\\x.txt",
                                                                 "host": "elsewhere"})


async def test_a_remote_host_still_gets_the_awk_command(tmp_path):
    fake, calls = tool(address="192.0.2.10")
    text, code = await handle_read_file(fake, {"path": "/etc/hostname", "host": "server"})
    assert code == 0 and text == "remote text"
    assert len(calls) == 1 and calls[0].startswith("awk -v start=1 ")


def test_the_port_prints_what_gawk_printed_for_every_shared_case(tmp_path):
    vectors = json.loads(VECTORS.read_text())
    for name, data in vectors["corpus"].items():  # a prefix keeps "nul" from naming the device
        (tmp_path / f"case-{name}").write_bytes(base64.b64decode(data))
    for name, delivery_budget, raw_mode, start, count, code, digest in vectors["cases"]:
        numbered, raw_budget = min(10_500, delivery_budget - 256), min(8_000, delivery_budget - 600)
        returned, output = windows_read.read_local(
            str(tmp_path / f"case-{name}"), start=start, start_label=f"n{start}", count=count,
            budget=raw_budget if raw_mode else numbered, raw_mode=raw_mode)
        assert (returned, hashlib.sha256(output.encode()).hexdigest()) == (code, digest), (
            name, delivery_budget, raw_mode, start, count)

